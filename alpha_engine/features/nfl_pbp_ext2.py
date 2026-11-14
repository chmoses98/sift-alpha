"""NFL play-by-play extension builders, batch 2 (RESEARCH_ONLY): drive-, quarter-, kickoff- and conversion-level team features from nflverse pbp.

Every input is PARTIAL: the catalog definitions describe multinomial/lognormal/copula models with random effects and opponent adjustment that are NOT implemented; each spec lists what is missing.
What IS implemented are the measured components, as deterministic historical transformations (no model fitting, no outcome-optimised weights):
  * EWMA (half-life 8 team games, min 3 observations) of per-game quantities of STRICTLY EARLIER games (core.prior_ewm shifts by one game per team);
  * for the sparse-event inputs, counts accumulated over ALL strictly earlier team games, shrunk to the league rate of strictly earlier DATES with the k stated by the catalog (k = occasions).
Point in time: a game's features never use the game's own plays, nor any later game; only play-structure columns (drive result/clock, quarter, scores, kickoff and conversion flags) are used, never EPA / win-probability model columns.
Documented rules: drive attributes are the first NON-NULL value of each attribute in play order within each (game, posteam, fixed_drive); drive_time_of_possession "M:SS" -> seconds; regulation only (quarter <= 4); a team-game with no usable pbp rows is NaN, never zero;
Opp touchdown drives (pick-six against) count as turnover drives for the drive that ended; "other" = turnover on downs, end of half, missed FG, safety.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec, prior_ewm
from .nfl_ext import _norm, _team_games

S = "NFL"
HL = 8.0
PBP_COLS = ["game_id", "play_id", "posteam", "defteam", "td_team", "qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining", "score_differential", "total_home_score", "total_away_score", "home_score", "away_score",
            "play_type", "pass_attempt", "rush_attempt", "sack", "qb_scramble", "qb_kneel", "qb_spike", "touchdown", "return_touchdown", "field_goal_attempt", "play_deleted", "aborted_play",
            "fixed_drive", "fixed_drive_result", "drive_time_of_possession", "drive_quarter_start", "drive_start_transition", "drive_start_yard_line",
            "kickoff_attempt", "touchback", "extra_point_attempt", "extra_point_result", "two_point_attempt", "two_point_conv_result"]
SCRAMBLE = [c for c in PBP_COLS if c not in ("game_id", "play_id")]
SHR_TD, SHR_XP, SHR_2PT, SHR_LATE = 15, 50, 15, 10
TD_RES, FG_RES, PUNT_RES, TO_RES = "Touchdown", "Field goal", "Punt", ("Turnover", "Opp touchdown")


def load_raw(pbp_dir, games_file) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=[c for c in PBP_COLS if c in pd.read_parquet(f).columns]) for f in fs], ignore_index=True)
    games = pd.read_csv(games_file, usecols=["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "home_score"])
    return {"pbp": pbp, "games": games}


def _num(d, c):
    return pd.to_numeric(d[c], errors="coerce") if c in d else pd.Series(np.nan, index=d.index)


def _secs(s: pd.Series) -> pd.Series:
    parts = s.astype(str).str.extract(r"^(\d+):(\d{1,2})$")
    return pd.to_numeric(parts[0], errors="coerce") * 60 + pd.to_numeric(parts[1], errors="coerce")


def _yl100(start: pd.Series, team: pd.Series) -> pd.Series:
    """drive_start_yard_line is 'TEAM n' (n yards from that team's own goal line) or '50'. Return yards to the opponent goal line from the receiving team's view (yardline_100)."""
    m = start.astype(str).str.extract(r"^(?:([A-Za-z]{2,3}) )?(\d{1,2})$"); n = pd.to_numeric(m[1], errors="coerce"); side = _norm(m[0].fillna(""))
    return pd.Series(np.where(side == "", n, np.where(side == team, 100 - n, n)), index=start.index).where(n.notna())


def _clean(p: pd.DataFrame) -> pd.DataFrame:
    p = p.copy()
    for c in ("pass_attempt", "rush_attempt", "sack", "qb_scramble", "qb_kneel", "qb_spike", "touchdown", "return_touchdown", "field_goal_attempt", "kickoff_attempt", "touchback", "extra_point_attempt", "two_point_attempt"):
        p[c] = _num(p, c).fillna(0.0)
    for c in ("qtr", "fixed_drive", "drive_quarter_start", "game_seconds_remaining", "score_differential", "total_home_score", "total_away_score", "home_score", "away_score", "play_id"):
        p[c] = _num(p, c)
    for c in ("posteam", "defteam", "td_team"):
        p[c] = _norm(p[c].astype(str)).where(~p[c].isna())
    drop = (_num(p, "play_deleted").fillna(0) == 1) | (_num(p, "aborted_play").fillna(0) == 1)
    return p[~drop].sort_values(["game_id", "play_id"], kind="mergesort")


def _drives(p: pd.DataFrame) -> pd.DataFrame:
    d = p[p.fixed_drive.notna() & p.posteam.notna()].groupby(["game_id", "posteam", "fixed_drive"], sort=False).first().reset_index()   # first NON-NULL value of each drive attribute in play order
    d["secs"] = _secs(d["drive_time_of_possession"]); d["idx"] = d.groupby(["game_id", "posteam"]).fixed_drive.rank(method="dense")
    r = d.fixed_drive_result
    d["cls"] = np.select([r == TD_RES, r == FG_RES, r == PUNT_RES, r.isin(TO_RES)], ["td", "fg", "punt", "to"], "other")
    return d


def _quarter_points(p: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    """Home/away points scored in each regulation quarter = score at the start of the first play of the next period minus the start of this one (Q4: first overtime play, else the final score)."""
    f = p[p.qtr.notna() & p.total_home_score.notna() & p.total_away_score.notna()].groupby(["game_id", "qtr"]).first()[["total_home_score", "total_away_score"]].unstack("qtr")
    fin = p.groupby("game_id")[["home_score", "away_score"]].first()
    out = {}
    for side, tot in (("home", "total_home_score"), ("away", "total_away_score")):
        b = {q: f[(tot, float(q))] if (tot, float(q)) in f.columns else pd.Series(np.nan, index=f.index) for q in (1, 2, 3, 4, 5)}
        b[5] = b[5].fillna(fin[f"{side}_score"].reindex(f.index))
        for q in (1, 2, 3, 4):
            out[(side, q)] = b[q + 1] - b[q]
    return pd.DataFrame(out)


def _per_game(p: pd.DataFrame, tg: pd.DataFrame):
    pc = _clean(p); p = pc[pc.posteam.notna() & ~pc.posteam.isin(["nan", "None", ""])]   # pc: all usable plays (quarter-start scores come from plays with no possession team too)
    key = ["game_id", "team"]; out: dict = {}
    d = _drives(p); d = d[d.drive_quarter_start <= 4]
    early = d[d.idx <= 3]; ge = early.groupby(["game_id", "posteam"])
    for cl in ("td", "fg", "punt", "to"):
        out[f"o3_{cl}"] = ge.apply(lambda x, cl=cl: float((x.cls == cl).mean()), include_groups=False)
    for cl in ("td", "fg", "punt", "to"):
        sub = d[d.cls == cl]; out[f"dur_{cl}"] = sub.groupby(["game_id", "posteam"]).secs.mean()
    for q in (1, 2, 3, 4):
        dq = d[d.drive_quarter_start == q]; g = dq.groupby(["game_id", "posteam"])
        out[f"ds{q}"] = g.size(); out[f"dsec{q}"] = g.secs.mean()
        out[f"pq{q}_td"] = g.apply(lambda x: float((x.cls == "td").mean()), include_groups=False); out[f"pq{q}_fg"] = g.apply(lambda x: float((x.cls == "fg").mean()), include_groups=False)
    ko = p[p.kickoff_attempt == 1].dropna(subset=["defteam"])
    out["kr_n"] = ko.groupby(["game_id", "defteam"]).size(); out["kr_tb"] = ko.groupby(["game_id", "defteam"]).touchback.mean()
    out["kr_td"] = ko.groupby(["game_id", "defteam"]).apply(lambda x: float((x.return_touchdown == 1).mean()), include_groups=False)
    out["kk_tb"] = ko.groupby(["game_id", "posteam"]).touchback.mean()
    kd = _drives(p)
    kd = kd[kd.drive_start_transition.astype(str).str.upper() == "KICKOFF"].assign(y100=lambda x: _yl100(x.drive_start_yard_line, x.posteam)); out["kr_start"] = kd.groupby(["game_id", "posteam"]).y100.mean()
    xp = p[p.extra_point_attempt == 1]; out["xp_att"] = xp.groupby(["game_id", "posteam"]).size(); out["xp_made"] = xp.groupby(["game_id", "posteam"]).apply(lambda x: float((x.extra_point_result == "good").sum()), include_groups=False)
    tw = p[p.two_point_attempt == 1]; out["tp_att"] = tw.groupby(["game_id", "posteam"]).size(); out["tp_conv"] = tw.groupby(["game_id", "posteam"]).apply(lambda x: float((x.two_point_conv_result == "success").sum()), include_groups=False)
    td = p[(p.touchdown == 1) & p.td_team.notna()]; out["td_n"] = td.groupby(["game_id", "td_team"]).size()
    late = p[(p.qtr == 4) & (p.game_seconds_remaining <= 120) & p.score_differential.between(-3, 0)]
    scr = late[((late.pass_attempt == 1) | (late.rush_attempt == 1) | (late.sack == 1) | (late.qb_scramble == 1)) & (late.qb_kneel == 0) & (late.qb_spike == 0)]
    out["late_kneel"] = late[late.qb_kneel == 1].groupby(["game_id", "posteam"]).size(); out["late_fg"] = late[late.field_goal_attempt == 1].groupby(["game_id", "posteam"]).size(); out["late_go"] = scr.groupby(["game_id", "posteam"]).size()
    df = pd.DataFrame(out); df.index.names = key; df = df.reset_index()
    # quarter points (regulation) per team of each game, and per-game quarter indicators
    qp = _quarter_points(pc, tg); rows = []
    for gid, r in qp.iterrows():
        for side in ("home", "away"):
            rows.append({"game_id": gid, "side": side, **{f"qp{q}": r[(side, q)] for q in (1, 2, 3, 4)}, **{f"qo{q}": r[("away" if side == "home" else "home", q)] for q in (1, 2, 3, 4)}})
    qd = pd.DataFrame(rows)
    return df, qd


def _shrunk(t: pd.DataFrame, num: str, den: str, k: float) -> pd.Series:
    """(sum_num_before + k*L)/(sum_den_before + k): team sums over ALL strictly earlier team games, L = league ratio over strictly earlier DATES. NaN when the league has no history yet."""
    cn = t.groupby("team", sort=False)[num].transform(lambda s: s.fillna(0).cumsum().shift(1).fillna(0)); cd = t.groupby("team", sort=False)[den].transform(lambda s: s.fillna(0).cumsum().shift(1).fillna(0))
    dd = t.groupby("date")[[num, den]].sum(min_count=1).fillna(0).sort_index(); L = (dd[num].cumsum() - dd[num]) / (dd[den].cumsum() - dd[den]).replace(0, np.nan)
    Lm = t["date"].map(L)
    return (cn + k * Lm) / (cd + k)


def compute(raw: dict) -> dict:
    tg = _team_games(raw["games"]); p = raw["pbp"]
    pg, qd = _per_game(p, tg)
    # map quarter-point rows (home/away) to teams via the schedule
    g = raw["games"]; sides = pd.concat([g.assign(team=_norm(g.home_team), side="home")[["game_id", "team", "side"]], g.assign(team=_norm(g.away_team), side="away")[["game_id", "team", "side"]]])
    qd = qd.merge(sides, on=["game_id", "side"], how="inner")
    t = tg.merge(pg, on=["game_id", "team"], how="left").merge(qd.drop(columns="side"), on=["game_id", "team"], how="left")
    t = t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    has = t["ds1"].notna() | t["o3_td"].notna() | t["xp_att"].notna() | t["kr_n"].notna()           # a team-game with no usable pbp rows stays NaN; otherwise absent counts are zero
    for c in ["ds1", "ds2", "ds3", "ds4", "xp_att", "xp_made", "tp_att", "tp_conv", "td_n", "late_kneel", "late_fg", "late_go"]:
        t[c] = np.where(has, t[c].fillna(0.0), np.nan)
    # defence-faced rates of the first three drives: the opponent's offensive value in the same game
    opp = t[["game_id", "team", "o3_td", "o3_fg"]].rename(columns={"team": "opp", "o3_td": "o3_def_td", "o3_fg": "o3_def_fg"})
    t = t.merge(opp, on=["game_id", "opp"], how="left").sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    for q in (1, 2, 3, 4):
        t[f"qs{q}"] = (t[f"qp{q}"] > 0).astype(float).where(t[f"qp{q}"].notna()); t[f"qtie{q}"] = (t[f"qp{q}"] == t[f"qo{q}"]).astype(float).where(t[f"qp{q}"].notna() & t[f"qo{q}"].notna())
        t[f"qbtts{q}"] = ((t[f"qp{q}"] > 0) & (t[f"qo{q}"] > 0)).astype(float).where(t[f"qp{q}"].notna() & t[f"qo{q}"].notna())
    t["tp_share"] = t.tp_att / (t.xp_att + t.tp_att).where((t.xp_att + t.tp_att) > 0)
    t["late_n"] = t.late_kneel + t.late_fg + t.late_go
    names = {}
    for c in ["o3_td", "o3_fg", "o3_punt", "o3_to", "o3_def_td", "o3_def_fg", "dur_td", "dur_fg", "dur_punt", "dur_to", "kr_tb", "kr_td", "kk_tb", "kr_start"] + [f"{a}{q}" for q in (1, 2, 3, 4) for a in ("ds", "dsec", "qs", "qtie", "qbtts")] + [f"pq{q}_{x}" for q in (1, 2, 3, 4) for x in ("td", "fg")]:
        names[c] = c + "_pre"
    out = t[["game_id", "season", "week", "team", "opp", "date"]].copy()
    for c, n in names.items():
        out[n] = prior_ewm(t, "team", c, hl=HL, min_periods=3)
    out["xp_make_pre"] = _shrunk(t, "xp_made", "xp_att", SHR_XP); out["twopt_share_pre"] = _shrunk(t, "tp_att", "td_n", SHR_2PT); out["twopt_conv_pre"] = _shrunk(t, "tp_conv", "tp_att", SHR_2PT)
    for c in ("kneel", "fg", "go"):
        out[f"late_{c}_pre"] = _shrunk(t, f"late_{c}", "late_n", SHR_LATE)
    return {"team": out.reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    def F(cid, cols, d, done, miss, raw=("nflverse pbp (play structure columns only; no EPA/WP)", "nflverse schedule")):
        return FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, list(raw), "pregame_rolling")
    qc = lambda a: [f"{a}{q}_pre" for q in (1, 2, 3, 4)]
    return [
        F("nfl.drive_outcome_by_index", ["o3_td_pre", "o3_fg_pre", "o3_punt_pre", "o3_to_pre", "o3_def_td_pre", "o3_def_fg_pre"],
          "EWMA (half-life 8) of the share of the team's first three regulation drives (by fixed_drive order) ending in TD / field goal / punt / turnover (Turnover or Opp touchdown), and the TD / FG shares the opponent's first three drives had against it",
          ["empirical first-three-drive outcome shares for/against"], ["multinomial logit with covariates", "starting yardline covariate", "random effects", "half-life 15 recency", "shrinkage k=25", "drive-level (not game-averaged) weighting"]),
        F("nfl.drive_duration_by_outcome", ["dur_td_pre", "dur_fg_pre", "dur_punt_pre", "dur_to_pre"],
          "EWMA (half-life 8) of the per-game mean drive_time_of_possession (seconds) of the team's regulation TD / field goal / punt / turnover drives",
          ["mean drive seconds by outcome class"], ["lognormal fit", "opponent adjustment", "shrinkage k=15 drives", "20-game half-life-10 window", "quarter-end stop conversion"]),
        F("nfl.period_drive_scoring_rates", [f"pq{q}_{x}_pre" for q in (1, 2, 3, 4) for x in ("td", "fg")],
          "EWMA (half-life 8) of the per-game share of the team's drives that START in quarter q (regulation) ending in a touchdown / field goal",
          ["raw per-quarter TD and FG per drive"], ["multinomial logistic with opponent effects", "two-minute drives split from Q2", "garbage-time exclusion (needs win probability)", "shrinkage k=30", "3-season decay"]),
        F("nfl.drive_clock_allocation", qc("ds") + qc("dsec"),
          "EWMA (half-life 8) of the count of drives the team starts in each regulation quarter and of the mean drive seconds of those drives",
          ["drive starts per quarter", "seconds per drive by period"], ["opponent pace adjustment", "kickoff order", "P(second drive in Q1)", "shrinkage k=10"]),
        F("nfl.period_zero_tie_mass", qc("qs") + qc("qtie") + qc("qbtts"),
          "EWMA (half-life 8) of per-team-game indicators by regulation quarter: the team scored; the quarter finished level (both teams equal, including 0-0); both teams scored",
          ["team-level marginal quarter scoring/tie/BTTS frequencies"], ["joint P(home pts=a, away pts=b) atoms", "Gaussian copula", "isotonic atom fix", "league-pooled shrinkage k=300", "expected-total terciles"]),
        F("nfl.opening_kick_field_position", ["kr_tb_pre", "kr_td_pre", "kk_tb_pre", "kr_start_pre"],
          "EWMA (half-life 8) of per-game: touchback share of kickoffs the team received, return-TD share of kickoffs received, touchback share of kickoffs the team kicked, and mean yardline_100 of the team's drives that started after a kickoff",
          ["touchback rate (received/kicked)", "return TD per kickoff", "post-kick starting yardline (all kickoffs)"], ["opening-kick-only distribution", "returner and kicker level", "shrinkage k=20 by season", "rule-regime flag"]),
        F("nfl.scoring_event_point_values", ["xp_make_pre", "twopt_share_pre", "twopt_conv_pre"],
          "all-prior-games cumulative team rates shrunk to the league rate of strictly earlier dates: extra-point make rate (k=50 attempts), two-point attempts per touchdown scored (k=15), two-point conversion rate (k=15)",
          ["XP make rate with k=50 shrinkage", "2-pt attempt and conversion rates with k=15 shrinkage"], ["kicker and distance level XP model", "coach and win-probability-state 2-pt policy", "P(TD value in {6,7,8}) combination", "safety rate (see nfl.safety_risk)"]),
        F("nfl.late_tie_game_management", ["late_kneel_pre", "late_fg_pre", "late_go_pre"],
          "all-prior-games cumulative team shares of kneel / field-goal attempt / go-for-it (scrimmage pass, rush, sack, scramble) among those plays by the offence in the 4th quarter with <=120 s left and score differential in -3..0, shrunk to the league share of strictly earlier dates with k=10 occasions",
          ["kneel/FG/go shares with k=10 shrinkage"], ["coach-level rates (team level only)", "per-season split", "P(tie at final | state) and margin-distribution application"]),
    ]

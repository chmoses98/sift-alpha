"""NFL play-by-play extension builders (RESEARCH_ONLY): team-level EWMA of strictly earlier games from nflverse pbp, for catalog inputs not built by features/nfl.py.

Every input is PARTIAL: the catalog definitions mix the measured rate with modelling (opponent factors, coach random effects, simulation, shrinkage) that is NOT implemented; each spec lists what is missing.
Point in time: a game's features use only completed games dated strictly before it (prior_ewm shifts by one game per team); nothing from the game's own plays is used. Plays flagged deleted/aborted are dropped. Drive columns are read from the first row of each drive (a drive whose first row is NaN drops out); nflverse drive_ended_with_score is also 1 for drives ending in an opponent score.
Limits stated, not hidden: nflfastR EPA/win-probability columns are a CURRENT model re-run over history (retroactive model version) - only play-structure columns (flags, yardline, down, clock, scores) are used here, never EPA/WP.
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
PBP_COLS = ["game_id", "play_id", "posteam", "defteam", "td_team", "qtr", "down", "ydstogo", "yardline_100", "goal_to_go", "half_seconds_remaining", "play_type", "yards_gained", "pass_attempt", "rush_attempt", "qb_dropback", "qb_kneel", "qb_spike", "qb_scramble",
            "sack", "safety", "interception", "fumble_lost", "return_touchdown", "touchdown", "two_point_attempt", "fixed_drive", "drive_play_count", "drive_ended_with_score", "no_huddle", "play_deleted", "aborted_play", "season_type", "punt_attempt", "field_goal_attempt", "kick_distance", "special_teams_play"]
SCRAMBLE = [c for c in PBP_COLS if c not in ("game_id", "play_id")]


def load_raw(pbp_dir, games_file) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=[c for c in PBP_COLS if c in pd.read_parquet(f).columns]) for f in fs], ignore_index=True)
    games = pd.read_csv(games_file, usecols=["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "home_score"])
    return {"pbp": pbp, "games": games}


def _num(d, c):
    return pd.to_numeric(d[c], errors="coerce") if c in d else pd.Series(np.nan, index=d.index)


def _per_game(p: pd.DataFrame) -> pd.DataFrame:
    """Raw per team-game quantities (own offense unless named def_/against). One row per (game_id, team)."""
    p = p.copy()
    for c in ("pass_attempt", "rush_attempt", "qb_dropback", "qb_kneel", "qb_spike", "qb_scramble", "sack", "safety", "interception", "fumble_lost", "return_touchdown", "touchdown", "two_point_attempt", "goal_to_go", "no_huddle", "punt_attempt", "field_goal_attempt"):
        p[c] = _num(p, c).fillna(0.0)
    for c in ("down", "ydstogo", "yardline_100", "half_seconds_remaining", "yards_gained", "fixed_drive", "drive_play_count", "drive_ended_with_score", "kick_distance"):
        p[c] = _num(p, c)
    p["posteam"] = _norm(p["posteam"].astype(str)); p["defteam"] = _norm(p["defteam"].astype(str)); p["td_team"] = _norm(p["td_team"].astype(str))
    drop = (_num(p, "play_deleted").fillna(0) == 1) | (_num(p, "aborted_play").fillna(0) == 1)
    p = p[~drop & p.posteam.notna() & ~p.posteam.isin(["nan", "None", ""])]
    scr = p[(p.pass_attempt == 1) | (p.rush_attempt == 1) | (p.sack == 1) | (p.qb_scramble == 1)]
    scr = scr[(scr.qb_kneel == 0) & (scr.qb_spike == 0)]
    key = ["game_id", "posteam"]; out = {}
    g = scr.groupby(key)
    out["plays"] = g.size()
    two = scr[scr.half_seconds_remaining <= 120]; out["tm_n"] = two.groupby(key).size(); out["tm_pass"] = two.groupby(key).pass_attempt.sum()
    first = scr[scr.fixed_drive.notna()]; fd = first.groupby(key).fixed_drive.transform("min"); op = first[first.fixed_drive == fd]
    out["open_n"] = op.groupby(key).size(); out["open_pass"] = op.groupby(key).pass_attempt.sum()
    dr = p[p.fixed_drive.notna()].drop_duplicates(["game_id", "posteam", "fixed_drive"])    # FIRST ROW of each drive: drive_play_count / drive_ended_with_score are read from it (documented rule; NaN drives drop out)
    fmin = first.groupby(key).fixed_drive.min().rename("_fmin").reset_index()               # the SAME first drive as open_n / open_pass: minimum fixed_drive among the team's scrimmage plays
    first_dr = dr.merge(fmin, on=key); first_dr = first_dr[first_dr.fixed_drive == first_dr._fmin].set_index(key)
    out["open_score"] = first_dr.drive_ended_with_score     # nflverse flag: 1 also for drives ending in an OPPONENT score (documented limit)
    out["safety_allowed"] = p[p.safety == 1].groupby(key).size()
    out["twopt_att"] = p[p.two_point_attempt == 1].groupby(key).size()
    # defensive / special-teams touchdowns scored BY the team: a TD whose td_team is not the possessing team (credited to the defence of that play)
    nonoff = p[(p.touchdown == 1) & (p.td_team != p.posteam) & p.td_team.notna()]
    out["nonoff_td_for"] = nonoff.groupby(["game_id", "td_team"]).size()
    deftd = scr[(scr.touchdown == 1) & (scr.td_team != scr.posteam) & scr.td_team.notna()]            # scrimmage-play defensive TDs only (no kick/punt returns)
    out["def_td_for"] = deftd.groupby(["game_id", "td_team"]).size()
    out["safety_for"] = p[p.safety == 1].groupby(["game_id", "defteam"]).size()
    out["nonoff_td_against"] = nonoff.groupby(key).size()
    out["giveaways"] = scr.groupby(key).apply(lambda d: float((d.interception + d.fumble_lost).sum()), include_groups=False)
    out["takeaways"] = scr.groupby(["game_id", "defteam"]).apply(lambda d: float((d.interception + d.fumble_lost).sum()), include_groups=False)
    f4 = scr[(scr.down == 4) & (scr.ydstogo <= 3)]; out["f4s_n"] = f4.groupby(key).size()
    f4a = p[(p.down == 4) & (p.ydstogo <= 3) & (p.goal_to_go == 1)]; out["f4g_n"] = f4a.groupby(key).size()
    f4all = p[(p.down == 4) & (p.ydstogo <= 3) & p.play_type.isin(["pass", "run", "punt", "field_goal"])]
    out["f4s_all"] = f4all.groupby(key).size(); out["f4s_go"] = f4all[f4all.play_type.isin(["pass", "run"])].groupby(key).size()
    out["f4g_all"] = f4all[f4all.goal_to_go == 1].groupby(key).size(); out["f4g_go"] = f4all[(f4all.goal_to_go == 1) & f4all.play_type.isin(["pass", "run"])].groupby(key).size()
    gtg = scr[scr.goal_to_go == 1]; out["gtg_n"] = gtg.groupby(key).size(); out["gtg_db"] = gtg.groupby(key).qb_dropback.sum()
    out["db_n"] = scr.groupby(key).qb_dropback.sum(); out["db_leak"] = scr.groupby(key).apply(lambda d: float(((d.sack == 1) | (d.qb_scramble == 1)).sum()), include_groups=False)
    rush = scr[(scr.rush_attempt == 1) & (scr.qb_scramble == 0)]; out["rush_n"] = rush.groupby(key).size(); out["rush_expl"] = rush.groupby(key).apply(lambda d: float((d.yards_gained >= 10).sum()), include_groups=False)
    out["def_rush_n"] = rush.groupby(["game_id", "defteam"]).size(); out["def_rush_expl"] = rush.groupby(["game_id", "defteam"]).apply(lambda d: float((d.yards_gained >= 10).sum()), include_groups=False)
    neu = scr[(scr.down.isin([1, 2])) & (scr.qtr <= 3) & (scr.half_seconds_remaining > 120) & ((scr.pass_attempt == 1) | (scr.rush_attempt == 1))]
    out["neu_n"] = neu.groupby(key).size(); out["neu_run"] = neu.groupby(key).rush_attempt.sum()
    out["def_neu_n"] = neu.groupby(["game_id", "defteam"]).size(); out["def_neu_run"] = neu.groupby(["game_id", "defteam"]).rush_attempt.sum()
    out["drive_len"] = dr.groupby(key).drive_play_count.mean()
    out["def_drive_len"] = dr.groupby(["game_id", "defteam"]).drive_play_count.mean()
    out["gl_plays"] = scr[(scr.yardline_100 >= 95)].groupby(key).size(); out["own1"] = scr[scr.yardline_100 == 99].groupby(key).size()
    df = pd.DataFrame(out); df.index.names = ["game_id", "team"]
    return df.reset_index()


def _agg_index(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["game_id", "team"], as_index=False).first()


def compute(raw: dict) -> dict:
    tg = _team_games(raw["games"]); p = raw["pbp"]
    # opponent-side series (defense) come from the same per-game table keyed by the DEFENDING team: re-key by merging both orientations
    pg = _per_game(p)
    t = tg.merge(pg, on=["game_id", "team"], how="left")
    for c in pg.columns[2:]:
        t[c] = t[c].astype(float)
    cnt = ["tm_n", "tm_pass", "open_n", "open_pass", "safety_allowed", "twopt_att", "nonoff_td_for", "def_td_for", "safety_for", "nonoff_td_against", "giveaways", "takeaways", "f4s_n", "f4g_n", "f4s_all", "f4s_go", "f4g_all", "f4g_go", "gtg_n", "gtg_db", "neu_n", "neu_run", "def_neu_n", "def_neu_run",
           "rush_n", "rush_expl", "def_rush_n", "def_rush_expl", "gl_plays", "own1", "db_leak", "db_n"]
    has = t["plays"].notna()          # a team-game with no usable pbp rows stays NaN, never zero
    for c in cnt:
        t[c] = np.where(has, t[c].fillna(0.0), np.nan)
    t = t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    r = lambda n, d: n / d.where(d > 0)
    base = {
        "two_min_pass_rate": r(t.tm_pass, t.tm_n), "open_pass_rate": r(t.open_pass, t.open_n), "open_drive_n": t.open_n, "open_drive_score": t.open_score,
        "safety_allowed": t.safety_allowed, "twopt_att": t.twopt_att, "nonoff_td_for": t.nonoff_td_for, "nonoff_score_for": t.nonoff_td_for + t.safety_for, "nonoff_td_against": t.nonoff_td_against,
        "giveaway_rate": r(t.giveaways, t.plays), "takeaway_td_rate": r(t.def_td_for, t.takeaways), "takeaway_n": t.takeaways,
        "go_4th_short": r(t.f4s_go, t.f4s_all), "go_4th_goal": r(t.f4g_go, t.f4g_all), "gtg_db_rate": r(t.gtg_db, t.gtg_n), "db_leak_rate": r(t.db_leak, t.db_n),
        "rush_expl": r(t.rush_expl, t.rush_n), "def_rush_expl": r(t.def_rush_expl, t.def_rush_n), "neu_run": r(t.neu_run, t.neu_n), "def_neu_run": r(t.def_neu_run, t.def_neu_n), "drive_len": t.drive_len, "def_drive_len": t.def_drive_len, "gl_plays": t.gl_plays, "own1": t.own1}
    # defence-keyed series live on the DEFENDING team's row of the same game: re-key (defteam rows were grouped under 'team' via defteam above where named def_*)
    for k, v in base.items():
        t["_" + k] = v
    cols = {}
    for k in base:
        hl = 20.0 if k in ("safety_allowed", "twopt_att", "nonoff_td_for", "nonoff_score_for", "nonoff_td_against", "takeaway_td_rate", "own1", "gl_plays") else HL
        cols[k] = prior_ewm(t, "team", "_" + k, hl=hl, min_periods=3 if hl == HL else 5).rename(k + "_pre")
    out = tg_cols = t[["game_id", "season", "week", "team", "opp", "date"]].copy()
    for k, v in cols.items():
        out[v.name] = v
    return {"team": out.reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    def F(cid, cols, d, done, miss):
        return FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, ["nflverse pbp (play structure columns only; no EPA/WP)", "nflverse schedule"], "pregame_rolling")
    m_opp = "opponent-adjustment factor"; m_coach = "coach-level effect (team level only)"
    return [
        F("nfl.two_minute_tempo", ["two_min_pass_rate_pre"], "EWMA (half-life 8) of the team's pass rate on scrimmage plays with <=120 s left in a half, strictly earlier games", ["two-minute pass rate"], ["points per two-minute drive", m_opp, "QB-specific view"]),
        F("nfl.opening_script", ["open_pass_rate_pre", "open_drive_n_pre", "open_drive_score_pre"], "EWMA of the team's first-drive pass rate, plays and scoring share", ["first drive plays/pass/score"], ["per-half opening drives", "pass rate vs expected"]),
        F("nfl.safety_risk", ["safety_allowed_pre", "twopt_att_pre"], "EWMA (half-life 20) of safeties conceded and two-point attempts per game", ["safeties", "2-pt attempts"], ["pick-six and return-TD rates", "sack-rate adjustment", "punter hang time"]),
        F("nfl.dst_td_hazard", ["giveaway_rate_pre", "takeaway_td_rate_pre"], "EWMA giveaway rate per scrimmage play and defensive-TD rate per takeaway", ["giveaway and takeaway-TD rates"], ["shrinkage k=40", "returner threat from kick/punt return TDs"]),
        F("nfl.non_offensive_scoring_rate", ["nonoff_td_for_pre", "nonoff_score_for_pre", "nonoff_td_against_pre"], "EWMA (half-life 20) of defensive/special-teams TDs (and safeties) scored and conceded per game", ["scored/conceded non-offensive scores"], ["25-game window with half-life 12", "shrinkage k=40"]),
        F("nfl.opponent_ball_control_denial", ["neu_run_pre", "def_neu_run_pre", "drive_len_pre", "def_drive_len_pre"], "EWMA neutral-situation run rate and mean drive length, offence and as the defence faces them", ["neutral run rate", "drive length"], ["seconds per play", "12-game half-life-6 window"]),
        F("nfl.fourth_and_goal_policy", ["go_4th_goal_pre"], "EWMA go-for-it rate on 4th down and <=3 yards to go inside the goal-to-go zone", ["go rate 4th&goal<=3"], [m_coach, "win-probability adjustment"]),
        F("nfl.fourth_down_fg_decision_rate", ["go_4th_short_pre"], "EWMA go-for-it rate on 4th down with <=3 yards to go (all field positions), among go/punt/field-goal decisions", ["go rate on 4th & <=3"], [m_coach, "dependence on yard line, score and time"]),
        F("nfl.goal_to_go_pass_rate", ["gtg_db_rate_pre"], "EWMA dropback rate on goal-to-go scrimmage plays", ["goal-to-go dropback rate"], [m_coach, "down and score buckets"]),
        F("nfl.rush_explosive_tail_rate", ["rush_expl_pre", "def_rush_expl_pre"], "EWMA rate of designed rushes of 10+ yards, for and against", ["explosive-run rate for/against"], [m_opp, "25-game half-life-12 window"]),
        F("nfl.qb_dropback_to_attempt_leakage", ["db_leak_rate_pre"], "EWMA share of dropbacks that are sacks or scrambles (kneels/spikes excluded), team level", ["(sacks+scrambles)/dropbacks"], ["individual QB over his last 17 starts"]),
        F("nfl.endzone_exposure_plays", ["gl_plays_pre"], "EWMA (half-life 20) count of scrimmage plays run from the offense's own 5-yard line or deeper", ["own-end-zone plays"], ["punts from >=90", "per-play safety probability"]),
        F("nfl.own_one_yard_line_snap_rate", ["own1_pre"], "EWMA (half-life 20) count of scrimmage plays (kneels excluded) from the own 1-yard line", ["snap count at yardline_100==99"], ["negative-binomial rate with opponent factors"]),
    ]

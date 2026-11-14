"""College football team-game builders from public cfbfastR play-by-play (RESEARCH_ONLY): opponent-adjusted EPA ratings (offence / defence, rush / pass), drive rates, scoring-trip TD rate and points,
neutral-situation pass rate, havoc, goal-to-go run/pass mix.

Raw data: sportsdataverse-data `cfbfastR_cfb_pbp` release assets (CollegeFootballData-derived play-by-play), collected by `college_collect.py` with an explicit column allowlist: spread, over/under, win
probability, WPA and pregame-Elo columns are never loaded. No CFBD API call, no key. Upstream licence terms are not stated for the mirror (internal research use only).
Output table ``team`` keyed (game_id, team): every value for game G is computed from games on STRICTLY EARLIER DATES only, never the game's own plays.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .cbb_ext import _add, _decay, _ridge_state, _solve
from .core import FeatureSpec, prior_ewm

S = "CFB"
PL_COLS = ["game_id", "season", "pos_team", "def_pos_team", "home", "away", "period", "down", "distance", "yards_to_goal", "yards_gained", "EPA", "pos_score_diff_start", "rush", "pass", "pass_attempt", "sack", "int",
           "penalty_no_play", "drive_id", "drive_start_yards_to_goal", "drive_result", "rush_td", "pass_td", "pass_breakup_player_name", "fumble_forced_player_name", "start_date", "neutral_site"]
PL_CONTENT = ["period", "down", "distance", "yards_to_goal", "yards_gained", "EPA", "pos_score_diff_start", "rush", "pass", "pass_attempt", "sack", "int", "penalty_no_play", "drive_start_yards_to_goal", "drive_result",
              "rush_td", "pass_td", "pass_breakup_player_name", "fumble_forced_player_name"]
SC_CONTENT: list[str] = []
GARBAGE = {1: 43, 2: 38, 3: 35}           # |score diff| above this in the quarter = garbage time (quarter 4 and later: 28)
HALF_LIFE_DAYS, LAMBDA, LAMBDA_MU, RHO = 40.0, 6.0, 1.0, 0.6
MIN_PLAYS = {"epa": 20, "rush": 10, "pass": 10}
TRIP_DECAY, TRIP_N, TRIP_K, TD_SPLIT_K = 0.85, 10, 25.0, 30.0
HV_HL = 6


def load_raw(d) -> dict:
    d = Path(d) / "cfb"
    pl = pd.concat([pd.read_parquet(f, columns=PL_COLS) for f in sorted(d.glob("plays_*.parquet"))], ignore_index=True)
    games = pl.drop_duplicates("game_id")[["game_id", "start_date"]].copy(); games["game_date"] = pd.to_datetime(games.start_date.str[:10])
    return {"plays": pl, "schedule": games[["game_id", "game_date"]]}


def _team_games(raw: dict) -> pd.DataFrame:
    pl = raw["plays"]; pl = pl[pl.pos_team.notna() & pl.def_pos_team.notna()].copy()
    g = pl.drop_duplicates("game_id")[["game_id", "season", "home", "away", "neutral_site"]].merge(raw["schedule"], on="game_id")
    pl = pl[pl.game_id.isin(g.game_id)]
    rush = (pl.rush == 1) & (pl.penalty_no_play != True); pas = (pl["pass"] == 1) & (pl.penalty_no_play != True)   # noqa: E712
    scr = rush | pas
    thr = pl.period.map(lambda p: GARBAGE.get(int(p), 28) if pd.notna(p) else np.nan)
    ng = scr & (pl.pos_score_diff_start.abs() <= thr) & pl.EPA.notna()
    q = pd.DataFrame({"game_id": pl.game_id, "team": pl.pos_team, "drive_id": pl.drive_id, "scr": scr.astype(float), "rush_ng": (ng & rush).astype(float), "pass_ng": (ng & pas).astype(float), "ng": ng.astype(float)})
    q["epa_ng"] = np.where(ng, pl.EPA, 0.0); q["epa_rush"] = np.where(ng & rush, pl.EPA, 0.0); q["epa_pass"] = np.where(ng & pas, pl.EPA, 0.0)
    neu = scr & pl.down.isin([1, 2]) & (pl.pos_score_diff_start.abs() <= 7) & (pl.period <= 3)
    q["neu_n"] = neu.astype(float); q["neu_pass"] = (neu & pas).astype(float); q["dropbacks"] = pas.astype(float)
    havoc = scr & ((pl.sack == 1) | (rush & (pl.yards_gained < 0)) | (pl["int"] == 1) | pl.pass_breakup_player_name.notna() | pl.fumble_forced_player_name.notna())
    q["havoc"] = havoc.astype(float)
    gtg = scr & ((pl.yards_to_goal <= 10) | (pl.down.isin([3, 4]) & (pl.distance <= 2)))
    q["gtg_n"] = gtg.astype(float); q["gtg_run"] = (gtg & rush).astype(float); q["gtg_run_td"] = (gtg & rush & (pl.rush_td == 1)).astype(float); q["gtg_pass_n"] = (gtg & pas).astype(float); q["gtg_pass_td"] = (gtg & pas & (pl.pass_td == 1)).astype(float)
    q["rush_td"] = (rush & (pl.rush_td == 1)).astype(float); q["pass_td"] = (pas & (pl.pass_td == 1)).astype(float)
    q["first40"] = (scr & (pl.down == 1) & (pl.yards_to_goal <= 40)).astype(float)
    a = q.groupby(["game_id", "team"]).sum(numeric_only=True).drop(columns=["drive_id"], errors="ignore")
    # drive level
    d = pl[scr | pl.drive_result.notna()].assign(scr=scr.astype(float), first40=q.first40).dropna(subset=["drive_id", "drive_result"])
    dv = d.groupby(["game_id", "drive_id", "pos_team"]).agg(plays=("scr", "sum"), start=("drive_start_yards_to_goal", "first"), res=("drive_result", "first"), trip=("first40", "max")).reset_index()
    dv = dv[dv.plays >= 1]; dv["pts"] = np.where(dv.res == "TD", 7.0, np.where(dv.res == "FG", 3.0, 0.0)); dv["td"] = (dv.res == "TD").astype(float)
    dv["trip_pts"] = dv.pts * dv.trip; dv["trip_pts_sq"] = dv.trip_pts ** 2; dv["trip_td"] = dv.td * dv.trip
    b = dv.groupby(["game_id", "pos_team"]).agg(n_drv=("plays", "size"), drv_plays=("plays", "sum"), drv_start=("start", "sum"), drv_pts=("pts", "sum"), trips=("trip", "sum"), trip_td=("trip_td", "sum"), trip_pts=("trip_pts", "sum"), trip_pts_sq=("trip_pts_sq", "sum")).rename_axis(["game_id", "team"])
    o = a.join(b, how="outer").fillna(0.0).reset_index()
    rows = []
    for me, op, hv in (("home", "away", 1), ("away", "home", -1)):
        r = g[["game_id", "season", "game_date", "neutral_site", me, op]].rename(columns={me: "team", op: "opp"}); r["hv"] = np.where(r.neutral_site.fillna(False).astype(bool), 0, hv); rows.append(r)
    t = pd.concat(rows, ignore_index=True).merge(o.add_prefix("o_").rename(columns={"o_game_id": "game_id", "o_team": "team"}), on=["game_id", "team"], how="left")
    ag = o.add_prefix("a_").rename(columns={"a_game_id": "game_id", "a_team": "opp"})
    t = t.merge(ag, on=["game_id", "opp"], how="left")
    t = t[t.o_scr.notna() & t.a_scr.notna() & (t.o_scr > 0) & (t.a_scr > 0)].copy()
    t = t[t.game_date.notna()].copy(); t["date"] = t.game_date
    return t.sort_values(["date", "game_id", "hv", "team"], ascending=[True, True, False, True], kind="mergesort").reset_index(drop=True)


def _season_ridge(g: pd.DataFrame, ycol: str, prev: dict | None, major: set) -> tuple[pd.DataFrame, dict]:
    """Walk-forward ridge of ``ycol`` (the team's offensive per-play value in the game) on offence effect o_i, opponent defence effect d_j and a home term: half-life 40 days, penalty 6 games, prior mean 0.6 x previous final."""
    ids = sorted(major & (set(g.team) | set(g.opp))); T = len(ids) + 1; pos = {t: i for i, t in enumerate(ids)}; OTHER = len(ids)
    pr = np.zeros(2 + 2 * T)
    if prev is not None:
        pr[1] = prev["h"]
        for t, i in {**pos, "OTHER": OTHER}.items():
            if t in prev["o"]: pr[2 + i] = RHO * prev["o"][t]; pr[2 + T + i] = RHO * prev["d"][t]
    pen = np.full(2 + 2 * T, LAMBDA); pen[0] = LAMBDA_MU
    st = _ridge_state(2 + 2 * T); ge = g.assign(ti=g.team.map(pos).fillna(OTHER).astype(int), oi=g.opp.map(pos).fillna(OTHER).astype(int)); out = []; last = None
    for d in sorted(ge.date.unique()):
        if last is not None: _decay(st, 0.5 ** ((d - last).days / HALF_LIFE_DAYS))
        day = ge[ge.date == d]; th, _, _ = _solve(st, pr, pen)
        out.append(pd.DataFrame({"game_id": day.game_id.to_numpy(), "team": day.team.to_numpy(), "o": th[2 + day.ti.to_numpy()], "d": th[2 + T + day.ti.to_numpy()]}))
        ok = day[ycol].notna().to_numpy(); dd = day[ok]
        if len(dd):
            ti, oi = dd.ti.to_numpy(), dd.oi.to_numpy(); hv = dd.hv.to_numpy().astype(float)
            _add(st, np.stack([np.zeros(len(dd), int), np.ones(len(dd), int), 2 + ti, 2 + T + oi], 1), np.stack([np.ones(len(dd)), hv, np.ones(len(dd)), np.ones(len(dd))], 1), dd[ycol].to_numpy())
        last = d
    _decay(st, 0.5 ** (1 / HALF_LIFE_DAYS)); th, _, _ = _solve(st, pr, pen)
    names = {**pos, "OTHER": OTHER}
    return pd.concat(out, ignore_index=True), {"h": th[1], "o": {t: th[2 + i] for t, i in names.items()}, "d": {t: th[2 + T + i] for t, i in names.items()}}


def _wsum(t: pd.DataFrame, col: str, n: int = TRIP_N, decay: float = TRIP_DECAY) -> pd.Series:
    """sum over the team's previous n games (continuous across seasons) of decay^(k-1) x value, k = 1 for the most recent game; missing earlier games contribute 0."""
    g = t.groupby("team", sort=False)[col]; out = 0.0
    for k in range(1, n + 1): out = out + (decay ** (k - 1)) * g.shift(k).fillna(0.0)
    return out


def _lg(t: pd.DataFrame, cols: list[str]) -> dict:
    """league cumulative sums over strictly EARLIER dates for each column (aligned to the rows of t)."""
    day = t.groupby("date")[cols].sum().sort_index(); cs = day.cumsum() - day
    return {c: t.date.map(cs[c]).to_numpy() for c in cols}


def compute(raw: dict) -> dict:
    t = _team_games(raw); seasons = sorted(t.season.unique()); cnt = {s: pd.concat([t[t.season == s].team]).value_counts() for s in seasons}
    t["y_epa"] = np.where(t.o_ng >= MIN_PLAYS["epa"], t.o_epa_ng / t.o_ng.replace(0, np.nan), np.nan)
    t["y_rush"] = np.where(t.o_rush_ng >= MIN_PLAYS["rush"], t.o_epa_rush / t.o_rush_ng.replace(0, np.nan), np.nan)
    t["y_pass"] = np.where(t.o_pass_ng >= MIN_PLAYS["pass"], t.o_epa_pass / t.o_pass_ng.replace(0, np.nan), np.nan)
    res = {}
    for name in ("y_epa", "y_rush", "y_pass"):
        parts = []; prev = None
        for k, s in enumerate(seasons):
            major = {tm for q in (seasons[max(0, k - 2):k] or [s]) for tm, c in cnt[q].items() if c >= 8}
            r, prev = _season_ridge(t[t.season == s], name, prev, major)
            if k == 0: r[["o", "d"]] = np.nan
            parts.append(r)
        r = pd.concat(parts, ignore_index=True); res[name] = r
        m = t[["game_id", "team"]].merge(r, on=["game_id", "team"], how="left"); t["ppa_off_" + name[2:] + "_pre"] = m.o.to_numpy(); t["ppa_def_" + name[2:] + "_pre"] = m.d.to_numpy()
    t = t.sort_values(["date", "game_id", "hv", "team"], ascending=[True, True, False, True], kind="mergesort").reset_index(drop=True)
    pair = lambda cols: t[["game_id", "team", *cols]].rename(columns={"team": "opp", **{c: "opp_" + c for c in cols}})
    # --- drives (EWMA, half-life 6 games, min 3) + opponent-adjusted points per drive
    t["_dpg"] = t.o_n_drv; t["_ppd"] = t.o_drv_plays / t.o_n_drv.replace(0, np.nan); t["_avail"] = t.o_drv_start / t.o_n_drv.replace(0, np.nan); t["_pts"] = t.o_drv_pts / t.o_n_drv.replace(0, np.nan)
    t["_pts_allowed"] = t.a_drv_pts / t.a_n_drv.replace(0, np.nan)
    for c, nm in (("_dpg", "drv_n_pre"), ("_ppd", "drv_plays_pre"), ("_avail", "drv_avail_pre"), ("_pts", "drv_pts_pre"), ("_pts_allowed", "_pts_allowed_pre")): t[nm] = prior_ewm(t, "team", c, hl=HV_HL, min_periods=3)
    lg = _lg(t, ["o_drv_pts", "o_n_drv"]); t["_lg_dpts"] = lg["o_drv_pts"] / np.where(lg["o_n_drv"] > 0, lg["o_n_drv"], np.nan)
    t = t.merge(pair(["drv_n_pre", "_pts_allowed_pre"]), on=["game_id", "opp"], how="left")
    t["drv_pts_adj_pre"] = t.drv_pts_pre - t.opp__pts_allowed_pre + t._lg_dpts; t["drv_exp_drives_pre"] = (t.drv_n_pre + t.opp_drv_n_pre) / 2
    # --- scoring trips: decayed TD rate / points per trip, opponent-adjusted, shrunk
    for c in ("o_trips", "o_trip_td", "o_trip_pts", "o_trip_pts_sq", "a_trips", "a_trip_td", "a_trip_pts"): t["w" + c] = _wsum(t, c)
    lg = _lg(t, ["o_trips", "o_trip_td", "o_trip_pts", "o_trip_pts_sq"]); lg_n = np.where(lg["o_trips"] > 0, lg["o_trips"], np.nan)
    lg_td, lg_pt = lg["o_trip_td"] / lg_n, lg["o_trip_pts"] / lg_n; lg_var = np.maximum(lg["o_trip_pts_sq"] / lg_n - lg_pt ** 2, 0.0)
    t["_td_own"] = (t.wo_trip_td + TRIP_K * lg_td) / (t.wo_trips + TRIP_K); t["_td_alw"] = (t.wa_trip_td + TRIP_K * lg_td) / (t.wa_trips + TRIP_K)
    t["_pt_own"] = (t.wo_trip_pts + TRIP_K * lg_pt) / (t.wo_trips + TRIP_K); t["_pt_alw"] = (t.wa_trip_pts + TRIP_K * lg_pt) / (t.wa_trips + TRIP_K)
    t = t.merge(pair(["_td_alw", "_pt_alw"]), on=["game_id", "opp"], how="left")
    t["tdt_rate_adj_pre"] = t._td_own - t.opp__td_alw + lg_td; t["ste_adj_pre"] = t._pt_own - t.opp__pt_alw + lg_pt; t["ste_se_pre"] = np.sqrt(lg_var / (t.wo_trips + TRIP_K))
    # TD type split over the current and previous season (shrunk, k = 30 TDs)
    for c in ("o_rush_td", "o_pass_td"):
        t["_s_" + c] = t.groupby(["team", "season"], sort=False)[c].transform(lambda s: s.cumsum() - s)
    tot = t.groupby(["team", "season"])[["o_rush_td", "o_pass_td"]].sum().reset_index(); tot["season"] += 1; tot = tot.rename(columns={"o_rush_td": "_p_rush", "o_pass_td": "_p_pass"})
    t = t.merge(tot, on=["team", "season"], how="left"); t[["_p_rush", "_p_pass"]] = t[["_p_rush", "_p_pass"]].fillna(0.0)
    lgs = _lg(t, ["o_rush_td", "o_pass_td"]); lg_tot = lgs["o_rush_td"] + lgs["o_pass_td"]; lg_tot = np.where(lg_tot > 0, lg_tot, np.nan)
    rt, pt_ = t._s_o_rush_td + t._p_rush, t._s_o_pass_td + t._p_pass; n_td = rt + pt_
    t["tdt_rush_share_pre"] = (rt + TD_SPLIT_K * lgs["o_rush_td"] / lg_tot) / (n_td + TD_SPLIT_K); t["tdt_pass_share_pre"] = (pt_ + TD_SPLIT_K * lgs["o_pass_td"] / lg_tot) / (n_td + TD_SPLIT_K)
    # --- neutral-situation pass rate (decayed weights, shrunk k = 100 plays) and dropbacks per game
    for c in ("o_neu_n", "o_neu_pass", "a_neu_n", "a_neu_pass"): t["w" + c] = _wsum(t, c)
    lg = _lg(t, ["o_neu_n", "o_neu_pass"]); lg_pr = lg["o_neu_pass"] / np.where(lg["o_neu_n"] > 0, lg["o_neu_n"], np.nan)
    t["_pr_own"] = (t.wo_neu_pass + 100 * lg_pr) / (t.wo_neu_n + 100); t["_pr_alw"] = (t.wa_neu_pass + 100 * lg_pr) / (t.wa_neu_n + 100)
    t = t.merge(pair(["_pr_alw"]), on=["game_id", "opp"], how="left")
    t["pr_neutral_pre"] = t._pr_own; t["pr_neutral_allowed_pre"] = t._pr_alw; t["pr_exp_pre"] = t._pr_own + t.opp__pr_alw - lg_pr
    t["_db"] = t.o_dropbacks; t["_db_alw"] = t.a_dropbacks
    t["sapa_dropbacks_pre"] = prior_ewm(t, "team", "_db", hl=HV_HL, min_periods=3); t["_sapa_alw"] = prior_ewm(t, "team", "_db_alw", hl=HV_HL, min_periods=3)
    t = t.merge(pair(["_sapa_alw"]), on=["game_id", "opp"], how="left"); lgd = _lg(t, ["o_dropbacks"]); ng_ = t.groupby("date").size().sort_index(); cs_g = (ng_.cumsum() - ng_); lg_db = lgd["o_dropbacks"] / t.date.map(cs_g).to_numpy()
    t["sapa_opp_allowed_pre"] = t.opp__sapa_alw; t["sapa_exp_dropbacks_pre"] = t.sapa_dropbacks_pre + t.opp__sapa_alw - lg_db
    # --- havoc
    t["_hv_def"] = t.a_havoc / t.a_scr; t["_hv_off"] = t.o_havoc / t.o_scr
    t["hv_def_pre"] = prior_ewm(t, "team", "_hv_def", hl=HV_HL, min_periods=3); t["hv_off_allowed_pre"] = prior_ewm(t, "team", "_hv_off", hl=HV_HL, min_periods=3)
    lg = _lg(t, ["o_havoc", "o_scr"]); lg_hv = lg["o_havoc"] / np.where(lg["o_scr"] > 0, lg["o_scr"], np.nan)
    t = t.merge(pair(["hv_off_allowed_pre"]), on=["game_id", "opp"], how="left"); t["hv_def_adj_pre"] = t.hv_def_pre - t.opp_hv_off_allowed_pre + lg_hv
    # --- goal-to-go / short-yardage run-pass mix: current season weight 1, previous season 0.5, shrunk k = 40 plays
    keys = ["o_gtg_n", "o_gtg_run", "o_gtg_run_td", "o_gtg_pass_n", "o_gtg_pass_td"]
    for c in keys: t["_s_" + c] = t.groupby(["team", "season"], sort=False)[c].transform(lambda s: s.cumsum() - s)
    tot = t.groupby(["team", "season"])[keys].sum().reset_index(); tot["season"] += 1; tot = tot.rename(columns={c: "_p_" + c for c in keys})
    t = t.merge(tot, on=["team", "season"], how="left"); w = {c: t["_s_" + c] + 0.5 * t["_p_" + c].fillna(0.0) for c in keys}
    lg = _lg(t, keys); L = lambda a, b: lg[a] / np.where(lg[b] > 0, lg[b], np.nan)
    t["gtg_run_share_pre"] = (w["o_gtg_run"] + 40 * L("o_gtg_run", "o_gtg_n")) / (w["o_gtg_n"] + 40)
    t["gtg_td_rate_run_pre"] = (w["o_gtg_run_td"] + 40 * L("o_gtg_run_td", "o_gtg_run")) / (w["o_gtg_run"] + 40); t["gtg_td_rate_pass_pre"] = (w["o_gtg_pass_td"] + 40 * L("o_gtg_pass_td", "o_gtg_pass_n")) / (w["o_gtg_pass_n"] + 40)
    t = t.sort_values(["date", "game_id", "hv", "team"], ascending=[True, True, False, True], kind="mergesort").reset_index(drop=True)
    keep = ["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]
    return {"team": t[list(dict.fromkeys(keep))]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, ["cfbfastR_cfb_pbp"], "pregame_rolling")
    return [
        F("cfb.off_ppa", ["ppa_off_epa_pre", "ppa_off_rush_pre", "ppa_off_pass_pre"], "PARTIAL",
          "offence effect o_i of a walk-forward ridge of the team's non-garbage EPA per play (all / rush / pass) on offence and opponent-defence effects plus a home term (half-life 40 days, penalty 6, prior mean 0.6 x previous final); EPA is the play-by-play expected-points-added model output, not CFBD's PPA",
          ["EPA per non-garbage play", "garbage-time filter by quarter margin (43/38/35/28)", "rush / pass split", "ridge opponent adjustment with home term", "recency weights"],
          ["CFBD PPA proper (EPA used instead)", "preseason prior from returning production and recruiting talent (previous-season carry stand-in)", "current-QB split", "inverse-games blend weight 1/(1+n/k)"]),
        F("cfb.def_ppa", ["ppa_def_epa_pre", "ppa_def_rush_pre", "ppa_def_pass_pre"], "PARTIAL",
          "defence effect d_j (EPA per play allowed, positive = worse defence) from the same ridge fits, all / rush / pass",
          ["defensive effect in the same ridge framework", "rush / pass split", "garbage-time filter", "recency weights"],
          ["shrink toward a prior from returning defensive production and recruiting talent", "current injuries of defensive starters", "CFBD PPA proper"]),
        F("cfb.drives", ["drv_n_pre", "drv_plays_pre", "drv_avail_pre", "drv_pts_pre", "drv_pts_adj_pre", "drv_exp_drives_pre"], "PARTIAL",
          "EWMA (half-life 6 games) of drives per game, scrimmage plays per drive, mean drive start yards-to-goal, points per drive (TD 7, FG 3); opponent-adjusted points per drive; expected game drives = mean of both teams' rates",
          ["drives per game", "plays per drive", "available yards", "points per drive", "opponent adjustment"], ["drive-level success rate", "forecast of drives from expected script and turnover rates"]),
        F("cfb.td_per_scoring_trip", ["tdt_rate_adj_pre", "tdt_rush_share_pre", "tdt_pass_share_pre"], "PARTIAL",
          "trips = drives with a first-down scrimmage play at or inside the opponent 40; decay-0.85 weighted TD per trip over the last 10 games shrunk (k = 25 trips) to the league rate, opponent-adjusted by the opponent defence's shrunk rate allowed; rush / pass share of TDs over the current and previous season shrunk (k = 30 TDs)",
          ["trips definition", "TD per trip over 10 games with 0.85 decay", "opponent adjustment", "shrinkage k = 25 trips", "TD type split with shrinkage k = 30"], ["expected team TDs and negative-binomial dispersion (model outputs)", "'other' TD category (return TDs are not offensive trips)"]),
        F("cfb.scoring_trip_efficiency", ["ste_adj_pre", "ste_se_pre"], "PARTIAL",
          "points (TD 7, FG 3) per trip drive over the last 10 games with 0.85 decay, shrunk (k = 25) to the league mean, opponent-adjusted; SE = league per-trip sd / sqrt(effective trips + 25)",
          ["points per trip drive", "10 games, 0.85 decay", "opponent allowed adjustment", "shrinkage k = 25", "mean and SE"], ["kicker field-goal value adjustment", "shrinkage toward the conference mean (league mean used)", "additive deviation combination of offence and defence"]),
        F("cfb.pass_rate", ["pr_neutral_pre", "pr_neutral_allowed_pre", "pr_exp_pre"], "PARTIAL",
          "neutral-situation pass rate (downs 1-2, score within 7, first three quarters), decay-0.85 weighted over 10 games shrunk (k = 100 plays) to the league rate; rate allowed by the defence; additive expected rate",
          ["neutral-situation pass rate (non-garbage by construction)", "opponent rate allowed"], ["pass rate over expected by down/distance/score", "response slope to score difference", "forecast attempts under a script distribution"]),
        F("cfb.script_adjusted_pass_attempts", ["sapa_dropbacks_pre", "sapa_opp_allowed_pre", "sapa_exp_dropbacks_pre"], "PARTIAL",
          "EWMA (half-life 6 games) dropbacks per game (pass attempts + sacks), the opponent defence's dropbacks allowed, additive expected dropbacks",
          ["dropbacks per game", "opponent neutral allowed (dropback form)"], ["regression on neutral pass rate and expected margin with +/-14/21 terms", "negative-binomial dispersion", "expected margin from non-market ratings"]),
        F("cfb.havoc", ["hv_def_pre", "hv_off_allowed_pre", "hv_def_adj_pre"], "PARTIAL",
          "havoc play = sack, rush for a loss, interception, pass breakup or forced fumble on a scrimmage play; EWMA (half-life 6 games) rate by the defence, rate suffered by the offence, defence rate adjusted by the opponent's rate suffered",
          ["havoc rate with TFL, forced fumbles, PBU, INT", "defence and offence-allowed sides", "opponent adjustment"], ["turnover-luck process-vs-outcome comparison"]),
        F("cfb.goal_to_go_run_pass_mix", ["gtg_run_share_pre", "gtg_td_rate_run_pre", "gtg_td_rate_pass_pre"], "PARTIAL",
          "run share and TD rate by play type on plays inside the opponent 10 or 3rd/4th-and-2-or-less; current season weight 1 plus previous season weight 0.5; shrunk (k = 40 plays) to the league rate",
          ["run share inside the 10 and short yardage", "TD conversion rate by type", "decay 0.5 per season", "shrinkage k = 40"], ["score-state logistic conditioning", "expected rushing / receiving TD counts"]),
    ]

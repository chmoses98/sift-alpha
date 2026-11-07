"""MLB feature builders from the StatsAPI schedule/linescore/umpire/weather table (2015-2025) and boxscores (2024-2025) collected by alpha_engine.collect (RESEARCH_ONLY).
Output tables: ``team`` (team-game), ``pitcher`` (starting-pitcher start), ``hitter`` (hitter-game). IMPORTANT point-in-time limits are carried in each FeatureSpec: weather, officials and lineups are
retrieval-time values (no forecast or lineup-posting vintage); the probable pitcher is checked against the boxscore starter in the audit."""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, games_in_window, opp_adjusted, pair_rows, prior_count, prior_date_mean, prior_ewm, prior_mean, rest_days

S = "MLB"


def load_raw(p: Paths) -> dict:
    sch = pd.read_csv(p.raw / "mlb_schedule_games.csv.gz", parse_dates=["date"])
    box = pd.read_csv(p.raw / "mlb_player_games.csv.gz", parse_dates=["date"])
    return {"schedule": sch, "box": box}


def _wind(w):
    if not isinstance(w, str):
        return (np.nan, np.nan)
    m = re.match(r"\s*(\d+)\s*mph,?\s*(.*)", w)
    if not m:
        return (np.nan, np.nan)
    sp, d = float(m.group(1)), m.group(2).lower()
    out = sp if d.startswith("out") else (-sp if d.startswith("in") else 0.0)
    return (sp, out)


def _runs(js):
    try:
        return [x if x is not None else 0 for x in json.loads(js)]
    except Exception:
        return None


def _team(raw: dict) -> pd.DataFrame:
    g = raw["schedule"].copy()
    g = g[g.home_score.notna()].copy()
    w = g.wind.map(_wind)
    g["wind_speed"], g["wind_out"] = [a for a, _ in w], [b for _, b in w]
    g["roof_closed"] = g.weather_condition.isin(["Roof Closed", "Dome"]).astype(float)
    g["night"] = (g.day_night == "night").astype(float)
    hr, ar = g.home_runs_by_inning.map(_runs), g.away_runs_by_inning.map(_runs)
    rows = []
    for r, h_, a_ in zip(g.itertuples(index=False), hr, ar):
        for side, tid, oid, rs, ra, mine, theirs in (("h", r.home_id, r.away_id, r.home_score, r.away_score, h_, a_), ("a", r.away_id, r.home_id, r.away_score, r.home_score, a_, h_)):
            f = lambda lst, n: sum(lst[:n]) if lst and len(lst) >= n else np.nan
            rows.append({"game_id": r.game_pk, "date": r.date, "season": r.season, "team": tid, "opp": oid, "home": side == "h", "rs": rs, "ra": ra, "venue_id": r.venue_id, "ump": r.home_plate_ump_id,
                         "dh": float(r.double_header in ("Y", "S")), "night": float(r.day_night == "night"), "innings": r.innings_played, "r1": f(mine, 1), "ra1": f(theirs, 1), "r3": f(mine, 3), "ra3": f(theirs, 3),
                         "r5": f(mine, 5), "ra5": f(theirs, 5), "extra": float((r.innings_played or 9) > 9)})
    t = pd.DataFrame(rows)
    gm = g[["game_pk", "temp", "wind_speed", "wind_out", "roof_closed"]].rename(columns={"game_pk": "game_id"})
    t = t.merge(gm, on="game_id", how="left")
    return t.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)


def _team_features(t: pd.DataFrame, box: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["total"] = t.rs + t.ra
    t["won"] = (t.rs > t.ra).astype(float)
    t["yrfi"] = (t.r1 > 0).astype(float); t["nrfi_both"] = ((t.r1 == 0) & (t.ra1 == 0)).astype(float)
    t["f5_share"] = t.r5 / t.rs.replace(0, np.nan)
    for c in ("rs", "ra", "r1", "ra1", "r3", "ra3", "r5", "ra5", "extra", "yrfi", "nrfi_both", "total", "f5_share", "won"):
        t[f"{c}_pre"] = prior_ewm(t, "team", c, hl=15)
    t["runs_var_pre"] = t.groupby("team", sort=False)["total"].transform(lambda s: s.shift(1).rolling(40, min_periods=15).var())
    t = pair_rows(t, cols=["rs_pre", "ra_pre"]).sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    t["lg_rs_pre"] = prior_date_mean(t, "date", "rs")
    t["adj_rs"] = opp_adjusted(t, "rs", "opp_ra_pre", "lg_rs_pre"); t["adj_ra"] = opp_adjusted(t, "ra", "opp_rs_pre", "lg_rs_pre")
    t["off_adj_pre"] = prior_ewm(t, "team", "adj_rs", hl=15); t["def_adj_pre"] = prior_ewm(t, "team", "adj_ra", hl=15)
    # park: running mean of total runs at the venue over EARLIER dates relative to league (>=40 earlier games)
    hm = t[t.home][["game_id", "date", "venue_id", "total"]].copy()
    cs = prior_date_mean(hm, "date", "total", by="venue_id"); cn = hm.groupby("venue_id").cumcount()
    hm["park_runs_pre"] = (cs - prior_date_mean(hm, "date", "total")).where(cn >= 40)
    t = t.merge(hm[["game_id", "park_runs_pre"]], on="game_id", how="left")
    # plate umpire: running mean of total runs in the umpire's earlier games relative to league (>=40 earlier games)
    um = t[t.home][["game_id", "date", "ump", "total"]].dropna(subset=["ump"]).copy()
    cs = prior_date_mean(um, "date", "total", by="ump"); cn = um.groupby("ump").cumcount()
    um["ump_runs_pre"] = (cs - prior_date_mean(um, "date", "total")).where(cn >= 40)
    t = t.merge(um[["game_id", "ump_runs_pre"]], on="game_id", how="left")
    # schedule
    t["rest_days"] = rest_days(t, "team", cap=10); t["games_last7"] = games_in_window(t, "team", days=7)
    prev_night = t.groupby("team", sort=False)["night"].shift(1)
    t["day_after_night"] = ((t.night == 0) & (prev_night == 1) & (t.rest_days <= 1)).astype(float).where(t.rest_days.notna())
    t["games_played_pre"] = prior_count(t, ["team", "season"]); t["win_pct_pre"] = prior_mean(t, ["team", "season"], "won", min_periods=1)
    py = (t.rs ** 1.83) / (t.rs ** 1.83 + t.ra ** 1.83); t["_resid"] = t.won - py
    t["pythag_resid_pre"] = prior_mean(t, "team", "_resid", window=60, min_periods=25)
    # bullpen workload from boxscores (2024-25): non-starter pitches/outs by this team in the previous 1 and 3 CALENDAR days
    b = box[(box.pitches.notna()) & (box.gs != 1)].groupby(["team_id", "date"])[["pitches", "outs"]].sum().reset_index().rename(columns={"team_id": "team", "pitches": "bp_pitches", "outs": "bp_outs"})
    t = t.merge(b[["team", "date", "bp_pitches"]].assign(date=lambda d: d.date + pd.Timedelta(days=1)).rename(columns={"bp_pitches": "bullpen_pitches_yday"}), on=["team", "date"], how="left")
    for k in (2, 3):
        t = t.merge(b[["team", "date", "bp_pitches"]].assign(date=lambda d, k=k: d.date + pd.Timedelta(days=k)).rename(columns={"bp_pitches": f"_bp{k}"}), on=["team", "date"], how="left")
    t["bullpen_pitches_last3"] = t[["bullpen_pitches_yday", "_bp2", "_bp3"]].fillna(0).sum(axis=1).where(t.season >= 2024)
    t["bullpen_pitches_yday"] = t.bullpen_pitches_yday.fillna(0).where(t.season >= 2024)
    return t


def _pitchers(raw: dict, t: pd.DataFrame) -> pd.DataFrame:
    b = raw["box"]
    s = b[b.gs == 1].copy()
    s["pid"] = s.player_id
    s = s.merge(raw["schedule"][["game_pk", "home_id", "away_id"]], on="game_pk", how="left")
    s["opp"] = np.where(s.side == "home", s.away_id, s.home_id)
    s["ip"] = s.outs / 3.0
    s["k_rate"], s["bb_rate"] = s.k / s.bf.replace(0, np.nan), s.bb_alw / s.bf.replace(0, np.nan)
    s["hr_rate"] = s.hr_alw / s.bf.replace(0, np.nan)
    s["pitches_pbf"] = s.pitches / s.bf.replace(0, np.nan)
    s["er9"] = s.er / s.outs.replace(0, np.nan) * 27
    s["babip_alw"] = (s.h_alw - s.hr_alw) / (s.bf - s.bb_alw - s.k - s.hr_alw).replace(0, np.nan)
    s["big_pitch_day"] = (s.pitches >= 100).astype(float)
    s["short_start"] = (s.outs <= 12).astype(float)
    s = s.sort_values(["date", "game_pk"], kind="mergesort").reset_index(drop=True)
    for c in ("ip", "outs", "bf", "pitches", "k_rate", "bb_rate", "hr_rate", "pitches_pbf", "er9", "babip_alw", "big_pitch_day", "short_start"):
        s[f"{c}_pre"] = prior_ewm(s, "pid", c, hl=6, min_periods=2)
    s["rest_days"] = rest_days(s, "pid", cap=30); s["starts_pre"] = prior_count(s, "pid")
    # shrunk K-BB% (prior toward the pre-game league value, 150 batters)
    ck = s.groupby("pid", sort=False)["k"].transform(lambda x: x.shift(1).expanding().sum()); cb = s.groupby("pid", sort=False)["bb_alw"].transform(lambda x: x.shift(1).expanding().sum()); cf = s.groupby("pid", sort=False)["bf"].transform(lambda x: x.shift(1).expanding().sum())
    lg = prior_date_mean(s.assign(_r=(s.k - s.bb_alw) / s.bf.replace(0, np.nan)), "date", "_r")
    s["kbb_shrunk_pre"] = ((ck.fillna(0) - cb.fillna(0)) + 150 * lg) / (cf.fillna(0) + 150)
    s["babip_dev_pre"] = s.babip_alw_pre - prior_date_mean(s, "date", "babip_alw")
    # opponent lineup K% / BB% (team-level EWMA over the opponent's earlier games, from all batter rows)
    bt = b[b.pa.notna()].groupby(["team_id", "game_pk", "date"])[["pa", "so", "bb", "hr", "tb"]].sum().reset_index().rename(columns={"team_id": "opp"})
    bt = bt.sort_values(["date", "game_pk"], kind="mergesort").reset_index(drop=True)
    for c in ("so", "bb", "hr", "tb"):
        bt[f"_{c}r"] = bt[c] / bt.pa
    for c in ("so", "bb", "hr", "tb"):
        bt[f"opp_{c}_rate_pre"] = prior_ewm(bt, "opp", f"_{c}r", hl=15)
    s = s.merge(bt[["opp", "game_pk", "opp_so_rate_pre", "opp_bb_rate_pre", "opp_hr_rate_pre"]], on=["opp", "game_pk"], how="left")
    return s


def _hitters(raw: dict) -> pd.DataFrame:
    b = raw["box"]
    h = b[b.pa.notna() & (b.pa > 0)].copy()
    h["pid"] = h.player_id
    for c, n in (("hr", "hr_rate"), ("so", "k_rate"), ("bb", "bb_rate"), ("tb", "tb_rate"), ("rbi", "rbi_rate"), ("r", "r_rate"), ("h", "h_rate")):
        h[n] = h[c] / h.pa
    h["slot"] = (h.bat_order // 100).astype(float)
    h["obp_proxy"] = (h.h + h.bb) / h.pa
    h["started"] = h.bat_order.notna().astype(float)
    h["woba_proxy"] = (h.tb + h.bb) / h.pa
    h = h.sort_values(["date", "game_pk"], kind="mergesort").reset_index(drop=True)
    for c in ("hr_rate", "k_rate", "bb_rate", "tb_rate", "rbi_rate", "r_rate", "h_rate", "pa", "sb", "slot", "started", "obp_proxy", "woba_proxy"):
        h[f"{c}_pre"] = prior_ewm(h, "pid", c, hl=20, min_periods=5)
    h["form_dev_pre"] = prior_ewm(h, "pid", "woba_proxy", hl=5, min_periods=3) - h.woba_proxy_pre
    h["games_pre"] = prior_count(h, "pid"); h["rest_days"] = rest_days(h, "pid", cap=30)
    ch = h.groupby("pid", sort=False)["hr"].transform(lambda x: x.shift(1).expanding().sum()); cp = h.groupby("pid", sort=False)["pa"].transform(lambda x: x.shift(1).expanding().sum())
    lg = prior_date_mean(h.assign(_r=h.hr / h.pa), "date", "_r")
    h["hr_rate_shrunk_pre"] = (ch.fillna(0) + 200 * lg) / (cp.fillna(0) + 200)
    h["slot_pa_pre"] = h.groupby("slot", sort=False)["pa"].transform(lambda x: x.shift(1).expanding(min_periods=100).mean()) if False else np.nan
    return h


def _starter_match(raw: dict) -> dict:
    """Audit fact: how often the schedule's listed probable pitcher equals the boxscore starter (2024-25)."""
    s = raw["schedule"]; b = raw["box"]
    st = b[b.gs == 1][["game_pk", "side", "player_id"]]
    m = st.merge(s[["game_pk", "home_sp_id", "away_sp_id"]], on="game_pk")
    m["listed"] = np.where(m.side == "home", m.home_sp_id, m.away_sp_id)
    return {"n": int(len(m)), "match_rate": float((m.listed == m.player_id).mean())}


def compute(raw: dict) -> dict:
    t = _team_features(_team(raw), raw["box"])
    return {"team": t, "pitcher": _pitchers(raw, t), "hitter": _hitters(raw)}


def specs() -> list[FeatureSpec]:
    F = lambda cid, tab, cols, lvl, d, done=(), miss=(), raw=("mlb_schedule",), pit="pregame_rolling": FeatureSpec(S, cid, tab, list(cols), lvl, d, list(done), list(miss), list(raw), pit)
    T, P, H = "team", "pitcher", "hitter"
    BX = ("mlb_boxscores",)
    return [
        F("mlb.run_dist", T, ["rs_pre", "ra_pre", "runs_var_pre"], "PARTIAL", "EWMA (half-life 15) runs scored/allowed and rolling-40 variance of game total runs", ["run-scoring level and dispersion"], ["inning-level negative-binomial fit"]),
        F("mlb.opp_strength", T, ["off_adj_pre", "def_adj_pre"], "FULL", "opponent-adjusted runs scored/allowed (EWMA), re-centred on the pre-game league mean", ["opponent-adjusted offence and defence"]),
        F("mlb.first_inning", T, ["r1_pre", "ra1_pre", "yrfi_pre", "nrfi_both_pre"], "FULL", "EWMA first-inning runs for/against, share of games with the team scoring in the 1st, and share with no run by either side", ["RFI/YRFI base rates"]),
        F("mlb.f3_split", T, ["r3_pre", "ra3_pre"], "PARTIAL", "EWMA runs for/against through three innings", ["first-three-innings split"], ["top-of-order exposure"]),
        F("mlb.f5_split", T, ["r5_pre", "ra5_pre", "f5_share_pre"], "PARTIAL", "EWMA runs through five innings and the first-five share of the team's runs", ["first-five split"], ["starter vs bullpen attribution (needs starter outs)"]),
        F("mlb.extras_prob", T, ["extra_pre"], "PARTIAL", "EWMA share of the team's games that went past nine innings", ["extra-innings frequency"], ["tied-after-nine rate and ghost-runner rule effect"]),
        F("mlb.pythag_luck", T, ["pythag_resid_pre"], "PARTIAL", "mean over the last 60 earlier games of (win - Pythagorean expectation, exponent 1.83)", ["Pythagorean residual"], ["BaseRuns"]),
        F("mlb.park", T, ["park_runs_pre"], "PARTIAL", "mean total runs at the venue over earlier dates minus the league mean (>=40 earlier games)", ["run park factor"], ["HR/hit-type factors and dimensions"]),
        F("mlb.weather_pit", T, ["temp", "wind_speed", "wind_out", "roof_closed"], "PARTIAL", "recorded game-time temperature, wind speed, wind component (+out/-in) and roof/dome flag", ["observed conditions"], ["forecast vintage (the API returns the final recorded values)", "wind relative to park orientation"], pit="final_postgame"),
        F("mlb.umpire", T, ["ump_runs_pre"], "PARTIAL", "mean total runs in the home-plate umpire's earlier games minus the league mean (>=40 earlier games)", ["plate-umpire run tendency"], ["strike-zone size"], pit="final_postgame"),
        F("mlb.rest_travel", T, ["rest_days", "games_last7", "dh"], "PARTIAL", "days of rest, games in the previous 7 days and doubleheader flag", ["rest and density"], ["travel distance"], pit="schedule_known"),
        F("mlb.rest_day_patterns", T, ["day_after_night"], "FULL", "day game on <=1 day of rest following a night game", ["day-after-night flag"], pit="schedule_known"),
        F("mlb.bullpen", T, ["bullpen_pitches_yday", "bullpen_pitches_last3"], "PARTIAL", "relief pitches thrown by the team yesterday and in the previous 3 calendar days (2024-25 only)", ["bullpen fatigue"], ["leverage order, specific reliever availability", "history before 2024"], raw=BX),
        F("mlb.sp_workload", P, ["outs_pre", "bf_pre", "pitches_pre", "ip_pre"], "FULL", "EWMA (half-life 6 starts) outs, batters faced, pitches and innings per start", ["expected innings/BF/pitches"], raw=BX),
        F("mlb.leash", P, ["pitches_pre", "big_pitch_day_pre", "short_start_pre"], "PARTIAL", "EWMA pitches per start, share of starts with >=100 pitches and with <=12 outs", ["hook tendency of the pitcher"], ["manager-specific rules; score-state hooks"], raw=BX),
        F("mlb.sp_rest_days", P, ["rest_days", "starts_pre"], "PARTIAL", "days since the pitcher's previous start and number of earlier starts in the data", ["starter rest"], ["consecutive-start workload with relief appearances"], raw=BX),
        F("mlb.sp_quality", P, ["kbb_shrunk_pre", "er9_pre", "k_rate_pre"], "PARTIAL", "K-BB% shrunk toward the league (150 BF), EWMA ER/9 and K%", ["skill indicators"], ["Stuff+/SIERA/xFIP"], raw=BX),
        F("mlb.k_rates", P, ["k_rate_pre", "kbb_shrunk_pre", "opp_so_rate_pre"], "PARTIAL", "pitcher K% (EWMA) and the opponent's team strikeout rate (EWMA over its earlier games)", ["pitcher K%", "opposing K% (team level)"], ["CSW/whiff, lineup handedness weighting"], raw=BX),
        F("mlb.sp_efficiency", P, ["pitches_pbf_pre"], "PARTIAL", "EWMA pitches per batter faced", ["pitches per PA"], ["first-pitch strike rate"], raw=BX),
        F("mlb.pitcher_hr_vulnerability", P, ["hr_rate_pre", "opp_hr_rate_pre"], "PARTIAL", "pitcher HR per batter faced (EWMA) and the opponent's team HR rate", ["HR allowed rate"], ["HR/FB, barrels allowed"], raw=BX),
        F("mlb.babip_luck", P, ["babip_dev_pre"], "PROXY", "EWMA BABIP allowed minus the league mean (no expected-BABIP/xBABIP from batted-ball quality)", [], ["xBABIP"], raw=BX),
        F("mlb.plate_discipline", H, ["bb_rate_pre", "k_rate_pre"], "PARTIAL", "hitter BB% and K% (EWMA half-life 20 games)", ["walk and strikeout rates"], ["chase and zone-contact rates"], raw=BX),
        F("mlb.hitter_hr_profile", H, ["hr_rate_pre", "hr_rate_shrunk_pre"], "PARTIAL", "hitter HR per PA (EWMA) and HR/PA shrunk toward league (200 PA)", ["HR rate"], ["barrels, fly-ball and pull rates"], raw=BX),
        F("mlb.hitter_recent_form", H, ["form_dev_pre"], "PROXY", "EWMA (hl 5) minus EWMA (hl 20) of (TB+BB)/PA (no xwOBA)", [], ["xwOBA-based form"], raw=BX),
        F("mlb.playing_time_role", H, ["started_pre", "slot_pre", "pa_pre"], "PARTIAL", "share of the player's games in the starting lineup, usual batting slot and PA per game", ["starter vs bench role"], ["platoon splits"], raw=BX),
        F("mlb.expected_pa", H, ["slot_pre", "pa_pre"], "PARTIAL", "the hitter's usual lineup slot and EWMA PA per game", ["slot-based PA"], ["game-script dependence"], raw=BX),
        F("mlb.baserunning", H, ["sb_pre"], "PARTIAL", "EWMA stolen bases per game", ["steal rate"], ["sprint speed, catcher arm"], raw=BX),
        F("mlb.contact_dist", H, ["h_rate_pre", "tb_rate_pre"], "PARTIAL", "hit and total-base rates per PA (EWMA)", ["hit/TB rates"], ["count distributions given PA"], raw=BX),
        F("mlb.run_scoring_opportunity", H, ["r_rate_pre", "obp_proxy_pre"], "PARTIAL", "runs per PA and (H+BB)/PA", ["runs and on-base skill"], ["quality of hitters behind"], raw=BX),
    ]

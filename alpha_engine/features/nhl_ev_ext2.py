"""Phase 15 NHL team-game builders from the event archive (RESEARCH_ONLY): pregame starter probability, goalie minutes-in-net distribution, early-window goal rate, first-goal hazard,
period scoring split, overtime scoring rate, shots-on-goal-for rates and projected shots faced.

Raw data: owner's NHL-edge-finder player-event archive (players/team_states, goals, shots, goalies; NHL API derived, regular seasons 2021-22 .. 2025-26). Output table ``team`` keyed (game_id, team):
every value for game G uses games on STRICTLY EARLIER DATES only. In particular the starter flag, the goals and the shots of game G itself never enter its own features.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nba_ext3 import before

S = "NHL"
TS_COLS = ["game_id", "season", "game_date", "game_type", "team_id", "is_home", "sec_ev", "sec_pp", "sec_sh", "n_seconds"]
GO_COLS = ["game_id", "period", "period_type", "t_s", "is_home"]
SH_COLS = ["game_id", "is_home", "kind", "strength"]
GL_COLS = ["game_id", "team_id", "player_id", "starter", "toi_s"]
TS_CONTENT = ["sec_ev", "sec_pp", "sec_sh", "n_seconds"]
GO_CONTENT = ["period", "period_type", "t_s", "is_home"]
SH_CONTENT = ["is_home", "kind", "strength"]
GL_CONTENT = ["starter", "toi_s"]


def load_raw(nhl_dir) -> dict:
    h = Path(nhl_dir) / "players"
    cat = lambda stem, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / f"{stem}_*.parquet")))], ignore_index=True)
    return {"team_states": cat("team_states", TS_COLS), "goals": cat("goals", GO_COLS), "shots": cat("shots", SH_COLS), "goalies": cat("goalies", GL_COLS)}


def _rate(s, n):
    return np.where(n > 0, s / np.where(n > 0, n, 1.0), np.nan)


def _ewm(t, col, hl, mp):
    return t.groupby("team", sort=False)[col].transform(lambda s: s.shift(1).ewm(halflife=hl, min_periods=mp).mean())


def _prev(t, col):
    v = t[col].fillna(0.0)
    return v.groupby(t.team, sort=False).cumsum() - v


def _opp(t, cols):
    o = t[["game_id", "team", *cols]].rename(columns={"team": "opp", **{c: f"o_{c}" for c in cols}})
    return t.merge(o, on=["game_id", "opp"], how="left")


def _table(raw: dict) -> pd.DataFrame:
    t = raw["team_states"]; t = t[(t.game_type == 2) & (t.season <= 2025)].drop_duplicates(["game_id", "team_id"]).copy()
    t["date"] = pd.to_datetime(t.game_date); t = t.rename(columns={"team_id": "team"}); t["home"] = t.is_home.astype(bool)
    n = t.groupby("game_id").team.transform("size"); t = t[n == 2]
    o = t[["game_id", "team"]].rename(columns={"team": "opp"}); t = t.merge(o, on="game_id"); t = t[t.team != t.opp]
    for c in TS_CONTENT: t[c] = t[c].astype(float)
    t = t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    gids = set(t.game_id)
    # ---- goals: per (game, side) counts
    g = raw["goals"]; g = g[g.game_id.isin(gids)].copy(); g["home"] = g.is_home.astype(bool)
    reg = g.period_type.astype(str) == "REG"
    cnt = lambda m, nm: g[m].groupby(["game_id", "home"]).size().rename(nm).reset_index()
    parts = [cnt((g.period == 1) & (g.t_s < 600), "f10"), cnt((g.period == 1) & (g.t_s < 300), "f5"), cnt(g.period_type.astype(str) == "OT", "fot")] + [cnt(reg & (g.period == k), f"fp{k}") for k in (1, 2, 3)]
    for part in parts: t = t.merge(part, on=["game_id", "home"], how="left")
    cs = ["f10", "f5", "fot", "fp1", "fp2", "fp3"]
    t[cs] = t[cs].fillna(0.0)
    first = g.sort_values(["game_id", "t_s"], kind="mergesort").groupby("game_id").agg(tmin=("t_s", "min"))
    g2 = g.merge(first, left_on="game_id", right_index=True); g2 = g2[g2.t_s == g2.tmin].groupby("game_id").home.agg(["min", "max"])
    fh = g2[g2["min"] == g2["max"]]["min"]          # home flag of the side that scored first (dropped when both sides share the first time stamp)
    t["first_home"] = t.game_id.map(fh)
    ot_first = g[g.period_type.astype(str) == "OT"].groupby("game_id").t_s.min()        # game-clock second of the first overtime goal
    ot_len = (t.game_id.map(ot_first).astype(float) - 3600.0).clip(lower=0.0, upper=300.0).fillna(300.0)
    t["ot_sec"] = np.where(t.n_seconds > 3600.0, ot_len, 0.0)                              # n_seconds is the period grid (3600 or 4800), not the time actually played
    t["sf"] = np.where(t.first_home.isna(), 0.5, (t.first_home == t.home).astype(float))
    # ---- shots on goal by strength
    s = raw["shots"]; s = s[s.game_id.isin(gids) & s.kind.isin(["SOG", "GOAL"])].copy(); s["home"] = s.is_home.astype(bool)
    for st, nm in (("EV", "sog_ev"), ("PP", "sog_pp")):
        t = t.merge(s[s.strength == st].groupby(["game_id", "home"]).size().rename(nm).reset_index(), on=["game_id", "home"], how="left")
    t[["sog_ev", "sog_pp"]] = t[["sog_ev", "sog_pp"]].fillna(0.0)
    # ---- designated starter per team-game
    gl = raw["goalies"]; gl = gl[gl.game_id.isin(gids)].copy(); gl["st"] = (gl.starter == True).astype(int); gl["toi_s"] = gl.toi_s.astype(float)   # noqa: E712
    gl = gl.sort_values(["game_id", "team_id", "st", "toi_s", "player_id"], ascending=[True, True, False, False, True], kind="mergesort").drop_duplicates(["game_id", "team_id"])
    t = t.merge(gl.rename(columns={"team_id": "team", "player_id": "starter_id", "toi_s": "st_toi"})[["game_id", "team", "starter_id", "st_toi"]], on=["game_id", "team"], how="left")
    t = _opp(t, cs + ["sog_ev"]); t = t.rename(columns={f"o_{c}": f"a{c[1:]}" for c in cs})     # a10 = goals against in the window, ...
    return t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _goalies(t: pd.DataFrame) -> pd.DataFrame:
    cols = ("gs_top_share_pre", "gs_consec_pre", "gs_top_rest_pre", "top_id", "y")
    out = {c: np.full(len(t), np.nan) for c in cols}
    for _, g in t.groupby("team", sort=False):
        st = g.starter_id.to_numpy(float); dts = g.date.to_numpy(); idx = g.index.to_numpy()
        for i in range(len(g)):
            if i < 5: continue
            w = st[max(0, i - 20):i]; wd = dts[max(0, i - 20):i]; ok = ~np.isnan(w)
            if not ok.any(): continue
            best = None
            for gid in np.unique(w[ok]):
                pos = np.flatnonzero(w == gid); key = (len(pos), pos[-1])
                if best is None or key > best[0]: best = (key, gid, pos)
            _, top, pos = best
            j = idx[i]
            out["top_id"][j] = top; out["gs_top_share_pre"][j] = len(pos) / len(w)
            c = 0
            for v in w[::-1]:
                if v == top: c += 1
                else: break
            out["gs_consec_pre"][j] = c
            out["gs_top_rest_pre"][j] = min(float((dts[i] - wd[pos[-1]]) / np.timedelta64(1, "D")), 14.0)
            if not np.isnan(st[i]): out["y"][j] = float(st[i] == top)
    for c in cols: t[c] = out[c]
    prev_date = t.groupby("team", sort=False).date.shift(1)
    t["b2b"] = ((t.date - prev_date).dt.days == 1).astype(float)
    ok = t.y.notna().to_numpy(); yv = np.where(ok, t.y, 0.0)
    q = _rate(before(t, yv, by=("b2b",)), before(t, ok.astype(float), by=("b2b",)))
    t["_y"] = yv; t["_n"] = ok.astype(float)
    sy = t._y.groupby([t.team, t.b2b], sort=False).cumsum() - t._y; sn = t._n.groupby([t.team, t.b2b], sort=False).cumsum() - t._n
    t["gs_p_top_pre"] = np.where(t.top_id.notna(), (sy + 10.0 * q) / (sn + 10.0), np.nan)
    # ---- minutes-in-net distribution of the expected starter (the top goalie), from his earlier starts for any team
    starts = t[t.starter_id.notna() & t.st_toi.notna()][["date", "starter_id", "st_toi"]].sort_values(["date"], kind="mergesort")
    cls = {"lt40": (starts.st_toi < 2400), "40_55": (starts.st_toi >= 2400) & (starts.st_toi < 3300), "full": (starts.st_toi >= 3300)}
    one = np.ones(len(starts)); nl_by_date = pd.Series(before(starts, one), index=starts.index)
    lg = {}
    for k, m in cls.items():
        lg[k] = pd.DataFrame({"date": starts.date, "v": _rate(before(starts, m.astype(float)), nl_by_date.to_numpy())}).drop_duplicates("date").set_index("date").v
    hist = {gid: (g.date.to_numpy(), {k: np.cumsum(cls[k].loc[g.index].to_numpy(float)) for k in cls}) for gid, g in starts.groupby("starter_id", sort=False)}
    res = {k: np.full(len(t), np.nan) for k in cls}
    for i, (top, d) in enumerate(zip(t.top_id.to_numpy(), t.date)):
        if np.isnan(top) or d not in lg["full"].index: continue
        dts, cum = hist.get(top, (np.array([], dtype="datetime64[ns]"), None)); n = int(np.searchsorted(dts, np.datetime64(d), side="left"))
        for k in cls:
            q0 = lg[k].loc[d]
            if np.isnan(q0): continue
            res[k][i] = ((cum[k][n - 1] if n > 0 else 0.0) + 25.0 * q0) / (n + 25.0)
    for k in cls: t[f"gm_p_{k}_pre"] = res[k]
    return t


def _shrunk(t, col, hl, mp, k, cap):
    """EWMA of earlier games shrunk to the league mean over earlier dates: (n x ewma + k x league)/(n + k), n = min(earlier games, cap)."""
    n = t.groupby("team", sort=False).cumcount().clip(upper=cap).astype(float)
    lg = _rate(before(t, t[col]), before(t, np.ones(len(t))))
    return (n * _ewm(t, col, hl, mp) + k * lg) / (n + k)


def _goals(t: pd.DataFrame) -> pd.DataFrame:
    for c in ("f10", "a10", "f5", "a5", "sf"): t[f"{c}_s"] = _shrunk(t, c, 60, 10, 30.0, 120)
    t = _opp(t, ["f10_s", "a10_s"])
    la = (t.f10_s + t.o_a10_s) / 2.0; lb = (t.o_f10_s + t.a10_s) / 2.0
    t["ew_gf10_pre"] = t.f10_s; t["ew_ga10_pre"] = t.a10_s; t["ew_lambda_pre"] = la + lb; t["ew_p_goal_pre"] = 1.0 - np.exp(-(la + lb))
    t["fgh_gf5_pre"] = t.f5_s; t["fgh_ga5_pre"] = t.a5_s; t["fgh_p_first_pre"] = la / (la + lb); t["fgh_first_share_pre"] = t.sf_s
    # ---- period split of regulation goals (for + against)
    for k in (1, 2, 3): t[f"c{k}"] = t[f"fp{k}"] + t[f"ap{k}"]
    t["c_all"] = t.c1 + t.c2 + t.c3
    lt = before(t, t.c_all); tt = _prev(t, "c_all")
    for k in (1, 2, 3):
        sh = _rate(before(t, t[f"c{k}"]), lt)
        t[f"ps_lg_p{k}_pre"] = sh
        with np.errstate(invalid="ignore", divide="ignore"):
            t[f"ps_dev_p{k}_pre"] = (_prev(t, f"c{k}") + 300.0 * sh) / (tt + 300.0) / sh
    # ---- overtime scoring per 5 minutes
    t["t5"] = t.ot_sec / 300.0
    lg = _rate(before(t, t.fot), before(t, t.t5)); T = _prev(t, "t5")
    t["ot_gf5_pre"] = (_prev(t, "fot") + 20.0 * lg) / (T + 20.0); t["ot_ga5_pre"] = (_prev(t, "aot") + 20.0 * lg) / (T + 20.0)
    t = _opp(t, ["ot_gf5_pre", "ot_ga5_pre"])
    la = (t.ot_gf5_pre + t.o_ot_ga5_pre) / 2.0; lb = (t.o_ot_gf5_pre + t.ot_ga5_pre) / 2.0
    t["ot_p_decided_pre"] = 1.0 - np.exp(-(la + lb)); t["ot_p_win_pre"] = la / (la + lb)
    return t


def _sog(t: pd.DataFrame) -> pd.DataFrame:
    n = t.groupby("team", sort=False).cumcount().clip(upper=80).astype(float)
    t["sog_eva"] = t.o_sog_ev
    e = {c: _ewm(t, c, 40, 5) for c in ("sog_ev", "sog_pp", "sog_eva", "sec_ev", "sec_pp", "sec_sh")}
    lg_ev = 3600.0 * _rate(before(t, t.sog_ev), before(t, t.sec_ev)); lg_pp = 3600.0 * _rate(before(t, t.sog_pp), before(t, t.sec_pp))
    with np.errstate(invalid="ignore", divide="ignore"):
        t["os_ev60_pre"] = (n * (3600.0 * e["sog_ev"] / e["sec_ev"]) + 15.0 * lg_ev) / (n + 15.0)
        t["os_pp60_pre"] = (n * (3600.0 * e["sog_pp"] / e["sec_pp"]) + 15.0 * lg_pp) / (n + 15.0)
        t["os_eva60_pre"] = (n * (3600.0 * e["sog_eva"] / e["sec_ev"]) + 15.0 * lg_ev) / (n + 15.0)
    t = _opp(t, ["os_ev60_pre", "os_pp60_pre"])
    t["os_exp_sog_faced_pre"] = lg_ev * (t.o_os_ev60_pre / lg_ev) * (t.os_eva60_pre / lg_ev) * (e["sec_ev"] / 3600.0) + t.o_os_pp60_pre * (e["sec_sh"] / 3600.0)
    return t


def compute(raw: dict) -> dict:
    t = _table(raw)
    t = _goalies(t); t = _goals(t); t = _sog(t)
    out = t[["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]].copy()
    return {"team": out.loc[:, ~out.columns.duplicated()]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, d, done, miss, raw: FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, list(raw), "pregame_rolling")
    return [
        F("nhl.goalie_start", ["gs_top_share_pre", "gs_consec_pre", "gs_top_rest_pre", "gs_p_top_pre"],
          "pregame (before confirmation) starter model from EARLIER games only: the team's top goalie = most frequent starter over its last 20 games; his start share, current consecutive starts, days since his last start (cap 14), and P(top goalie starts) = the team's earlier rate in the same back-to-back class shrunk to the league rate with 10 pseudo-games",
          ["P(starter) before confirmation from rest days, back-to-back second-game rate and consecutive starts"],
          ["timestamped announcements from each source and the confirmation time", "P = 1 after confirmation and the confirmed identity", "coach pattern"], ("nhl_goalie_games", "nhl_team_states")),
        F("nhl.goalie_minutes_in_net_dist", ["gm_p_lt40_pre", "gm_p_40_55_pre", "gm_p_full_pre"],
          "for the team's expected starter (top goalie over the last 20 games): share of his earlier starts with time on ice < 40:00, 40:00-55:00 and >= 55:00, each shrunk to the league share over earlier dates with 25 pseudo-starts",
          ["empirical pmf of minutes conditional on starting: pulled before 40:00, 40-55, full + OT", "shrinkage with k = 25 starts"],
          ["history since 2015-16 (2021-22 onward archived)", "team-coach level in the shrinkage", "pull hazard by first-period goals allowed", "mixture with P(start) and the fair-price no-start component"], ("nhl_goalie_games", "nhl_team_states")),
        F("nhl.early_window_goal_rate", ["ew_gf10_pre", "ew_ga10_pre", "ew_lambda_pre", "ew_p_goal_pre"],
          "team goals for and against in minutes 0:00-9:59 of period one per game (EWMA half-life 60 games, shrunk 30 games to the league mean), window goal expectation for the pair = mean of offence and opposing defence for both sides, P(at least one goal) = 1 - exp(-lambda)",
          ["goals for and against in the first 10:00", "half-life 60 games, shrunk 30 games to league", "lambda for the pair and P(YES)"],
          ["5v5 / power-play split and early-penalty rate", "opposing goalie GSAx adjustment", "negative-binomial dispersion", "history since 2018-19 (2021-22 onward archived)"], ("nhl_goals", "nhl_team_states")),
        F("nhl.first_goal_hazard", ["fgh_gf5_pre", "fgh_ga5_pre", "fgh_p_first_pre", "fgh_first_share_pre"],
          "team goals for and against in the first 5 minutes per game (EWMA half-life 60 games, shrunk 30 games), P(team scores first) = rate_A/(rate_A + rate_B) from the pair's first-10-minute rates, and the team's shrunk share of earlier games in which it scored first",
          ["per-team goal rates for the first 5 and 10 minutes", "first-goal team probability = rate_A/(rate_A + rate_B)"], ["first-period power-play adjustment", "explicit home-advantage term", "goalie-quality term"], ("nhl_goals", "nhl_team_states")),
        F("nhl.period_split", ["ps_lg_p1_pre", "ps_lg_p2_pre", "ps_lg_p3_pre", "ps_dev_p1_pre", "ps_dev_p2_pre", "ps_dev_p3_pre"],
          "league share of regulation goals by period over earlier dates and the team's multiplicative deviation from it (team games' goals for + against by period, shrunk with 300 pseudo-goals)",
          ["league period shape of goals", "team-specific multiplicative deviations with heavy shrinkage"], ["shot shape by period", "per-season league shape", "Poisson/negative-binomial period distributions", "joint period correlation"], ("nhl_goals", "nhl_team_states")),
        F("nhl.ot_3v3_rate", ["ot_gf5_pre", "ot_ga5_pre", "ot_p_decided_pre", "ot_p_win_pre"],
          "regular-season overtime goals for and against per 5 overtime minutes over all earlier games, shrunk to the league rate with 20 pseudo-periods; P(overtime is decided before the shootout) = 1 - exp(-(lambda_A + lambda_B)) and the team's share lambda_A/(lambda_A + lambda_B)",
          ["team overtime goals-for/against per 5 minutes with shrinkage", "P(OT win) before the shootout"], ["skater-count check (4v3 power plays in overtime are included)", "star-player overtime TOI shares", "multi-season weighting"], ("nhl_goals", "nhl_team_states")),
        F("nhl.opp_sog_for_rate", ["os_ev60_pre", "os_pp60_pre", "os_eva60_pre", "os_exp_sog_faced_pre"],
          "shots on goal for per 60 at even strength and on the power play and even-strength shots on goal against per 60 (EWMA half-life 40 games of counts over seconds, shrunk to the league rate with 15 games); projected shots faced = league x opponent offence x own defence x projected even-strength minutes + opponent power-play rate x projected short-handed minutes",
          ["SOG for per 60 by strength state with a 40-game half-life and k = 15 shrinkage", "log-additive combination with the defending team's SOG-against", "projection by state minutes"],
          ["score-and-venue adjustment", "5v5-only and 5v4-only states (all even-strength and all power-play time are used)"], ("nhl_shots_xy", "nhl_team_states")),
    ]

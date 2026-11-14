"""Phase 15 NHL team-game builders from game results and team-game xG (RESEARCH_ONLY): settlement-adjusted margin probabilities, team season points distribution, playoff context ratios,
series context (series win probability by dynamic programming), xG-based scoring rates and score-script probabilities.

Raw data: owner's NHL-edge-finder archive: NHL API game results (nhl/games_*.parquet, 2008-2025) and MoneyPuck team-game rows, situation 'all' (moneypuck/team_games_*.parquet; xG is a published
model output, MoneyPuck terms unresolved -> internal research only). Output table ``team`` keyed (game_id, team): every value for game G uses games on STRICTLY EARLIER DATES only, never the game's own result.
"""
from __future__ import annotations

import glob
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nba_ext3 import before

S = "NHL"
G_COLS = ["game_id", "season", "game_type", "game_date", "home_team_id", "away_team_id", "home_score", "away_score", "last_period_type", "final"]
MP_COLS = ["game_id", "team_id", "situation", "iceTime", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"]
G_CONTENT = ["home_score", "away_score", "last_period_type"]
MP_CONTENT = ["iceTime", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"]
SEASON_GAMES = {2012: 48, 2020: 56}        # scheduled regular-season length where it was not 82 (known before the season started)


def load_raw(nhl_dir) -> dict:
    h = Path(nhl_dir)
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    mp = cat("moneypuck/team_games_*.parquet", MP_COLS)
    return {"games": cat("nhl/games_*.parquet", G_COLS), "mp": mp[mp.situation == "all"].reset_index(drop=True)}


def _rows(raw: dict) -> pd.DataFrame:
    g = raw["games"]; g = g[g.final == True].copy(); g["date"] = pd.to_datetime(g.game_date)   # noqa: E712
    rows = []
    for side, opp, me_s, op_s, home in (("home_team_id", "away_team_id", "home_score", "away_score", True), ("away_team_id", "home_team_id", "away_score", "home_score", False)):
        rows.append(pd.DataFrame({"game_id": g.game_id.astype("int64"), "team": g[side].astype("int64"), "opp": g[opp].astype("int64"), "date": g.date, "season": g.season.astype("int64"), "gtype": g.game_type.astype("int64"), "home": home,
                                  "gf": g[me_s].astype(float), "ga": g[op_s].astype(float), "lpt": g.last_period_type.astype(str)}))
    t = pd.concat(rows, ignore_index=True)
    t["beyond"] = t.lpt.isin(["OT", "SO"]).astype(float); t["win"] = (t.gf > t.ga).astype(float)
    return t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _opp(t, cols):
    o = t[["game_id", "team", *cols]].rename(columns={"team": "opp", **{c: f"o_{c}" for c in cols}})
    return t.merge(o, on=["game_id", "opp"], how="left")


def _rate(s, n):
    return np.where(n > 0, s / np.where(n > 0, n, 1.0), np.nan)


def _settlement(t: pd.DataFrame) -> pd.DataFrame:
    reg = (t.gtype == 2)
    t["rgd"] = np.where(reg, np.where(t.beyond == 1, 0.0, t.gf - t.ga), np.nan)          # regulation goal difference (a game beyond regulation was tied after 60 minutes)
    r = t[reg].groupby("team", sort=False).rgd.transform(lambda s: s.shift(1).ewm(halflife=40, min_periods=10).mean())
    t["r_pre"] = r.reindex(t.index)
    t = _opp(t, ["r_pre"])
    gap = t.r_pre - t.o_r_pre
    b = np.where(gap.isna() | ~reg, np.nan, np.where(gap < -0.75, 0.0, np.where(gap < -0.25, 1.0, np.where(gap < 0.25, 2.0, np.where(gap < 0.75, 3.0, 4.0)))))
    t["bkt"] = b; t["hm"] = t.home.astype(float)
    ok = ~np.isnan(b); d = t.gf - t.ga
    ev = {"regtie": t.beyond, "ge1": (d >= 1).astype(float), "ge2": (d >= 2).astype(float), "ge3": (d >= 3).astype(float)}
    nc = before(t, ok.astype(float), by=("bkt", "hm")); nl = before(t, ok.astype(float))
    for k, v in ev.items():
        v = np.where(ok, v, 0.0)
        L = _rate(before(t, v), nl)
        t[f"sg_p_{k}_pre"] = np.where(ok, (before(t, v, by=("bkt", "hm")) + 200.0 * L) / (nc + 200.0), np.nan)
    return t


def _season_points(t: pd.DataFrame) -> pd.DataFrame:
    reg = (t.gtype == 2).to_numpy(); z = lambda v: np.where(reg, v, 0.0)
    t["rg"] = reg.astype(float)
    t["rw"] = z(t.win * (1 - t.beyond)); t["ew"] = z(t.win * t.beyond); t["el"] = z((1 - t.win) * t.beyond)
    ks = ("team", "season")
    sp = lambda c: t[c].groupby([t[k] for k in ks], sort=False).cumsum() - t[c]
    n, rw, ew, el = sp("rg"), sp("rw"), sp("ew"), sp("el")
    nl = before(t, t.rg); q = {c: _rate(before(t, t[c]), nl) for c in ("rw", "ew", "el")}
    prw, pew, pel = ((x + 20.0 * q[c]) / (n + 20.0) for x, c in ((rw, "rw"), (ew, "ew"), (el, "el")))
    ppg = 2.0 * (prw + pew) + pel; var = 4.0 * (prw + pew) + pel - ppg ** 2
    R = np.maximum(t.season.map(lambda s: SEASON_GAMES.get(int(s), 82)).astype(float) - n, 0.0)
    pts = 2.0 * (rw + ew) + el
    t["tp_points_pre"] = np.where(reg, pts, np.nan)
    t["tp_exp_final_pre"] = np.where(reg, pts + R * ppg, np.nan)
    t["tp_sd_final_pre"] = np.where(reg, np.sqrt(R * var), np.nan)
    return t


def _playoff_context(t: pd.DataFrame) -> pd.DataFrame:
    h = t.home.to_numpy(); out = {}
    for gt in (2, 3):
        m = h & (t.gtype == gt).to_numpy(); n = before(t, m.astype(float))
        out[gt] = (_rate(before(t, np.where(m, t.gf + t.ga, 0.0)), n), _rate(before(t, np.where(m, t.beyond, 0.0)), n), _rate(before(t, np.where(m, t.win, 0.0)), n))
    with np.errstate(invalid="ignore", divide="ignore"):
        for i, nm in enumerate(("goals", "ot", "homewin")):
            den = out[2][i]
            t[f"pc_{nm}_ratio_pre"] = np.where(den > 0, out[3][i] / np.where(den > 0, den, 1.0), np.nan)
    return t


def _series_p(w1: int, w2: int, k: int, ph: float) -> float:
    """P(the team that hosted game 1 wins a best-of-seven) from the state entering game k (2-2-1-1-1: it hosts games 1, 2, 5, 7); ph = P(home team wins a game)."""
    @lru_cache(maxsize=None)
    def f(a, b, g):
        if a >= 4: return 1.0
        if b >= 4: return 0.0
        if g > 7: return 0.5
        p = ph if g in (1, 2, 5, 7) else 1.0 - ph
        return p * f(a + 1, b, g + 1) + (1.0 - p) * f(a, b + 1, g + 1)
    return f(w1, w2, k)


def _series(t: pd.DataFrame) -> pd.DataFrame:
    po = t[t.gtype == 3].copy()
    po["skey"] = po.season.astype(str) + "|" + po[["team", "opp"]].min(axis=1).astype(str) + "|" + po[["team", "opp"]].max(axis=1).astype(str)
    hm = (t.home & (t.gtype == 3)).to_numpy(); n = before(t, hm.astype(float)); ph = np.where(n >= 50, before(t, np.where(hm, t.win, 0.0)) / np.where(n > 0, n, 1.0), np.nan)
    t["sc_p_home_hist_pre"] = np.where(t.gtype == 3, ph, np.nan)
    psr = np.full(len(t), np.nan); gdf = np.full(len(t), np.nan); phv = t.sc_p_home_hist_pre.to_numpy()
    for _, s in po.groupby("skey", sort=False):
        gids = list(dict.fromkeys(s.game_id.tolist()))
        first = s[s.game_id == gids[0]]; top = int(first[first.home].team.iloc[0]) if first.home.any() else int(first.team.min())
        wins: dict = {}; gd: dict = {}
        for k, gid in enumerate(gids, start=1):
            rows = s[s.game_id == gid]
            for i, r in rows.iterrows():
                w_me, w_op = wins.get(r.team, 0), wins.get(r.opp, 0)
                gdf[i] = gd.get(r.team, 0.0)
                if not np.isnan(phv[i]):
                    pt = _series_p(w_me, w_op, k, float(phv[i])) if r.team == top else 1.0 - _series_p(w_op, w_me, k, float(phv[i]))
                    psr[i] = pt
            for r in rows.itertuples():
                wins[r.team] = wins.get(r.team, 0) + int(r.win); gd[r.team] = gd.get(r.team, 0.0) + (r.gf - r.ga)
    t["sc_p_series_pre"] = psr; t["sc_goal_diff_pre"] = gdf
    return t


def _wlast_nan(x: np.ndarray, n: int, hl: float, minobs: int):
    """for each i: weighted mean of the non-NaN values among x[i-n..i-1], weight 0.5**(age/hl) with age = 1 for x[i-1]; (mean, number of non-NaN values used); NaN mean if fewer than minobs."""
    m = np.full(len(x), np.nan); k = np.zeros(len(x))
    for i in range(len(x)):
        seg = x[max(0, i - n):i][::-1]; w = 0.5 ** (np.arange(1, len(seg) + 1) / hl); ok = ~np.isnan(seg); k[i] = ok.sum()
        if k[i] >= minobs: m[i] = float((seg[ok] * w[ok]).sum() / w[ok].sum())
    return m, k


def _pois(lam: float, kmax: int = 15) -> np.ndarray:
    return np.array([math.exp(-lam) * lam ** i / math.factorial(i) for i in range(kmax + 1)])


def _xg(t: pd.DataFrame, raw: dict) -> pd.DataFrame:
    mp = raw["mp"].dropna(subset=["game_id", "team_id"]).drop_duplicates(["game_id", "team_id"]).rename(columns={"team_id": "team"})
    mp = mp.astype({"game_id": "int64", "team": "int64"})
    t = t.merge(mp[["game_id", "team", "iceTime", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"]], on=["game_id", "team"], how="left")
    reg = (t.gtype == 2)
    ice = t.iceTime.astype(float).where(t.iceTime > 0) / 3600.0
    t["xgf60"] = (t.scoreVenueAdjustedxGoalsFor.astype(float) / ice).where(reg); t["xga60"] = (t.scoreVenueAdjustedxGoalsAgainst.astype(float) / ice).where(reg)
    res = {}
    for _, g in t[reg].groupby("team", sort=False):
        for c in ("xgf60", "xga60"):
            m, k = _wlast_nan(g[c].to_numpy(float), 40, 20.0, 5)
            res[c] = res.get(c, {}); res[c].update(dict(zip(g.index, zip(m, k))))
    okf = t.xgf60.notna().to_numpy(); nl = before(t, okf.astype(float)); lg = _rate(before(t, t.xgf60.fillna(0.0)), nl)
    for c, nm in (("xgf60", "rs_xgf60_pre"), ("xga60", "rs_xga60_pre")):
        m = np.array([res[c].get(i, (np.nan, 0.0))[0] for i in t.index]); k = np.array([res[c].get(i, (np.nan, 0.0))[1] for i in t.index])
        t[nm] = (k * m + 25.0 * lg) / (k + 25.0)
    hm = (t.home & t.xgf60.notna() & t.xga60.notna()).to_numpy(); hn = before(t, hm.astype(float)); hc = _rate(before(t, np.where(hm, t.xgf60 - t.xga60, 0.0)), hn)
    t = _opp(t, ["rs_xga60_pre"])
    t["rs_lambda_pre"] = lg * (t.rs_xgf60_pre / lg) * (t.o_rs_xga60_pre / lg) + np.where(t.home, 0.5, -0.5) * hc
    t = _opp(t, ["rs_lambda_pre"])
    la = t.rs_lambda_pre.to_numpy(); lb = t.o_rs_lambda_pre.to_numpy()
    out = {c: np.full(len(t), np.nan) for c in ("gsp_lead20_pre", "gsp_tied20_pre", "gsp_lead40_pre", "gsp_tied40_pre")}
    for i in range(len(t)):
        if np.isnan(la[i]) or np.isnan(lb[i]) or la[i] <= 0 or lb[i] <= 0: continue
        for T in (20, 40):
            pa, pb = _pois(la[i] * T / 60.0), _pois(lb[i] * T / 60.0)
            J = np.outer(pa, pb)
            out[f"gsp_lead{T}_pre"][i] = float(np.tril(J, -1).sum()); out[f"gsp_tied{T}_pre"][i] = float(np.trace(J))
    for c, v in out.items(): t[c] = v
    return t


def compute(raw: dict) -> dict:
    t = _rows(raw)
    t = _settlement(t); t = _season_points(t); t = _playoff_context(t); t = _series(t); t = _xg(t, raw)
    out = t[["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]].copy()
    return {"team": out.loc[:, ~out.columns.duplicated()]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, d, done, miss, raw=("nhl_games",): FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, list(raw), "pregame_rolling")
    return [
        F("nhl.settlement_goal_pmf", ["sg_p_regtie_pre", "sg_p_ge1_pre", "sg_p_ge2_pre", "sg_p_ge3_pre"],
          "regular season: P(regulation tie) and P(settlement margin >= 1, 2, 3) (overtime and shootout wins count as +1) as empirical rates over earlier team rows in the same (rating-gap bucket, home/away) cell, shrunk to the league rate with 200 pseudo-rows; rating = EWMA (half-life 40 games) of the regulation goal difference, gap buckets at +-0.25 and +-0.75",
          ["P(margin >= m) for m = 1..3 per team", "P(regulation tie)", "settlement convention: an extra-time or shootout win is a one-goal margin"],
          ["bivariate overdispersed count model at 55:00 and the final-5-minute pull/6v5 jump process", "3v3 overtime hazard and shootout talent (k = 60 attempts)", "m = 4..6", "validation against the league margin histogram"]),
        F("nhl.team_season_points_distribution", ["tp_points_pre", "tp_exp_final_pre", "tp_sd_final_pre"],
          "regular season: standings points to date, expected final points = points to date + remaining scheduled games x points per game, and its sd, from the team's season-to-date P(regulation win), P(extra-time win), P(extra-time loss) each shrunk to the league rate over earlier dates with 20 pseudo-games (independent identical games)",
          ["points = 2 x wins + 1 x extra-time losses", "points to date plus remaining games", "per-game P(regulation win), P(OT/SO win), P(OT/SO loss)"],
          ["per-game probabilities from the team ratings posterior (xG differential, goalie GSAx, PDO regression, home and rest)", "opponent-specific remaining schedule", "simulation of 20000 seasons with a rating draw", "joint distribution across teams and tiebreaks"]),
        F("nhl.playoff_context", ["pc_goals_ratio_pre", "pc_ot_ratio_pre", "pc_homewin_ratio_pre"],
          "ratio of playoff to regular-season league means over all earlier dates: total goals per game, share of games beyond regulation, home win rate",
          ["historic playoff/regular-season ratio of goals per game", "multiplicative adjustment factors as of the game date"], ["TOI by line position ratio", "penalties per game ratio", "application inside the downstream models"]),
        F("nhl.series_context", ["sc_p_series_pre", "sc_goal_diff_pre", "sc_p_home_hist_pre"],
          "playoff rows: P(team wins the series) by dynamic programming over the remaining games of a best-of-seven (2-2-1-1-1) from the series score entering the game with per-game P(home win) = the historical playoff home-win rate over earlier dates (>= 50 games), plus the cumulative series goal difference",
          ["dynamic program over remaining games with home/away per-game probabilities", "series state (wins, games played) encoded"],
          ["per-game probabilities from ratings adjusted for injuries (a league home-win rate is used)", "rest days", "simulation", "2020 best-of-five qualifying and round-robin formats (treated as best-of-seven)"]),
        F("nhl.ratings_script_distribution", ["rs_xgf60_pre", "rs_xga60_pre", "rs_lambda_pre"],
          "regular season: score-and-venue-adjusted xG for and against per 60 over the last 40 games (half-life 20 games) shrunk 25 games toward the league mean, and the expected goal rate lambda = league x attack x opponent defence + half the league home edge (all from earlier dates)",
          ["ratings from score-adjusted xGF/xGA per 60 over a 40-game window with 20-game half-life shrunk 25 games to the league mean", "lambda = league mean x attack x defence", "home-ice constant"],
          ["5v5 and special-teams split", "goalie factor (starter GSAx)", "negative-binomial simulation of 20000 games with score effects, pull rule and event times", "home constant from 5 seasons only"], ("nhl_games", "moneypuck_team_games")),
        F("nhl.game_script_prob", ["gsp_lead20_pre", "gsp_tied20_pre", "gsp_lead40_pre", "gsp_tied40_pre"],
          "P(team leads) and P(tied) after 20 and 40 minutes from two independent Poisson counts with rates lambda x T/60 (own and opponent lambda of nhl.ratings_script_distribution), goal counts truncated at 15",
          ["lead/trail/tied probabilities by period from team ratings"], ["simulation with score effects", "expected fraction of time in each score state", "calibration against historical score states"], ("nhl_games", "moneypuck_team_games")),
    ]

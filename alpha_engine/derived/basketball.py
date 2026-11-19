"""Shared NBA + CBB derived-input engine on archived ESPN team box scores and schedule linescores (RESEARCH_ONLY).

One code path for both sports (the sportsdataverse team_box / schedule schemas are identical): possessions, pace, per-possession ratings, four factors,
shot-volume and opportunity rates, each as a point-in-time pre-game value, then matchup compositions and walk-forward score-distribution parameters.

Point-in-time rules (enforced by alpha_engine.derived.verify, not just asserted here):
  * a team's value for game G uses only that team's STRICTLY EARLIER games (shift(1) inside team x season after a chronological sort);
  * shrink targets are the team's PREVIOUS season mean, falling back to the league mean over strictly earlier DATES of the season, then the previous season's league mean;
  * every fitted coefficient (pace composition, home edge, variance, overtime, correlation tables) applied to season S is fitted on seasons < S only (annual refit);
  * no market price or line enters anywhere.
Raw: sift-data-vault archives/NBA/espn_pbp_boxes_schedules and archives/CBB/espn_team_box_schedules (restored with tools/vault.py restore).
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.core import pair_rows, prior_date_mean, sort_chrono

CFG = {
    "NBA": dict(box="espn_nba_team_boxscores", sched="espn_nba_schedules", periods=4, reg_min=48, types=(2, 3, 5), hl=20.0, k=20.0, window=5,
                hl_over={"fg3a100": 15.0, "d_fg3a100": 20.0}, k_over={"d_fg3a100": 25.0, "d_efg": 40.0, "fg3_pct": 40.0, "d_fg3_pct": 200.0, "ft_pct": 30.0, "fg2_pct": 30.0}),
    "CBB": dict(box="team_box", sched="schedules", periods=2, reg_min=40, types=(2, 3), hl=8.0, k=10.0, window=5,
                hl_over={}, k_over={"d_efg": 25.0, "fg3_pct": 25.0, "d_fg3_pct": 90.0, "ft_pct": 20.0, "fg2_pct": 20.0}),
}
# per-game metrics that get an offensive and a defensive (opponent's value in the same game) pre-game estimate, opponent- and venue-adjusted
ADJ = ["ortg", "efg", "tov_pct", "orb_pct", "ftr100", "fg3a100", "fg2a100", "ast100", "stl100", "blk100", "fb100"]
RAW_ONLY = ["fg3_pct", "fg2_pct", "ft_pct"]          # shooting accuracy: shrunk, opponent side kept (d_fg3_pct) but not opponent-adjusted (weak persistence)
_LS = re.compile(r"\{[^}]*\}")
_NUM = lambda key, s: (re.search(rf"'{key}':\s*([\d.]+)", s) or [None, "nan"])[1]


def parse_linescores(v) -> list[float]:
    """ESPN schedule linescores (stringified list of dicts) -> points per period, ordered by period."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return []
    if not isinstance(v, str):
        v = str(v)
    out = sorted((float(_NUM("period", m)), float(_NUM("value", m))) for m in _LS.findall(v))
    return [p for _, p in out]


def load_raw(root, sport: str) -> dict:
    c = CFG[sport]; root = Path(root)
    box = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(root / c["box"] / "*.parquet")))], ignore_index=True)
    cols = ["game_id", "neutral_site", "home_linescores", "away_linescores", "status_type_completed", "status_period"]
    sch = pd.concat([pd.read_parquet(f).reindex(columns=cols) for f in sorted(glob.glob(str(root / c["sched"] / "*.parquet")))], ignore_index=True)   # early seasons lack linescores
    return {"box": box, "sched": sch}


def team_games(raw: dict, sport: str) -> pd.DataFrame:
    """One row per game x team with this team's and the opponent's box line, possessions, pace and per-possession rates (the game's own outcome; never a feature)."""
    c = CFG[sport]; b = raw["box"]
    b = b[b.season_type.isin(c["types"])].copy()
    if sport == "NBA":
        b = b[b.team_id.between(1, 30) & b.opponent_team_id.between(1, 30)]          # the 30 franchises only (drops All-Star / exhibition sides)
    num = {"pts": "team_score", "fgm": "field_goals_made", "fga": "field_goals_attempted", "fg3m": "three_point_field_goals_made", "fg3a": "three_point_field_goals_attempted",
           "ftm": "free_throws_made", "fta": "free_throws_attempted", "oreb": "offensive_rebounds", "dreb": "defensive_rebounds", "ast": "assists", "stl": "steals", "blk": "blocks",
           "pf": "fouls", "fb": "fast_break_points"}
    t = pd.DataFrame({"game_id": b.game_id.astype("int64"), "season": b.season.astype(int), "date": pd.to_datetime(b.game_date), "team": b.team_id.astype(int),
                      "home": (b.team_home_away.astype(str) == "home").astype(int)})
    for k, v in num.items():
        t[k] = pd.to_numeric(b[v], errors="coerce").to_numpy()
    tot = pd.to_numeric(b["total_turnovers"], errors="coerce"); t["tov"] = tot.where(tot.notna(), pd.to_numeric(b["turnovers"], errors="coerce")).to_numpy()
    t = t[t.fga > 0].drop_duplicates(["game_id", "team"])
    t = t[t.groupby("game_id").team.transform("size") == 2]
    s = raw["sched"].drop_duplicates("game_id").copy(); s["game_id"] = s.game_id.astype("int64")
    hl, al = s.home_linescores.map(parse_linescores), s.away_linescores.map(parse_linescores)
    P = c["periods"]
    s["n_per"] = hl.map(len)
    sp_ = pd.to_numeric(s.status_period, errors="coerce")
    # periods played = ESPN status_period when valid, else the linescore length (a linescore can carry an empty trailing placeholder period)
    s["has_ls"] = (s.n_per >= P).astype(int); s["n_per"] = sp_.where(sp_ >= P, s.n_per.where(s.n_per >= P, 0)).astype(int)
    s["ot_n"] = (s.n_per - P).clip(lower=0)
    s["h_reg"] = hl.map(lambda x: sum(x[:P]) if len(x) >= P else np.nan); s["a_reg"] = al.map(lambda x: sum(x[:P]) if len(x) >= P else np.nan)
    s["h_h1"] = hl.map(lambda x: sum(x[:P // 2]) if len(x) >= P else np.nan); s["a_h1"] = al.map(lambda x: sum(x[:P // 2]) if len(x) >= P else np.nan)
    s["neutral"] = s.neutral_site.fillna(False).astype(int)
    t = t.merge(s[["game_id", "neutral", "ot_n", "n_per", "has_ls", "h_reg", "a_reg", "h_h1", "a_h1"]], on="game_id", how="left")
    t["neutral"] = t.neutral.fillna(0).astype(int); t["has_ls"] = t.has_ls.fillna(0).astype(int); t["ot_n"] = t.ot_n.where(t.n_per >= P)
    t["reg_pts"] = np.where(t.home == 1, t.h_reg, t.a_reg); t["h1_pts"] = np.where(t.home == 1, t.h_h1, t.a_h1)
    t = sort_chrono(t.drop(columns=["h_reg", "a_reg", "h_h1", "a_h1", "n_per"]))
    t["poss_own"] = t.fga - t.oreb + t.tov + 0.44 * t.fta
    base = ["pts", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "pf", "fb", "tov", "poss_own", "reg_pts", "h1_pts", "tid"]
    t["tid"] = t.team
    t = pair_rows(t, cols=base).rename(columns={"opp_tid": "opp"}).drop(columns="tid")
    t["poss"] = (t.poss_own + t.opp_poss_own) / 2.0
    minutes = c["reg_min"] + 5.0 * t.ot_n.fillna(0)
    t["pace"] = t.poss * c["reg_min"] / minutes                      # possessions per regulation length
    for side, p in (("", ""), ("d_", "opp_")):                        # d_* = what the opponent did against this team in this game
        g = lambda k: t[p + k]
        o = (lambda k: t["opp_" + k]) if not p else (lambda k: t[k])
        t[side + "ortg"] = 100 * g("pts") / t.poss
        t[side + "efg"] = (g("fgm") + 0.5 * g("fg3m")) / g("fga")
        t[side + "tov_pct"] = g("tov") / g("poss_own")
        t[side + "orb_pct"] = g("oreb") / (g("oreb") + o("dreb")).replace(0, np.nan)
        t[side + "ftr100"] = 100 * g("fta") / t.poss
        t[side + "fg3a100"] = 100 * g("fg3a") / t.poss
        t[side + "fg2a100"] = 100 * (g("fga") - g("fg3a")) / t.poss
        t[side + "ast100"] = 100 * g("ast") / t.poss
        t[side + "stl100"] = 100 * g("stl") / t.poss
        t[side + "blk100"] = 100 * g("blk") / t.poss
        t[side + "fb100"] = 100 * g("fb") / t.poss
        t[side + "fg3_pct"] = g("fg3m") / g("fg3a").replace(0, np.nan)
        t[side + "fg2_pct"] = (g("fgm") - g("fg3m")) / (g("fga") - g("fg3a")).replace(0, np.nan)
        t[side + "ft_pct"] = g("ftm") / g("fta").replace(0, np.nan)
    t["margin"] = t.pts - t.opp_pts; t["total"] = t.pts + t.opp_pts
    t["reg_margin"] = t.reg_pts - t.opp_reg_pts; t["reg_total"] = t.reg_pts + t.opp_reg_pts
    t["ot"] = (t.ot_n > 0).astype(float).where(t.ot_n.notna())
    return t


# ---------------------------------------------------------------- point-in-time primitives
def league_pre(t: pd.DataFrame, col: str) -> pd.Series:
    """League mean over strictly earlier dates of the same season; before any game of the season, the previous season's full mean."""
    m = prior_date_mean(t, "date", col, by="season")
    sm = t.groupby("season")[col].mean()
    return m.where(m.notna(), t.season.map({s: sm.get(s - 1, np.nan) for s in sm.index}))


def shrunk(t: pd.DataFrame, col: str, hl: float, k: float, lg: pd.Series) -> pd.Series:
    """Pre-game estimate: EWMA (half-life hl games) of the team's strictly earlier games this season, shrunk with weight n/(n+k) toward the team's previous-season mean (league pre-mean if none)."""
    keys = [t.team, t.season]
    s1 = t.groupby(["team", "season"], sort=False)[col].shift(1)
    ew = s1.groupby(keys, sort=False).ewm(halflife=hl, min_periods=1).mean().reset_index(level=[0, 1], drop=True).reindex(t.index)
    n = s1.notna().groupby(keys, sort=False).cumsum().astype(float)
    ps = t.groupby(["team", "season"])[col].agg(["mean", "count"]); ps = ps["mean"].where(ps["count"] >= 10)      # a prior-season target needs a real sample
    prev = pd.Series(ps.reindex(pd.MultiIndex.from_arrays([t.team.to_numpy(), t.season.to_numpy() - 1])).to_numpy(), index=t.index)
    target = prev.where(prev.notna(), lg)
    out = (n * ew.fillna(0) + k * target) / (n + k)
    return out.where(target.notna(), ew)


def walk_forward(df: pd.DataFrame, fit, apply, window: int = 5, min_seasons: int = 2) -> pd.Series:
    """Fit on the `window` seasons strictly before S, apply to season S. Returns NaN until `min_seasons` of history exist."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for S in sorted(df.season.unique()):
        tr = df[(df.season < S) & (df.season >= S - window)]
        if tr.season.nunique() < min_seasons:
            continue
        cur = df[df.season == S]
        out.loc[cur.index] = np.asarray(apply(fit(tr), cur), dtype=float)
    return out


def _ols(X, y):
    ok = np.isfinite(X).all(1) & np.isfinite(y)
    A = np.c_[np.ones(ok.sum()), X[ok]]
    return np.linalg.lstsq(A, y[ok], rcond=None)[0]


def _lin(cols, y):
    return (lambda tr: _ols(tr[cols].to_numpy(float), tr[y].to_numpy(float))), (lambda b, cur: b[0] + cur[cols].to_numpy(float) @ b[1:])


def _logit_fit(X, y, iters=40, l2=1e-3):
    """Newton logistic regression on standardised columns; returns coefficients on the ORIGINAL scale (intercept first)."""
    ok = np.isfinite(X).all(1) & np.isfinite(y); Xo = X[ok]; yy = y[ok]
    mu, sd = Xo.mean(0), Xo.std(0); sd[sd == 0] = 1.0
    A = np.c_[np.ones(len(Xo)), (Xo - mu) / sd]; b = np.zeros(A.shape[1]); b[0] = np.log(max(yy.mean(), 1e-4) / max(1 - yy.mean(), 1e-4))
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ b)); W = p * (1 - p) + 1e-9
        b = b + np.linalg.solve(A.T @ (A * W[:, None]) + l2 * np.eye(len(b)), A.T @ (yy - p) - l2 * b * np.r_[0, np.ones(len(b) - 1)])
    return np.r_[b[0] - (b[1:] * mu / sd).sum(), b[1:] / sd]


BUCKETS = [0, 5, 10, 20, np.inf]


def _bucket(x):
    return pd.cut(np.abs(x), BUCKETS, labels=False, right=False, include_lowest=True)


# ---------------------------------------------------------------- feature build
def features(t: pd.DataFrame, sport: str) -> pd.DataFrame:
    """Point-in-time pre-game features, one row per game x team (same index order as ``t``)."""
    c = CFG[sport]; hl = lambda m: c["hl_over"].get(m, c["hl"]); kk = lambda m: c["k_over"].get(m, c["k"])
    f = t[["game_id", "season", "date", "team", "opp", "home", "neutral"]].copy()
    f["n_pre"] = t.groupby(["team", "season"], sort=False).cumcount()
    site = np.where(t.neutral == 1, 0.0, np.where(t.home == 1, 1.0, -1.0))            # +1 home, -1 away, 0 neutral
    lg, w = {}, t.copy()
    # venue edge per metric: half the mean (home - away) gap in non-neutral games of EARLIER seasons (annual refit)
    edge = {}
    nn = t[t.neutral == 0]
    for m in ADJ + ["pace"]:
        lg[m] = league_pre(t, m)
        d = nn.groupby(["season", "home"])[m].mean().unstack()
        gap = ((d[1] - d[0]) / 2.0) if (m != "pace" and 1 in d and 0 in d) else pd.Series(0.0, index=sorted(t.season.unique()))
        prior = {s: gap[(gap.index < s) & (gap.index >= s - c["window"])].mean() for s in t.season.unique()}
        edge[m] = t.season.map(prior).fillna(0.0)
    for m in RAW_ONLY:
        lg[m] = league_pre(t, m); lg["d_" + m] = lg[m]
    # stage 1: raw shrunk estimates (own offence, own defence)
    for m in ADJ + ["pace"]:
        w["o1_" + m] = shrunk(t, m, hl(m), kk(m), lg[m])
        if m != "pace":
            w["d1_" + m] = shrunk(t, "d_" + m, hl("d_" + m), kk("d_" + m), lg[m])
    s1 = [x for x in w.columns if x[:3] in ("o1_", "d1_")]
    w = pair_rows(w, cols=s1)
    # stage 2: each game's value net of venue and of the opponent's pre-game tendency, then shrunk again
    for m in ADJ + ["pace"]:
        opp_d = w["opp_d1_" + m] if m != "pace" else w["opp_o1_pace"]
        w["a_" + m] = t[m] - site * edge[m] - (opp_d - lg[m]).fillna(0.0)
        f[("off_" if m != "pace" else "") + m + "_pre"] = shrunk(w, "a_" + m, hl(m), kk(m), lg[m])
        if m != "pace":
            w["a_d_" + m] = t["d_" + m] + site * edge[m] - (w["opp_o1_" + m] - lg[m]).fillna(0.0)
            f["def_" + m + "_pre"] = shrunk(w, "a_d_" + m, hl("d_" + m), kk("d_" + m), lg[m])
        f["lg_" + m + "_pre"] = lg[m]
    for m in RAW_ONLY:
        f["off_" + m + "_pre"] = shrunk(t, m, hl(m), kk(m), lg[m]); f["def_" + m + "_pre"] = shrunk(t, "d_" + m, hl("d_" + m), kk("d_" + m), lg[m]); f["lg_" + m + "_pre"] = lg[m]
    f["net_rtg_pre"] = f.off_ortg_pre - f.def_ortg_pre
    pre = [x for x in f.columns if x.startswith(("off_", "def_", "pace_pre", "net_rtg", "n_pre"))]
    f = pair_rows(f, cols=pre)
    f = f.copy()
    # ---- matchup compositions (team offence against opponent defence, relative to league)
    for m in ADJ:
        f["mx_" + m + "_pre"] = f["off_" + m + "_pre"] + f["opp_def_" + m + "_pre"] - f["lg_" + m + "_pre"]
    f["ff_edge_pre"] = (f.mx_efg_pre - (f.opp_off_efg_pre + f.def_efg_pre - f.lg_efg_pre)) * 100 * 0.4 - (f.mx_tov_pct_pre - (f.opp_off_tov_pct_pre + f.def_tov_pct_pre - f.lg_tov_pct_pre)) * 100 * 0.25 \
        + (f.mx_orb_pct_pre - (f.opp_off_orb_pct_pre + f.def_orb_pct_pre - f.lg_orb_pct_pre)) * 100 * 0.2 + (f.mx_ftr100_pre - (f.opp_off_ftr100_pre + f.def_ftr100_pre - f.lg_ftr100_pre)) * 0.15
    f["exp_poss_add_pre"] = f.pace_pre + f.opp_pace_pre - f.lg_pace_pre
    f["pace_mean_pre"] = (f.pace_pre + f.opp_pace_pre) / 2; f["pace_absdiff_pre"] = (f.pace_pre - f.opp_pace_pre).abs()
    f["pace_slow_pre"] = np.minimum(f.pace_pre, f.opp_pace_pre); f["pace_inter_pre"] = (f.pace_pre - f.lg_pace_pre) * (f.opp_pace_pre - f.lg_pace_pre)
    f["tov_sum_pre"] = f.mx_tov_pct_pre + f.opp_off_tov_pct_pre + f.def_tov_pct_pre - f.lg_tov_pct_pre
    f["fb_sum_pre"] = f.off_fb100_pre + f.opp_off_fb100_pre
    rest = t.groupby("team", sort=False).date.transform(lambda s: (s - s.shift(1)).dt.days).clip(upper=7).fillna(7)
    f["rest_days"] = rest; f = pair_rows(f, cols=["rest_days"]); f["rest_min_pre"] = np.minimum(f.rest_days, f.opp_rest_days)
    g = f.copy(); g["y_pace"] = t.pace.to_numpy(); g["y_dev"] = g.y_pace - g.lg_pace_pre
    g["pd_t"] = g.pace_pre - g.lg_pace_pre; g["pd_o"] = g.opp_pace_pre - g.lg_pace_pre
    # walk-forward pace models: joint (mean, slower team, interaction) and composition (+ turnover, transition, rest)
    for name, cols in (("exp_poss_joint_pre", ["pace_mean_pre", "pace_slow_pre", "pace_inter_pre"]), ("exp_poss_comp_pre", ["pace_mean_pre", "pace_absdiff_pre", "tov_sum_pre", "fb_sum_pre", "rest_min_pre"])):
        f[name] = walk_forward(g, *_lin(cols, "y_pace"), window=c["window"])
    f["exp_poss_elastic_pre"] = f.lg_pace_pre + walk_forward(g, lambda tr: _ols(tr[["pd_t", "pd_o"]].to_numpy(float), tr["y_dev"].to_numpy(float)),
                                                              lambda b, cur: b[0] + cur[["pd_t", "pd_o"]].to_numpy(float) @ b[1:], window=c["window"])
    g["pace_res"] = g.y_pace - f.exp_poss_joint_pre
    fast = (g.pd_t > 0).astype(int) + (g.pd_o > 0).astype(int)                         # 0 slow-slow, 1 mixed, 2 fast-fast
    g["mtype"] = fast
    f["poss_sd_pre"] = walk_forward(g, lambda tr: tr.groupby("mtype").pace_res.std().to_dict(), lambda d, cur: cur.mtype.map(d), window=c["window"], min_seasons=3)
    ep = f.exp_poss_joint_pre.where(f.exp_poss_joint_pre.notna(), f.exp_poss_add_pre)
    f["exp_poss_pre"] = ep
    # ---- expected points, margin, total from fundamentals only
    f["exp_pts_pre"] = f.mx_ortg_pre * ep / 100.0
    f["opp_exp_pts_pre"] = (f.opp_off_ortg_pre + f.def_ortg_pre - f.lg_ortg_pre) * ep / 100.0
    g["mu0"] = f.exp_pts_pre - f.opp_exp_pts_pre; g["y_margin"] = t.margin.to_numpy(); g["site"] = site
    hca = walk_forward(g, lambda tr: float((tr.y_margin - tr.mu0)[(tr.site == 1)].mean()), lambda h, cur: np.full(len(cur), h), window=c["window"]).fillna(0.0)
    f["hca_pts_pre"] = hca
    f["exp_margin_pre"] = g.mu0 + site * hca; f["exp_total_pre"] = f.exp_pts_pre + f.opp_exp_pts_pre
    # ---- shot volume / opportunity
    f["fg3a_index_pre"] = f.opp_def_fg3a100_pre / f.lg_fg3a100_pre
    f["exp_fg3a_pre"] = f.off_fg3a100_pre * f.fg3a_index_pre * ep / 100.0
    f["exp_fg2a_pre"] = f.mx_fg2a100_pre * ep / 100.0
    f["exp_fta_pre"] = ep * (0.5 * f.off_ftr100_pre + 0.5 * f.opp_def_ftr100_pre) / 100.0
    f["exp_ft_pts_pre"] = f.exp_fta_pre * f.off_ft_pct_pre
    f["exp_ast_pre"] = f.mx_ast100_pre * ep / 100.0; f["exp_stl_pre"] = f.mx_stl100_pre * ep / 100.0; f["exp_blk_pre"] = f.mx_blk100_pre * ep / 100.0
    f["exp_reb_pool_pre"] = f.exp_fg3a_pre * (1 - f.off_fg3_pct_pre) + f.exp_fg2a_pre * (1 - f.off_fg2_pct_pre)      # this team's expected missed field goals
    f = pair_rows(f, cols=["exp_fg3a_pre", "exp_fg2a_pre", "exp_fta_pre", "exp_reb_pool_pre"])
    f["exp_oreb_pre"] = f.exp_reb_pool_pre * f.mx_orb_pct_pre; f["exp_dreb_pre"] = f.opp_exp_reb_pool_pre * (1 - (f.opp_off_orb_pct_pre + f.def_orb_pct_pre - f.lg_orb_pct_pre))
    # opponent three-point defence split: persistent attempts conceded vs noisy accuracy conceded
    for col, out in (("opp_def_fg3a100_pre", "opp_fg3a_allowed_z_pre"), ("opp_def_fg3_pct_pre", "opp_fg3pct_allowed_z_pre")):
        g["_v"] = f[col]; g["_v2"] = f[col] ** 2
        mu = prior_date_mean(g, "date", "_v", by="season")
        sd = np.sqrt((prior_date_mean(g, "date", "_v2", by="season") - mu ** 2).clip(lower=0))
        seen = g.groupby("season", sort=False).cumcount()                                 # rows earlier in the season (chronological order; not outcome dependent)
        ss = g.groupby("season")["_v"].agg(["mean", "std"])
        early = seen < 200                                                                 # too few earlier rows this season: use the previous season's distribution
        mu = mu.where(~early, g.season.map({k: ss["mean"].get(k - 1, np.nan) for k in ss.index}))
        sd = sd.where(~early, g.season.map({k: ss["std"].get(k - 1, np.nan) for k in ss.index}))
        f[out] = ((f[col] - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    f["fg3a_matchup_adj_pre"] = 0.6 * f.opp_fg3a_allowed_z_pre * 0.8
    f["fg3pct_matchup_adj_pre"] = 0.1 * f.opp_fg3pct_allowed_z_pre * 1.5
    f = f.copy()                                                                       # defragment before the next block of column inserts
    # ---- variance structure
    p3, p2, pf_ = f.off_fg3_pct_pre, f.off_fg2_pct_pre, f.off_ft_pct_pre
    f["shot_var_pre"] = f.exp_fg3a_pre * 9 * p3 * (1 - p3) + f.exp_fg2a_pre * 4 * p2 * (1 - p2) + f.exp_fta_pre * pf_ * (1 - pf_)
    f = pair_rows(f, cols=["shot_var_pre"])
    ppp = f.exp_total_pre / (2 * ep)
    f["total_var_load_pre"] = f.shot_var_pre + f.opp_shot_var_pre + (f.poss_sd_pre ** 2) * (2 * ppp) ** 2
    f["fg3_share_sum_pre"] = f.off_fg3a100_pre / (f.off_fg3a100_pre + f.off_fg2a100_pre) + f.opp_off_fg3a100_pre / (f.opp_off_fg3a100_pre + f.opp_off_fg2a100_pre)
    f["ftr_sum_pre"] = f.off_ftr100_pre + f.opp_off_ftr100_pre
    g["tot_res"] = t.total.to_numpy() - f.exp_total_pre; g["mar_res"] = g.y_margin - f.exp_margin_pre; g["pts_res"] = t.pts.to_numpy() - f.exp_pts_pre
    g["load"] = f.total_var_load_pre; g["r2"] = g.tot_res ** 2
    lam = walk_forward(g, lambda tr: float(tr.r2.mean() / tr.load.mean()) if tr.load.notna().any() else np.nan, lambda l, cur: np.full(len(cur), l), window=2, min_seasons=2)
    f["sd_total_load_pre"] = np.sqrt(lam * f.total_var_load_pre)
    g["l_ep"] = np.log(ep); g["s3"] = f.fg3_share_sum_pre; g["sft"] = f.ftr_sum_pre; g["l_r2"] = np.log(g.r2.clip(lower=0.25))
    lv = walk_forward(g, *_lin(["l_ep", "s3", "sft"], "l_r2"), window=c["window"], min_seasons=3)
    # E[log chi2_1] = -1.27: de-bias so that exp(fit) estimates the variance, not the geometric mean of squared residuals
    f["sd_total_style_pre"] = np.sqrt(np.exp(lv + 1.27))
    g["sq_ep"] = np.sqrt(ep); g["abs_mu"] = f.exp_margin_pre.abs(); g["abs_mr"] = g.mar_res.abs() * np.sqrt(np.pi / 2)
    f["sd_margin_pre"] = walk_forward(g, *_lin(["sq_ep", "abs_mu"], "abs_mr"), window=c["window"], min_seasons=3)
    g["o3"] = f.off_fg3a100_pre / (f.off_fg3a100_pre + f.off_fg2a100_pre); g["opp3"] = f.opp_def_fg3a100_pre; g["abs_pr"] = g.pts_res.abs() * np.sqrt(np.pi / 2)
    f["sd_pts_style_pre"] = walk_forward(g, *_lin(["o3", "sq_ep", "abs_mu"], "abs_pr"), window=c["window"], min_seasons=3)
    # ---- overtime: P(regulation tie) from |expected margin| and expected total (logistic, annual refit)
    g["y_ot"] = t.ot.to_numpy(); g["et"] = f.exp_total_pre
    f["p_ot_pre"] = walk_forward(g, lambda tr: _logit_fit(tr[["abs_mu", "et"]].to_numpy(float), tr.y_ot.to_numpy(float)),
                                 lambda b, cur: 1 / (1 + np.exp(-(b[0] + cur[["abs_mu", "et"]].to_numpy(float) @ b[1:]))), window=c["window"], min_seasons=3)
    g["ot2"] = (t.ot_n >= 2).astype(float).where(t.ot_n >= 1).to_numpy()
    f["p_ot2_given_ot_pre"] = walk_forward(g, lambda tr: float((tr.ot2.sum() + 200 * 0.15) / (tr.ot2.notna().sum() + 200)), lambda p, cur: np.full(len(cur), p), window=c["window"], min_seasons=3)
    # ---- joint structure tables (favourite-size bucket x pace tercile; role x bucket), shrunk to pooled, annual refit
    g["bk"] = _bucket(f.exp_margin_pre); g["z_m"] = g.mar_res / f.sd_margin_pre; g["z_t"] = g.tot_res / f.sd_total_style_pre
    g["ter"] = walk_forward(g, lambda tr: tr.sq_ep.quantile([1 / 3, 2 / 3]).to_numpy(), lambda q, cur: np.searchsorted(q, cur.sq_ep.to_numpy()), window=c["window"], min_seasons=3)
    g["fav"] = (f.exp_margin_pre > 0).astype(int)

    def corr_fit(tr):
        tr = tr.dropna(subset=["z_m", "z_t", "bk", "ter"]); tr = tr[tr.fav == 1]              # one row per game (favourite's view), sign-consistent
        pooled = tr.z_m.corr(tr.z_t) if len(tr) > 50 else np.nan
        out = {}
        for key, d in tr.groupby(["bk", "ter"]):
            n = len(d); r = d.z_m.corr(d.z_t) if n > 5 else pooled
            out[key] = (n * r + 200 * pooled) / (n + 200)
        return out, pooled

    def corr_apply(m, cur):
        tab, pooled = m; r = np.array([tab.get((b, q), pooled) for b, q in zip(cur.bk, cur.ter)], dtype=float)
        return np.where(cur.fav.to_numpy() == 1, r, -r)                                         # underdog's margin is the negative
    f["rho_margin_total_pre"] = walk_forward(g, corr_fit, corr_apply, window=c["window"], min_seasons=3)

    def k_fit(tr):
        tr = tr.dropna(subset=["pts_res", "mar_res", "bk"]); pooled = np.cov(tr.pts_res, tr.mar_res)[0, 1] / tr.mar_res.var() if len(tr) > 50 else np.nan
        out = {}
        for key, d in tr.groupby(["fav", "bk"]):
            n = len(d); k = np.cov(d.pts_res, d.mar_res)[0, 1] / d.mar_res.var() if n > 5 else pooled
            out[key] = (n * k + 250 * pooled) / (n + 250)
        return out, pooled
    f["k_pts_margin_pre"] = walk_forward(g, k_fit, lambda m, cur: [m[0].get((a, b), m[1]) for a, b in zip(cur.fav, cur.bk)], window=8, min_seasons=3)
    return f.drop(columns=[x for x in f.columns if x.startswith("lg_") and x not in ("lg_pace_pre", "lg_ortg_pre")])


def build(root, sport: str):
    raw = load_raw(root, sport); t = team_games(raw, sport)
    return raw, t, features(t, sport)

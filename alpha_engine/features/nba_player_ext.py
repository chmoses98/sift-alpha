"""NBA player-game extension builders (RESEARCH_ONLY): heavy-minutes tail, 35-point ceiling tail, points upper tail, shot-type attempt rates, teammate-absence minute shifts, first-basket share, early-game usage.

Raw data: owner's nba-edge-finder ESPN box scores (player_games) and shot events, regular season only. Output table ``team`` is keyed (game_id, team) where ``team`` is the PLAYER id (one row per player-game, players who played);
the replay machinery only needs a (game_id, entity) key. Every feature for game G uses STRICTLY EARLIER games of that player (shift(1) / earlier-date league baselines); team-level rotation lookups use the team's earlier games only.
Every input is PARTIAL (see `missing`): no GPD / logistic / copula fits, no tonight's-lineup conditioning, no own-model margin conditioning.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec, prior_count, prior_date_mean, sort_chrono

S = "NBA"
PG_COLS = ["game_id", "game_date_et", "season", "season_type", "team_id", "nba_id", "started", "played", "minutes", "pts", "fga", "fta", "fg3a", "fgm", "tov", "n_ot", "home"]
SH_COLS = ["game_id", "period", "clock_seconds_remaining", "sequence", "shooter_player_id", "is_home", "shot_made", "is_free_throw", "is_shooting_play", "season_type"]
PG_CONTENT = ["started", "minutes", "pts", "fga", "fta", "fg3a", "fgm", "tov", "n_ot"]
SH_CONTENT = ["period", "clock_seconds_remaining", "sequence", "shooter_player_id", "shot_made", "is_free_throw", "is_shooting_play"]
HL_W = lambda n, hl: 0.5 ** (np.arange(1, n + 1) / hl)


def load_raw(nba_dir) -> dict:
    h = Path(nba_dir) / "espn"
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"player_games": cat("player_games_*.parquet", PG_COLS), "shots": cat("shot_events_*.parquet", SH_COLS)}


def _wmean_last(x: np.ndarray, n: int, hl: float, minobs: int) -> np.ndarray:
    """for each i: weighted mean of x[i-n..i-1] with weight 0.5**(age/hl), age=1 for x[i-1]; NaN if fewer than minobs earlier games."""
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        lo = max(0, i - n); seg = x[lo:i][::-1]
        if len(seg) >= minobs:
            w = HL_W(len(seg), hl); out[i] = float((seg * w).sum() / w.sum())
    return out


def _grp(p, col, fn):
    return p.groupby("pid", sort=False)[col].transform(fn)


def compute(raw: dict) -> dict:
    p = raw["player_games"]; p = p[(p.season_type == "regular") & (p.played == True)].copy()
    p["date"] = pd.to_datetime(p.game_date_et); p = p.rename(columns={"nba_id": "pid", "team_id": "tm"}); p["home"] = p.home.astype(bool)
    p = p.sort_values(["date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    p["season_n"] = p.season.astype(str).str[:4].astype(int)
    # ---- team-game totals used as denominators
    tt = p.groupby(["game_id", "tm"]).agg(t_fga=("fga", "sum"), t_fta=("fta", "sum")).reset_index(); p = p.merge(tt, on=["game_id", "tm"], how="left")
    p["usg"] = p.fga + 0.44 * p.fta; p["usg_share"] = p.usg / (p.t_fga + 0.44 * p.t_fta)
    sr = _grp(p, "started", lambda s: s.astype(float).shift(1).ewm(halflife=15, min_periods=3).mean())
    p["role"] = (sr >= 0.5).astype(float).where(sr.notna())
    p["games_pre"] = prior_count(p, "pid")
    # ---- heavy minutes
    p["heavy38"] = (p.minutes >= 38).astype(float)
    p["heavy38_rate_pre"] = _grp(p, "heavy38", lambda s: pd.Series(_wmean_last(s.to_numpy(float), 80, 30, 5), index=s.index))
    lg = prior_date_mean(p, "date", "heavy38", by="role")
    n_eff = p.games_pre.clip(upper=80)
    p["heavy38_shr_pre"] = (n_eff * p.heavy38_rate_pre + 15 * lg) / (n_eff + 15)
    p["heavy38_n_pre"] = _grp(p, "heavy38", lambda s: s.shift(1).rolling(80, min_periods=1).sum())
    # ---- 35-point ceiling
    p["ge35"] = (p.pts >= 35).astype(float)
    cum = _grp(p, "ge35", lambda s: s.shift(1).expanding(min_periods=10).mean())
    lg35 = prior_date_mean(p, "date", "ge35", by="role")
    p["p35_pre"] = cum
    p["p35_shr_pre"] = (p.games_pre * cum + 30 * lg35) / (p.games_pre + 30)
    p["n35_pre"] = _grp(p, "ge35", lambda s: s.shift(1).expanding().sum())
    p["season_max_pts_pre"] = p.groupby(["pid", "season_n"], sort=False).pts.transform(lambda s: s.shift(1).expanding().max())
    # ---- upper tail of points vs minutes-conditional mean
    cp = _grp(p, "pts", lambda s: s.shift(1).expanding().sum()); cm = _grp(p, "minutes", lambda s: s.shift(1).expanding().sum())
    ppm = cp / cm.where(cm > 0); m_g = ppm * p.minutes
    base = (p.minutes >= 30) & m_g.notna() & (m_g > 0)
    for k, nm in ((1.4, "ex14"), (1.7, "ex17"), (2.0, "ex20")):
        p[f"_{nm}"] = np.where(base, (p.pts >= k * m_g).astype(float), np.nan)
        p[f"{nm}_rate_pre"] = _grp(p, f"_{nm}", lambda s: s.shift(1).expanding(min_periods=5).mean())
    p["tail_n_pre"] = p._ex14.notna().astype(float).groupby(p.pid, sort=False).transform(lambda s: s.shift(1).expanding().sum())
    # ---- attempt rates per 36 by shot type, exponentially weighted sums (hl 20 games) shrunk to the role mean with 300 minutes
    p["a2"] = p.fga - p.fg3a
    for att, nm in (("a2", "a2"), ("fg3a", "a3"), ("fta", "fta")):
        num = _grp(p, att, lambda s: s.shift(1).ewm(halflife=20, adjust=True).sum()); den = _grp(p, "minutes", lambda s: s.shift(1).ewm(halflife=20, adjust=True).sum())
        lgm = prior_date_mean(p.assign(_r=p[att] / p.minutes.where(p.minutes > 0)), "date", "_r", by="role")
        p[f"{nm}_per36_pre"] = np.where(den.notna() & (p.games_pre >= 3), 36 * (num + 300 * lgm) / (den + 300), np.nan)
    # ---- teammate-absence minute shifts (top-3 teammates by minutes over the team's previous 10 games)
    p = _absence(p)
    # ---- shot-event features
    p = _shots(raw, p)
    p["season"] = p.season_n; p = p.rename(columns={"pid": "team"})
    cols = [c for s in specs() for c in s.columns]
    out = p[["game_id", "team", "date", "season"] + cols].copy()
    return {"team": out.loc[:, ~out.columns.duplicated()]}


def _absence(p: pd.DataFrame) -> pd.DataFrame:
    res: dict = {}
    for tm, g in p.groupby("tm", sort=False):
        gids = list(dict.fromkeys(g.game_id.tolist())); gi = {x: i for i, x in enumerate(gids)}
        pids = sorted(g.pid.unique()); pj = {x: j for j, x in enumerate(pids)}
        M = np.full((len(gids), len(pids)), np.nan)
        for r in g.itertuples(): M[gi[r.game_id], pj[r.pid]] = r.minutes
        played = ~np.isnan(M); Mz = np.where(played, M, 0.0)
        cs = np.cumsum(Mz, axis=0)
        win = np.vstack([np.zeros((1, len(pids))), cs])  # prefix sums
        for r in g.itertuples():
            i = gi[r.game_id]; j = pj[r.pid]
            if i == 0: continue
            lo = max(0, i - 10); tot = win[i] - win[lo]; tot = tot.copy(); tot[j] = -1; order = np.lexsort((np.arange(len(pids)), -tot))
            mine = M[:i, j]; pm = ~np.isnan(mine)
            for k in (1, 2, 3):
                x = order[k - 1]
                if tot[x] <= 0 or x == j: continue
                xm = M[:i, x]; f0 = int(np.argmax(~np.isnan(xm))); onroster = np.arange(i) >= f0     # X counts as absent only after his first appearance for this team
                absent = (np.isnan(xm) | (xm < 5)) & onroster; present = ~np.isnan(xm) & (xm >= 5)
                a = pm & absent; b = pm & present
                n_a = int(a.sum())
                if n_a >= 3 and b.sum() >= 3:
                    res[(r.Index, k)] = ((mine[a].mean() - mine[b].mean()) * n_a / (n_a + 15), n_a)
    for k in (1, 2, 3):
        ks = [(i, v) for (i, kk), v in res.items() if kk == k]
        d = pd.Series({i: v[0] for i, v in ks}, dtype=float); n = pd.Series({i: v[1] for i, v in ks}, dtype=float)
        p[f"tm_abs_dmin{k}_pre"] = d.reindex(p.index); p[f"tm_abs_n{k}_pre"] = n.reindex(p.index)
    return p


def _shots(raw: dict, p: pd.DataFrame) -> pd.DataFrame:
    s = raw["shots"]; s = s[(s.season_type == "regular") & (s.is_shooting_play == True)].copy()
    s["sid"] = s.shooter_player_id.astype(float); s["is_home"] = s.is_home.astype(bool)
    fg = s[(s.is_free_throw == False)].sort_values(["game_id", "period", "clock_seconds_remaining", "sequence"], ascending=[True, True, False, True], kind="mergesort")
    made = fg[fg.shot_made == True]
    ft = made.groupby(["game_id", "is_home"]).head(1)[["game_id", "is_home", "sid"]].assign(fb_team=1.0)
    fgm_ = made.groupby("game_id").head(1)[["game_id", "sid"]].assign(fb_game=1.0)
    early = s[(s.period == 1) & (s.clock_seconds_remaining >= 360)]
    early = early.assign(u=np.where(early.is_free_throw == True, 0.44, 1.0))      # each shooting-play row is one attempt: FGA weight 1, FTA weight 0.44
    ea = early.groupby(["game_id", "sid"]).agg(e_att=("u", "sum")).reset_index()
    em = early[(early.is_free_throw == False) & (early.shot_made == True)].groupby(["game_id", "sid"]).size().rename("e_made").reset_index()
    ea = ea.merge(em, on=["game_id", "sid"], how="left")
    ft = ft.drop_duplicates(["game_id", "sid"]); fgm_ = fgm_.drop_duplicates(["game_id", "sid"]); ea = ea.drop_duplicates(["game_id", "sid"])
    p = p.copy(); p["sid"] = p.pid.astype(float)
    p = p.merge(ft[["game_id", "sid", "fb_team"]], on=["game_id", "sid"], how="left").merge(fgm_, on=["game_id", "sid"], how="left").merge(ea, on=["game_id", "sid"], how="left")
    has = p.game_id.isin(set(s.game_id))
    for c in ("fb_team", "fb_game", "e_att", "e_made"): p[c] = p[c].fillna(0.0).where(has)
    p = p.sort_values(["date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    p["usage_share_pre"] = p.groupby("pid", sort=False).usg_share.transform(lambda x: x.shift(1).ewm(halflife=30, min_periods=3).mean())
    gp = p.games_pre.clip(upper=60)
    for c, nm in (("fb_team", "fb_team"), ("fb_game", "fb_game")):
        r = p.groupby("pid", sort=False)[c].transform(lambda x: x.shift(1).ewm(halflife=40, min_periods=5).mean())
        p[f"{nm}_rate_pre"] = r
        scale = 1.0 if nm == "fb_team" else 0.5
        p[f"{nm}_shr_pre"] = (gp * r + 10 * p.usage_share_pre * scale) / (gp + 10)
    tea = p.groupby(["game_id", "tm"]).e_att.transform("sum"); p["_tea"] = tea; tem = p.groupby(["game_id", "tm"]).e_made.transform("sum"); p["_tem"] = tem
    sp = p.groupby("pid", sort=False).e_att.transform(lambda x: x.shift(1).ewm(halflife=25, adjust=True).sum()); st = p.groupby("pid", sort=False)._tea.transform(lambda x: x.shift(1).ewm(halflife=25, adjust=True).sum())
    p["early_usg_share_pre"] = np.where(p.games_pre >= 10, (sp + 120 * p.usage_share_pre) / (st + 120), np.nan)
    sm = p.groupby("pid", sort=False).e_made.transform(lambda x: x.shift(1).ewm(halflife=25, adjust=True).sum()); stm = p.groupby("pid", sort=False)._tem.transform(lambda x: x.shift(1).ewm(halflife=25, adjust=True).sum())
    p["early_made_share_pre"] = np.where(p.games_pre >= 10, sm / stm.where(stm > 0), np.nan)
    return p


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, d, done, miss, raw=("espn_player_games",): FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, list(raw), "pregame_rolling")
    return [
        F("nba.heavy_minutes_tail_prob", ["heavy38_rate_pre", "heavy38_shr_pre", "heavy38_n_pre"], "share of games with >=38 minutes over the last 80 games (half-life 30), shrunk to the league starter/bench role rate with k=15",
          ["80-game half-life-30 share", "role prior k=15"], ["own-model closeness conditioning", "OT probability 0.06", "per-minute rate x 40", "as-of lineup status"]),
        F("nba.single_game_ceiling_tail", ["p35_pre", "p35_shr_pre", "n35_pre", "season_max_pts_pre"], "empirical share of the player's earlier games with >=35 points (all games incl OT), shrunk to the role league share with k=30, earlier-game count, season-to-date maximum",
          ["empirical >=35 share", "league-share shrink k=30", "season-to-date maximum"], ["GPD fit and P(pts>=54)", "minutes-mix term", "games-remaining mixture", "usage-tier league share (role used)"]),
        F("nba.points_upper_tail_rate", ["ex14_rate_pre", "ex17_rate_pre", "ex20_rate_pre", "tail_n_pre"], "share of earlier >=30-minute games with pts >= 1.4/1.7/2.0 x the minutes-conditional mean (the player's cumulative points per minute as of that game x that game's minutes)",
          ["exceedance rates at 1.4/1.7/2.0"], ["generalised-Pareto fit above the 85th percentile", "shape shrinkage", "3-season window"]),
        F("nba.fga_per_minute_by_shot_type", ["a2_per36_pre", "a3_per36_pre", "fta_per36_pre"], "2PA/3PA/FTA per 36 minutes: exponentially weighted (hl 20 games) sums shrunk to the league role per-minute rate with k=300 minutes",
          ["per-36 rates by shot type", "role shrink k=300"], ["0.6/0.4 season weighting", "position role (derived role used)", "minutes scenario mixture", "with/without teammate shift", "sd for NB model"]),
        F("nba.teammate_absence_shift", [f"tm_abs_dmin{k}_pre" for k in (1, 2, 3)] + [f"tm_abs_n{k}_pre" for k in (1, 2, 3)], "player's mean minutes with the k-th ranked teammate (by minutes over the team's previous 10 games) absent (no play or <5 min, counted only after his first game for the team) minus present (>=5 min), shrunk by n/(n+15)",
          ["minutes shift per top-3 teammate", "k=15 shrink"], ["usage, rebound and assist share shifts", "regression adjustments", "role-based redistribution prior", "multi-absence combinations", "injury-report vintage conditioning"]),
        F("nba.first_basket_share", ["fb_team_rate_pre", "fb_team_shr_pre", "fb_game_rate_pre", "fb_game_shr_pre", "usage_share_pre"], "share of earlier games in which the player scored his team's / the game's first made field goal (EWMA hl 40), shrunk toward usage share (k=10)",
          ["first team basket rate", "first game basket rate", "usage-share prior"], ["lineup identity conditioning", "P(team scores first)", "P(tip)", "1-2 season window"], ("espn_player_games", "espn_shot_events")),
        F("nba.early_game_usage_first6", ["early_usg_share_pre", "early_made_share_pre"], "share of the team's first-6-minutes-of-Q1 FGA+0.44*FTA (and made FG) taken by the player, exponentially weighted (hl 25) and shrunk to overall usage share with k=120 team early attempts",
          ["early usage share shrunk k=120", "early made-FG share"], ["60-game window", "renormalisation across expected starters", "precision-weighted combination with first_basket_share"], ("espn_player_games", "espn_shot_events")),
    ]

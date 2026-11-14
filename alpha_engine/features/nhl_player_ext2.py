"""Phase 15 NHL skater-game builders (RESEARCH_ONLY): individual expected goals per 60, individual points percentage by state, season points projection, award-stat projection,
games-played hazard state, and player/team joint-outcome correlations.

Raw data: owner's NHL-edge-finder player-event archive (players, goals; NHL API derived) and MoneyPuck shot rows with xGoal (moneypuck/shots_*.parquet; published model output, terms unresolved ->
internal research only), regular seasons 2021-22 .. 2025-26. Output table ``team`` is keyed (game_id, team) where ``team`` is the PLAYER id (one row per skater-game). Every value for game G uses the
player's (and the league's) games on STRICTLY EARLIER DATES only.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nba_ext3 import before

S = "NHL"
PL_COLS = ["game_id", "season", "game_date", "game_type", "player_id", "team_id", "position", "goals", "assists", "points", "sog", "toi_s", "toi_ev_s", "toi_pp_s", "gf_ev", "gf_pp"]
GO_COLS = ["game_id", "scorer_id", "a1_id", "a2_id", "strength"]
MP_COLS = ["nhl_game_id", "shooterPlayerId", "xGoal", "isHomeTeam", "homeSkatersOnIce", "awaySkatersOnIce"]
PL_CONTENT = ["goals", "assists", "points", "sog", "toi_s", "toi_ev_s", "toi_pp_s", "gf_ev", "gf_pp"]
GO_CONTENT = ["scorer_id", "a1_id", "a2_id", "strength"]
MP_CONTENT = ["xGoal", "shooterPlayerId", "homeSkatersOnIce", "awaySkatersOnIce"]
NUM = ["goals", "assists", "points", "sog", "toi_s", "toi_ev_s", "toi_pp_s", "gf_ev", "gf_pp"]


def load_raw(nhl_dir) -> dict:
    h = Path(nhl_dir)
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"players": cat("players/players_*.parquet", PL_COLS), "goals": cat("players/goals_*.parquet", GO_COLS), "mp": cat("moneypuck/shots_*.parquet", MP_COLS)}


def perturb_nv(raw: dict, ids, seed: int) -> dict:
    """Non-vacuity perturbation ONLY (never used by the leak tests): besides permuting the content of the block, zero the ice time of 30% of the block's player rows, so that participation-driven
    features (games played, games missed) must respond. The row universe is unchanged."""
    rng = np.random.default_rng(seed); o = dict(raw)
    for tb, gc, cols in (("players", "game_id", PL_CONTENT), ("goals", "game_id", GO_CONTENT), ("mp", "nhl_game_id", MP_CONTENT)):
        d = raw[tb].copy(); ix = np.flatnonzero(d[gc].isin(ids).to_numpy())
        for c in cols:
            v = d[c].to_numpy(copy=True); v[ix] = rng.permutation(v[ix]); d[c] = v
        o[tb] = d
    d = o["players"]; ix = np.flatnonzero(d.game_id.isin(ids).to_numpy()); z = ix[rng.random(len(ix)) < 0.3]
    for c in ("toi_s", "toi_ev_s", "toi_pp_s"):
        v = d[c].to_numpy(copy=True); v[z] = 0; d[c] = v
    return o


def _rate(s, n):
    return np.where(n > 0, s / np.where(n > 0, n, 1.0), np.nan)


def _wsum(x: np.ndarray, n: int, hl: float) -> np.ndarray:
    """out[i] = sum over k = 1..min(n, i) of x[i-k] * 0.5**(k/hl)."""
    w = 0.5 ** (np.arange(1, n + 1) / hl)
    return np.convolve(x, np.concatenate([[0.0], w]))[:len(x)]


def _by_player(p, col, n, hl):
    out = np.empty(len(p)); v = p[col].to_numpy(float)
    for _, ix in p.groupby("pid", sort=False).indices.items(): out[ix] = _wsum(v[ix], n, hl)
    return out


def _table(raw: dict) -> pd.DataFrame:
    p = raw["players"]; p = p[(p.game_type == 2) & (p.season <= 2025)].drop_duplicates(["game_id", "player_id"]).copy()
    p["date"] = pd.to_datetime(p.game_date); p = p.rename(columns={"player_id": "pid"}); p["pg"] = np.where(p.position.astype(str) == "D", "D", "F")
    for c in NUM: p[c] = p[c].astype(float)
    p = p.sort_values(["date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    gids = set(p.game_id)
    # points by strength state from the goal rows (scorer + up to two assists)
    g = raw["goals"]; g = g[g.game_id.isin(gids)]
    lg = pd.concat([g[["game_id", "strength", c]].rename(columns={c: "pid"}) for c in ("scorer_id", "a1_id", "a2_id")], ignore_index=True).dropna(subset=["pid"])
    lg["pid"] = lg.pid.astype("int64")
    for st, nm in (("EV", "pts_ev"), ("PP", "pts_pp")):
        p = p.merge(lg[lg.strength == st].groupby(["game_id", "pid"]).size().rename(nm).reset_index(), on=["game_id", "pid"], how="left")
        p[nm] = p[nm].fillna(0.0)
    # individual xG by state from the shot rows (state from the skater counts: equal = EV, shooter's side larger = PP)
    m = raw["mp"]; m = m[m.nhl_game_id.isin(gids)].copy()
    own = np.where(m.isHomeTeam == 1, m.homeSkatersOnIce, m.awaySkatersOnIce); opp = np.where(m.isHomeTeam == 1, m.awaySkatersOnIce, m.homeSkatersOnIce)
    m["st"] = np.where(own == opp, "EV", np.where(own > opp, "PP", "X")); m["pid"] = m.shooterPlayerId.astype("int64"); m["game_id"] = m.nhl_game_id.astype("int64")
    m["xGoal"] = m.xGoal.astype("float64")          # the archive stores xGoal as float32: sum in double precision (a float32 accumulation loses ~1e-7 relative, found by the blind comparison)
    has = p.game_id.isin(set(m.game_id)).to_numpy()
    for st, nm in (("EV", "ixg_ev"), ("PP", "ixg_pp")):
        p = p.merge(m[m.st == st].groupby(["game_id", "pid"]).xGoal.sum().rename(nm).reset_index(), on=["game_id", "pid"], how="left")
        p[nm] = np.where(has, p[nm].fillna(0.0), np.nan)
    # team games played before each game, team goals for / against
    tg = p.drop_duplicates(["game_id", "team_id"])[["game_id", "team_id", "season", "date"]].copy()
    tg["team_gp"] = tg.groupby(["team_id", "season"]).cumcount().astype(float)
    p = p.merge(tg[["game_id", "team_id", "team_gp"]], on=["game_id", "team_id"], how="left")
    p["tgf"] = p.groupby(["game_id", "team_id"]).goals.transform("sum"); p["tga"] = p.groupby("game_id").goals.transform("sum") - p.tgf
    p["gpf"] = (p.toi_s > 0).astype(float); p["one"] = 1.0
    return p


def _features(p: pd.DataFrame) -> pd.DataFrame:
    # a few rows have no state split (toi_ev_s / toi_pp_s / gf_ev / gf_pp missing): such a game is skipped for that state (numerator and denominator), never imputed
    for st in ("ev", "pp"):
        tk = p[f"toi_{st}_s"].notna(); gk = p[f"gf_{st}"].notna()
        p[f"tok_{st}"] = tk.astype(float); p[f"toc_{st}"] = p[f"toi_{st}_s"].fillna(0.0)
        p[f"gfc_{st}"] = p[f"gf_{st}"].fillna(0.0); p[f"ptc_{st}"] = np.where(gk, p[f"pts_{st}"], 0.0); p[f"gok_{st}"] = gk.astype(float)
    # ---------------- ixG per 60 (last 60 games, half-life 25), shrunk to the position-group rate
    for st, m0 in (("ev", 18000.0), ("pp", 3600.0)):
        ok = (p[f"ixg_{st}"].notna() & (p[f"tok_{st}"] == 1)).to_numpy()
        p["_x"] = np.where(ok, p[f"ixg_{st}"], 0.0); p["_t"] = np.where(ok, p[f"toc_{st}"], 0.0)
        r = _rate(before(p, p._x, by=("pg",)), before(p, p._t, by=("pg",)))
        p[f"ix_{st}60_pre"] = 3600.0 * (_by_player(p, "_x", 60, 25.0) + m0 * r) / (_by_player(p, "_t", 60, 25.0) + m0)
        p[f"ptoi_{st}"] = _rate(_by_player(p, f"toc_{st}", 60, 25.0), _by_player(p, f"tok_{st}", 60, 25.0))
    p["ix_exp_pre"] = p.ix_ev60_pre / 3600.0 * p.ptoi_ev + p.ix_pp60_pre / 3600.0 * p.ptoi_pp
    # ---------------- season totals of the previous two seasons
    cols = ["ptc_ev", "ptc_pp", "gfc_ev", "gfc_pp", "points", "goals", "assists", "gpf"]
    tot = p.groupby(["pid", "season"])[cols].sum().reset_index()
    for lag, pre in ((1, "pv_"), (2, "pw_")):
        x = tot.copy(); x["season"] += lag
        p = p.merge(x.rename(columns={c: pre + c for c in cols}), on=["pid", "season"], how="left")
    cur = lambda c: p[c].groupby([p.pid, p.season], sort=False).cumsum() - p[c]
    z = lambda c: p[c].fillna(0.0)
    # ---------------- IPP by state: seasons weighted 1.0 (to date) / 0.6 / 0.4, shrunk to the position-group IPP with 25 on-ice goals
    for st in ("ev", "pp"):
        P = cur(f"ptc_{st}") + 0.6 * z(f"pv_ptc_{st}") + 0.4 * z(f"pw_ptc_{st}"); G = cur(f"gfc_{st}") + 0.6 * z(f"pv_gfc_{st}") + 0.4 * z(f"pw_gfc_{st}")
        prior = _rate(before(p, p[f"ptc_{st}"], by=("pg",)), before(p, p[f"gfc_{st}"], by=("pg",)))
        p[f"ipp_{st}_pre"] = (P + 25.0 * prior) / (G + 25.0)
        p[f"gfpg_{st}"] = _rate(_by_player(p, f"gfc_{st}", 40, 20.0), _by_player(p, f"gok_{st}", 40, 20.0))
    p["ipp_exp_pts_pre"] = p.gfpg_ev * p.ipp_ev_pre + p.gfpg_pp * p.ipp_pp_pre
    # ---------------- season projection of points, goals and assists
    GP = cur("gpf")
    avail = np.where(p.team_gp > 0, np.minimum(1.0, GP / np.where(p.team_gp > 0, p.team_gp, 1.0)), 1.0)
    R = np.maximum(82.0 - p.team_gp, 0.0) * avail
    ngp = before(p, p.gpf, by=("pg",))
    for c, nm, pref in (("points", "points", "psp"), ("goals", "goals", "aw"), ("assists", "assists", "aw")):
        S0 = cur(c)
        lgpos = _rate(before(p, p[c] * p.gpf, by=("pg",)), ngp)
        pvg = z("pv_gpf")
        prior = np.where(pvg >= 20, z(f"pv_{c}") / np.where(pvg > 0, pvg, 1.0), lgpos)
        epg = (S0 + 10.0 * prior) / (GP + 10.0)
        p[f"{pref}_{nm}_pre"] = S0
        if pref == "psp": p["psp_exp_pg_pre"] = epg
        p[f"{pref}_proj_{nm}_pre" if pref == "aw" else "psp_proj_final_pre"] = S0 + R * epg
    # ---------------- games-played hazard state
    p["gph_share_pre"] = np.where(p.team_gp >= 5, np.minimum(1.0, GP / np.where(p.team_gp > 0, p.team_gp, 1.0)), np.nan)
    p["gph_exp_remaining_pre"] = R
    num = np.zeros(len(p)); den = np.zeros(len(p))
    for w, pre in ((0.5, "pv_"), (0.3, "pw_")):
        g = z(pre + "gpf").to_numpy(); ok = g >= 1
        num += np.where(ok, w * np.maximum(82.0 - g, 0.0), 0.0); den += np.where(ok, w, 0.0)
    p["gph_prior_missed_pre"] = _rate(num, den)
    app = {k: set(v) for k, v in p[p.gpf == 1].groupby(["game_id", "team_id"]).pid}
    order = {k: g.game_id.tolist() for k, g in p.drop_duplicates(["game_id", "team_id"]).groupby(["team_id", "season"], sort=False)}
    miss = np.full(len(p), np.nan)
    for i, (gid, tm, sn, pid, k) in enumerate(zip(p.game_id, p.team_id, p.season, p.pid, p.team_gp)):
        k = int(k)
        if k == 0: continue
        miss[i] = sum(1 for g in order[(tm, sn)][max(0, k - 10):k] if pid not in app.get((g, tm), ()))
    p["gph_missed10_pre"] = miss
    # ---------------- joint-outcome correlations over the player's last 82 games (>= 20)
    p["win"] = np.where(p.tgf > p.tga, 1.0, np.where(p.tgf == p.tga, 0.5, 0.0)); p["tot"] = p.tgf + p.tga
    res = {nm: np.full(len(p), np.nan) for nm in ("joc_pts_tgf_pre", "joc_sog_total_pre", "joc_pts_win_pre")}
    pairs = (("joc_pts_tgf_pre", "points", "tgf"), ("joc_sog_total_pre", "sog", "tot"), ("joc_pts_win_pre", "points", "win"))
    arr = {c: p[c].to_numpy(float) for c in ("points", "tgf", "sog", "tot", "win")}
    for _, ix in p.groupby("pid", sort=False).indices.items():
        n = len(ix)
        if n <= 20: continue
        lo = np.maximum(np.arange(n) - 82, 0); hi = np.arange(n); cnt = (hi - lo).astype(float)
        for nm, a, b in pairs:
            x, y = arr[a][ix], arr[b][ix]
            c = lambda v: np.concatenate([[0.0], np.cumsum(v)])
            sx, sy, sxx, syy, sxy = (c(v)[hi] - c(v)[lo] for v in (x, y, x * x, y * y, x * y))
            vx = cnt * sxx - sx * sx; vy = cnt * syy - sy * sy
            with np.errstate(invalid="ignore", divide="ignore"):
                r = (cnt * sxy - sx * sy) / np.sqrt(vx * vy)
            res[nm][ix] = np.where((cnt >= 20) & (vx > 0) & (vy > 0), r, np.nan)
    for nm, v in res.items(): p[nm] = v
    return p


def compute(raw: dict) -> dict:
    p = _features(_table(raw)).rename(columns={"pid": "team"})
    out = p[["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]].copy()
    return {"team": out.loc[:, ~out.columns.duplicated()]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, d, done, miss, raw=("nhl_player_games",): FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, list(raw), "pregame_rolling")
    return [
        F("nhl.ixg_player", ["ix_ev60_pre", "ix_pp60_pre", "ix_exp_pre"],
          "individual expected goals per 60 at even strength and on the power play over the last 60 games (half-life 25 games), shrunk to the position-group (F/D) rate over earlier dates with 5 hours (EV) / 1 hour (PP) of prior ice time; projected ixG for the game = rates x the player's weighted mean state TOI",
          ["ixG/60 split by EV and PP over the last 60 games (EWMA)", "position-specific prior shrinkage", "projection by TOI by strength state"], ["opponent xGA-by-position adjustment"], ("nhl_player_games", "moneypuck_shots")),
        F("nhl.ipp_by_state", ["ipp_ev_pre", "ipp_pp_pre", "ipp_exp_pts_pre"],
          "individual points percentage = (goals + assists)/on-ice goals for at EV and on the PP, current season to date and the two previous seasons weighted 1.0/0.6/0.4 (= 0.5/0.3/0.2), shrunk to the position-group IPP with k = 25 on-ice goals; expected points per game = sum over states of on-ice GF per game (last 40 games, half-life 20) x IPP",
          ["IPP per state with the 0.5/0.3/0.2 season weights", "position prior with k = 25 on-ice goals", "expected points per game = sum over states of on-ice GF x IPP"],
          ["role (line/unit) in the prior", "separate primary and secondary assist components (k = 60)", "per-60 conversion with projected state TOI"], ("nhl_player_games", "nhl_goals")),
        F("nhl.player_season_points_projection", ["psp_points_pre", "psp_exp_pg_pre", "psp_proj_final_pre"],
          "points to date this season, expected points per game = gamma-Poisson style posterior (points to date + 10 x prior)/(games played + 10) with prior = previous-season points per game (>= 20 games) else the position-group mean, and projected final points = to date + (82 - team games) x min(1, games played/team games) x expected points per game",
          ["points to date plus the sum over remaining games of expected points per game", "current-season rate posterior update"],
          ["strength-state decomposition inside the projection (see nhl.ipp_by_state)", "3-season weighting and role priors", "pmf of games remaining from nhl.games_played_hazard", "negative-binomial simulation and P(total >= threshold)"]),
        F("nhl.award_stats", ["aw_goals_pre", "aw_assists_pre", "aw_proj_goals_pre", "aw_proj_assists_pre"],
          "goals and assists to date this season and their rest-of-season projection: to date + expected remaining games x regressed per-game rate ((to date + 10 x prior)/(games + 10), prior = previous-season rate or position-group mean)",
          ["candidate production to date", "rest-of-season rate projection (regressed) x expected games remaining"], ["EWMA rate", "health probability", "leaderboard simulation", "voter-score regression on historical winners"]),
        F("nhl.games_played_hazard", ["gph_share_pre", "gph_missed10_pre", "gph_prior_missed_pre", "gph_exp_remaining_pre"],
          "share of the team's games this season in which the skater played (>= 5 team games), number of the team's last 10 games he missed, games missed in the two previous seasons weighted 0.5/0.3 (82 - games played, seasons in which he appeared), and expected remaining games = (82 - team games) x availability share",
          ["games missed per skater-season with prior-season weights", "update for the current season with games already played", "expected games remaining"],
          ["zero-inflated negative-binomial fit with age, position and injury covariates", "current injury status", "third prior season (weight 0.2) and 10 seasons of logs (five archived)", "cohort shrinkage k = 25", "pmf of games remaining"]),
        F("nhl.joint_outcome_correlation", ["joc_pts_tgf_pre", "joc_sog_total_pre", "joc_pts_win_pre"],
          "Pearson correlation over the skater's last 82 games (>= 20) between his points and his team's goals, his shots on goal and the game's total goals, and his points and the team result (1 win, 0.5 level after overtime, 0 loss; goals from the player rows, shootout excluded)",
          ["correlations of a player stat with team result and total estimated from historical game logs"], ["latent pace/script/goalie simulation", "between-player correlations", "check of combinations against empirical joint frequencies"]),
    ]

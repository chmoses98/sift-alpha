"""Phase 15 NBA player-game builders (RESEARCH_ONLY): shrunk per-36 stat-rate posterior, season-average state and projected final average, season plus-minus projection, rare three-point make accrual rate.

Raw data: owner's nba-edge-finder ESPN player box scores, regular season only. Output table ``team`` is keyed (game_id, team) where ``team`` is the PLAYER id (one row per player-game of players who played).
Every value for game G uses the player's games on STRICTLY EARLIER DATES only (a player plays at most once per date; league baselines are cumulative sums over earlier dates). Every input is PARTIAL.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nba_ext3 import before

S = "NBA"
PG_COLS = ["game_id", "game_date_et", "season", "season_type", "team_id", "nba_id", "played", "minutes", "pts", "reb", "ast", "stl", "blk", "fg3m", "fg3a", "plus_minus"]
PG_CONTENT = ["minutes", "pts", "reb", "ast", "stl", "blk", "fg3m", "fg3a", "plus_minus"]
STATS = ("pts", "reb", "ast", "stl", "blk", "fg3m")


def load_raw(nba_dir) -> dict:
    h = Path(nba_dir) / "espn"
    return {"player_games": pd.concat([pd.read_parquet(f, columns=PG_COLS) for f in sorted(glob.glob(str(h / "player_games_*.parquet")))], ignore_index=True)}


def compute(raw: dict) -> dict:
    a = raw["player_games"]; a = a[a.season_type == "regular"].copy(); a["date"] = pd.to_datetime(a.game_date_et); a["sidx"] = a.season.astype(str).str[:4].astype(int)
    # team games played before each date (all regular-season games of the team that season, whoever played)
    tg = a.drop_duplicates(["game_id", "team_id"])[["game_id", "team_id", "sidx", "date"]].sort_values(["date", "game_id"], kind="mergesort")
    tg["team_gp"] = tg.groupby(["team_id", "sidx"]).cumcount().astype(float)
    p = a[a.played == True].copy()   # noqa: E712
    p = p.rename(columns={"nba_id": "pid"}).sort_values(["date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    for c in PG_CONTENT: p[c] = p[c].astype(float)
    p = p.merge(tg[["game_id", "team_id", "team_gp"]], on=["game_id", "team_id"], how="left")
    p["one"] = 1.0
    cur = lambda c: p[c].groupby([p.pid, p.sidx], sort=False).cumsum() - p[c]          # this season, earlier games
    car = lambda c: p[c].groupby(p.pid, sort=False).cumsum() - p[c]                    # all earlier games
    tot = p.groupby(["pid", "sidx"])[["one", "minutes", "fg3a", *STATS]].sum().reset_index(); tot["sidx"] += 1
    p = p.merge(tot.rename(columns={c: f"pv_{c}" for c in tot.columns if c not in ("pid", "sidx")}), on=["pid", "sidx"], how="left")
    G, M = cur("one"), cur("minutes")
    Gp, Mp = p.pv_one.fillna(0.0), p.pv_minutes.fillna(0.0)
    n_lg = before(p, p.one); lg_min = before(p, p.minutes)
    # ---- per-36 posterior: (36 x season sum + 400 x prior per-36) / (season minutes + 400)
    for s in STATS:
        with np.errstate(invalid="ignore", divide="ignore"):
            lg36 = np.where(lg_min > 0, 36.0 * before(p, p[s]) / np.where(lg_min > 0, lg_min, 1.0), np.nan)
            r0 = np.where(Mp >= 200, 36.0 * p[f"pv_{s}"].fillna(0.0) / np.where(Mp > 0, Mp, 1.0), lg36)
        p[f"srp_{s}36_pre"] = (36.0 * cur(s) + 400.0 * r0) / (M + 400.0)
    # ---- remaining expected games: (82 - team games so far) x min(1, own games / team games)
    avail = np.where(p.team_gp > 0, np.minimum(1.0, G / np.where(p.team_gp > 0, p.team_gp, 1.0)), 1.0)
    R = np.maximum(82.0 - p.team_gp, 0.0) * avail
    # ---- season average state and projected final average
    for s in ("pts", "reb", "ast"):
        Ss = cur(s)
        with np.errstate(invalid="ignore", divide="ignore"):
            lgavg = np.where(n_lg > 0, before(p, p[s]) / np.where(n_lg > 0, n_lg, 1.0), np.nan)
            prior = np.where(Gp >= 10, p[f"pv_{s}"].fillna(0.0) / np.where(Gp > 0, Gp, 1.0), lgavg)
            p[f"ag_avg_{s}_pre"] = np.where(G > 0, Ss / np.where(G > 0, G, 1.0), np.nan)
            mu = (Ss + 10.0 * prior) / (G + 10.0)
            p[f"ag_proj_{s}_pre"] = np.where(G + R > 0, (Ss + R * mu) / np.where(G + R > 0, G + R, 1.0), np.nan)
    # ---- season plus-minus projection
    p["pm_todate_pre"] = cur("plus_minus")
    p["pm_rate_pre"] = car("plus_minus") / (car("minutes") + 500.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mpg = np.where(G > 0, M / np.where(G > 0, G, 1.0), np.where(Gp > 0, Mp / np.where(Gp > 0, Gp, 1.0), np.nan))
    p["pm_proj_pre"] = p.pm_todate_pre + R * mpg * p.pm_rate_pre
    # ---- rare three-point make accrual: two seasons weighted 0.6 (current, to date) / 0.4 (previous)
    wa = 0.6 * cur("fg3a") + 0.4 * p.pv_fg3a.fillna(0.0); wm = 0.6 * cur("fg3m") + 0.4 * p.pv_fg3m.fillna(0.0); wmin = 0.6 * M + 0.4 * Mp
    with np.errstate(invalid="ignore", divide="ignore"):
        p["rm_3pa36_pre"] = np.where(wmin > 0, 36.0 * wa / np.where(wmin > 0, wmin, 1.0), np.nan)
        p["rm_p3_pre"] = (wm + 40.0 * 0.30) / (wa + 40.0)
        mpg2 = np.where(G + Gp > 0, (M + Mp) / np.where(G + Gp > 0, G + Gp, 1.0), np.nan)
    p["rm_lambda_pre"] = p.rm_3pa36_pre * mpg2 / 36.0 * p.rm_p3_pre
    p["rm_p_any_pre"] = 1.0 - np.exp(-p.rm_lambda_pre * R)
    p["season"] = p.sidx; p = p.rename(columns={"pid": "team"})
    out = p[["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]].copy()
    return {"team": out}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, d, done, miss: FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, ["espn_player_games"], "pregame_rolling")
    return [
        F("nba.stat_rate_posterior", [f"srp_{s}36_pre" for s in STATS],
          "per-36 posterior mean for points, rebounds, assists, steals, blocks and threes made: (36 x season-to-date total + 400 x prior per-36)/(season-to-date minutes + 400), prior = the player's previous-season per-36 rate (>= 200 minutes) else the league per-36 rate over earlier dates",
          ["per-36 basis for the six stats", "minutes-weighted posterior mean (n_prior x prior + n x observed)/(n_prior + n)"],
          ["n_prior estimated per stat by method of moments on a 10-season backtest (a fixed 400 minutes is used)", "last-two-season blend with aging adjustment as the prior", "posterior sd with overdispersion", "per-game conversion with projected minutes"]),
        F("nba.avg_rounding_and_games_state", [f"ag_avg_{s}_pre" for s in ("pts", "reb", "ast")] + [f"ag_proj_{s}_pre" for s in ("pts", "reb", "ast")],
          "season-to-date per-game average of points, rebounds and assists and the projected final average (total to date + remaining games x shrunk rest-of-season average)/(games played + remaining games); remaining games = (82 - team games) x min(1, own games/team games); rest-of-season average shrunk to the previous-season average (>= 10 games, else league) with 10 pseudo-games",
          ["state = totals to date, games played, games remaining", "shrunk rest-of-season average times remaining games plus totals to date", "denominator = games actually played"],
          ["distribution of the final average and P(rounded average >= strike)", "rounding rule (not confirmed by the rules text)", "probability of playing zero games", "threes made (covered per-36 in nba.stat_rate_posterior)"]),
        F("nba.season_plus_minus_projection", ["pm_todate_pre", "pm_rate_pre", "pm_proj_pre"],
          "official box plus/minus to date this season (all teams), career-to-date plus/minus per minute shrunk to zero with 500 minutes, and projected final total = to date + remaining games x minutes per game x per-minute margin",
          ["plus/minus to date summed across teams", "final total = to date + remaining minutes x per-minute margin"],
          ["team opponent-adjusted net rating plus shrunk on/off differential (prior 3000 possessions)", "P(plays) from nba.injury_risk_season and projected minutes from nba.minutes", "simulation of the final total"]),
        F("nba.rare_make_accrual_rate", ["rm_3pa36_pre", "rm_p3_pre", "rm_lambda_pre", "rm_p_any_pre"],
          "3PA per 36 over the current (weight 0.6, to date) and previous (0.4) seasons, make probability shrunk to 0.30 with 40 attempts, per-game make rate lambda = 3PA/36 x minutes per game x p3, and 1 - exp(-lambda x remaining expected games)",
          ["two-season 0.4/0.6 weighting of attempts per 36", "p3 shrunk to 0.30 with k = 40 attempts", "lambda x exposure"],
          ["pre-season attempts at weight 2.0", "position-specific prior", "Cup knockout exposure and scheduled availability", "Gamma(k = 3) mixing of lambda"]),
    ]

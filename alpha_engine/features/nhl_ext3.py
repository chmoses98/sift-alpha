"""Phase 6 NHL team-game builder (RESEARCH_ONLY): nhl.long_change_effect.

Raw data (owner's NHL-edge-finder archive, read only, no new collection): ``players/team_states_*.parquet`` (team-game universe and venue), ``players/goals_*.parquet`` (goal events with period),
``moneypuck/shots_*.parquet`` (shot events with MoneyPuck xGoal and period; seasons 2021-2025 only).

Catalog definition: "Estimate 2nd-period goal and xG rates relative to league baseline by team and compare home/away; shrink heavily and treat as period-level multiplier."

Implementation (every number for game G uses only games on STRICTLY EARLIER DATES):
  * events: regulation (periods 1-3) goals and xG FOR the team, excluding empty-net goals / shots on an empty net (they cluster in period 3 and are not a period-rate effect);
  * window: the team's games in the current season before the date plus all games of the previous season, split by venue (home games / away games);
  * team period-2 share s_T = (P2 events + k x L) / (regulation events + k), with the league share L = league P2 events / league regulation events over the same window (all teams,
    both venues) and heavy shrinkage k = 250 events (about one team-season of regulation goals);
  * period-level multiplier m = s_T / L (1.0 = league-typical second period); computed for goals and for xG, for home games and for away games; home-away difference m_home - m_away;
    the multiplier for THIS game's venue (venue is known from the schedule) is also returned.
xG uses only games that have MoneyPuck shot rows; for the 2026-27 season (no MoneyPuck rows in the archive) the xG columns rest on the previous season.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nba_ext3 import before

S = "NHL"
K = 250.0
TS_COLS = ["game_id", "season", "game_date", "game_type", "team_id", "is_home"]
GO_COLS = ["game_id", "period", "team_id", "empty_net"]
MP_COLS = ["nhl_game_id", "period", "isHomeTeam", "xGoal", "shotOnEmptyNet"]
GO_CONTENT = ["period", "team_id", "empty_net"]
MP_CONTENT = ["period", "isHomeTeam", "xGoal", "shotOnEmptyNet"]
COLS = ["lce_g_mult_home_pre", "lce_g_mult_away_pre", "lce_g_ha_diff_pre", "lce_g_mult_pre",
        "lce_xg_mult_home_pre", "lce_xg_mult_away_pre", "lce_xg_ha_diff_pre", "lce_xg_mult_pre"]


def load_raw(nhl_dir) -> dict:
    h = Path(nhl_dir)
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"team_states": cat("players/team_states_*.parquet", TS_COLS), "goals": cat("players/goals_*.parquet", GO_COLS), "mp": cat("moneypuck/shots_*.parquet", MP_COLS)}


def _events(raw: dict) -> pd.DataFrame:
    """Per team-game: regulation and period-2 goals and xG FOR (empty net excluded)."""
    t = raw["team_states"].drop_duplicates(["game_id", "team_id"]).copy()
    g = raw["goals"]; g = g[g.period.isin([1, 2, 3]) & (g.empty_net != True)]   # noqa: E712
    gg = g.assign(p2=(g.period == 2).astype(float), reg=1.0).groupby(["game_id", "team_id"])[["p2", "reg"]].sum().rename(columns={"p2": "g_p2", "reg": "g_reg"})
    m = raw["mp"]; mp_games = set(m.nhl_game_id.dropna().astype("int64"))
    m = m[m.period.isin([1, 2, 3]) & (m.shotOnEmptyNet.fillna(0) == 0)].copy()
    m["xg"] = m.xGoal.astype(float); m["is_home"] = m.isHomeTeam.astype(float) == 1.0; m["game_id"] = m.nhl_game_id.astype("int64")
    mx = m.assign(x_p2=np.where(m.period == 2, m.xg, 0.0), x_reg=m.xg).groupby(["game_id", "is_home"])[["x_p2", "x_reg"]].sum()
    t = t.merge(gg, left_on=["game_id", "team_id"], right_index=True, how="left")
    t = t.merge(mx, left_on=["game_id", "is_home"], right_index=True, how="left")
    t[["g_p2", "g_reg"]] = t[["g_p2", "g_reg"]].fillna(0.0)
    has = t.game_id.isin(mp_games)
    t[["x_p2", "x_reg"]] = t[["x_p2", "x_reg"]].fillna(0.0).where(has, 0.0)
    return t


def compute(raw: dict) -> dict:
    t = _events(raw)
    t["date"] = pd.to_datetime(t.game_date); t["season"] = t.season.astype(int); t["venue"] = np.where(t.is_home.astype(bool), "H", "A")
    t = t.sort_values(["date", "game_id", "team_id"], kind="mergesort").reset_index(drop=True)
    out = t[["game_id", "team_id", "date", "season", "venue"]].rename(columns={"team_id": "team"}).copy()
    for kind in ("g", "x"):
        p2, rg = f"{kind}_p2", f"{kind}_reg"
        # league window: current season strictly before the date + full previous season
        prev_l = t.groupby("season")[[p2, rg]].sum(); prev_l.index = prev_l.index + 1
        L2 = before(t, t[p2], by=["season"]) + t.season.map(prev_l[p2]).fillna(0.0).to_numpy()
        LR = before(t, t[rg], by=["season"]) + t.season.map(prev_l[rg]).fillna(0.0).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            L = np.where(LR > 0, L2 / np.where(LR > 0, LR, 1.0), np.nan)
        name = "g" if kind == "g" else "xg"
        mult = {}
        for v, lab in (("H", "home"), ("A", "away")):
            sel = (t.venue == v).astype(float)
            prev = t[t.venue == v].groupby(["team_id", "season"])[[p2, rg]].sum().reset_index(); prev["season"] += 1
            pv = t[["team_id", "season"]].merge(prev, on=["team_id", "season"], how="left")
            T2 = before(t, t[p2] * sel, by=["team_id", "season"]) + pv[p2].fillna(0.0).to_numpy()
            TR = before(t, t[rg] * sel, by=["team_id", "season"]) + pv[rg].fillna(0.0).to_numpy()
            with np.errstate(invalid="ignore", divide="ignore"):
                m = ((T2 + K * L) / (TR + K)) / L
            mult[v] = m; out[f"lce_{name}_mult_{lab}_pre"] = m
        out[f"lce_{name}_ha_diff_pre"] = mult["H"] - mult["A"]
        out[f"lce_{name}_mult_pre"] = np.where(t.venue == "H", mult["H"], mult["A"])
    return {"team": out[["game_id", "team", "date", "season"] + COLS]}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "nhl.long_change_effect", "team", COLS, "FULL",
                        "period-2 share of the team's regulation goals FOR and MoneyPuck xG FOR (empty net excluded) over earlier games of the current and previous season, by venue, shrunk to the league "
                        "period-2 share with k = 250 events, divided by the league share: a period-level multiplier (1.0 = league-typical second period); home, away, home minus away, and this game's venue",
                        ["2nd-period goal rate relative to league baseline, by team (P2 share of regulation goals / league P2 share)",
                         "2nd-period xG rate relative to league baseline, by team (MoneyPuck xGoal)",
                         "compare home/away (separate home and away multipliers and their difference)",
                         "shrink heavily (k = 250 events toward the league share)",
                         "treat as period-level multiplier (ratio to the league share; applied to period 2 of a game-rate model)"],
                        [], ["nhl_archive team_states", "nhl_archive goals", "moneypuck shots (xGoal)"], "pregame_rolling")]

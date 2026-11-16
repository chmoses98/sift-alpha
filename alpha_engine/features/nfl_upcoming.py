"""Point-in-time features for SCHEDULED (not yet played) NFL games, from the same certified builders (RESEARCH_ONLY).

The certified builders (features/nfl.py, features/nfl_pbp_ext3.py) emit rows for completed games only, so an upcoming game had no
features. This module gives a scheduled game exactly the value the builders would give it once played:

* legacy builder: one stub team-game row per side is appended AFTER every completed game (stats NaN, outcome NaN, schedule-known
  fields from the schedule) and the builder's own `_pre_features` runs over completed + stub rows. Every *_pre column is a
  function of strictly earlier rows, so a stub's value uses completed games only and completed rows are unchanged.
* ext3 (opponent-adjusted pass/run EPA): its `_pass_run_split` already evaluates "games strictly before date d"; the stub rows
  are passed as the rows to evaluate while the history stays the completed schedule.

Admission (fail closed):
* a game is emitted only when it is the NEXT scheduled game of BOTH teams (no stacked stubs: a later stub would otherwise count
  an earlier stub in game counters such as n_pre);
* `inputs_complete` is False when any game the schedule reports as completed before the cutoff has no play-by-play rows for one
  of the two teams (published score, play-by-play not yet released): those rows keep their features but are flagged stale.

Equivalence check (`truncation_equivalence`): hide every game on/after a past date D (scores and plays), score the games on D with
this module, and compare against the full build's values for the same games. They must match exactly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import nfl as N
from . import nfl_pbp_ext3 as X3

STUB_FIELDS = ["season", "week", "game_type", "date", "home_team", "away_team", "home_rest", "away_rest", "div_game", "roof", "surface",
               "temp", "wind", "referee", "overtime", "home_score", "away_score", "home_coach", "away_coach"]


def next_games(games: pd.DataFrame) -> pd.DataFrame:
    """Scheduled games (no score) that are the next scheduled game of both teams."""
    g = games.copy(); g["date"] = pd.to_datetime(g.gameday)
    # current season only: earlier seasons hold unscored games that were never played (2022_17_BUF_CIN), which are nobody's "next game"
    current = g.loc[g.home_score.notna(), "season"].max()      # the latest season with a completed game
    sched = g[g.home_score.isna() & (g.season == current)]
    if sched.empty:                                             # season over (or week 1 not yet played): the next season's opener
        nxt = g.loc[g.home_score.isna() & (g.season > current), "season"].min()
        sched = g[g.home_score.isna() & (g.season == nxt)]
    sched = sched.sort_values(["date", "game_id"], kind="mergesort")
    long = pd.concat([sched.assign(team=sched.home_team), sched.assign(team=sched.away_team)]).sort_values(["date", "game_id"], kind="mergesort")
    first = long.groupby("team", sort=False).game_id.first()
    ok = sched.home_team.map(first).eq(sched.game_id) & sched.away_team.map(first).eq(sched.game_id)
    return sched[ok].reset_index(drop=True)


def _stub_rows(sched: pd.DataFrame) -> pd.DataFrame:
    """Two team rows per scheduled game with the schedule-known fields the legacy builder reads; every play statistic stays NaN."""
    rows = []
    for home in (1.0, 0.0):
        r = sched[["game_id"] + [c for c in STUB_FIELDS if c in sched.columns and c != "date"]].copy()
        r["date"] = sched["date"].values
        r["team"] = sched.home_team.values if home else sched.away_team.values
        r["home"] = home
        r["opp_name"] = sched.away_team.values if home else sched.home_team.values
        r["rest"] = sched.home_rest.values if home else sched.away_rest.values
        r["coach"] = sched.home_coach.values if home else sched.away_coach.values
        rows.append(r)
    s = pd.concat(rows, ignore_index=True)
    s["referee"] = np.nan; s["temp"] = np.nan; s["wind"] = np.nan        # not known pregame: never read from the schedule for a stub
    s["opp"] = s["opp_name"]
    return s


def legacy_scheduled(raw: dict, sched: pd.DataFrame) -> pd.DataFrame:
    t = N._team_stats(raw)
    s = _stub_rows(sched)
    for c in t.columns:
        if c not in s.columns:
            s[c] = np.nan
    s["win"] = np.nan; s["margin"] = np.nan; s["total"] = np.nan; s["pts"] = np.nan; s["pts_a"] = np.nan
    both = pd.concat([t, s[t.columns]], ignore_index=True)
    both = both.sort_values(["date", "game_id", "home"], ascending=[True, True, False], kind="mergesort").reset_index(drop=True)
    out = N._pre_features(both)
    return out[out.game_id.isin(set(sched.game_id))].reset_index(drop=True)


def ext3_scheduled(raw: dict, sched: pd.DataFrame) -> pd.DataFrame:
    g = X3._games(raw["games"]); p = raw["pbp"]
    s = sched[sched.season >= X3.FIRST].copy()
    tr = X3._team_rows(s)
    if tr.empty:
        return pd.DataFrame(columns=["game_id", "team"])
    return X3._pass_run_split(p, g, tr)


def staleness(raw_games: pd.DataFrame, pbp: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    """Completed games (schedule has a score) dated before `cutoff` whose play-by-play is missing: a stub built now would miss them."""
    g = raw_games.copy(); g["date"] = pd.to_datetime(g.gameday)
    done = g[g.home_score.notna() & (g.date < cutoff) & (g.season == g.season.max())]
    have = set(pbp.game_id.unique())
    missing = sorted(set(done.game_id) - have)
    return {"completed_before_cutoff": int(len(done)), "missing_pbp": missing}


def stale_teams(raw_games: pd.DataFrame, pbp: pd.DataFrame, sched: pd.DataFrame) -> dict:
    """game_id -> teams whose completed game (score published) dated before this scheduled game has no play-by-play yet."""
    g = raw_games.copy(); g["date"] = pd.to_datetime(g.gameday)
    have = set(pbp.game_id.unique())
    miss = g[g.home_score.notna() & ~g.game_id.isin(have) & (g.season == g.season[g.home_score.notna()].max())]
    out = {}
    for _, r in sched.iterrows():
        bad = [t for t in (r.home_team, r.away_team) if ((miss.date < r.date) & ((miss.home_team == t) | (miss.away_team == t))).any()]
        if bad:
            out[r.game_id] = bad
    return out


def truncate(raw: dict, games_full: pd.DataFrame, d: pd.Timestamp) -> tuple[dict, pd.DataFrame]:
    """The world as of date d: scores and plays of games on/after d are hidden."""
    g = games_full.copy(); dt = pd.to_datetime(g.gameday)
    hide = dt >= d
    for c in ("home_score", "away_score", "result", "total", "overtime"):
        if c in g:
            g.loc[hide, c] = np.nan
    gone = set(g.loc[hide, "game_id"])
    pbp = raw["pbp"][~raw["pbp"].game_id.isin(gone)]
    return {**raw, "pbp": pbp, "games": g[[c for c in raw["games"].columns]] if set(raw["games"].columns) <= set(g.columns) else g}, g

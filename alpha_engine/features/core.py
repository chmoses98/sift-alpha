"""Shared building blocks for point-in-time feature builders.

Rules every builder follows (and the audit enforces by perturbation): a team's or player's value for game G is computed from rows of STRICTLY EARLIER games only
(``shift(1)`` inside the entity group after sorting by date, then game id), league baselines use only earlier DATES, and no column of the game's own outcome enters its own features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

HL = 8.0   # default EWMA half-life in games


@dataclass
class FeatureSpec:
    sport: str
    catalog_id: str                 # exact catalog input id
    table: str                      # which output table holds the columns
    columns: list[str]
    level: str                      # FULL = whole definition implemented; PARTIAL = a stated subset; PROXY = different measurement of the same mechanism
    definition: str                 # what the columns measure, exactly
    done: list[str] = field(default_factory=list)       # components of the catalog definition that are implemented
    missing: list[str] = field(default_factory=list)    # components of the catalog definition that are NOT (and why)
    raw: list[str] = field(default_factory=list)        # raw datasets used
    pit: str = "pregame_rolling"    # pregame_rolling | static_pregame | schedule_known | final_postgame (NOT pregame-eligible)


class Paths:
    """Where raw datasets live. Defaults are the cache layout produced by alpha_engine.collect / repo_archives."""
    def __init__(self, raw="/tmp/rawcache", nfl="/tmp/nflcache", soccer="/tmp/soc"):
        self.raw, self.nfl, self.soccer = Path(raw), Path(nfl), Path(soccer)


def prior_ewm(df: pd.DataFrame, by, col: str, hl: float = HL, min_periods: int = 3) -> pd.Series:
    """Pre-game EWMA of ``col`` per entity: values of strictly earlier rows only. df must be sorted chronologically."""
    return df.groupby(by, sort=False)[col].transform(lambda s: s.shift(1).ewm(halflife=hl, min_periods=min_periods).mean())


def prior_mean(df: pd.DataFrame, by, col: str, window: int | None = None, min_periods: int = 3) -> pd.Series:
    g = df.groupby(by, sort=False)[col]
    if window:
        return g.transform(lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean())
    return g.transform(lambda s: s.shift(1).expanding(min_periods=min_periods).mean())


def prior_count(df: pd.DataFrame, by) -> pd.Series:
    return df.groupby(by, sort=False).cumcount()


def prior_date_mean(df: pd.DataFrame, date_col: str, col: str, by=None) -> pd.Series:
    """Running mean of ``col`` over rows on STRICTLY EARLIER dates (optionally within ``by``): a league/venue baseline with no same-day information."""
    keys = [date_col] + ([by] if isinstance(by, str) else list(by or []))
    agg = df.groupby(keys)[col].agg(["sum", "count"]).reset_index().sort_values(keys)
    grp = [] if by is None else ([by] if isinstance(by, str) else list(by))
    agg["cs"] = (agg.groupby(grp)["sum"].cumsum() - agg["sum"]) if grp else (agg["sum"].cumsum() - agg["sum"])
    agg["cn"] = (agg.groupby(grp)["count"].cumsum() - agg["count"]) if grp else (agg["count"].cumsum() - agg["count"])
    agg["m"] = np.where(agg.cn > 0, agg.cs / agg.cn.replace(0, np.nan), np.nan)
    return df.merge(agg[keys + ["m"]], on=keys, how="left")["m"].set_axis(df.index)


def rest_days(df: pd.DataFrame, by, date_col="date", cap=14) -> pd.Series:
    d = df.groupby(by, sort=False)[date_col].transform(lambda s: (s - s.shift(1)).dt.days)
    return d.clip(upper=cap)


def games_in_window(df: pd.DataFrame, by, date_col="date", days=7) -> pd.Series:
    """Number of the entity's games in the `days` days BEFORE this game's date (excludes today)."""
    out = pd.Series(0.0, index=df.index)
    for _, idx in df.groupby(by, sort=False).groups.items():
        d = df.loc[idx, date_col].to_numpy("datetime64[D]")
        lo = np.searchsorted(d, d - np.timedelta64(days, "D"), side="left")
        out.loc[idx] = np.arange(len(d)) - lo
    return out


def opp_adjusted(df: pd.DataFrame, value: str, opp_allowed_pre: str, league_pre: str) -> pd.Series:
    """value expressed relative to what this opponent usually allows, re-centred on the pre-game league mean (the opponent term uses the opponent's EARLIER games only)."""
    return df[value] - df[opp_allowed_pre] + df[league_pre]


def sort_chrono(df: pd.DataFrame, date="date", key="game_id") -> pd.DataFrame:
    return df.sort_values([date, key], kind="mergesort").reset_index(drop=True)


def pair_rows(df: pd.DataFrame, game="game_id", team="team", cols=()) -> pd.DataFrame:
    """For a long team-game table with exactly two rows per game, attach the opponent's value of each ``cols`` (opponent's PRE-game columns when cols are pre-game features)."""
    m = df[[game, team, *cols]].rename(columns={team: "_t", **{c: f"opp_{c}" for c in cols}})
    j = df[[game, team]].merge(m, on=game, how="left")
    j = j[j[team] != j["_t"]].drop(columns="_t").drop_duplicates([game, team])
    return df.merge(j, on=[game, team], how="left")

"""Phase 15 CBB research data build (research only; imports nothing from cbb_edge production paths).

Builds two derived tables from the vault's sportsdataverse ESPN snapshot (archives/CBB/espn_team_box_schedules,
espn_player_box_pbp_early_seasons):

* games: one row per completed game (season = ESPN end year, 2026 = 2025-26), scores, neutral flag, D-I flags,
  possessions (FGA - ORB + TO + 0.475 FTA, mean of both teams; NaN when no team box), tip time.
* halftime: 1H / 2H(+OT) scores from ESPN schedule linescores (available 2023+), OT flag.
* returning: per (season, team) prior-season minutes and the athlete ids that produced them (for continuity),
  computed from player boxes only.

Usage: python research/phase15/cbb_p15_data.py <raw_dir> <out_dir>
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SEASONS = range(2006, 2028)


def _lines(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, str):
        try:
            x = ast.literal_eval(x.replace("}\n {", "}, {").replace("} {", "}, {"))
        except (ValueError, SyntaxError):
            return None
    try:
        return [float(e["value"]) for e in x]
    except (KeyError, TypeError, ValueError):
        return None


def build_games(raw: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    games, halves = [], []
    for y in SEASONS:
        s = pd.read_parquet(raw / f"espn_team_box_schedules/schedules/mbb_schedule_{y}.parquet")
        s = s[(s.status_type_completed == True) & s.home_score.notna() & s.away_score.notna()].copy()  # noqa: E712
        s = s[(s.home_score + s.away_score) > 0]
        t = pd.read_parquet(raw / f"espn_team_box_schedules/team_box/team_box_{y}.parquet")
        to = t["total_turnovers"].fillna(t["turnovers"]) if "total_turnovers" in t else t["turnovers"]
        t = t.assign(poss=t.field_goals_attempted - t.offensive_rebounds + to + 0.475 * t.free_throws_attempted)
        pg = t.groupby("game_id").poss.agg(["mean", "size"])
        pg = pg[pg["size"] == 2]["mean"]
        g = pd.DataFrame({
            "game_id": s.game_id.astype(np.int64), "season": y, "season_type": s.season_type.astype(int),
            "date": pd.to_datetime(s.game_date), "start": pd.to_datetime(s.start_date, utc=True, errors="coerce"),
            "neutral": s.neutral_site.fillna(False).astype(bool),
            "home_id": s.home_id.astype(np.int64), "away_id": s.away_id.astype(np.int64),
            "home_abbr": s.home_abbreviation, "away_abbr": s.away_abbreviation,
            "home_d1": s.home_conference_id.notna(), "away_d1": s.away_conference_id.notna(),
            "home_conf": s.home_conference_id, "away_conf": s.away_conference_id,
            "home_pts": s.home_score.astype(int), "away_pts": s.away_score.astype(int),
        })
        g["poss"] = g.game_id.map(pg)
        games.append(g)
        if "home_linescores" in s:
            hl = s.home_linescores.map(_lines)
            al = s.away_linescores.map(_lines)
            ok = hl.notna() & al.notna()
            for gid, h, a, hs, as_ in zip(s.game_id[ok], hl[ok], al[ok], s.home_score[ok], s.away_score[ok], strict=False):
                if len(h) < 2 or len(h) != len(a):
                    continue
                if abs(sum(h) - hs) > 0.5 or abs(sum(a) - as_) > 0.5:
                    continue  # linescore does not reconcile with the final: drop, never guess
                halves.append((int(gid), y, int(h[0]), int(a[0]), int(sum(h[1:])), int(sum(a[1:])), len(h) - 2))
    games = pd.concat(games, ignore_index=True).drop_duplicates("game_id").sort_values(["date", "game_id"])
    hv = pd.DataFrame(halves, columns=["game_id", "season", "home_1h", "away_1h", "home_2hot", "away_2hot", "n_ot"])
    hv = hv.drop_duplicates("game_id")
    hv["provenance"] = "espn schedule linescores (sportsdataverse snapshot-20261116); sum(periods)==final checked"
    return games.reset_index(drop=True), hv


def build_returning(raw: Path) -> pd.DataFrame:
    """Per (season, team, athlete): minutes played in that season. Continuity features are derived from this
    as-of (only games strictly before the forecast date) in the model module."""
    out = []
    for y in range(2005, 2028):
        p = pd.read_parquet(raw / f"espn_player_box_pbp_early_seasons/espn_mens_college_basketball_player_boxscores/player_box_{y}.parquet",
                            columns=["game_id", "game_date", "athlete_id", "team_id", "minutes"])
        p = p[p.athlete_id.notna() & (p.minutes.fillna(0) > 0)]
        out.append(pd.DataFrame({"season": y, "game_id": p.game_id.astype(np.int64), "date": pd.to_datetime(p.game_date),
                                 "team_id": p.team_id.astype(np.int64), "athlete_id": p.athlete_id.astype(np.int64),
                                 "minutes": p.minutes.astype(float)}))
    return pd.concat(out, ignore_index=True)


if __name__ == "__main__":
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    g, h = build_games(raw)
    g.to_parquet(out / "cbb_games.parquet", index=False)
    h.to_parquet(out / "cbb_halftime_scores.parquet", index=False)
    r = build_returning(raw)
    r.to_parquet(out / "cbb_player_minutes.parquet", index=False)
    print(len(g), len(h), len(r), h.groupby("season").size().to_dict())

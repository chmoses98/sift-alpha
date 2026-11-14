"""MLB StatsAPI season schedule collector: one row per regular-season game with scores, linescore by inning, venue, day/night, recorded weather, home-plate umpire, probable pitchers
and posted lineups (RESEARCH_ONLY). Endpoint: statsapi.mlb.com/api/v1/schedule with hydrate; ~14 calls per season, no per-game calls.

Point-in-time caveat (measured, not assumed): the API returns the CURRENT state of each game. Lineups, officials and weather are the values at retrieval time (post-game for history),
not the pregame vintage; probable pitchers are the final listed. They are valid as *as-played* inputs and as pregame inputs only where the pregame value is known to equal the final one
(starters, home-plate umpire, venue); they are NOT archived vintages. Timestamps of lineup posting are not provided.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from .common import completeness, get_json, now, sha256_file

URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gameType=R&startDate={a}&endDate={b}&hydrate=probablePitcher,lineups,weather,officials,venue,linescore"


def rows_from(day: dict):
    for g in day["games"]:
        if g.get("status", {}).get("abstractGameState") != "Final":
            continue
        ls = g.get("linescore") or {}
        innings = ls.get("innings") or []
        lu = g.get("lineups") or {}
        off = {o["officialType"]: o["official"]["id"] for o in g.get("officials", []) if "official" in o}
        w = g.get("weather") or {}
        h, a = g["teams"]["home"], g["teams"]["away"]
        yield {"game_pk": g["gamePk"], "date": g["officialDate"], "season": int(g["season"]), "game_number": g.get("gameNumber"), "double_header": g.get("doubleHeader"),
               "home_id": h["team"]["id"], "away_id": a["team"]["id"], "home_score": h.get("score"), "away_score": a.get("score"), "innings_played": len(innings) or None,
               "home_runs_by_inning": json.dumps([i.get("home", {}).get("runs") for i in innings]) if innings else None, "away_runs_by_inning": json.dumps([i.get("away", {}).get("runs") for i in innings]) if innings else None,
               "venue_id": (g.get("venue") or {}).get("id"), "day_night": g.get("dayNight"), "game_time_utc": g.get("gameDate"), "weather_condition": w.get("condition"), "temp": pd.to_numeric(w.get("temp"), errors="coerce"),
               "wind": w.get("wind"), "home_plate_ump_id": off.get("Home Plate"), "home_sp_id": (h.get("probablePitcher") or {}).get("id"), "away_sp_id": (a.get("probablePitcher") or {}).get("id"),
               "home_lineup": json.dumps([p["id"] for p in lu.get("homePlayers", [])]) if lu.get("homePlayers") else None, "away_lineup": json.dumps([p["id"] for p in lu.get("awayPlayers", [])]) if lu.get("awayPlayers") else None}


def collect(seasons, cache: Path) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in seasons:
        d = dt.date(y, 3, 15)
        while d < dt.date(y, 11, 5):
            e = min(d + dt.timedelta(days=13), dt.date(y, 11, 5))
            js = get_json(URL.format(a=d, b=e), pause=0.2)
            for day in (js or {}).get("dates", []):
                rows.extend(rows_from(day))
            d = e + dt.timedelta(days=1)
        print(y, len(rows), flush=True)
    df = pd.DataFrame(rows).drop_duplicates("game_pk").sort_values(["date", "game_pk"]).reset_index(drop=True)
    f = cache / "mlb_schedule_games.csv.gz"
    df.to_csv(f, index=False)
    fields = ["home_score", "innings_played", "home_runs_by_inning", "venue_id", "day_night", "weather_condition", "temp", "wind", "home_plate_ump_id", "home_sp_id", "away_sp_id", "home_lineup", "away_lineup"]
    return {"source": "statsapi.mlb.com /api/v1/schedule (hydrate probablePitcher,lineups,weather,officials,venue,linescore)", "retrieved_utc": now(), "seasons": sorted(int(x) for x in df.season.unique()), "games": int(len(df)),
            "games_by_season": {str(k): int(v) for k, v in df.groupby("season").size().items()}, "date_min": str(df.date.min()), "date_max": str(df.date.max()), "field_completeness_by_season": completeness(df, fields),
            "cache_file": f.name, "sha256": sha256_file(f), "timestamp_reliability": "AS_PLAYED_NOT_PREGAME_VINTAGE: lineups, officials and weather are the retrieval-time values; lineup posting times are not provided",
            "unlocks_raw_fields": ["final score", "runs by inning", "venue", "day/night", "recorded weather", "home-plate umpire", "starting pitchers", "batting orders"]}


def main():
    seasons = [int(x) for x in sys.argv[2:]] or list(range(2015, 2026))
    led = collect(seasons, Path(sys.argv[1]))
    out = Path(__file__).resolve().parents[2] / "research/input_research/data_collection/mlb_schedule_ledger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(led, indent=1, sort_keys=True))
    print(led["games"], "games", led["seasons"])


if __name__ == "__main__":
    main()

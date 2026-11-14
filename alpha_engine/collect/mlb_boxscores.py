"""MLB StatsAPI boxscore collector: one row per player-game with batting (PA, AB, H, 2B, 3B, HR, RBI, R, BB, K, SB, TB, batting-order slot) and pitching (outs, BF, pitches, H, ER, BB, K,
starter flag) lines (RESEARCH_ONLY). Game ids come from the schedule cache (mlb_schedule.py). One call per game; FINAL post-game records. Pregame rolling features must use only earlier games.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from .common import completeness, get_json, now, sha256_file

URL = "https://statsapi.mlb.com/api/v1/game/{pk}/boxscore"
BAT = {"plateAppearances": "pa", "atBats": "ab", "hits": "h", "doubles": "d2", "triples": "d3", "homeRuns": "hr", "rbi": "rbi", "runs": "r", "baseOnBalls": "bb", "strikeOuts": "so", "stolenBases": "sb", "totalBases": "tb"}
PIT = {"outs": "outs", "battersFaced": "bf", "numberOfPitches": "pitches", "hits": "h_alw", "earnedRuns": "er", "baseOnBalls": "bb_alw", "strikeOuts": "k", "gamesStarted": "gs", "homeRuns": "hr_alw"}


def parse(pk, x):
    rows = []
    for side in ("home", "away"):
        t = x["teams"][side]
        for p in t["players"].values():
            st = p.get("stats", {})
            bat, pit = st.get("batting") or {}, st.get("pitching") or {}
            if not bat and not pit:
                continue
            r = {"game_pk": pk, "side": side, "team_id": t["team"]["id"], "player_id": p["person"]["id"], "pos": (p.get("position") or {}).get("abbreviation"), "bat_order": int(p["battingOrder"]) if p.get("battingOrder") else None}
            r.update({v: bat.get(k) for k, v in BAT.items()} if bat else {})
            r.update({v: pit.get(k) for k, v in PIT.items()} if pit else {})
            rows.append(r)
    return rows


def collect(sched_file: Path, seasons, cache: Path, limit=None) -> dict:
    g = pd.read_csv(sched_file)
    g = g[g.season.isin(seasons)]
    pks = g.game_pk.tolist()[:limit]
    rows, miss = [], 0
    for i, pk in enumerate(pks):
        x = get_json(URL.format(pk=pk), pause=0.05)
        if x is None:
            miss += 1; continue
        rows.extend(parse(pk, x))
        if i % 500 == 0: print(i, len(pks), len(rows), flush=True)
    df = pd.DataFrame(rows).merge(g[["game_pk", "season", "date"]], on="game_pk", how="left")
    f = cache / "mlb_player_games.csv.gz"
    df.to_csv(f, index=False)
    return {"source": "statsapi.mlb.com /api/v1/game/{pk}/boxscore", "retrieved_utc": now(), "seasons": sorted(int(s) for s in df.season.unique()), "games_requested": len(pks), "games_missing": miss, "player_game_rows": int(len(df)),
            "rows_by_season": {str(k): int(v) for k, v in df.groupby("season").size().items()}, "field_completeness_by_season": completeness(df, ["pa", "ab", "hr", "so", "outs", "pitches", "bf", "er", "k", "gs", "bat_order"]),
            "starting_pitcher_rows": int((df.gs == 1).sum()), "cache_file": f.name, "sha256": sha256_file(f), "timestamp_reliability": "FINAL_POSTGAME",
            "unlocks_raw_fields": ["player batting lines", "player pitching lines (outs, BF, pitches, ER, K)", "starter flag", "batting-order slot", "stolen bases", "total bases"]}


def main():
    cache, seasons = Path(sys.argv[1]), [int(x) for x in sys.argv[2:]]
    led = collect(cache / "mlb_schedule_games.csv.gz", seasons, cache)
    out = Path(__file__).resolve().parents[2] / "research/input_research/data_collection/mlb_boxscores_ledger.json"
    out.write_text(json.dumps(led, indent=1, sort_keys=True))
    print(led["player_game_rows"], "rows")


if __name__ == "__main__":
    main()

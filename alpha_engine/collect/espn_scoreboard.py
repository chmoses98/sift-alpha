"""ESPN scoreboard collector for college basketball and college football (RESEARCH_ONLY): one row per completed game with both teams' scores and period scores, rankings, records,
venue, neutral-site and attendance flags. One call per date. Odds/lines fields in the ESPN payload are NEVER read (market-free policy).

Point-in-time: final post-game records (period scores, final scores); rankings/records are those ESPN attached at retrieval time (post-game state), so only use them for
as-played context or compute pre-game values from earlier games.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from .common import completeness, get_json, now, sha256_file

LEAGUES = {"CBB": ("basketball/mens-college-basketball", "groups=50&limit=400", (11, 1), (4, 10)), "CFB": ("football/college-football", "groups=80&limit=300", (8, 20), (1, 20))}


def parse(ev, league):
    c = ev["competitions"][0]
    if not ev.get("status", {}).get("type", {}).get("completed"):
        return None
    t = {x["homeAway"]: x for x in c["competitors"]}
    if "home" not in t or "away" not in t:
        return None
    def ls(x): return [int(float(p["value"])) for p in x.get("linescores", []) if "value" in p]
    return {"league": league, "game_id": ev["id"], "date": ev["date"][:10], "start_utc": ev["date"], "season": None, "home_id": t["home"]["team"]["id"], "away_id": t["away"]["team"]["id"], "home_name": t["home"]["team"].get("displayName"),
            "away_name": t["away"]["team"].get("displayName"), "home_score": pd.to_numeric(t["home"].get("score"), errors="coerce"), "away_score": pd.to_numeric(t["away"].get("score"), errors="coerce"),
            "home_periods": json.dumps(ls(t["home"])), "away_periods": json.dumps(ls(t["away"])), "n_periods": len(ls(t["home"])) or None,
            "home_rank": (t["home"].get("curatedRank") or {}).get("current"), "away_rank": (t["away"].get("curatedRank") or {}).get("current"), "neutral_site": c.get("neutralSite"),
            "attendance": c.get("attendance"), "venue_id": (c.get("venue") or {}).get("id"), "indoor": (c.get("venue") or {}).get("indoor"), "conference_game": c.get("conferenceCompetition"),
            "season_type": (ev.get("season") or {}).get("type"), "week": (ev.get("week") or {}).get("number")}


def daterange(league, seasons):
    path, q, (sm, sd), (em, ed) = LEAGUES[league]
    for y in seasons:
        a = dt.date(y, sm, sd) if league == "CFB" else dt.date(y - 1, sm, sd)
        b = dt.date(y + 1, em, ed) if league == "CFB" else dt.date(y, em, ed)
        d = a
        while d <= b:
            yield y, d
            d += dt.timedelta(days=1 if league == "CBB" else 1)


def collect(league, seasons, cache: Path) -> dict:
    path, q, _, _ = LEAGUES[league]
    rows = []
    for y, d in daterange(league, seasons):
        if league == "CFB" and d.weekday() not in (3, 4, 5, 0, 1, 2, 6):
            continue
        js = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d:%Y%m%d}&{q}", pause=0.15)
        for ev in (js or {}).get("events", []):
            r = parse(ev, league)
            if r:
                r["season"] = y; rows.append(r)
        if d.day == 1: print(league, d, len(rows), flush=True)
    df = pd.DataFrame(rows).drop_duplicates("game_id").reset_index(drop=True)
    f = cache / f"espn_{league.lower()}_games.csv.gz"
    df.to_csv(f, index=False)
    fields = ["home_score", "home_periods", "n_periods", "home_rank", "neutral_site", "attendance", "venue_id", "indoor", "conference_game", "week"]
    return {"source": f"site.api.espn.com scoreboard ({path})", "retrieved_utc": now(), "seasons": sorted(int(s) for s in df.season.unique()), "games": int(len(df)), "games_by_season": {str(k): int(v) for k, v in df.groupby("season").size().items()},
            "date_min": str(df.date.min()), "date_max": str(df.date.max()), "field_completeness_by_season": completeness(df, fields), "cache_file": f.name, "sha256": sha256_file(f),
            "timestamp_reliability": "FINAL_POSTGAME (scores, period scores); rank/records are retrieval-time values", "odds_fields_read": False}


def main():
    league, cache, seasons = sys.argv[1], Path(sys.argv[2]), [int(x) for x in sys.argv[3:]]
    led = collect(league, seasons, cache)
    out = Path(__file__).resolve().parents[2] / f"research/input_research/data_collection/espn_{league.lower()}_ledger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(led, indent=1, sort_keys=True))
    print(led["games"], "games", led["seasons"])


if __name__ == "__main__":
    main()

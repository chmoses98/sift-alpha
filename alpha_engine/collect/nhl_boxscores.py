"""NHL API regular-season boxscore collector: team-game rows (goals, shots on goal, start time, venue, final period type) and player-game rows (TOI, shots, goals, assists, PP goals, hits,
blocks, faceoff %, goalie starter flag, saves/shots against) from api-web.nhle.com (RESEARCH_ONLY). Enumerates game ids YYYY02NNNN (regular season) per season.

Point-in-time: boxscores are FINAL (post-game) records. They support rolling pre-game features (using only earlier games) and as-played checks; they do not provide pregame lineups,
confirmed goalie starts or scratches (those need a pregame source: see the lineup-probe archive in nhl-edge-finder).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from .common import completeness, get_json, now, sha256_file

URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"


def toi_min(s):
    try:
        m, sec = str(s).split(":"); return int(m) + int(sec) / 60
    except Exception:
        return None


def parse(x):
    if not x or x.get("gameState") not in ("OFF", "FINAL") or x.get("gameType") != 2:
        return None, []
    h, a = x["homeTeam"], x["awayTeam"]
    game = {"game_id": x["id"], "season": int(str(x["season"])[:4]), "date": x["gameDate"], "start_utc": x["startTimeUTC"], "home": h["abbrev"], "away": a["abbrev"], "home_goals": h.get("score"), "away_goals": a.get("score"),
            "home_sog": h.get("sog"), "away_sog": a.get("sog"), "last_period": (x.get("gameOutcome") or {}).get("lastPeriodType"), "venue": (x.get("venue") or {}).get("default")}
    players = []
    for side, team in (("homeTeam", h["abbrev"]), ("awayTeam", a["abbrev"])):
        for grp in ("forwards", "defense", "goalies"):
            for p in x["playerByGameStats"][side].get(grp, []):
                r = {"game_id": x["id"], "season": game["season"], "team": team, "home": side == "homeTeam", "player_id": p["playerId"], "pos": p.get("position"), "toi": toi_min(p.get("toi"))}
                if grp == "goalies":
                    r.update({"starter": p.get("starter"), "saves": p.get("saves"), "shots_against": p.get("shotsAgainst"), "goals_against": p.get("goalsAgainst")})
                else:
                    r.update({"goals": p.get("goals"), "assists": p.get("assists"), "sog": p.get("sog"), "pp_goals": p.get("powerPlayGoals"), "hits": p.get("hits"), "blocks": p.get("blockedShots"), "shifts": p.get("shifts"),
                              "faceoff_pct": p.get("faceoffWinningPctg"), "pim": p.get("pim")})
                players.append(r)
    return game, players


def collect(seasons, cache: Path, max_games=1400) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    games, players = [], []
    for y in seasons:
        miss = 0
        for n in range(1, max_games + 1):
            x = get_json(URL.format(gid=f"{y}02{n:04d}"), pause=0.05)
            if x is None:
                miss += 1
                if miss > 25: break
                continue
            miss = 0
            g, ps = parse(x)
            if g: games.append(g); players.extend(ps)
        print(y, len(games), flush=True)
    G, P = pd.DataFrame(games), pd.DataFrame(players)
    fg, fp = cache / "nhl_games.csv.gz", cache / "nhl_player_games.csv.gz"
    G.to_csv(fg, index=False); P.to_csv(fp, index=False)
    return {"source": "api-web.nhle.com /v1/gamecenter/{id}/boxscore", "retrieved_utc": now(), "seasons": sorted(int(s) for s in G.season.unique()), "games": int(len(G)), "player_game_rows": int(len(P)),
            "games_by_season": {str(k): int(v) for k, v in G.groupby("season").size().items()}, "date_min": str(G.date.min()), "date_max": str(G.date.max()),
            "game_field_completeness_by_season": completeness(G, ["home_goals", "home_sog", "last_period", "start_utc"]),
            "player_field_completeness_by_season": completeness(P, ["toi", "sog", "hits", "blocks", "faceoff_pct", "pp_goals"]), "goalie_starter_flag_share": float(P[P.pos == "G"].starter.notna().mean()) if len(P) else None,
            "cache_files": {fg.name: sha256_file(fg), fp.name: sha256_file(fp)}, "timestamp_reliability": "FINAL_POSTGAME_RECORDS (start time recorded; no pregame lineup/scratch/goalie-confirmation vintage)",
            "unlocks_raw_fields": ["team goals and shots on goal", "player TOI", "player shots/goals/assists/PP goals", "hits and blocks", "faceoff %", "goalie starter flag, saves, shots against", "OT/SO flag", "start time and venue"]}


def main():
    seasons = [int(x) for x in sys.argv[2:]] or [2022, 2023, 2024]
    led = collect(seasons, Path(sys.argv[1]))
    out = Path(__file__).resolve().parents[2] / "research/input_research/data_collection/nhl_boxscores_ledger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(led, indent=1, sort_keys=True))
    print(led["games"], "games")


if __name__ == "__main__":
    main()

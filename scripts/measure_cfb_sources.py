"""Measure CFB source evidence from cfb-edge-finder checkouts and write research/audit/verification/source_verifications.json.
usage: python scripts/measure_cfb_sources.py CFB_CHECKOUT   (needs `main` checked out and FETCH_HEAD = research-sidecar with history)
Measurements only; the engine decides what they may change (never to VERIFIED)."""
import collections
import json
import statistics as st
import subprocess
import sys
from datetime import datetime
from pathlib import Path

repo = Path(sys.argv[1])
root = Path(__file__).resolve().parents[1]


def git(*a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


main_commit = git("rev-parse", "HEAD").strip()
side_commit = git("rev-parse", "FETCH_HEAD").strip()
tg = [json.loads(line) for line in (repo / "data/football/2026/team_games.jsonl").read_text().splitlines() if line.strip()]
man = json.loads((repo / "data/football/2026/manifest.json").read_text())
ko = {r["game_id"]: r["kickoff_utc"] for r in tg}
games = {r["game_id"] for r in tg}
with_pbp = [r for r in tg if r.get("pbp")]
obs = collections.Counter(r["observed_at"][:10] for r in tg)
ev = {"CFB:cfb.pace": ["box.plays", "box.possession_seconds", "pbp.early_plays", "pbp.neutral_plays"], "CFB:cfb.drives": ["pbp.drives", "pbp.drive_plays", "pbp.scoring_opps"],
      "CFB:cfb.pass_rate": ["pbp.pass_plays", "pbp.rush_plays", "pbp.neutral_pass_plays"]}
out = {"schema_version": "source-verifications-1.0",
       "note": "Measured facts about data that ALREADY EXISTS in sibling repos. The engine may use these only to move an input out of UNKNOWN/MISSING into COLLECTED_UNVERIFIED or STALE; nothing here can mark an input VERIFIED.",
       "inputs": {}}
meas = {"source": {"repo": "chmoses98/cfb-edge-finder", "commit": main_commit, "path": "data/football/2026/team_games.jsonl", "manifest_sha256": man["hashes"]["team_games.jsonl"]},
        "team_game_rows": len(tg), "games": len(games), "rows_with_play_log": len(with_pbp), "completed_games_in_manifest": man["completed_games_with_fbs_team"],
        "observed_at_dates": dict(obs), "availability": "observed_at is a backfill date, NOT publication time: point-in-time availability UNVERIFIED (use kickoff + lag as a conservative proxy)"}
for k, fields in ev.items():
    out["inputs"][k] = {"verification_class": "COLLECTED_UNVERIFIED_PIT", "collection": "COLLECTED_NOT_PIT_ARCHIVED", "measured": dict(meas, fields=fields),
                        "why": "ESPN box score + drive summary aggregates for every completed FBS game in the log; post-game rows usable only as lagged features for later games"}
side = {}
for kind in ("espn_injuries", "weather_forecast"):
    rows = [json.loads(line) for line in git("show", f"FETCH_HEAD:data/research/live_sidecar/{kind}/2026.jsonl").splitlines() if line.strip()]
    j = [r for r in rows if r["game_id"] in ko]
    lead = [(ts(ko[r["game_id"]]) - ts(r["fetched_at"])).total_seconds() / 3600 for r in j]
    log = git("log", "-p", "--format=##COMMIT%H\t%cI", "FETCH_HEAD", "--", f"data/research/live_sidecar/{kind}/2026.jsonl")
    lags, cur = [], None
    for line in log.splitlines():
        if line.startswith("##COMMIT"):
            cur = ts(line.split("\t")[1])
        elif line.startswith("+{") and cur:
            lags.append((cur - ts(json.loads(line[1:])["fetched_at"])).total_seconds() / 60)
    lags.sort()
    side[kind] = {"rows": len(rows), "games": len({r["game_id"] for r in rows}), "games_joined_to_completed": len({r["game_id"] for r in j}), "completed_games_total": len(games),
                  "coverage_of_completed_games": round(len({r["game_id"] for r in j}) / len(games), 4), "fetched_before_kickoff_share": round(sum(x > 0 for x in lead) / len(lead), 4),
                  "lead_hours_median": round(st.median(lead), 1), "lead_hours_min": round(min(lead), 1), "http_status": {str(k): v for k, v in collections.Counter(r["http_status"] for r in rows).items()},
                  "payload_sha256_present_share": round(sum(bool(r.get("payload_sha256")) for r in rows) / len(rows), 4),
                  "fetched_range": [min(r["fetched_at"] for r in rows), max(r["fetched_at"] for r in rows)], "git_commit_minus_fetched_minutes": {"p50": round(lags[len(lags) // 2], 1), "max": round(lags[-1], 1), "rows_committed_before_fetched": sum(x < 0 for x in lags)},
                  "nonempty_payload_share": round(sum((r["parsed"].get("count") or 0) > 0 for r in rows) / len(rows), 4) if kind == "espn_injuries" else None,
                  "source": {"repo": "chmoses98/cfb-edge-finder", "branch": "research-sidecar", "commit": side_commit, "path": f"data/research/live_sidecar/{kind}/2026.jsonl"}}
out["inputs"]["CFB:cfb.weather_pit"] = {"verification_class": "STALE_OR_PARTIAL", "collection": "PARTIAL_OR_STALE", "measured": side["weather_forecast"],
                                        "why": "Open-Meteo forecasts with per-row fetched_at, payload hash and git-history corroboration exist for a minority of games and capture stopped after the last fetch date"}
out["inputs"]["CFB:cfb.injuries"] = {"verification_class": "STALE_OR_PARTIAL", "collection": "PARTIAL_OR_STALE", "measured": side["espn_injuries"],
                                     "why": "ESPN core injuries are timestamped and hashed but almost always empty; capture stopped after the last fetch date"}
(root / "research/audit/verification/source_verifications.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print({k: (v["verification_class"]) for k, v in out["inputs"].items()}, {k: (v["coverage_of_completed_games"], v["fetched_range"][1][:10]) for k, v in side.items()})

"""Bounded, immutable-source audit of real CFB ESPN injury archive observations.

This verifies a *sample archive file* from the CFB repository's projection-data
branch, not the source's clinical or sporting accuracy, completeness, or that
any player was confirmed active. Only aggregates are reported.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

PIN_PATH = Path("research/audit/lineage/cfb_availability_archive_pin.json")
MAX_COMPRESSED = 20000
MAX_EXPANDED = 2_000_000
MAX_ROWS = 10_000
KINDS = {"injury", "lineup", "starter", "depth", "rotation", "line", "roster", "restriction"}
STATUSES = {"ACTIVE", "STARTING", "PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT",
            "INACTIVE", "BENCH", "NOT_STARTING", "LIMITED", "UNKNOWN"}
CERTAINTIES = {"CONFIRMED", "REPORTED", "PROJECTED", "UNKNOWN"}


def utc(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be explicit UTC")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Unparseable UTC timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp cannot lack timezone or use a non-UTC offset")
    return stamp.astimezone(timezone.utc)


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def validate_pin(pin):
    if (pin.get("schema_version") != 1 or pin.get("sport") != "CFB"
            or pin.get("source_repository") != "chmoses98/cfb-edge-finder"
            or pin.get("source_commit") != "a25f7359e93196a90de4a33e71d4f058f3b2f9e6"
            or pin.get("source_path") != "availability/cfb/2026-11-03/182807Z_fa2133e7cdad.jsonl.gz"
            or pin.get("source_git_blob_sha1") != "4212b907fac277b93fbdec5d7ee56c08e10ab97e"
            or type(pin.get("source_bytes")) is not int or pin["source_bytes"] != 11739):
        raise ValueError("Unapproved or changed CFB archive source pin")
    return pin


def load_rows(pin, payload):
    validate_pin(pin)
    if not isinstance(payload, bytes) or len(payload) != pin["source_bytes"] or len(payload) > MAX_COMPRESSED:
        raise ValueError("Compressed archive size mismatch or budget exceeded")
    if git_blob_sha(payload) != pin["source_git_blob_sha1"]:
        raise ValueError("Archive Git blob identity mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
        expanded = stream.read(MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED:
        raise ValueError("Archive decompression budget exceeded")
    lines = [x for x in expanded.splitlines() if x.strip()]
    if not 0 < len(lines) <= MAX_ROWS:
        raise ValueError("Empty or excessive availability rows")
    rows = [json.loads(line) for line in lines]
    return rows


def audit_rows(rows, *, source_sha="UNPINNED_TEST_FIXTURE"):
    """Strictly classify each archived statement; never infer missing player = active."""
    counts = Counter()
    teams, events, pregame_events = set(), set(), set()
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("schema") != "sift.availability.v1" or row.get("sport") != "CFB":
            raise ValueError("Wrong sport or availability schema")
        for key in ("event_id", "entity_id", "team", "source"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError("Missing statement provenance " + key)
        kind, status, certainty = row.get("kind"), row.get("status"), row.get("certainty")
        if kind not in KINDS or status not in STATUSES or certainty not in CERTAINTIES:
            raise ValueError("Invalid kind, status, or certainty")
        captured, kickoff = utc(row.get("captured_utc")), utc(row.get("event_start_utc"))
        updated = utc(row["source_updated_utc"]) if row.get("source_updated_utc") else None
        if updated and updated > captured:
            raise ValueError("Source update claims a timestamp after local capture")
        key = (row["event_id"], row["entity_id"], kind, row["captured_utc"], row["source"])
        if key in seen:
            raise ValueError("Duplicate observation identity in immutable source file")
        seen.add(key)
        events.add(row["event_id"])
        teams.add((row["event_id"], row["team"]))
        counts["rows"] += 1
        counts["kind_" + kind] += 1
        counts["certainty_" + certainty] += 1
        if captured >= kickoff:
            counts["at_or_after_kickoff_excluded"] += 1
            continue
        pregame_events.add(row["event_id"])
        counts["pre_kickoff_observations"] += 1
        if kind == "roster":
            counts["team_list_sentinals_not_healthy_rosters"] += 1
            if row["source"] == "espn_core_injuries":
                counts["espn_team_lists_read"] += int(row.get("detail", {}).get("injury_list_read") is True)
        if kind == "starter" and certainty == "PROJECTED":
            counts["projected_starters_not_confirmed"] += 1
        if kind == "injury":
            counts["player_injury_listings"] += 1
            detail = row.get("detail") or {}
            if detail.get("stale") is True:
                counts["injury_listings_source_marked_stale"] += 1
            if (row["source"] == "espn_core_injuries" and certainty == "REPORTED"
                    and status in {"OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE"}
                    and detail.get("stale") is False and updated):
                counts["fresh_reported_injury_designations"] += 1
        if certainty == "CONFIRMED" and kind in {"starter", "lineup"}:
            counts["confirmed_lineup_or_starter_statements"] += 1
    return {
        "schema_version": 1,
        "sport": "CFB",
        "authority": "PINNED_ARCHIVE_FILE_CONTENT_AUDITED_RESEARCH_ONLY",
        "source_blob_sha1": source_sha,
        "counts": dict(sorted(counts.items())),
        "distinct_events": len(events),
        "distinct_event_teams": len(teams),
        "events_with_any_pregame_observation": len(pregame_events),
        "player_participation_completeness": "NOT_ESTABLISHED",
        "injury_feed_freshness": "COUNTED_NOT_CERTIFIED",
        "model_use_verified": False,
        "predictive_validation": "NOT_ESTABLISHED",
        "trading_authority": "NONE",
        "limitations": [
            "One pinned CFB capture file; not full-season or all-event coverage.",
            "A team-list sentinel never proves any specific player is healthy.",
            "The ESPN source has previously returned 2022 injury records during 2026.",
            "A previous-game leading passer is a projected starter, not a confirmed starter.",
            "Rows at/after kickoff are excluded from pregame counts, not rewritten."
        ],
    }


def retrieve(pin):
    validate_pin(pin)
    url = ("https://raw.githubusercontent.com/" + pin["source_repository"] + "/"
           + pin["source_commit"] + "/" + pin["source_path"])
    with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-source-audit/1"}), timeout=25) as response:
        if response.geturl() != url:
            raise ValueError("Source redirected away from pinned GitHub URL")
        data = response.read(MAX_COMPRESSED + 1)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="artifacts/cfb_injury_archive_probe.json")
    args = ap.parse_args()
    pin = validate_pin(json.loads(PIN_PATH.read_text()))
    result = audit_rows(load_rows(pin, retrieve(pin)), source_sha=pin["source_git_blob_sha1"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

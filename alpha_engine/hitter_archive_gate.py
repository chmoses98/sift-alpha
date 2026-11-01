"""Read-only, point-in-time feasibility gate for archived MLB hitter snapshots.

A tree inventory proves that a file existed at a pinned source revision, NOT
that its forecast was available at the market observation timestamp.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from . import research_repair as rr

REPO = rr.REPO
COMMIT = rr.COMMIT
TREE_SHA = "9badc6104aa2e30c7084ff9675a9bc93ffcc9afb"
SNAPSHOT_DATE = "2026-08-24"
SNAPSHOT_SHA = "4a5e74bbbe69c11bcc466c8f7977e6b84bf661f2"
SNAPSHOT_PATH = f"data/edgelab/hitter_projection_snapshots/{SNAPSHOT_DATE}.jsonl"
MAX_TREE_BYTES = 16000
MAX_SNAPSHOT_BYTES = 60000
MAX_SNAPSHOT_ROWS = 100
EXPECTED_TREE_FILES = 31
_DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}\.jsonl$")
_HEX = re.compile(r"^[0-9a-f]{40}$")


def git_hash(kind, raw):
    return hashlib.sha1(f"{kind} {len(raw)}\0".encode() + raw).hexdigest()


def tree_inventory(payload):
    """Recreate Git's tree object, not merely trust an API's claimed SHA."""
    if not isinstance(payload, dict) or payload.get("sha") != TREE_SHA or payload.get("truncated") is not False:
        raise ValueError("Unpinned or truncated archive tree")
    entries = payload.get("tree")
    if not isinstance(entries, list) or len(entries) != EXPECTED_TREE_FILES:
        raise ValueError("Archive inventory incomplete")
    seen = set()
    git_entries = []
    by_date = {}
    for e in entries:
        if not isinstance(e, dict) or e.get("type") != "blob" or e.get("mode") != "100644":
            raise ValueError("Non-file entry in archive tree")
        path, sha, size = e.get("path"), e.get("sha"), e.get("size")
        if not isinstance(path, str) or not _DATE.fullmatch(path) or path in seen:
            raise ValueError("Invalid or duplicate archive date")
        if not isinstance(sha, str) or not _HEX.fullmatch(sha):
            raise ValueError("Invalid blob SHA")
        if type(size) is not int or not 0 < size <= 6000000:
            raise ValueError("Invalid archive file size")
        seen.add(path)
        by_date[path.removesuffix(".jsonl")] = {"sha": sha, "bytes": size}
        git_entries.append((path.encode(), b"100644 " + path.encode() + b"\0" + bytes.fromhex(sha)))
    raw = b"".join(entry for _, entry in sorted(git_entries))
    if git_hash("tree", raw) != TREE_SHA:
        raise ValueError("Archive Git tree object mismatch")
    if by_date.get(SNAPSHOT_DATE) != {"sha": SNAPSHOT_SHA, "bytes": 57692}:
        raise ValueError("Pilot snapshot absent or changed")
    return by_date


def _timestamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Timestamp must be explicit UTC")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("Non-UTC timestamp")
    return dt


def audit_snapshot(raw):
    """Verify original snapshot rows; no implied historical price/forecast join."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SNAPSHOT_BYTES:
        raise ValueError("Missing or oversized hitter snapshot")
    if git_hash("blob", raw) != SNAPSHOT_SHA:
        raise ValueError("Hitter snapshot source hash mismatch")
    try:
        lines = raw.decode("utf-8").splitlines()
        if not 0 < len(lines) <= MAX_SNAPSHOT_ROWS:
            raise ValueError("Unbounded snapshot row count")
        rows = [json.loads(line) for line in lines]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed snapshot rows") from exc
    tickers, ids = set(), set()
    families = Counter()
    generated_after_market = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Non-object hitter snapshot")
        ticker, ident = row.get("marketTicker"), row.get("hitterProjectionSnapshotId")
        if not isinstance(ticker, str) or not ticker.startswith("KXMLB") or ticker in tickers:
            raise ValueError("Missing/duplicate exact ticker")
        if not isinstance(ident, str) or not _HEX.fullmatch(ident) or ident in ids:
            raise ValueError("Missing/duplicate snapshot identity")
        tickers.add(ticker)
        ids.add(ident)
        if row.get("marketFamily") not in {"hitter_hits", "hitter_total_bases", "hitter_hits_runs_rbis", "hitter_rbis"}:
            raise ValueError("Unrecognized hitter family")
        if row.get("projectionStatus") != "PROJECTED" or row.get("pricingStatus") != "PRICED":
            raise ValueError("Unexpected forecast status; do not count as evaluated")
        if not isinstance(row.get("playerId"), str) or not row["playerId"].isdigit() or type(row.get("gameId")) is not int:
            raise ValueError("Unresolved player or game identity")
        p = row.get("modelProbability")
        if type(p) not in (int, float) or not 0 <= p <= 1:
            raise ValueError("Invalid forecast probability")
        market = _timestamp(row.get("marketObservedAt"))
        generated = _timestamp(row.get("projectionGeneratedAt"))
        snapshot = _timestamp(row.get("snapshotGeneratedAt"))
        if market.date().isoformat() != SNAPSHOT_DATE or generated.date().isoformat() != SNAPSHOT_DATE:
            raise ValueError("Snapshot date disagrees with timestamps")
        if generated > snapshot:
            raise ValueError("Snapshot published before its forecast existed")
        if generated > market:
            generated_after_market += 1
        families[row["marketFamily"]] += 1
    return {
        "rows": len(rows),
        "families": dict(sorted(families.items())),
        "forecasts_generated_after_recorded_market_observation": generated_after_market,
        "eligible_forecasts_at_recorded_market_observation": len(rows) - generated_after_market,
        "independently_valid_model_evaluations": None,
        "verified_game_start": False,
        "verified_player_team_at_game": False,
        "verified_market_quote_at_forecast_publication": False,
        "interpretation": "Source forecasts are later than the recorded quote; only independently archived later market observations could establish subsequent PIT eligibility.",
    }


def analyze(report, tree_payload, snapshot_raw):
    before = rr.audit_mlb(report)
    dates = report["report"].get("datesWithObservations")
    if not isinstance(dates, list) or len(dates) != len(set(dates)) or not dates:
        raise ValueError("Missing/duplicate historical observation dates")
    if any(not isinstance(d, str) or not _DATE.fullmatch(d + ".jsonl") for d in dates):
        raise ValueError("Invalid observation date")
    if sorted(dates) != dates or dates[0] != "2026-08-01" or dates[-1] != "2026-08-20":
        raise ValueError("Historical report date scope changed")
    archive = tree_inventory(tree_payload)
    overlap = sorted(set(dates) & set(archive))
    pilot = audit_snapshot(snapshot_raw)
    if pilot["rows"] != 31 or pilot["forecasts_generated_after_recorded_market_observation"] != 31:
        raise ValueError("Pilot counts changed; no silent rebaseline")
    if before["opportunity_rows"] != 138158 or before["model_evaluated_rows"] != 694:
        raise ValueError("Historical coverage counts changed")
    return {
        "schema_version": 1,
        "authority": "RESEARCH_ONLY_NO_BACKFILL",
        "sport": "MLB",
        "source_commit": COMMIT,
        "snapshot_directory_git_tree_sha1": TREE_SHA,
        "pilot_snapshot_git_blob_sha1": SNAPSHOT_SHA,
        "historical_opportunity_rows_unchanged": before["opportunity_rows"],
        "historical_model_evaluated_rows_unchanged": before["model_evaluated_rows"],
        "historical_hitter_hits_evaluated_unchanged": 0,
        "historical_hitter_hits_observed_unchanged": 23295,
        "historical_observation_dates": len(dates),
        "archive_dates_overlapping_historical_report": overlap,
        "archive_dates_not_present_in_historical_report": len(archive) - len(overlap),
        "historical_dates_without_snapshot_file_at_pin": len(dates) - len(overlap),
        "snapshot_archive_file_count": len(archive),
        "pilot_date": SNAPSHOT_DATE,
        "pilot": pilot,
        "repair_result": "BLOCKED_NO_SAFE_HISTORICAL_REPAIR",
        "blocker": "Two large Aug 19/20 source files require bounded row-level PIT market/evaluation reconciliation. Earlier dates lack this snapshot archive at pin; no historical forecast fabrication. Aug 24 pilot forecasts postdate its quoted market observations.",
        "source_accuracy_or_profitability_certified": False,
    }


def _fetch(url, limit):
    with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-hitter-archive/1"}), timeout=15) as response:
        if response.geturl() != url:
            raise ValueError("Source redirected")
        raw = response.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError("Remote source outside budget")
    return raw


def run():
    manifest = json.loads(Path("research/mlb_repair_source_pins.json").read_text())
    witnesses, _ = rr.load_sources(manifest)
    report = json.loads(witnesses["historical_quality"])
    tree_url = f"https://api.github.com/repos/{REPO}/git/trees/{TREE_SHA}"
    snap_url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{SNAPSHOT_PATH}"
    tree = json.loads(_fetch(tree_url, MAX_TREE_BYTES))
    return analyze(report, tree, _fetch(snap_url, MAX_SNAPSHOT_BYTES))


def main():
    result = run()
    out = Path("artifacts/mlb_hitter_archive_gate.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Hitter snapshot archive:", result["archive_dates_overlapping_historical_report"],
          "dates overlap historical report;", result["pilot"]["rows"],
          "pilot rows; zero eligible at original market observation time; no backfill.")
    print("Evidence:", out)


if __name__ == "__main__":
    main()

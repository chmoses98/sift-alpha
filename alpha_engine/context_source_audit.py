"""Independent archived NBA/NHL schedule + settlement source qualification.

Six immutable source files, each exact Git blob verified. This audits what
context and outcome fields EXIST. A matching contract ticker is not proof of
correct settlement rules; a schedule snapshot is not a game-to-contract map.
No betting, no paid API, no after-start inference, no source writes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from .delta_timeutil import parse_iso

REPOS = {"NBA": "chmoses98/nba-edge-finder", "NHL": "chmoses98/NHL-edge-finder"}
SHA = re.compile(r"^[0-9a-f]{40}$")
PATH = re.compile(r"^[A-Za-z0-9_./=-]+$")
CAPTURE = re.compile(r"_(\d{8}T\d{6}Z)_\d+\.jsonl\.gz$")
MAX_ROWS = 20000


def check_manifest(doc):
    if doc.get("schema_version") != 1 or not isinstance(doc.get("sources"), list):
        raise ValueError("Unexpected context manifest")
    if len(doc["sources"]) != 6:
        raise ValueError("Expected exactly two schedules + one settlement per sport")
    if type(doc.get("max_total_compressed_bytes")) is not int or not 0 < doc["max_total_compressed_bytes"] <= 100000:
        raise ValueError("Unbounded total retrieval")
    limit = doc.get("max_decompressed_bytes_per_file")
    if type(limit) is not int or not 0 < limit <= 3000000:
        raise ValueError("Unbounded expansion")
    total = 0
    count = Counter()
    seen = set()
    for item in doc["sources"]:
        sport, kind = item.get("sport"), item.get("kind")
        if sport not in REPOS or kind not in ("schedule", "settlement") or item.get("repository") != REPOS[sport]:
            raise ValueError("Unapproved sport/source")
        if not SHA.fullmatch(item.get("commit", "")) or not SHA.fullmatch(item.get("sha", "")):
            raise ValueError("Mutable or unverified source")
        path = item.get("path", "")
        prefix = "context/schedule/dt=" if kind == "schedule" else "settlements/dt="
        if (not PATH.fullmatch(path) or ".." in path.split("/") or
                not path.startswith(prefix) or not CAPTURE.search(path)):
            raise ValueError("Untrusted source path or filename timestamp")
        if path in seen:
            raise ValueError("Duplicate source path")
        seen.add(path)
        size = item.get("bytes")
        if type(size) is not int or not 0 < size <= 100000:
            raise ValueError("Unbounded source size")
        total += size
        count[(sport, kind)] += 1
    if total > doc["max_total_compressed_bytes"]:
        raise ValueError("Aggregate source size exceeded")
    for sport in REPOS:
        if count[(sport, "schedule")] != 2 or count[(sport, "settlement")] != 1:
            raise ValueError("Missing source coverage")
    return doc["sources"]


def capture_at(item):
    stamp = CAPTURE.search(item["path"])
    if not stamp:
        raise ValueError("Missing source capture timestamp")
    return datetime.strptime(stamp.group(1), "%Y%m%dT%H%M%SZ").replace(
        tzinfo=timezone.utc
    ).isoformat().replace("+00:00", "Z")


def source_url(item):
    return f"https://raw.githubusercontent.com/{item['repository']}/{item['commit']}/{item['path']}"


def read_source(item, limit, downloader=None):
    if downloader is None:
        url = source_url(item)
        req = Request(url, headers={"User-Agent": "SIFT-Alpha-context-qualifier/1"})
        with urlopen(req, timeout=15) as resp:
            if resp.geturl() != url:
                raise ValueError("Unexpected redirect")
            raw = resp.read(item["bytes"] + 1)
    else:
        raw = downloader(item)
    if len(raw) != item["bytes"]:
        raise ValueError("Source compressed size mismatch")
    actual_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual_sha != item["sha"]:
        raise ValueError("Source Git blob checksum mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        plain = gz.read(limit + 1)
    if len(plain) > limit:
        raise ValueError("Source gzip expansion budget exceeded")
    rows = []
    for line in plain.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("Source JSONL row not an object")
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ValueError("Source JSONL row budget exceeded")
    return rows, hashlib.sha256(raw).hexdigest()


def source_profile(rows):
    keys = Counter()
    nested = Counter()
    for row in rows:
        keys.update(row)
        for k, v in row.items():
            if isinstance(v, dict):
                nested.update(f"{k}.{sub}" for sub in v)
    return {"n_rows": len(rows), "top_level_fields": sorted(keys),
            "nested_fields": sorted(nested)[:100]}


def settlement_candidate(row):
    """No invented outcome from score, team win, status, or NO-side symmetry."""
    data = row.get("settlement") if isinstance(row.get("settlement"), dict) else row
    ticker = data.get("ticker") or row.get("ticker")
    result = data.get("result")
    if not isinstance(ticker, str) or not ticker.startswith("KX"):
        return None, "NO_EXACT_CONTRACT_TICKER"
    if not isinstance(result, str) or result.strip().lower() not in ("yes", "no"):
        return None, "NO_LITERAL_YES_NO_RESULT"
    return (ticker, result.strip().upper()), None


def select_schedule_asof(sources, cutoff):
    """Use source capture time only; never select a future schedule snapshot."""
    at = parse_iso(cutoff)
    candidates = [s for s in sources if s["kind"] == "schedule" and parse_iso(s["captured_at"]) <= at]
    return max(candidates, key=lambda x: x["captured_at"]) if candidates else None


def audit(manifest, tape_report, tape_rows, downloader=None):
    entries = check_manifest(manifest)
    if tape_report.get("authority") != "RESEARCH_ONLY" or set(tape_report.get("sports", {})) != set(REPOS):
        raise ValueError("Requires verified NBA/NHL research-only tape")
    if tape_report.get("full_day_or_season") is not False:
        raise ValueError("Unexpected tape coverage")
    tickers = defaultdict(set)
    for row in tape_rows:
        sport = row.get("sport")
        if sport not in REPOS or row.get("pregame_status") != "UNVERIFIED" or row.get("quote_execution_authority") != "NONE":
            raise ValueError("Unverified or non-research tape input")
        if not isinstance(row.get("ticker"), str):
            raise ValueError("Missing tape ticker")
        tickers[sport].add(row["ticker"])
    if not all(tickers.values()) or len(tickers) != 2:
        raise ValueError("Tape lacks both sports")

    sources = defaultdict(list)
    settlement_rows = defaultdict(list)
    for item in entries:
        rows, digest = read_source(item, manifest["max_decompressed_bytes_per_file"], downloader)
        profile = source_profile(rows)
        source = {"sport": item["sport"], "kind": item["kind"],
                  "captured_at": capture_at(item), "path": item["path"],
                  "blob_sha1": item["sha"], "content_sha256": digest,
                  "source_commit": item["commit"], "profile": profile}
        sources[item["sport"]].append(source)
        if item["kind"] == "settlement":
            settlement_rows[item["sport"]].extend(rows)

    results = {}
    for sport in sorted(REPOS):
        tape = tape_report["sports"][sport]
        source_list = sorted(sources[sport], key=lambda x: (x["captured_at"], x["kind"]))
        asof = select_schedule_asof(source_list, tape["base_at"])
        if asof is None:
            raise ValueError("No independent schedule snapshot available at tape base")
        after = [s for s in source_list if s["kind"] == "schedule" and parse_iso(s["captured_at"]) > parse_iso(tape["base_at"])]
        if not after:
            raise ValueError("No post-base schedule for lookahead test")
        if parse_iso(asof["captured_at"]) > parse_iso(tape["base_at"]):
            raise ValueError("Schedule time travel")
        seen = {}
        excluded = Counter()
        for row in settlement_rows[sport]:
            candidate, reason = settlement_candidate(row)
            if candidate is None:
                excluded[reason] += 1
                continue
            ticker, result = candidate
            if ticker in seen and seen[ticker] != result:
                raise ValueError("Conflicting literal contract settlement outcomes")
            seen[ticker] = result
        matches = sorted(t for t in seen if t in tickers[sport])
        results[sport] = {
            "tape_base_at": tape["base_at"],
            "tape_last_at": tape["last_verified_at"],
            "schedule_source_available_at_tape_base": asof["path"],
            "schedule_capture_at": asof["captured_at"],
            "n_schedule_snapshots_after_tape_base_excluded_from_base": len(after),
            "n_unique_literal_yes_no_settlement_tickers_in_sample": len(seen),
            "n_exact_ticker_matches_to_sparse_tape": len(matches),
            "n_unmatched_literal_settlement_tickers": sum(t not in tickers[sport] for t in seen),
            "settlement_row_exclusions": dict(excluded),
            "matched_examples": [{"ticker": t, "literal_result": seen[t],
                                  "settlement_rule_verification": "NOT_VERIFIED",
                                  "physical_game_id": None} for t in matches[:5]],
            "physical_game_join": "NOT_ESTABLISHED",
            "pregame_market_eligibility": "NOT_ESTABLISHED",
            "settlement_rules": "NOT_VERIFIED",
            "execution_or_profitability_authority": "NONE",
            "source_profiles": source_list,
        }
    return {"schema_version": 1, "authority": "RESEARCH_ONLY",
            "sports": results,
            "limitations": [
                "A source capture timestamp proves only when the archived schedule was captured, not the game start or exact contract mapping.",
                "Exact ticker result matches are descriptive and do not independently validate contract settlement rules.",
                "The sampled post-tape settlement files may contain no matching contracts.",
                "No pregame, fee, execution, model or profitability conclusion is authorized.",
            ]}

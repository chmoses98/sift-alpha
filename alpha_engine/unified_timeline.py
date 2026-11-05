"""Unified point-in-time Kalshi contract tape, read-only and fail-closed.

This v0 unifies archived quote *observations* across two sport repositories;
it does NOT infer game start times, historic executable fills, or profitable
strategies. Replaying full checkpoint/delta chains requires a later adapter.

No paid provider, authentication or live Kalshi API access.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

SHA = re.compile(r"^[a-f0-9]{40}$")
FILE_TS = re.compile(r"(\d{8}T\d{6}Z)")
ALLOWED = {"chmoses98/NHL-edge-finder", "chmoses98/nba-edge-finder"}
ALLOWED_KINDS = {"market", "settlement"}


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("Missing UTC observation timestamp")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Unparseable timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Observation timestamps must carry UTC timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def file_time(path):
    match = FILE_TS.search(path)
    if not match:
        raise ValueError("No immutable source-file timestamp; can't anchor observation")
    return parse_time(datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat())


def check_manifest(doc):
    if doc.get("schema_version") != 1 or not isinstance(doc.get("files"), list):
        raise ValueError("Malformed source manifest")
    entries = doc["files"]
    if not entries or not isinstance(doc.get("max_download_bytes_total"), int):
        raise ValueError("Missing bounded downloads")
    total = 0
    seen = set()
    sports = set()
    for entry in entries:
        if entry.get("repository") not in ALLOWED or entry.get("kind") not in ALLOWED_KINDS:
            raise ValueError("Source outside reviewed allowlist")
        if not SHA.fullmatch(entry.get("commit", "")) or not SHA.fullmatch(entry.get("git_blob_sha1", "")):
            raise ValueError("Unpinned source")
        path = entry.get("path", "")
        if not re.fullmatch(r"[A-Za-z0-9_./=-]+", path) or ".." in path.split("/") or not path.endswith(".jsonl.gz"):
            raise ValueError("Unsafe path/unsupported compression")
        if entry.get("sport") not in ("NBA", "NHL"):
            raise ValueError("Unexpected sport")
        key = (entry["repository"], entry["commit"], path)
        if key in seen:
            raise ValueError("Duplicate pinned file")
        seen.add(key)
        size = entry.get("compressed_bytes")
        if type(size) is not int or not 0 < size <= 2_000_000:
            raise ValueError("Missing or excessive file-size budget")
        total += size
        sports.add(entry["sport"])
    if total > doc["max_download_bytes_total"] or total > 4_000_000:
        raise ValueError("Would exceed strict free read budget")
    limit = doc.get("max_decompressed_bytes_per_file")
    if type(limit) is not int or not 0 < limit <= 50_000_000:
        raise ValueError("Invalid decompression guard")
    return entries


def raw_url(entry):
    return "https://raw.githubusercontent.com/" + entry["repository"] + "/" + entry["commit"] + "/" + entry["path"]


def decode_pinned(payload, entry, max_uncompressed):
    if len(payload) != entry["compressed_bytes"]:
        raise ValueError("Compressed archive byte-length mismatch")
    digest = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    if digest != entry["git_blob_sha1"]:
        raise ValueError("Source Git blob SHA mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
        plain = stream.read(max_uncompressed + 1)
    if len(plain) > max_uncompressed:
        raise ValueError("Decompression budget exceeded")
    records = []
    for i, line in enumerate(plain.splitlines(), start=1):
        if line.strip():
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"Source row {i} not an object")
            records.append(obj)
    return records, hashlib.sha256(payload).hexdigest()


def fetch_file(entry):
    # URL is composed strictly from pinned allowlisted constants and immutable
    # commit. Do not accept redirects to other hostnames or use credentials.
    url = raw_url(entry)
    req = Request(url, headers={"User-Agent": "SIFT-Alpha-ReadOnlyTape/0.1"})
    with urlopen(req, timeout=20) as response:
        if response.geturl() != url:
            raise ValueError("Unexpected redirect or mutable artifact")
        payload = response.read(entry["compressed_bytes"] + 1)
    return payload


def dollars(record, stem):
    """Read only exact quoted side, never infer YES ask from NO bid."""
    modern = record.get(stem + "_dollars")
    old = record.get(stem)
    if modern is None and old is None:
        return None
    try:
        if modern is not None:
            number = Decimal(str(modern))
        elif type(old) is int:
            number = Decimal(old) / 100
        else:
            raise ValueError("Ambiguous cents field")
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Unparseable price") from exc
    if not number.is_finite() or not 0 <= number <= 1:
        raise ValueError("Out of range quote")
    return str(number)


def unwrap(raw):
    if isinstance(raw.get("market"), dict):
        return raw["market"]
    return raw


def market_row(raw, source_file):
    market = unwrap(raw)
    ticker = market.get("ticker") or raw.get("ticker")
    if not isinstance(ticker, str) or not ticker.startswith("KX"):
        return None, "NO_TICKER"
    observed = (raw.get("_observed_at_utc") or raw.get("observed_at")
                or raw.get("captured_at") or market.get("_observed_at_utc"))
    source_confidence = "ROW_TIMESTAMP"
    if observed is None:
        observed = file_time(source_file)
        source_confidence = "ARCHIVE_FILE_TIMESTAMP_ONLY"
    observed = parse_time(observed)
    quote = {"yes_bid": dollars(market, "yes_bid"), "yes_ask": dollars(market, "yes_ask"),
             "no_bid": dollars(market, "no_bid"), "no_ask": dollars(market, "no_ask")}
    return {
        "ticker": ticker, "event_ticker": market.get("event_ticker"),
        "observed_at": observed, "timestamp_basis": source_confidence,
        "source_file": source_file, "quote": quote,
        "status": market.get("status"),
        # A Kalshi event ticker is NOT proof of the underlying physical game ID.
        "physical_game_id": None, "event_start_at": None,
    }, None


def settlement_row(raw):
    rec = raw.get("settlement") if isinstance(raw.get("settlement"), dict) else raw
    ticker = raw.get("ticker") or rec.get("ticker")
    outcome = rec.get("result") or rec.get("kalshi_result") or raw.get("result")
    if not isinstance(ticker, str) or not ticker.startswith("KX"):
        return None
    if not isinstance(outcome, str) or outcome.lower() not in ("yes", "no"):
        return None
    return {"ticker": ticker, "result": outcome.lower()}


def timeline(observations, settlements, max_examples=5):
    by_ticker = defaultdict(list)
    for row in observations:
        by_ticker[row["ticker"]].append(row)
    unique_settled = {}
    conflicts = 0
    for result in settlements:
        prior = unique_settled.get(result["ticker"])
        if prior is not None and prior != result["result"]:
            conflicts += 1
            continue
        unique_settled[result["ticker"]] = result["result"]
    if conflicts:
        raise ValueError("Conflicting official contract outcomes: quarantine source")
    counts = Counter()
    example = []
    for ticker, rows in sorted(by_ticker.items()):
        rows.sort(key=lambda x: (x["observed_at"], x["source_file"]))
        times = defaultdict(set)
        for row in rows:
            times[row["observed_at"]].add(json.dumps(row["quote"], sort_keys=True))
        if any(len(values) > 1 for values in times.values()):
            counts["conflicting_same_timestamp_quotes"] += 1
            continue
        quotes = [r for r in rows if any(v is not None for v in r["quote"].values())]
        unique_times = len(times)
        counts["tickers"] += 1
        counts["observations"] += len(rows)
        counts["tickers_with_multiple_timestamps"] += (unique_times >= 2)
        counts["tickers_with_quote_fields"] += bool(quotes)
        counts["tickers_with_settlement"] += ticker in unique_settled
        if unique_times >= 2 and len(quotes) >= 2:
            start = quotes[0]["quote"]
            end = quotes[-1]["quote"]
            moved = any(start[field] is not None and end[field] is not None
                        and start[field] != end[field] for field in start)
            counts["tickers_with_observed_quote_movement"] += moved
        if len(example) < max_examples:
            example.append({
                "ticker": ticker,
                "observation_count": len(rows),
                "first_observed_at": rows[0]["observed_at"],
                "last_observed_at": rows[-1]["observed_at"],
                "quote_at_first": rows[0]["quote"], "quote_at_last": rows[-1]["quote"],
                "observed_timestamp_basis": sorted({r["timestamp_basis"] for r in rows}),
                "settlement_result": unique_settled.get(ticker),
                "physical_game_join": "UNVERIFIED",
                "pregame_cutoff": "UNVERIFIED",
                "execution_status": "NOT_ASSESSED",
            })
    if counts["conflicting_same_timestamp_quotes"]:
        raise ValueError("Conflicting observations require independent source reconciliation")
    return {"counts": dict(counts), "examples": example,
            "settlements_in_source_not_matching_tickers": sum(t not in by_ticker for t in unique_settled),
            "n_unique_settlements_in_source": len(unique_settled),
            "research_authority": "DESCRIPTIVE_ONLY",
            "reason": "No verified physical-game joins, event start times, orderbook depth, fee schedule, or complete checkpoint/delta reconstruction. No profitable or pregame inference authorized."}


def run(manifest, downloader=None):
    entries = check_manifest(manifest)
    downloader = downloader or fetch_file
    tapes = defaultdict(list)
    results = defaultdict(list)
    excluded = defaultdict(Counter)
    provenance = []
    for entry in entries:
        data = downloader(entry)
        rows, digest = decode_pinned(data, entry, manifest["max_decompressed_bytes_per_file"])
        provenance.append({"id": entry["id"], "sport": entry["sport"], "kind": entry["kind"],
                           "sha256": digest, "git_blob_sha1": entry["git_blob_sha1"],
                           "rows": len(rows), "source": raw_url(entry)})
        for raw in rows:
            if entry["kind"] == "market":
                obs, reason = market_row(raw, entry["path"])
                if obs is None:
                    excluded[entry["sport"]][reason] += 1
                else:
                    tapes[entry["sport"]].append(obs)
            else:
                s = settlement_row(raw)
                if s is None:
                    excluded[entry["sport"]]["SETTLEMENT_UNRESOLVED"] += 1
                else:
                    results[entry["sport"]].append(s)
    return {
        "schema_version": 1, "status": "RESEARCH_ONLY",
        "provenance": provenance,
        "sport_tapes": {sport: {**timeline(tapes[sport], results[sport]),
                               "excluded_rows": dict(excluded[sport])}
                        for sport in sorted({entry["sport"] for entry in entries})},
        "limitations": [
            "Partial sampled archive checkpoints; full delta chains not reconstructed",
            "Quote snapshots are not necessarily pregame or executable without verified event-start and depth",
            "Result extraction requires authoritative settlement-rule and original-source verification",
            "No cross-contract independent game clustering or statistical profitability analysis",
        ],
    }

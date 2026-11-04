"""Bounded, source-hash verified Tennis Kalshi quote capture (NOT a full delta tape).

The first capture is an upstream hourly full snapshot; later captures contain
changed-fingerprint rows only. They cannot establish removals, a full later
board, fillable prices, physical games, or exchange settlement.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import re
from urllib.request import Request, urlopen

REPO = "chmoses98/Tennis-Edge-Finder"
ROOT = "tennis-edge-finder/data/kalshi/capture/"
SHA = re.compile(r"^[0-9a-f]{40}$")
RUN = re.compile(r"^\d{8}T\d{6}Z$")
SIDES = ("yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars")
TERMS = ("event_ticker", "series_ticker", "title", "subtitle", "yes_sub_title",
         "no_sub_title", "strike_type", "floor_strike", "cap_strike",
         "close_time", "occurrence_datetime", "expected_expiration_time")


def utc(value):
    if not isinstance(value, str):
        raise ValueError("Missing observation timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp is not UTC")
    return dt.astimezone(timezone.utc)


def validate_manifest(spec):
    if (spec.get("schema_version") != 1 or spec.get("sport") != "TENNIS"
            or spec.get("repository") != REPO or not SHA.fullmatch(spec.get("commit", ""))):
        raise ValueError("Unapproved source or mutable revision")
    captures = spec.get("captures")
    if not isinstance(captures, list) or len(captures) != 3:
        raise ValueError("Require one hourly full and two sequential changed captures")
    total = 0
    prev_run = ""
    paths = set()
    for i, capture in enumerate(captures):
        run_id = capture.get("run_id", "")
        if not RUN.fullmatch(run_id) or run_id <= prev_run:
            raise ValueError("Invalid or unordered run ids")
        prev_run = run_id
        date = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
        for kind, suffix in (("manifest", ".manifest.json"), ("quotes", ".quotes.jsonl.gz")):
            entry = capture.get(kind)
            if not isinstance(entry, dict):
                raise ValueError("Missing pinned capture file")
            path = entry.get("path", "")
            if path != f"{ROOT}{date}/{run_id}{suffix}" or path in paths:
                raise ValueError("Unexpected capture path or duplicate")
            paths.add(path)
            if not SHA.fullmatch(entry.get("sha", "")):
                raise ValueError("Missing source Git blob SHA")
            size = entry.get("bytes")
            if type(size) is not int or not 0 < size <= 200000:
                raise ValueError("Unbounded capture file")
            total += size
    if total > 300000 or spec.get("max_total_bytes") != 300000:
        raise ValueError("Aggregate source budget exceeded")
    if spec.get("max_expanded_bytes_per_file") != 4000000:
        raise ValueError("Unbounded decompression")
    return captures


def read_pinned(spec, entry, downloader=None):
    url = f"https://raw.githubusercontent.com/{REPO}/{spec['commit']}/{entry['path']}"
    if downloader is not None:
        raw = downloader(entry)
    else:
        with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-research/1"}), timeout=20) as response:
            if response.geturl() != url:
                raise ValueError("Unapproved redirect")
            raw = response.read(entry["bytes"] + 1)
    if not isinstance(raw, bytes) or len(raw) != entry["bytes"]:
        raise ValueError("Pinned source byte length mismatch")
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != entry["sha"]:
        raise ValueError("Pinned source content hash mismatch")
    return raw


def natural_count(value, field):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid count " + field)
    return value


def parse_capture(spec, capture, index, downloader):
    manifest = json.loads(read_pinned(spec, capture["manifest"], downloader))
    if (not isinstance(manifest, dict) or manifest.get("run_id") != capture["run_id"]
            or manifest.get("incomplete") != []
            or manifest.get("client_stats", {}).get("failures") != 0):
        raise ValueError("Incomplete or mismatched upstream capture")
    started, finished = utc(manifest.get("started_at")), utc(manifest.get("finished_at"))
    if finished <= started or (finished-started).total_seconds() > 1800:
        raise ValueError("Capture clock or duration inconsistent")
    counts = manifest["counts"]
    opened = natural_count(counts.get("open_markets"), "open_markets")
    written = natural_count(counts.get("quotes_written"), "quotes_written")
    unchanged = natural_count(counts.get("quotes_unchanged"), "quotes_unchanged")
    if not opened or written + unchanged != opened:
        raise ValueError("Upstream quote counts do not reconcile")
    if index == 0:
        if manifest.get("hourly_sweep") is not True or written != opened or unchanged:
            raise ValueError("No verified initial hourly full capture")
    elif manifest.get("hourly_sweep") is not False:
        raise ValueError("Expected changed-fingerprint capture")
    blob = read_pinned(spec, capture["quotes"], downloader)
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
        expanded = stream.read(spec["max_expanded_bytes_per_file"] + 1)
    if len(expanded) > spec["max_expanded_bytes_per_file"]:
        raise ValueError("Quote gzip expansion exceeded budget")
    rows = []
    tickers = set()
    for line in expanded.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("run_id") != capture["run_id"]:
            raise ValueError("Invalid quote row or run id")
        ticker = row.get("ticker")
        if not isinstance(ticker, str) or not ticker or ticker in tickers:
            raise ValueError("Missing or duplicate exact ticker")
        tickers.add(ticker)
        at = utc(row.get("captured_at"))
        if not started <= at <= finished:
            raise ValueError("Quote observed outside source capture window")
        kind = "full" if index == 0 else "changed"
        if row.get("snapshot_kind") != kind:
            raise ValueError("Unexpected source snapshot kind")
        quotes = {}
        for side in SIDES:
            price = row.get(side)
            if price is not None:
                if isinstance(price, bool) or not isinstance(price, (str, int, float)):
                    raise ValueError("Invalid quote type")
                try:
                    dec = Decimal(str(price))
                except InvalidOperation as exc:
                    raise ValueError("Invalid quote price") from exc
                if not dec.is_finite() or not 0 <= dec <= 1:
                    raise ValueError("Quote price outside contract probability range")
                price = str(dec)
            quotes[side] = price
        rows.append({
            "sport": "TENNIS", "ticker": ticker,
            "run_id": capture["run_id"],
            "observed_at_utc": at.isoformat().replace("+00:00", "Z"),
            "source_kind": "HOURLY_FULL_CAPTURE" if index == 0 else "CHANGED_FINGERPRINT_CAPTURE",
            "source_path": capture["quotes"]["path"],
            "source_blob_sha1": capture["quotes"]["sha"],
            "literal_terms": {key: row[key] for key in TERMS if key in row},
            "direct_quotes_dollars": quotes,
            "pregame_status": "UNVERIFIED", "quote_execution_authority": "NONE",
            "exchange_settlement_join": "NOT_VERIFIED",
        })
    if len(rows) != written:
        raise ValueError("Quote row count disagrees with upstream manifest")
    return rows, {"run_id": capture["run_id"], "source_manifest_sha1": capture["manifest"]["sha"],
                  "source_quotes_sha1": capture["quotes"]["sha"],
                  "started_at": manifest["started_at"], "finished_at": manifest["finished_at"],
                  "n_open_markets_reported": opened, "n_quote_rows_written": written,
                  "n_unchanged_fingerprints_reported": unchanged,
                  "snapshot_kind": "HOURLY_FULL" if index == 0 else "CHANGED_ONLY",
                  "complete_upstream_capture": True}


def audit(spec, downloader=None):
    captures = validate_manifest(spec)
    observations, reports = [], []
    previous = None
    for i, capture in enumerate(captures):
        rows, report = parse_capture(spec, capture, i, downloader)
        start = utc(report["started_at"])
        if previous is not None and start <= previous:
            raise ValueError("Capture windows overlap or reverse")
        previous = utc(report["finished_at"])
        observations.extend(rows)
        reports.append(report)
    latest = {}
    movement = Counter()
    for row in observations:
        old = latest.get(row["ticker"])
        if old is None:
            movement["first_observed_ticker_rows"] += 1
        elif old["direct_quotes_dollars"] != row["direct_quotes_dollars"]:
            movement["changed_direct_quotes_since_previous_observation"] += 1
        else:
            movement["same_direct_quotes_despite_upstream_fingerprint_change"] += 1
        latest[row["ticker"]] = row
    return {
        "schema_version": 1, "authority": "RESEARCH_ONLY", "sport": "TENNIS",
        "status": "PINNED_HOURLY_FULL_PLUS_CHANGED_CAPTURE_PREFIX_VERIFIED",
        "source_commit": spec["commit"], "capture_reports": reports,
        "n_observed_quote_rows": len(observations),
        "n_distinct_tickers_observed": len(latest),
        "observed_quote_change_counts": dict(movement),
        "full_board_at_later_ticks": "NOT_VERIFIED_REMOVALS_UNOBSERVED",
        "actual_market_change_times": "NOT_VERIFIED_CAPTURE_TIME_ONLY",
        "contract_to_physical_match": "NOT_ESTABLISHED",
        "exchange_settlement": "NOT_JOINED",
        "pregame_or_execution_authority": "NONE",
        "limitations": [
            "Upstream hourly full capture followed by changed-fingerprint quote rows only.",
            "Later open-market memberships/removals cannot be reconstructed from changed-only files.",
            "Fingerprint changes include size/status, not necessarily direct price changes.",
            "Observed timestamps are retrieval times, not proven market-change instants.",
            "No official actual match start, exchange-native settlement join, fees or executable fills.",
        ],
    }, observations

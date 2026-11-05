"""Read-only NBA/NHL verified Kalshi checkpoint + delta prefix replay.

Uses exact upstream Kalshi board delta algorithm (adapted to Alpha's UTC helper),
validates immutable git blobs, base checkpoint SHA256, contiguous delta sequence,
parent/result board hashes, time ordering and as-of boundaries.

Research only. Does not claim pregame observations or profitability.
"""
from __future__ import annotations
from collections import Counter
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.request import urlopen, Request
from .netretry import read_with_retry

from .source_delta import (
    Delta, canonical_board, board_sha256, apply_delta_in_place, BoardHash,
    verify_chain, DeltaChainError,
)
from .delta_timeutil import parse_iso
from .unified_timeline import dollars

SHA = re.compile(r"^[0-9a-f]{40}$")
ROOTS = {"NBA": "chmoses98/nba-edge-finder", "NHL": "chmoses98/NHL-edge-finder"}


def check_manifest(manifest):
    if manifest.get("schema_version") != 1 or set(manifest.get("chains", {})) != {"NBA", "NHL"}:
        raise ValueError("Need versioned NBA/NHL chain manifest")
    max_total = manifest.get("max_total_compressed_bytes")
    max_raw = manifest.get("max_decompressed_bytes")
    if type(max_total) is not int or max_total > 2_500_000 or max_total < 1:
        raise ValueError("Unbounded compressed retrieval")
    if type(max_raw) is not int or max_raw > 50_000_000 or max_raw < 1:
        raise ValueError("Unbounded expansion")
    total = 0
    for sport, chain in manifest["chains"].items():
        if chain.get("repository") != ROOTS[sport] or not SHA.fullmatch(chain.get("commit", "")):
            raise ValueError("Unapproved source, mutable revision, or unexpected sport")
        items = [chain.get("checkpoint")] + chain.get("deltas", [])
        if not 1 <= len(chain.get("deltas", [])) <= 6 or not all(isinstance(x, dict) for x in items):
            raise ValueError("Chain prefix must contain bounded deltas")
        paths = set()
        for i, entry in enumerate(items):
            path = entry.get("path", "")
            good_prefix = "kalshi/markets/dt=" if i == 0 else "kalshi/markets_delta/dt="
            good_suffix = ".jsonl.gz" if i == 0 else ".json.gz"
            if not (path.startswith(good_prefix) and path.endswith(good_suffix)
                    and re.fullmatch(r"[A-Za-z0-9_./=-]+", path) and ".." not in path.split("/")):
                raise ValueError("Unrecognized/untrusted archive path")
            if path in paths:
                raise ValueError("Duplicate path")
            paths.add(path)
            if not SHA.fullmatch(entry.get("sha", "")):
                raise ValueError("Missing raw Git blob digest")
            size = entry.get("bytes")
            if type(size) is not int or size < 1 or size > 1_500_000:
                raise ValueError("Archive size outside bound")
            total += size
    if total > max_total:
        raise ValueError("Combined archive read exceeds budget")
    return manifest["chains"]


def source_url(chain, entry):
    return "https://raw.githubusercontent.com/" + chain["repository"] + "/" + chain["commit"] + "/" + entry["path"]


def pinned_read(chain, entry, downloader=None):
    url = source_url(chain, entry)
    if downloader is not None:
        payload = downloader(chain, entry)
    else:
        request = Request(url, headers={"User-Agent": "SIFT-Alpha-zero-cost-market-research/1"})
        payload = read_with_retry(request, 20, entry["bytes"], opener=urlopen, expect_url=url)
    if len(payload) != entry["bytes"]:
        raise ValueError("Archive byte-length differs from reviewed manifest")
    digest = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    if digest != entry["sha"]:
        raise ValueError("Archive blob mismatch")
    return payload


def checkpoint_rows(raw, max_uncompressed):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as z:
        expanded = z.read(max_uncompressed + 1)
    if len(expanded) > max_uncompressed:
        raise ValueError("Checkpoint gzip exceeds decompression limit")
    rows = []
    tickers = set()
    n_nonmarkets = 0
    for line in expanded.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("Checkpoint row is not a record")
        ticker = row.get("ticker")
        if ticker is None:
            n_nonmarkets += 1
        else:
            if not isinstance(ticker, str) or not ticker:
                raise ValueError("Malformed market ticker")
            if ticker in tickers:
                raise ValueError("Duplicate ticker in single checkpoint")
            tickers.add(ticker)
        rows.append(row)
    if not tickers:
        raise ValueError("No market tickers in checkpoint")
    return rows, n_nonmarkets


def single_chain(chain, limit, downloader=None):
    checkpoint = chain["checkpoint"]
    raw = pinned_read(chain, checkpoint, downloader)
    rows, n_nonmarkets = checkpoint_rows(raw, limit)
    board = canonical_board(rows)
    base_at = {row.get("_observed_at_utc") for row in rows if row.get("ticker")}
    if len(base_at) != 1 or None in base_at:
        raise ValueError("Checkpoint has missing or conflicting observation timestamps")
    base_at = next(iter(base_at))
    base_sha = hashlib.sha256(raw).hexdigest()
    base_hash = board_sha256(board)
    deltas = []
    source_files = [{"path": checkpoint["path"], "blob_sha1": checkpoint["sha"],
                     "content_sha256": base_sha, "compressed_bytes": len(raw)}]
    for entry in chain["deltas"]:
        blob = pinned_read(chain, entry, downloader)
        d = Delta.from_bytes(blob)
        if d.base_path != checkpoint["path"] or d.base_sha256 != base_sha:
            raise DeltaChainError("Delta bound to wrong checkpoint or incorrect base bytes")
        if parse_iso(d.base_captured_at_utc) != parse_iso(base_at):
            raise DeltaChainError("Delta has incorrect base observation clock")
        if parse_iso(d.captured_at_utc) <= parse_iso(base_at):
            raise DeltaChainError("Delta timestamp before checkpoint")
        deltas.append(d)
        source_files.append({"path":entry["path"],"blob_sha1":entry["sha"],
                             "content_sha256":hashlib.sha256(blob).hexdigest(),
                             "compressed_bytes":len(blob)})
    final = verify_chain(board, deltas, base_sha256=base_hash)
    if deltas[-1].board_sha256 != board_sha256(final):
        raise DeltaChainError("Final chain board failed independent digest")
    # Evaluate each actual delta tick. Reconstruct only its touched markets to
    # measure observed price movement; do not copy the 10,000-market board per tick.
    working = {ticker: dict(row) for ticker, row in board.items()}
    hasher = BoardHash(working)
    observations = []
    changed_price_tickers = set()
    total_changed = 0
    for d in deltas:
        if d.n_markets_before != len(working):
            raise DeltaChainError("Delta reported wrong starting market count")
        touched = set(d.added) | set(d.removed) | set(d.changed) | set(d.cleared)
        before = {tk: dict(working[tk]) if tk in working else None for tk in touched}
        touched_actual = apply_delta_in_place(working, d)
        hasher.touch(working, touched_actual)
        if hasher.hexdigest() != d.board_sha256 or len(working) != d.n_markets_after:
            raise DeltaChainError("Intermediate board mismatch")
        movement = Counter()
        examples = []
        for ticker in sorted(touched):
            prev, curr = before[ticker], working.get(ticker)
            if prev is None or curr is None:
                movement["added_or_removed_tickers"] += 1
                continue
            changed_fields = {}
            for field in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
                a, b = dollars(prev, field), dollars(curr, field)
                if a is not None and b is not None and a != b:
                    changed_fields[field] = {"before": a, "after": b}
            if changed_fields:
                changed_price_tickers.add(ticker)
                movement["tickers_with_direct_quote_change"] += 1
                if len(examples) < 3:
                    examples.append({"ticker":ticker,"field_changes":changed_fields})
        total_changed += len(touched)
        observations.append({
            "at": d.captured_at_utc, "seq":d.seq,"board_sha256":d.board_sha256,
            "n_markets":len(working),"n_touched":len(touched),
            "observed_change_counts":dict(movement),
            "examples":examples,
        })
    if board_sha256(working) != board_sha256(final):
        raise DeltaChainError("Independent incremental reconstruction differs from upstream")
    return {
        "status":"CHECKPOINT_AND_CONTIGUOUS_DELTA_PREFIX_VERIFIED",
        "base_timestamp":base_at,
        "base_markets":len(board),
        "non_market_checkpoint_rows":n_nonmarkets,
        "base_board_sha256":base_hash,
        "delta_ticks":len(deltas),
        "last_tick_timestamp":deltas[-1].captured_at_utc,
        "final_market_count":len(final),
        "final_board_sha256":board_sha256(final),
        "n_unique_tickers_with_quote_movements":len(changed_price_tickers),
        "n_ticker_updates_across_ticks":total_changed,
        "source_files":source_files,
        "tick_summaries":observations,
        "not_pregame_without_independent_event_start":True,
        "profitability_authority":"NONE",
    }


def replay(manifest, downloader=None):
    chains = check_manifest(manifest)
    return {"schema_version":1,"research_authority":"RESEARCH_ONLY",
            "full_day_or_full_season":False,
            "sport_chains":{sport:single_chain(data,manifest["max_decompressed_bytes"],downloader)
                            for sport,data in sorted(chains.items())},
            "limitations":[
                "Only first 3 deltas for one checkpoint in each sport; not full day or complete market tape",
                "No independent game start, final contract settlement, fee or displayed size joins",
                "All histories are read-only; this study establishes reconstruction accuracy, not betting value",
            ]}

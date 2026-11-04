"""Verified event-sourced quote tape for immutable NBA/NHL checkpoint+delta prefixes.

Every emitted row is a literal market board observation (checkpoint or touched
delta), not an executed fill or a fresh trade. Source bytes, checkpoint and all
delta hashes are verified BEFORE any rows are returned. The sparse tape can be
queried only within its observed window. It does not infer game start or
contract outcome, and it does not forward-fill beyond its last verified tick.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from .delta_timeutil import parse_iso
from .source_delta import (
    BoardHash, Delta, DeltaChainError, apply_delta_in_place,
    board_sha256, canonical_board, verify_chain,
)
from .unified_timeline import dollars
from .verified_chains import check_manifest, checkpoint_rows, pinned_read

MAX_TAPE_ROWS = 120_000
TERMS = (
    "event_ticker", "series_ticker", "title", "subtitle",
    "yes_sub_title", "no_sub_title", "strike_type", "floor_strike",
    "cap_strike", "status", "result", "close_time", "expiration_time",
)
SIDES = ("yes_bid", "yes_ask", "no_bid", "no_ask")


def _direct_quotes(row):
    if row is None:
        return None
    return {side: dollars(row, side) for side in SIDES}


def _event(sport, ticker, observed, source, source_kind, row, previous=None):
    quotes = _direct_quotes(row)
    prev_quotes = _direct_quotes(previous)
    return {
        "schema_version": 1,
        "sport": sport,
        "ticker": ticker,
        "observed_at_utc": observed,
        "source_kind": source_kind,
        "source_path": source["path"],
        "source_blob_sha1": source["sha"],
        "lifecycle": "PRESENT" if row is not None else "REMOVED",
        "direct_quotes_dollars": quotes,
        "direct_quote_changed_since_previous_ticker_record": (
            None if source_kind == "CHECKPOINT" else quotes != prev_quotes
        ),
        "contract_terms_as_observed": (
            {key: row[key] for key in TERMS if key in row}
            if row is not None else None
        ),
        "quote_execution_authority": "NONE",
        "pregame_status": "UNVERIFIED",
    }


def _read_delta(blob, limit):
    # Delta.from_bytes uses gzip.decompress without a size cap. Expand under
    # an explicit limit first, then let the upstream parser handle plain JSON.
    if blob[:2] == b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Delta decompression budget exceeded")
        return Delta.from_bytes(raw)
    if len(blob) > limit:
        raise ValueError("Uncompressed delta exceeds budget")
    return Delta.from_bytes(blob)


def _sport_tape(sport, chain, max_expanded, downloader):
    checkpoint = chain["checkpoint"]
    raw = pinned_read(chain, checkpoint, downloader)
    rows, nonmarket = checkpoint_rows(raw, max_expanded)
    board = canonical_board(rows)
    observations = {row.get("_observed_at_utc") for row in rows if row.get("ticker")}
    if len(observations) != 1 or None in observations:
        raise ValueError("Conflicting or missing checkpoint observation time")
    base_at = next(iter(observations))
    base_time = parse_iso(base_at)
    base_bytes_sha256 = hashlib.sha256(raw).hexdigest()
    base_board_hash = board_sha256(board)
    deltas = []
    previous_time = base_time
    for source in chain["deltas"]:
        delta = _read_delta(pinned_read(chain, source, downloader), max_expanded)
        if delta.base_path != checkpoint["path"] or delta.base_sha256 != base_bytes_sha256:
            raise DeltaChainError("Delta checkpoint identity mismatch")
        if parse_iso(delta.base_captured_at_utc) != base_time:
            raise DeltaChainError("Delta checkpoint clock mismatch")
        at = parse_iso(delta.captured_at_utc)
        if at <= previous_time:
            raise DeltaChainError("Delta timestamp is not strictly increasing")
        previous_time = at
        deltas.append(delta)

    # This verifies all intermediate hashes, sequence numbers, parent hashes
    # and final state BEFORE exposing any event tape.
    expected_final = verify_chain(board, deltas, base_sha256=base_board_hash)

    events = [
        _event(sport, ticker, base_at, checkpoint, "CHECKPOINT", board[ticker])
        for ticker in sorted(board)
    ]
    working = {ticker: dict(row) for ticker, row in board.items()}
    hasher = BoardHash(working)
    counts = Counter({"checkpoint_rows": len(events)})
    for delta, source in zip(deltas, chain["deltas"]):
        if delta.n_markets_before != len(working):
            raise DeltaChainError("Delta starting market count mismatch")
        touched = set(delta.added) | set(delta.removed) | set(delta.changed) | set(delta.cleared)
        previous = {t: dict(working[t]) if t in working else None for t in touched}
        applied = apply_delta_in_place(working, delta)
        hasher.touch(working, applied)
        if (hasher.hexdigest() != delta.board_sha256
                or len(working) != delta.n_markets_after):
            raise DeltaChainError("Incremental board differs from source delta")
        for ticker in sorted(touched):
            before = previous[ticker]
            after = working.get(ticker)
            event = _event(sport, ticker, delta.captured_at_utc,
                           source, "DELTA_TOUCHED", after, before)
            events.append(event)
            counts["delta_touched_rows"] += 1
            if after is None:
                counts["removal_rows"] += 1
            elif before is None:
                counts["addition_rows"] += 1
            if event["direct_quote_changed_since_previous_ticker_record"]:
                counts["direct_quote_changed_rows"] += 1
        if len(events) > MAX_TAPE_ROWS:
            raise ValueError("Sparse tape exceeded bounded row count")

    if board_sha256(working) != board_sha256(expected_final):
        raise DeltaChainError("Reconstructed tape final board mismatch")
    report = {
        "sport": sport,
        "status": "CHECKPOINT_AND_DELTA_PREFIX_VERIFIED",
        "base_at": base_at,
        "last_verified_at": deltas[-1].captured_at_utc,
        "n_verified_delta_ticks": len(deltas),
        "n_base_tickers": len(board),
        "n_final_tickers": len(working),
        "n_nonmarket_checkpoint_rows": nonmarket,
        "n_sparse_tape_rows": len(events),
        "n_direct_quote_changed_rows": counts["direct_quote_changed_rows"],
        "n_addition_rows": counts["addition_rows"],
        "n_removal_rows": counts["removal_rows"],
        "n_delta_touched_rows": counts["delta_touched_rows"],
        "base_board_sha256": base_board_hash,
        "final_board_sha256": board_sha256(working),
        "source_files": [
            {"path": source["path"], "blob_sha1": source["sha"]}
            for source in [checkpoint] + chain["deltas"]
        ],
        "market_tape_coverage": "VERIFIED_PREFIX_ONLY",
        "pregame_status": "UNVERIFIED",
        "settlement_join": "NOT_VERIFIED",
        "execution_or_profitability_authority": "NONE",
    }
    return events, report


def build_tape(manifest, downloader=None):
    chains = check_manifest(manifest)
    all_events = []
    sports = {}
    for sport, chain in sorted(chains.items()):
        events, report = _sport_tape(
            sport, chain, manifest["max_decompressed_bytes"], downloader
        )
        all_events.extend(events)
        sports[sport] = report
        if len(all_events) > MAX_TAPE_ROWS:
            raise ValueError("Combined sparse tape exceeded bounded row count")
    return {
        "schema_version": 1,
        "authority": "RESEARCH_ONLY",
        "full_day_or_season": False,
        "sports": sports,
        "limitations": [
            "Only an immutable checkpoint plus 3 contiguous deltas per sport",
            "Sparse rows represent board observations, not independent trades",
            "Unchanged tickers are not repeated at each delta tick",
            "Actual quote change time may precede its observed delta tick",
            "No independent game start, settlement-rule join or executable fill",
        ],
    }, all_events


def asof_ticker(events, report, sport, ticker, cutoff):
    """Query the last known ticker state without looking beyond observed tape.

    The returned timestamp is the last TICKER ROW observation, not necessarily
    the last full board verification or the actual exchange quote change time.
    An absent ticker means absent on this board, not that it never existed.
    """
    if sport not in report["sports"]:
        raise ValueError("Unknown sport")
    if not isinstance(ticker, str) or not ticker:
        raise ValueError("Ticker required")
    window = report["sports"][sport]
    requested = parse_iso(cutoff)
    if not parse_iso(window["base_at"]) <= requested <= parse_iso(window["last_verified_at"]):
        raise ValueError("Cutoff outside independently verified observation window")
    latest = None
    last_board_tick = window["base_at"]
    for event in events:
        if event["sport"] != sport:
            continue
        observed = parse_iso(event["observed_at_utc"])
        if observed > requested:
            continue
        if observed > parse_iso(last_board_tick):
            last_board_tick = event["observed_at_utc"]
        if event["ticker"] == ticker:
            if latest is None or observed >= parse_iso(latest["observed_at_utc"]):
                latest = event
    return {
        "sport": sport, "ticker": ticker, "requested_at": cutoff,
        "last_ticker_observation_at": (
            latest["observed_at_utc"] if latest else None
        ),
        "lifecycle": latest["lifecycle"] if latest else "NOT_ON_BOARD",
        "direct_quotes_dollars": (
            latest["direct_quotes_dollars"] if latest else None
        ),
        "contract_terms_as_observed": (
            latest["contract_terms_as_observed"] if latest else None
        ),
        "pregame_status": "UNVERIFIED",
        "execution_or_profitability_authority": "NONE",
        "not_fresh_quote_guarantee": True,
    }


def write_gzip_jsonl(path, rows):
    """Deterministic, bounded compressed research artifact; never a live feed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if len(rows) > MAX_TAPE_ROWS:
        raise ValueError("Tape too large")
    with target.open("wb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as zipped:
            for row in rows:
                zipped.write((json.dumps(row, sort_keys=True, separators=(",", ":"))
                              + "\n").encode("utf-8"))
    return target

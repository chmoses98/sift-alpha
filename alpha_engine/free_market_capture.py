"""Opt-in, bounded, rate-limited public Kalshi market capture.

This is capture SOFTWARE, not an active daemon or deployed schedule. One
public page per call, no pagination loops, keys, paid services or orders.
Original response bytes and timestamped SHA-256 provenance are immutable.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HOST = "https://api.elections.kalshi.com"
PATH = "/trade-api/v2/markets"
SERIES = re.compile(r"KX[A-Z0-9-]{2,48}\Z")
MAX_BYTES = 750000
MAX_MARKETS = 100
MAX_FILES_PER_SERIES = 512
MIN_INTERVAL_SECONDS = 300


def clock(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Explicit UTC clock required")
    try:
        d = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if d.tzinfo != timezone.utc:
        raise ValueError("UTC only")
    return d


def endpoint(series):
    if not isinstance(series, str) or not SERIES.fullmatch(series):
        raise ValueError("Unapproved series ticker")
    return HOST + PATH + "?" + urlencode({
        "series_ticker": series, "status": "open", "limit": MAX_MARKETS})


def public_read(url):
    with urlopen(Request(url, headers={
            "User-Agent": "SIFT-Alpha-public-research-capture/1",
            "Accept": "application/json"}), timeout=12) as response:
        if response.geturl() != url or response.status != 200:
            raise ValueError("Unexpected redirect or HTTP status")
        if "json" not in response.headers.get("Content-Type", ""):
            raise ValueError("Non-JSON public response")
        return response.read(MAX_BYTES + 1), response.headers.get("Date")


def capture(series, now_utc, directory, *, fetcher=None):
    """One public read, no retries. fetcher(url) -> (raw_bytes, server_date).

    Cursor => INCOMPLETE_PAGE, not a reconstructed full-market board.
    Locking prevents concurrent processes from bypassing the rate limit.
    """
    url, now = endpoint(series), clock(now_utc)
    root = Path(directory) / series
    if root.is_symlink():
        raise ValueError("Symlink capture directory forbidden")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".capture.lock"
    if lock.is_symlink():
        raise ValueError("Symlink lock forbidden")
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return _capture_locked(series, url, now_utc, now, root, fetcher)


def _capture_locked(series, url, now_utc, now, root, fetcher):
    manifests = sorted(root.glob("*.manifest.json"))
    if len(manifests) >= MAX_FILES_PER_SERIES:
        raise ValueError("Bounded capture retention limit reached")
    for item in manifests:
        if item.is_symlink():
            raise ValueError("Symlink manifest forbidden")
        doc = json.loads(item.read_text(encoding="utf-8"))
        if doc.get("series") != series or doc.get("source_url") != url:
            raise ValueError("Untrusted previous capture provenance")
        delta = (now - clock(doc.get("captured_at_utc"))).total_seconds()
        if delta < MIN_INTERVAL_SECONDS:
            raise ValueError("Rate limit or clock rollback: denied")
    raw, server_date = fetcher(url) if fetcher is not None else public_read(url)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Missing or oversized response")
    try:
        payload = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Malformed market JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
        raise ValueError("Unexpected market response")
    markets = payload["markets"]
    if len(markets) > MAX_MARKETS:
        raise ValueError("Market page exceeds bound")
    tickers = set()
    for row in markets:
        if (not isinstance(row, dict) or not isinstance(row.get("ticker"), str)
                or not row["ticker"] or row["ticker"] in tickers):
            raise ValueError("Missing or duplicate literal market ticker")
        tickers.add(row["ticker"])
    if payload.get("cursor") is not None and not isinstance(payload["cursor"], str):
        raise ValueError("Invalid cursor")
    digest = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema_version": 1, "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "series": series, "source_url": url, "captured_at_utc": now_utc,
        "source_server_date": server_date, "source_sha256": digest,
        "source_bytes": len(raw), "page_contract_count": len(markets),
        "pagination": "INCOMPLETE_PAGE" if payload.get("cursor") else "NO_NEXT_CURSOR_REPORTED",
        "complete_series_or_market_tape": False,
        "actual_start_or_settlement_verified": False}
    stem = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + digest[:16]
    raw_path, manifest_path = root/(stem + ".json"), root/(stem + ".manifest.json")
    with raw_path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    try:
        with manifest_path.open("x", encoding="utf-8") as f:
            json.dump(manifest, f, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        raw_path.unlink()
        raise
    return manifest

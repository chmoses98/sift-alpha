"""Bounded, opt-in, immutable multi-page Kalshi *open* series discovery.

Repairs the single-page collector's 100-contract ceiling without claiming a
full historical tape, pregame status, or complete exchange-wide coverage.
No orders, credentials, retries, paid feeds, or scheduled live polling.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from .free_market_capture import (
    HOST, PATH, MAX_BYTES, MAX_MARKETS, MAX_FILES_PER_SERIES,
    MIN_INTERVAL_SECONDS, clock, endpoint, public_read,
)

MAX_PAGES = 8
MAX_TOTAL_BYTES = MAX_PAGES * MAX_BYTES
MAX_CURSOR_CHARS = 2048


def _cursor(value):
    if value in (None, ""):
        return None
    if (not isinstance(value, str) or len(value) > MAX_CURSOR_CHARS
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Invalid or oversized pagination cursor")
    return value


def _url(series, cursor):
    base = endpoint(series)
    return base if cursor is None else base + "&" + urlencode({"cursor": cursor})


def _existing_guard(root, series, now, base):
    manifests = sorted(root.glob("*.manifest.json"))
    if len(manifests) >= MAX_FILES_PER_SERIES:
        raise ValueError("Capture retention limit reached")
    for item in manifests:
        if item.is_symlink():
            raise ValueError("Symlink manifest forbidden")
        doc = json.loads(item.read_text(encoding="utf-8"))
        if doc.get("series") != series or doc.get("source_url") != base:
            raise ValueError("Previous capture provenance conflict")
        age = (now - clock(doc.get("captured_at_utc"))).total_seconds()
        if age < MIN_INTERVAL_SECONDS:
            raise ValueError("Rate limit or clock rollback: denied")


def capture_series(series, now_utc, directory, *, fetcher=None, max_pages=MAX_PAGES):
    """Capture up to max_pages original public pages, fail closed on errors.

    The immutable original bytes are written only after all fetched pages
    pass validation. If a cursor remains at the bound, coverage is PARTIAL.
    fetcher(url) -> (raw_bytes, HTTP Date) is injectable for offline CI.
    """
    base, now = endpoint(series), clock(now_utc)
    if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
        raise ValueError("Unbounded page request")
    root = Path(directory) / series
    if root.is_symlink():
        raise ValueError("Symlink series directory forbidden")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".capture.lock"
    if lock.is_symlink():
        raise ValueError("Symlink capture lock forbidden")
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        _existing_guard(root, series, now, base)
        pages, tickers, cursors = [], set(), set()
        cursor = None
        total = 0
        for index in range(max_pages):
            url = _url(series, cursor)
            raw, server_date = (fetcher(url) if fetcher else public_read(url))
            received = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
                raise ValueError("Missing or oversized page")
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Total response budget exceeded")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Invalid source JSON") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
                raise ValueError("Missing source markets")
            markets = payload["markets"]
            if len(markets) > MAX_MARKETS:
                raise ValueError("Page contract limit exceeded")
            page_tickers = set()
            for market in markets:
                if not isinstance(market, dict):
                    raise ValueError("Malformed market")
                ticker = market.get("ticker")
                if (not isinstance(ticker, str) or not ticker.startswith(series + "-")
                        or ticker in tickers or ticker in page_tickers
                        or market.get("series_ticker", series) != series):
                    raise ValueError("Duplicate or mismatched series ticker")
                page_tickers.add(ticker)
            tickers.update(page_tickers)
            next_cursor = _cursor(payload.get("cursor"))
            if next_cursor is not None:
                if next_cursor in cursors:
                    raise ValueError("Cyclic pagination cursor")
                cursors.add(next_cursor)
            pages.append({
                "index": index, "request_url": url, "request_cursor": cursor,
                "next_cursor": next_cursor, "server_date": server_date,
                "received_at_utc": received, "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "n_contracts": len(markets), "raw": raw,
            })
            cursor = next_cursor
            if cursor is None:
                break
        complete = cursor is None
        capture_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + pages[0]["sha256"][:16]
        manifest = {
            "schema_version": 2, "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "series": series, "source_url": base, "captured_at_utc": now_utc,
            "source_scope": "PUBLIC_OPEN_MARKETS_ONLY",
            "observed_denominator": len(tickers),
            "denominator_unit": "distinct_open_contract_tickers_in_this_capture",
            "n_pages": len(pages), "all_reported_pages_retrieved": complete,
            "pagination": "NO_NEXT_CURSOR_REPORTED" if complete else "INCOMPLETE_PAGE_LIMIT",
            "complete_series_or_market_tape": False,
            "actual_start_or_settlement_verified": False,
            "pregame_or_forecast_join_verified": False,
            "pages": [
                {k: v for k, v in page.items() if k != "raw"} |
                {"file": capture_id + ".page%03d.json" % page["index"]}
                for page in pages
            ],
        }
        created = []
        try:
            for page in pages:
                name = capture_id + ".page%03d.json" % page["index"]
                target = root / name
                with target.open("xb") as f:
                    created.append(target)
                    f.write(page["raw"])
                    f.flush()
                    os.fsync(f.fileno())
            manifest_path = root / (capture_id + ".manifest.json")
            with manifest_path.open("x", encoding="utf-8") as f:
                created.append(manifest_path)
                json.dump(manifest, f, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            for target in created:
                target.unlink()
            raise
        return manifest


def verify_capture(directory, manifest):
    """Independently reconcile stored original bytes and cursor chronology."""
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 2
            or manifest.get("authority") != "RESEARCH_ONLY_NO_EXECUTION"
            or manifest.get("complete_series_or_market_tape") is not False
            or manifest.get("source_scope") != "PUBLIC_OPEN_MARKETS_ONLY"):
        raise ValueError("Untrusted capture manifest")
    series = manifest.get("series")
    if manifest.get("source_url") != endpoint(series):
        raise ValueError("Untrusted capture endpoint")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("Unbounded capture manifest")
    if manifest.get("n_pages") != len(pages):
        raise ValueError("Page denominator mismatch")
    root = Path(directory) / series
    tickers = set()
    expected_cursor = None
    for index, page in enumerate(pages):
        name = page.get("file")
        if (not isinstance(name, str) or "/" in name or "\\" in name
                or not name.endswith(".page%03d.json" % index)
                or page.get("index") != index
                or page.get("request_cursor") != expected_cursor
                or page.get("request_url") != _url(series, expected_cursor)):
            raise ValueError("Page identity or cursor mismatch")
        target = root / name
        if target.is_symlink():
            raise ValueError("Symlink source page forbidden")
        raw = target.read_bytes()
        if (not 0 < len(raw) <= MAX_BYTES or page.get("bytes") != len(raw)
                or page.get("sha256") != hashlib.sha256(raw).hexdigest()):
            raise ValueError("Original source page tampered")
        payload = json.loads(raw)
        rows = payload.get("markets")
        if not isinstance(rows, list) or len(rows) != page.get("n_contracts"):
            raise ValueError("Page source denominator changed")
        for row in rows:
            ticker = row.get("ticker") if isinstance(row, dict) else None
            if (not isinstance(ticker, str) or not ticker.startswith(series + "-")
                    or ticker in tickers or row.get("series_ticker", series) != series):
                raise ValueError("Duplicated or invalid source contract")
            tickers.add(ticker)
        if _cursor(payload.get("cursor")) != page.get("next_cursor"):
            raise ValueError("Cursor provenance changed")
        expected_cursor = page["next_cursor"]
        if index < len(pages) - 1 and expected_cursor is None:
            raise ValueError("Page appended after terminal cursor")
    if (manifest.get("observed_denominator") != len(tickers)
            or manifest.get("all_reported_pages_retrieved") is not (expected_cursor is None)
            or manifest.get("pagination") != (
                "NO_NEXT_CURSOR_REPORTED" if expected_cursor is None else "INCOMPLETE_PAGE_LIMIT")):
        raise ValueError("Inflated or falsely completed capture")
    return {"observed_denominator": len(tickers), "n_pages": len(pages),
            "all_reported_pages_retrieved": expected_cursor is None,
            "point_in_time_pregame": "UNKNOWN", "full_market_tape": False}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Explicit opt-in free public open-series discovery")
    p.add_argument("--series", required=True)
    p.add_argument("--directory", required=True)
    p.add_argument("--max-pages", type=int, default=MAX_PAGES)
    p.add_argument("--live", action="store_true", help="Explicitly authorize bounded public GET requests")
    a = p.parse_args()
    if not a.live:
        p.error("--live is required; no automatic network capture")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = capture_series(a.series, now, a.directory, max_pages=a.max_pages)
    print(json.dumps({"manifest": report, "verification": verify_capture(a.directory, report)}, sort_keys=True))

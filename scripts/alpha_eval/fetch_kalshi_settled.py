#!/usr/bin/env python3
"""Manual, anonymous, read-only fetch of SETTLED Kalshi markets (official `result`) for given series (RESEARCH_ONLY).

Public market-data endpoint only (no key, no orders). Call-capped, sequential, 429/5xx backoff. Raw pages are written OUTSIDE
the repository (--out-dir); only aggregate digests produced from them are ever committed.

usage: python3 -I scripts/alpha_eval/fetch_kalshi_settled.py --series KXNHLGAME,KXNHLTOTAL --min-close 2026-09-28 --out-dir /home/user/data/kalshi_nhl_settled
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"


def _get(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "research-client"}), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 ** i * (2 if e.code == 429 else 1))
                continue
            raise
        except urllib.error.URLError:
            if i < tries - 1:
                time.sleep(2 ** i)
                continue
            raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--min-close", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--max-close", help="YYYY-MM-DD (UTC), exclusive")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-calls", type=int, default=1500)
    ap.add_argument("--sleep", type=float, default=0.25)
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    ts = lambda d: int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())  # noqa: E731
    calls, log = 0, []
    for s in [x.strip() for x in a.series.split(",") if x.strip()]:
        cursor, page = "", 0
        while True:
            if calls >= a.max_calls:
                raise SystemExit(f"call cap {a.max_calls} reached at series {s} page {page}; nothing beyond this point fetched")
            q = dict(series_ticker=s, status="settled", limit=1000, min_close_ts=ts(a.min_close))
            if a.max_close:
                q["max_close_ts"] = ts(a.max_close)
            if cursor:
                q["cursor"] = cursor
            url = BASE + "?" + urllib.parse.urlencode(q)
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            d = _get(url)
            calls += 1
            raw = json.dumps(d, sort_keys=True).encode()
            fn = os.path.join(a.out_dir, f"{s}_p{page:04d}.json.gz")
            with gzip.open(fn, "wb") as f:
                f.write(raw)
            log.append(dict(series=s, page=page, url=url, fetched_at_utc=fetched_at, n=len(d.get("markets", [])), sha256=hashlib.sha256(raw).hexdigest()))
            cursor = d.get("cursor") or ""
            page += 1
            time.sleep(a.sleep)
            if not cursor or not d.get("markets"):
                break
    with open(os.path.join(a.out_dir, "fetch_log.jsonl"), "a") as f:
        for r in log:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    print(f"calls={calls} markets={sum(r['n'] for r in log)}")


if __name__ == "__main__":
    main()

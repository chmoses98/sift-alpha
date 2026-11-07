"""Shared helpers for free-API raw-data collectors (RESEARCH_ONLY): polite GET with backoff, content hashing, coverage/missingness ledger.

Collectors write raw-derived tables to a cache directory (not committed: size) and return a ledger dict that IS committed: rows, date span, per-field completeness by season,
source URL pattern, retrieval time and the sha256 of the cache file, so the data's existence and quality are reproducible and auditable without storing the data in git.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = {"User-Agent": "sift-alpha-research/1"}


def get_json(url: str, tries: int = 6, pause: float = 0.0, timeout: int = 60):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = json.load(r)
            if pause:
                time.sleep(pause)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 + 3 * i); continue
            if e.code == 404:
                return None
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(2 + 3 * i)
    return None


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def completeness(df, fields, by="season") -> dict:
    return {f: {str(k): round(float(v), 4) for k, v in df.groupby(by)[f].apply(lambda s: s.notna().mean()).items()} for f in fields if f in df}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

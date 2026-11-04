"""Bounded-retry + hash-verified-cache behaviour of fetch_pinned (offline; no assertion of the audit is weakened)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alpha_engine import hitter_archive_gate as gate
from alpha_engine import hitter_overlap_audit as ov

DATE = "2026-08-19"


def fake(raw, url_suffix=None):
    class R:
        def __init__(s): s.b = raw
        def __enter__(s): return s
        def __exit__(s, *a): return False
        def geturl(s): return url_suffix or s.url
        def read(s, n): return s.b[:n]
    return R


class Fetch(unittest.TestCase):
    def setUp(self):
        self.raw = b"x" * 10
        self.pins = {DATE: (gate.git_hash("blob", self.raw), 10)}
        self.p = patch.dict(ov.PINS, self.pins, clear=True); self.p.start()
        self.addCleanup(self.p.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def opener(self, behaviours, calls):
        def op(req, timeout):
            calls.append(timeout)
            b = behaviours[min(len(calls) - 1, len(behaviours) - 1)]
            if isinstance(b, Exception): raise b
            r = fake(b)(); r.url = req.full_url; return r
        return op

    def test_timeout_is_retried_then_succeeds(self):
        calls = []
        out = ov.fetch_pinned(DATE, opener=self.opener([TimeoutError("t"), TimeoutError("t"), self.raw], calls), sleep=lambda s: None)
        self.assertEqual(out, self.raw); self.assertEqual(len(calls), 3)

    def test_retries_are_bounded_and_fail_closed(self):
        calls = []
        with self.assertRaises(ConnectionError):
            ov.fetch_pinned(DATE, opener=self.opener([TimeoutError("t")], calls), sleep=lambda s: None)
        self.assertEqual(len(calls), ov.ATTEMPTS)

    def test_hash_mismatch_is_not_retried_and_not_cached(self):
        calls = []
        with patch.dict(os.environ, {ov.CACHE_ENV: self.tmp.name}):
            with self.assertRaises(ValueError):
                ov.fetch_pinned(DATE, opener=self.opener([b"y" * 10], calls), sleep=lambda s: None)
        self.assertEqual(len(calls), 1); self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_cache_hit_avoids_network_and_corrupt_cache_is_ignored(self):
        with patch.dict(os.environ, {ov.CACHE_ENV: self.tmp.name}):
            calls = []
            ov.fetch_pinned(DATE, opener=self.opener([self.raw], calls), sleep=lambda s: None)   # populates cache
            calls2 = []
            self.assertEqual(ov.fetch_pinned(DATE, opener=self.opener([TimeoutError()], calls2)), self.raw)
            self.assertEqual(calls2, [])
            (Path(self.tmp.name) / f"{self.pins[DATE][0]}.blob").write_bytes(b"z" * 10)          # tamper
            calls3 = []
            self.assertEqual(ov.fetch_pinned(DATE, opener=self.opener([self.raw], calls3), sleep=lambda s: None), self.raw)
            self.assertEqual(len(calls3), 1)

    def test_redirect_rejected(self):
        def op(req, timeout):
            r = fake(self.raw)(); r.url = "https://evil.example/x"; return r
        with self.assertRaises(ValueError):
            ov.fetch_pinned(DATE, opener=op, sleep=lambda s: None)

    def test_unapproved_date_rejected(self):
        with self.assertRaises(ValueError):
            ov.fetch_pinned("2026-01-01")


if __name__ == "__main__":
    unittest.main()

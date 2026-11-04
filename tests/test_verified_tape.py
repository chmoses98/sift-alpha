"""Fail-closed time-travel tests for real-source-compatible sparse quote tape."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone

from alpha_engine.source_delta import build_delta, canonical_board
from alpha_engine.verified_tape import (
    _direct_quotes, _read_delta, asof_ticker, build_tape,
)
from tests.test_verified_chains import make_fixture


def fixture():
    chain, base, delta = make_fixture()
    other = copy.deepcopy(chain)
    other["repository"] = "chmoses98/NHL-edge-finder"
    manifest = {
        "schema_version": 1,
        "max_total_compressed_bytes": 2500000,
        "max_decompressed_bytes": 50000000,
        "chains": {"NBA": chain, "NHL": other},
    }
    return manifest, base, delta


def downloader(base, delta):
    return lambda chain, entry: (
        base if entry == chain["checkpoint"] else delta
    )


class SparseTapeTests(unittest.TestCase):
    def test_exact_asof_and_no_future_leakage(self):
        manifest, base, delta = fixture()
        report, rows = build_tape(manifest, downloader(base, delta))
        self.assertEqual(len(rows), 4)
        for sport in ("NBA", "NHL"):
            status = report["sports"][sport]
            self.assertEqual(status["n_verified_delta_ticks"], 1)
            ticker = "KXNBAGAME-26TEST-AAA"
            before = asof_ticker(rows, report, sport, ticker, "2026-10-25T00:10:20Z")
            after = asof_ticker(rows, report, sport, ticker, "2026-10-25T00:10:21Z")
            self.assertEqual(before["direct_quotes_dollars"]["yes_bid"], "0.40")
            self.assertEqual(after["direct_quotes_dollars"]["yes_bid"], "0.52")
            self.assertTrue(before["not_fresh_quote_guarantee"])
            self.assertEqual(after["pregame_status"], "UNVERIFIED")
            self.assertEqual(status["n_sparse_tape_rows"], 2)
            with self.assertRaises(ValueError):
                asof_ticker(rows, report, sport, ticker, "2026-10-25T00:02:23Z")
            with self.assertRaises(ValueError):
                asof_ticker(rows, report, sport, ticker, "2026-10-25T00:10:22Z")

    def test_unknown_ticker_does_not_inherit_other_ticker(self):
        manifest, base, delta = fixture()
        report, rows = build_tape(manifest, downloader(base, delta))
        absent = asof_ticker(rows, report, "NBA", "KXNOTFOUND", "2026-10-25T00:10:21Z")
        self.assertEqual(absent["lifecycle"], "NOT_ON_BOARD")
        self.assertIsNone(absent["direct_quotes_dollars"])

    def test_source_hash_tamper_fails_before_tape_emission(self):
        manifest, base, delta = fixture()
        with self.assertRaises(ValueError):
            build_tape(manifest, downloader(base, delta + b"tampered"))

    def test_gzip_bomb_bound_is_enforced(self):
        import gzip
        bomb = gzip.compress(b"x" * 5000)
        with self.assertRaises(ValueError):
            _read_delta(bomb, 100)

    def test_no_synthetic_no_bid_from_yes_ask(self):
        row = {"ticker": "KXTEST", "yes_ask_dollars": "0.63"}
        prices = _direct_quotes(row)
        self.assertEqual(prices["yes_ask"], "0.63")
        self.assertIsNone(prices["no_bid"])
        self.assertIsNone(prices["yes_bid"])

    def test_duplicate_or_backwards_time_is_rejected(self):
        manifest, base, delta = fixture()
        bad = json.loads(delta)
        bad["captured_at_utc"] = "2026-10-25T00:02:24Z"
        payload = (json.dumps(bad) + "\n").encode()
        digest = hashlib.sha1(
            b"blob " + str(len(payload)).encode() + b"\0" + payload
        ).hexdigest()
        for chain in manifest["chains"].values():
            chain["deltas"][0]["sha"] = digest
            chain["deltas"][0]["bytes"] = len(payload)
        with self.assertRaises(Exception):
            build_tape(manifest, downloader(base, payload))


if __name__ == "__main__":
    unittest.main()

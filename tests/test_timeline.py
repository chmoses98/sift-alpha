"""Adversarial tests for immutable Kalshi market tape first milestone."""
import copy
from decimal import Decimal
import gzip
import hashlib
import json
import unittest

from alpha_engine.unified_timeline import (
    check_manifest, decode_pinned, dollars, market_row,
    settlement_row, timeline, run,
)


def source(sport="NHL", kind="market"):
    payload = gzip.compress((json.dumps({"ticker": "KXNHLGAME-26OCT25A-B",
                                          "_observed_at_utc": "2026-10-25T15:00:00Z",
                                          "yes_bid_dollars": "0.52",
                                          "yes_ask_dollars": "0.54"}) + "\n").encode())
    sha = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    entry = {"id": sport + kind, "sport": sport, "kind": kind,
             "repository": "chmoses98/NHL-edge-finder" if sport == "NHL" else "chmoses98/nba-edge-finder",
             "commit": "a" * 40, "path": "kalshi/markets/dt=2026-10-25/kalshi_markets_20261025T000602Z_test.jsonl.gz",
             "git_blob_sha1": sha, "compressed_bytes": len(payload)}
    return entry, payload


class TimelineTests(unittest.TestCase):
    def test_decimal_values_not_inferred_from_other_side(self):
        self.assertEqual(dollars({"yes_bid_dollars": "0.42"}, "yes_bid"), "0.42")
        self.assertEqual(dollars({"yes_bid": 42}, "yes_bid"), "0.42")
        self.assertIsNone(dollars({"no_bid": 57}, "yes_ask"))
        with self.assertRaises(ValueError):
            dollars({"yes_bid_dollars": "1.11"}, "yes_bid")

    def test_unknown_game_start_remains_unknown_not_fake_pregame(self):
        observation, reason = market_row(
            {"ticker": "KXNHLGAME-ABC", "_observed_at_utc": "2026-10-25T15:00:00Z",
             "yes_bid_dollars": "0.43"}, "file_20261025T010000Z.jsonl.gz")
        self.assertIsNone(reason)
        self.assertIsNone(observation["event_start_at"])
        self.assertIsNone(observation["physical_game_id"])
        self.assertIsNone(observation["quote"]["yes_ask"])

    def test_checkpoint_movement_and_exact_settlement_join(self):
        a, _ = market_row({"market": {"ticker": "KXNHLGAME-ABC", "event_ticker": "KXNHL-ABC",
                                      "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44"},
                           "_observed_at_utc": "2026-10-25T15:00:00Z"}, "snapshot_20261025T010000Z.jsonl.gz")
        b = copy.deepcopy(a)
        b["observed_at"] = "2026-10-25T16:00:00Z"
        b["quote"]["yes_bid"] = "0.55"
        b["quote"]["yes_ask"] = "0.58"
        s = settlement_row({"ticker": "KXNHLGAME-ABC", "result": "yes"})
        report = timeline([a, b], [s])
        self.assertEqual(report["counts"]["tickers_with_multiple_timestamps"], 1)
        self.assertEqual(report["counts"]["tickers_with_observed_quote_movement"], 1)
        self.assertEqual(report["counts"]["tickers_with_settlement"], 1)
        self.assertEqual(report["examples"][0]["physical_game_join"], "UNVERIFIED")
        self.assertEqual(report["research_authority"], "DESCRIPTIVE_ONLY")

    def test_ambiguity_and_conflicting_same_timestamp_are_blocked(self):
        a, _ = market_row({"ticker": "KXNHLGAME-ABC", "_observed_at_utc": "2026-10-25T15:00:00Z",
                           "yes_bid_dollars": "0.40"}, "x_20261025T010000Z.jsonl.gz")
        b = copy.deepcopy(a)
        b["quote"]["yes_bid"] = "0.70"
        with self.assertRaisesRegex(ValueError, "Conflicting observations"):
            timeline([a, b], [])
        with self.assertRaisesRegex(ValueError, "Conflicting official"):
            timeline([a], [{"ticker": "KXNHLGAME-ABC", "result": "yes"},
                           {"ticker": "KXNHLGAME-ABC", "result": "no"}])

    def test_pin_verification_blocks_tampered_bytes(self):
        entry, payload = source()
        doc = {"schema_version": 1, "files": [entry],
               "max_download_bytes_total": 4000000, "max_decompressed_bytes_per_file": 50000000}
        self.assertEqual(len(check_manifest(doc)), 1)
        rows, _ = decode_pinned(payload, entry, 50000000)
        self.assertEqual(len(rows), 1)
        with self.assertRaises(ValueError):
            decode_pinned(payload[:-1] + b"0", entry, 50000000)
        with self.assertRaises(ValueError):
            decode_pinned(payload, {**entry, "git_blob_sha1": "a" * 40}, 50000000)
        with self.assertRaises(ValueError):
            check_manifest({**doc, "files": [{**entry, "repository": "evil/paid-provider"}]})
        with self.assertRaises(ValueError):
            check_manifest({**doc, "files": [{**entry, "compressed_bytes": 99999999}]})

    def test_reproducible_offline_pilot(self):
        entry, payload = source()
        doc = {"schema_version": 1, "files": [entry],
               "max_download_bytes_total": 4000000, "max_decompressed_bytes_per_file": 50000000}
        output = run(doc, downloader=lambda e: payload)
        self.assertEqual(output["status"], "RESEARCH_ONLY")
        self.assertEqual(output["sport_tapes"]["NHL"]["counts"]["tickers"], 1)
        self.assertTrue(output["provenance"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()

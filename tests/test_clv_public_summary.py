"""The committed public CLV summary must stay aggregate-only, and every displayed metric must name its denominator."""
import json
import re
import unittest
from pathlib import Path

SUMMARY = Path(__file__).resolve().parents[1] / "reports" / "clv_recalc" / "clv_public_summary_2026-11-04.json"
FORBIDDEN_KEYS = {"stake", "net_profit_loss", "gross_return", "roi", "economics", "source_bet_key", "market_ticker",
                  "ticker", "execution_price", "order_id", "fill_ids", "wager_id", "by_family_real"}


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


class PublicSummary(unittest.TestCase):
    def setUp(self):
        self.d = json.loads(SUMMARY.read_text())

    def test_no_private_keys_anywhere(self):
        self.assertFalse({k.lower() for k in walk(self.d)} & FORBIDDEN_KEYS)

    def test_no_ticker_shaped_strings(self):
        blob = SUMMARY.read_text()
        self.assertIsNone(re.search(r"KX[A-Z0-9]{3,}-\d{2}[A-Z]{3}\d{2}", blob))
        self.assertIsNone(re.search(r"kalshi:v1:[0-9a-f]{16,}", blob))

    def test_every_real_wager_block_has_denominators_and_reasons(self):
        for sport, b in self.d["real_wagers"].items():
            den = b["denominators"]
            self.assertEqual(set(den), {"wagers_in_ledger", "pregame_entries_eligible", "verified_clv_observations"}, sport)
            self.assertEqual(b["actual_execution_clv"]["n"], den["verified_clv_observations"], sport)
            self.assertLessEqual(den["verified_clv_observations"], den["pregame_entries_eligible"], sport)
            self.assertTrue(b["unverifiable_by_reason"], sport)
            self.assertEqual(b["recommendation_linked_wagers"], 0, sport)
            self.assertEqual(b["selection_clv"]["verified"], 0, sport)
            self.assertEqual(b["fee_adjustment_count_max"], 1, sport)      # the entry fee is subtracted exactly once

    def test_fee_adjusted_is_actual_minus_one_fee(self):
        for sport, b in self.d["real_wagers"].items():
            gap = b["actual_execution_clv"]["mean"] - b["fee_adjusted_difference"]["mean"]
            self.assertAlmostEqual(gap, b["fee_per_contract"]["mean"], places=9, msg=sport)

    def test_definitions_cover_every_measure(self):
        self.assertTrue({"selection_clv", "quoted_execution_clv", "actual_execution_clv", "fee_adjusted_difference",
                         "close_validity", "independence"} <= set(self.d["metric_definitions"]))

    def test_shadow_spread_plus_fee_drag_identity(self):
        a = self.d["hypothetical_selections"]["NFL_shadow_v2"]["after_gated_deduped"]
        self.assertAlmostEqual(a["selection"]["mean"] - a["quoted_exec"]["mean"], a["spread_drag_mean"], places=9)


if __name__ == "__main__":
    unittest.main()

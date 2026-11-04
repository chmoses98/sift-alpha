"""The committed public EXECUTION summary: aggregate-only, labelled, and internally consistent."""
import json
import re
import unittest
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "reports" / "clv_recalc" / "execution_summary_2026-11-04.json"
FORBIDDEN = {"stake", "net_profit_loss", "gross_return", "roi", "economics", "source_bet_key", "market_ticker", "ticker",
             "execution_price", "order_id", "fill_ids", "wager_id", "contracts", "by_family_real"}
SPORTS = ("NFL", "CFB", "NBA", "NHL")


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


class ExecutionSummary(unittest.TestCase):
    def setUp(self):
        self.text = P.read_text()
        self.d = json.loads(self.text)

    def test_no_private_fields(self):
        self.assertFalse({k.lower() for k in walk(self.d)} & FORBIDDEN)
        self.assertIsNone(re.search(r"KX[A-Z0-9]{3,}-\d{2}[A-Z]{3}\d{2}", self.text))
        self.assertIsNone(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", self.text))
        for b in self.d["real_wagers"].values():
            self.assertNotIn("by_family", b)                          # owner trading behaviour is not published

    def test_every_block_declares_verified_or_hypothetical(self):
        for s in SPORTS:
            self.assertIn("VERIFIED ACTUAL TRADES", self.d["real_wagers"][s]["evidence"])
        self.assertIn("HYPOTHETICAL", self.d["hypothetical_early_taker_nfl"]["evidence"])
        self.assertIn("HYPOTHETICAL", self.d["limit_order_simulation_nfl"]["evidence"])

    def test_real_wager_identities(self):
        for s in SPORTS:
            b = self.d["real_wagers"][s]
            m, half, fee = b["measures_cents"], b["closing_half_spread_cents_mean"], b["entry_fee_cents_mean"]
            self.assertAlmostEqual(m["executable_purchase_clv"]["mean"] - m["midpoint_execution_clv"]["mean"], half, delta=1e-3, msg=s)
            self.assertAlmostEqual(m["midpoint_execution_clv"]["mean"] - m["liquidation_clv"]["mean"], half, delta=1e-3, msg=s)
            self.assertAlmostEqual(m["executable_purchase_clv"]["mean"] - m["executable_purchase_net_of_entry_fee"]["mean"], fee, delta=2e-3, msg=s)
            self.assertAlmostEqual(m["midpoint_execution_clv"]["mean"] - m["midpoint_execution_net_of_entry_fee"]["mean"], fee, delta=2e-3, msg=s)
            dec = b["cost_decomposition_cents_vs_close_mid"]
            self.assertAlmostEqual(dec["price_disadvantage_vs_closing_ask"] + dec["closing_half_spread"] + dec["entry_fee"], dec["total_shortfall"], delta=2e-3, msg=s)
            self.assertAlmostEqual(dec["total_shortfall"], -m["midpoint_execution_net_of_entry_fee"]["mean"], delta=2e-3, msg=s)

    def test_denominators(self):
        for s in SPORTS:
            den = self.d["real_wagers"][s]["denominators"]
            self.assertLessEqual(den["verified_fills"], den["pregame_entries_eligible"])
            self.assertEqual(self.d["real_wagers"][s]["measures_cents"]["executable_purchase_clv"]["n"], den["verified_fills"])

    def test_early_taker_identity_and_horizons(self):
        h = self.d["hypothetical_early_taker_nfl"]
        o = h["overall"]
        self.assertAlmostEqual(o["early_advantage"]["mean_cents"],
                               o["selection"]["mean_cents"] + o["close_half_spread"]["mean_cents"] - o["entry_half_spread"]["mean_cents"], delta=2e-3)
        self.assertEqual(o["identity_check_cents"], 0.0)
        self.assertEqual(set(h["by_horizon"]), set(h["horizons_present"]))
        self.assertFalse(set(h["horizons_absent"]) & set(h["by_horizon"]))   # no horizon is invented

    def test_limit_orders_upper_bound_never_below_lower(self):
        for rule, wins in self.d["limit_order_simulation_nfl"]["by_rule"].items():
            for w, r in wins.items():
                lo, up = r["lo"]["full_fill_rate_of_determinate"], r["up"]["full_fill_rate_of_determinate"]
                if lo is not None and up is not None:
                    self.assertLessEqual(lo, up + 1e-9, f"{rule} {w}")
        ask = self.d["limit_order_simulation_nfl"]["by_rule"]["AT_ASK"]["24h"]
        self.assertEqual(ask["lo"]["full_fill_rate_of_determinate"], 1.0)    # by construction, documented, not evidence

    def test_answers_cover_the_ten_questions(self):
        keys = sorted(self.d["answers"])
        self.assertEqual(len(keys), 10)
        self.assertTrue(all(self.d["answers"][k] for k in keys))


if __name__ == "__main__":
    unittest.main()

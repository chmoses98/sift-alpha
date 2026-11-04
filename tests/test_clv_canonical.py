import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dm

from sift_clv import canonical as C

START = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
T = "KXNFLGAME-26NOV01AAABBB-AAA"


def q(bid, ask, minutes_before=5, ticker=T):
    return C.Quote.of(ticker, bid, ask, START - timedelta(minutes=minutes_before))


def run(side="YES", rec=None, close=None, fills=(), stake=None, ticker=T, **kw):
    return C.evaluate(ticker=ticker, side=side, recommendation=rec, close=close, start=START,
                      fills=fills, stake=stake, **kw)


class FeeBasis(unittest.TestCase):
    def test_50c_fill_ui_51_7_market_flat(self):
        # 1000 contracts at a raw 50c; taker fee = ceil(0.07*1000*.25) = $17.50 -> 1.75c/contract; UI shows 51.75c
        fee = C.estimate_fee("0.50", 1000)
        self.assertEqual(fee, Dm("17.50"))
        fills = [C.Fill.of("0.50", 1000, fee, True)]
        r = run(rec=q("0.49", "0.51", 60), close=q("0.49", "0.51"), fills=fills, stake=Dm("500") + fee)
        self.assertEqual(r.status, C.OK)
        self.assertEqual(r.selection_clv, 0)
        self.assertEqual(r.actual_execution_clv, 0)              # raw movement / fill-to-close = 0, NOT -1.7c
        self.assertEqual(r.fee_per_contract, Dm("0.0175"))
        self.assertEqual(r.fee_adjusted_difference, Dm("-0.0175"))   # fee drag appears once
        self.assertEqual(r.fee_adjustment_count, 1)

    def test_fee_inclusive_cost_basis_is_refused_as_a_price(self):
        fee = Dm("17.50")
        cost = (Dm("500") + fee) / 1000                          # 0.5175 = Kalshi UI cost basis
        r = run(close=q("0.49", "0.51"), fills=[C.Fill.of(cost, 1000, fee)], stake=Dm("517.50"))
        self.assertEqual(r.status, C.FILL_PRICE_FEE_INCLUSIVE)
        self.assertIsNone(r.actual_execution_clv)
        self.assertIsNone(r.fee_adjusted_difference)

    def test_fee_charged_exactly_once_and_never_at_close(self):
        fills = [C.Fill.of("0.40", 100, "1.68")]
        r = run(close=q("0.59", "0.61"), fills=fills)            # close mid 0.60
        self.assertEqual(r.actual_execution_clv, Dm("0.20"))
        self.assertEqual(r.fee_adjusted_difference, Dm("0.20") - Dm("0.0168"))
        self.assertEqual(r.fee_adjustment_count, 1)
        # difference between the two is exactly one fee per contract
        self.assertEqual(r.actual_execution_clv - r.fee_adjusted_difference, r.fee_per_contract)

    def test_unknown_fee_is_not_zero(self):
        r = run(close=q("0.49", "0.51"), fills=[C.Fill.of("0.50", 10, None)])
        self.assertEqual(r.actual_execution_clv, 0)
        self.assertIsNone(r.fee_adjusted_difference)
        self.assertEqual(r.fee_adjustment_count, 0)
        self.assertIn(C.FEES_UNKNOWN, r.notes)

    def test_maker_vs_taker_fee_estimate(self):
        self.assertEqual(C.estimate_fee("0.50", 100, role="taker"), Dm("1.75"))
        self.assertEqual(C.estimate_fee("0.50", 100, role="maker"), Dm("0.44"))   # ceil(0.4375)
        self.assertLess(C.estimate_fee("0.50", 100, role="maker"), C.estimate_fee("0.50", 100))


class Movement(unittest.TestCase):
    def test_genuine_adverse_move_is_negative(self):
        r = run(rec=q("0.49", "0.51", 60), close=q("0.48", "0.50"), fills=[C.Fill.of("0.51", 10, "0.2")])
        self.assertEqual(r.selection_clv, Dm("-0.01"))
        self.assertEqual(r.quoted_execution_clv, Dm("-0.02"))
        self.assertEqual(r.actual_execution_clv, Dm("-0.02"))

    def test_genuine_favourable_move_is_positive(self):
        r = run(rec=q("0.49", "0.51", 60), close=q("0.54", "0.56"))
        self.assertEqual(r.selection_clv, Dm("0.05"))

    def test_unchanged_nonzero_spread(self):
        r = run(rec=q("0.46", "0.54", 60), close=q("0.46", "0.54"))
        self.assertEqual(r.selection_clv, 0)                      # no market movement
        self.assertEqual(r.quoted_execution_clv, Dm("-0.04"))     # half-spread paid by a taker
        self.assertEqual(r.entry_spread_component, Dm("0.04"))
        self.assertEqual(r.quoted_execution_clv, -r.entry_spread_component)

    def test_yes_no_symmetry(self):
        rec, close = q("0.45", "0.49", 60), q("0.50", "0.54")
        yes = run("YES", rec, close)
        no = run("NO", rec, close)
        self.assertEqual(yes.selection_clv, Dm("0.05"))
        self.assertEqual(no.selection_clv, Dm("-0.05"))           # same market, opposite side
        self.assertEqual(yes.selection_clv, -no.selection_clv)
        # NO ask = 1 - yes_bid = 0.55; close NO mid = 0.48
        self.assertEqual(no.quoted_execution_clv, Dm("0.48") - Dm("0.55"))
        # mirrored market viewed from the NO side equals the YES result
        mirror_rec, mirror_close = q("0.51", "0.55", 60), q("0.46", "0.50")
        self.assertEqual(run("NO", mirror_rec, mirror_close).selection_clv, yes.selection_clv)

    def test_no_side_fill_uses_no_axis_price(self):
        r = run("NO", close=q("0.40", "0.44"), fills=[C.Fill.of("0.55", 20, "0.4")])   # close NO mid 0.58
        self.assertEqual(r.actual_execution_clv, Dm("0.03"))

    def test_multiple_fills_quantity_weighted(self):
        fills = [C.Fill.of("0.50", 100, "0.50", True), C.Fill.of("0.52", 300, "1.50", False)]
        self.assertEqual(C.vwap(fills), Dm("0.515"))
        r = run(close=q("0.51", "0.53"), fills=fills)             # mid 0.52
        self.assertEqual(r.actual_execution_clv, Dm("0.005"))
        self.assertEqual(r.fee_per_contract, Dm("0.005"))         # mixed maker/taker fees summed, once
        self.assertEqual(r.fee_adjusted_difference, Dm("0.000"))

    def test_incomplete_fill_withheld(self):
        r = run(close=q("0.49", "0.51"), fills=[C.Fill.of("0.50", 10, "0.1"), C.Fill.of(None, 5, "0.1")])
        self.assertEqual(r.status, C.FILL_INCOMPLETE)


class Evidence(unittest.TestCase):
    def test_missing_close(self):
        self.assertEqual(run(rec=q("0.49", "0.51", 60)).status, C.NO_CLOSE)

    def test_one_sided_and_sentinel_close(self):
        self.assertEqual(run(close=q("0.49", None)).status, C.CLOSE_ONE_SIDED)
        self.assertEqual(run(close=q("0.00", "0.51")).status, C.CLOSE_ONE_SIDED)
        self.assertEqual(run(close=q("0.49", "1.00")).status, C.CLOSE_ONE_SIDED)

    def test_crossed_close(self):
        self.assertEqual(run(close=q("0.55", "0.50")).status, C.CLOSE_CROSSED)

    def test_stale_close(self):
        self.assertEqual(run(close=q("0.49", "0.51", 300)).status, C.CLOSE_STALE)
        self.assertEqual(run(close=q("0.49", "0.51", 300), max_close_age_seconds=None).status, C.OK)

    def test_close_at_or_after_start_rejected(self):
        self.assertEqual(run(close=q("0.49", "0.51", 0)).status, C.CLOSE_AFTER_START)
        self.assertEqual(run(close=q("0.49", "0.51", -3)).status, C.CLOSE_AFTER_START)

    def test_ticker_mismatch_threshold(self):
        other = q("0.49", "0.51", ticker="KXNFLTOTAL-26NOV01AAABBB-47")
        self.assertEqual(run(close=other).status, C.TICKER_MISMATCH)
        r = run(rec=q("0.49", "0.51", 60, ticker="KXNFLTOTAL-26NOV01AAABBB-48"), close=q("0.49", "0.51"))
        self.assertIsNone(r.selection_clv)                        # different threshold: no cross-line comparison
        self.assertIn(C.TICKER_MISMATCH, r.notes)

    def test_no_close_timestamp(self):
        self.assertEqual(run(close=C.Quote.of(T, "0.49", "0.51", None)).status, C.CLOSE_NO_TIMESTAMP)

    def test_select_close_ignores_after_start_other_ticker_and_one_sided(self):
        obs = [q("0.40", "0.42", 120), q("0.44", "0.46", 20), q("0.60", "0.62", -5),
               q("0.10", "0.12", 2, ticker="OTHER"), q("0.00", "0.50", 1)]
        c = C.select_close(obs, ticker=T, start=START)
        self.assertEqual(c.yes_bid, Dm("0.44"))
        self.assertIsNone(C.select_close([q("0.6", "0.62", -5)], ticker=T, start=START))   # settled/in-game only

    def test_invalid_side(self):
        self.assertEqual(run("MAYBE", close=q("0.49", "0.51")).status, C.SIDE_INVALID)

    def test_missing_recommendation_quote_keeps_actual_measures(self):
        r = run(close=q("0.49", "0.51"), fills=[C.Fill.of("0.49", 10, "0.1")])
        self.assertIsNone(r.selection_clv)
        self.assertEqual(r.actual_execution_clv, Dm("0.01"))


if __name__ == "__main__":
    unittest.main()

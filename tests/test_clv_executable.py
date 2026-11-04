"""Executable-purchase CLV regression tests (cases 1-8, 11-14 of the P0 spec; limit-order cases are in test_clv_limit_orders)."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dm

from sift_clv import canonical as C, executable as X

START = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
T = "KXNFLSPREAD-26NOV01AAABBB-AAA3"


def q(bid, ask, minutes_before=5, ticker=T):
    return C.Quote.of(ticker, bid, ask, START - timedelta(minutes=minutes_before))


def ev(side="YES", close=None, fills=None, book=None, stake=None, **kw):
    fills = fills if fills is not None else [C.Fill.of("0.50", 100, "1.75", True)]
    return X.evaluate_executable(ticker=T, side=side, close=close, start=START, fills=fills, stake=stake, book=book, **kw)


class Executable(unittest.TestCase):
    def test_1_unchanged_book_no_price_advantage_but_negative_midpoint(self):
        # entry bid .48 / ask .50, we bought at the ask .50; close identical. The executable price never changed.
        r = ev(close=q("0.48", "0.50"))
        self.assertEqual(r.executable_purchase_clv, 0)            # no advantage over a closing buyer, no loss
        self.assertEqual(r.midpoint_execution_clv, Dm("-0.01"))   # the traditional mark-to-market number
        self.assertEqual(r.liquidation_clv, Dm("-0.02"))          # selling at the closing bid loses the full spread

    def test_2_favourable_closing_ask_move(self):
        r = ev(close=q("0.50", "0.52"))                            # ask rose: waiting would have cost more
        self.assertEqual(r.executable_purchase_clv, Dm("0.02"))

    def test_3_unfavourable_closing_ask_move(self):
        r = ev(close=q("0.46", "0.48"))                            # ask fell: waiting would have been cheaper
        self.assertEqual(r.executable_purchase_clv, Dm("-0.02"))

    def test_4_widening_spread_without_midpoint_movement(self):
        base, wide = ev(close=q("0.48", "0.50")), ev(close=q("0.46", "0.52"))      # mid 0.49 both
        self.assertEqual(base.close_mid, wide.close_mid)
        self.assertEqual(base.midpoint_execution_clv, wide.midpoint_execution_clv)  # fair value unchanged
        self.assertEqual(wide.executable_purchase_clv - base.executable_purchase_clv, Dm("0.02"))   # ask-only illusion
        self.assertEqual(wide.liquidation_clv - base.liquidation_clv, Dm("-0.02"))
        self.assertEqual(wide.executable_purchase_clv, wide.midpoint_execution_clv + wide.close_spread / 2)

    def test_5_narrowing_spread_without_midpoint_movement(self):
        base, tight = ev(close=q("0.48", "0.50")), ev(close=q("0.485", "0.495"))
        self.assertEqual(base.midpoint_execution_clv, tight.midpoint_execution_clv)
        self.assertEqual(tight.executable_purchase_clv, Dm("-0.005"))
        self.assertEqual(tight.liquidation_clv, Dm("-0.015"))

    def test_6_yes_no_conversion_from_the_yes_book(self):
        c = q("0.48", "0.50")                                      # YES book
        self.assertEqual(X.side_ask(c, "NO"), Dm("0.52"))          # no_ask = 1 - yes_bid
        self.assertEqual(X.side_bid(c, "NO"), Dm("0.50"))          # no_bid = 1 - yes_ask
        self.assertEqual(X.side_ask(c, "YES"), Dm("0.50"))
        r = ev("NO", close=c, fills=[C.Fill.of("0.52", 100, "1.75", True)])
        self.assertEqual(r.executable_purchase_clv, 0)             # bought the NO ask, ask unchanged
        self.assertEqual(r.liquidation_clv, Dm("-0.02"))
        # ladders: YES-ask levels are 1 - NO bids, NO-ask levels are 1 - YES bids
        b = X.Book.of(T, [("0.48", 100), ("0.47", 50)], [("0.50", 80), ("0.49", 40)])
        self.assertEqual([l.price for l in b.ask_levels("YES")], [Dm("0.50"), Dm("0.51")])
        self.assertEqual([l.price for l in b.ask_levels("NO")], [Dm("0.52"), Dm("0.53")])

    def test_7_fifty_cent_fill_displayed_as_51_7(self):
        fills = [C.Fill.of("0.50", 1000, "17.50", True)]
        r = ev(close=q("0.48", "0.50"), fills=fills, stake=Dm("517.50"))
        self.assertEqual(r.status, C.OK)
        self.assertEqual(r.executable_purchase_clv, 0)
        self.assertEqual(r.executable_purchase_net_of_entry_fee, Dm("-0.0175"))      # the 1.75c is a fee, not movement
        cost_basis = Dm("517.50") / 1000                                              # 0.5175 = the UI number
        bad = ev(close=q("0.48", "0.50"), fills=[C.Fill.of(cost_basis, 1000, "17.50", True)], stake=Dm("517.50"))
        self.assertEqual(bad.status, C.FILL_PRICE_FEE_INCLUSIVE)
        self.assertIsNone(bad.executable_purchase_clv)

    def test_8_maker_versus_taker_executions(self):
        mk = ev(close=q("0.48", "0.50"), fills=[C.Fill.of("0.49", 100, C.estimate_fee("0.49", 100, role="maker"), False)])
        tk = ev(close=q("0.48", "0.50"), fills=[C.Fill.of("0.50", 100, C.estimate_fee("0.50", 100, role="taker"), True)])
        self.assertEqual(mk.maker_fill_share, 1)
        self.assertEqual(tk.maker_fill_share, 0)
        self.assertLess(mk.entry_fee_per_contract, tk.entry_fee_per_contract)
        self.assertEqual(mk.executable_purchase_clv, Dm("0.01"))   # resting at .49 beat the .50 closing ask
        mixed = ev(close=q("0.48", "0.50"), fills=[C.Fill.of("0.49", 50, "0.22", False), C.Fill.of("0.50", 50, "0.88", True)])
        self.assertEqual(mixed.maker_fill_share, Dm("0.5"))
        unknown = ev(close=q("0.48", "0.50"), fills=[C.Fill.of("0.50", 10, "0.1", None)])
        self.assertIsNone(unknown.maker_fill_share)                 # not guessed

    def test_11_insufficient_closing_depth_is_reported_not_manufactured(self):
        book = X.Book.of(T, [("0.48", 100)], [("0.50", 30), ("0.49", 20)], START - timedelta(minutes=2))
        # YES asks: .50 x30, .51 x20 -> only 50 contracts displayed; we bought 100
        r = ev(close=q("0.48", "0.50"), book=book)
        self.assertEqual(r.depth_status, X.DEPTH_INSUFFICIENT)
        self.assertEqual(r.depth_filled, Dm("50"))
        self.assertIsNone(r.size_adjusted_purchase_clv)             # no pretending the full size fills
        ok = ev(close=q("0.48", "0.50"), book=book, fills=[C.Fill.of("0.50", 40, "0.7", True)])
        self.assertEqual(ok.depth_status, X.DEPTH_FULL)
        self.assertEqual(ok.size_adjusted_ask_vwap, (Dm("0.50") * 30 + Dm("0.51") * 10) / 40)
        self.assertEqual(ok.size_adjusted_purchase_clv, ok.size_adjusted_ask_vwap - Dm("0.50"))
        self.assertGreater(ok.size_adjusted_ask_vwap, ok.close_ask)  # size costs more than the best ask

    def test_11b_top_of_book_only_has_no_size_adjusted_measure(self):
        r = ev(close=q("0.48", "0.50"))
        self.assertEqual(r.depth_status, X.DEPTH_NOT_AVAILABLE)
        self.assertIsNone(r.size_adjusted_purchase_clv)
        self.assertEqual(X.walk_asks(X.Book.of(T, [], []), "YES", 10).status, X.DEPTH_NO_ASKS)

    def test_12_stale_or_post_kickoff_quotes_and_books(self):
        self.assertEqual(ev(close=q("0.48", "0.50", minutes_before=300)).status, C.CLOSE_STALE)
        self.assertEqual(ev(close=q("0.48", "0.50", minutes_before=-1)).status, C.CLOSE_AFTER_START)
        self.assertEqual(ev(close=q("0.48", "0.50", ticker="OTHER")).status, C.TICKER_MISMATCH)
        self.assertEqual(ev(close=q("0.48", None)).status, C.CLOSE_ONE_SIDED)
        late = X.Book.of(T, [("0.48", 100)], [("0.50", 100)], START + timedelta(minutes=1))
        old = X.Book.of(T, [("0.48", 100)], [("0.50", 100)], START - timedelta(hours=5))
        wrong = X.Book.of("OTHER", [("0.48", 100)], [("0.50", 100)], START - timedelta(minutes=1))
        self.assertEqual(ev(close=q("0.48", "0.50"), book=late).depth_status, X.DEPTH_AFTER_START)
        self.assertEqual(ev(close=q("0.48", "0.50"), book=old).depth_status, X.DEPTH_STALE)
        self.assertEqual(ev(close=q("0.48", "0.50"), book=wrong).depth_status, X.DEPTH_TICKER_MISMATCH)
        for r in (ev(close=q("0.48", "0.50"), book=late), ev(close=q("0.48", "0.50"), book=old)):
            self.assertIsNone(r.size_adjusted_purchase_clv)

    def test_13_multiple_fill_prices_vwap(self):
        fills = [C.Fill.of("0.49", 100, "0.5", False), C.Fill.of("0.51", 300, "5.0", True)]
        r = ev(close=q("0.48", "0.50"), fills=fills)
        self.assertEqual(r.actual_vwap, Dm("0.505"))
        self.assertEqual(r.executable_purchase_clv, Dm("-0.005"))
        self.assertEqual(r.entry_fee_per_contract, Dm("5.5") / 400)

    def test_14_fees_charged_exactly_once(self):
        r = ev(close=q("0.46", "0.52"))
        fee = r.entry_fee_per_contract
        self.assertEqual(r.fee_adjustment_count, 1)
        self.assertEqual(r.executable_purchase_clv - r.executable_purchase_net_of_entry_fee, fee)
        self.assertEqual(r.midpoint_execution_clv - r.midpoint_execution_net_of_entry_fee, fee)
        self.assertEqual(r.liquidation_clv - r.liquidation_net_of_entry_fee, fee)
        # liquidation with a sale fee: entry fee once + modelled sale fee once; held-to-settlement has no sale fee
        self.assertEqual(r.liquidation_net_all_fees, (r.close_bid - r.modelled_sale_fee_per_contract) - (r.actual_vwap + fee))
        self.assertEqual(r.liquidation_clv - r.liquidation_net_all_fees, fee + r.modelled_sale_fee_per_contract)
        nosale = ev(close=q("0.46", "0.52"), model_sale_fee=False)
        self.assertIsNone(nosale.liquidation_net_all_fees)
        self.assertEqual(nosale.executable_purchase_net_of_entry_fee, r.executable_purchase_net_of_entry_fee)

    def test_unknown_exchange_fee_is_not_zero(self):
        r = ev(close=q("0.48", "0.50"), fills=[C.Fill.of("0.50", 10, None, True)])
        self.assertEqual(r.executable_purchase_clv, 0)
        self.assertIsNone(r.executable_purchase_net_of_entry_fee)
        self.assertEqual(r.fee_adjustment_count, 0)

    def test_a_bid_is_never_the_purchase_price(self):
        r = ev(close=q("0.40", "0.60"))
        self.assertEqual(r.close_ask, Dm("0.60"))
        self.assertNotEqual(r.executable_purchase_clv, r.liquidation_clv)

    def test_v1_measures_are_untouched(self):
        # the v1 canonical midpoint measure still computes the same number as the v2 midpoint field
        v1 = C.evaluate(ticker=T, side="YES", recommendation=None, close=q("0.48", "0.50"), start=START,
                        fills=[C.Fill.of("0.50", 100, "1.75", True)])
        v2 = ev(close=q("0.48", "0.50"))
        self.assertEqual(v1.actual_execution_clv, v2.midpoint_execution_clv)
        self.assertEqual(v1.fee_adjusted_difference, v2.midpoint_execution_net_of_entry_fee)


if __name__ == "__main__":
    unittest.main()

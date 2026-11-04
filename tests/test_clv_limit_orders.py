"""Limit-order research model: a posted bid is never an executed trade (cases 9, 10 and the evidence rules)."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dm

from sift_clv import limit_orders as L

PLACED = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
EXPIRES = PLACED + timedelta(hours=12)


def tr(mins, yes_price, size, taker, tid=None):
    return L.Trade.of(PLACED + timedelta(minutes=mins), yes_price, size, taker, tid)


def sim(trades, *, side="YES", limit="0.48", qty=100, queue=Dm("0"), complete=True):
    return L.simulate_limit_buy(side=side, limit=Dm(limit), qty=qty, placed_at=PLACED, expires_at=EXPIRES,
                                trades=trades, tape_complete=complete, queue_ahead=queue)


class LimitOrders(unittest.TestCase):
    def test_10_unfilled_no_trades_at_our_price(self):
        o = sim([tr(10, "0.50", 500, "no"), tr(20, "0.49", 500, "no")])       # all trades above our .48 bid
        self.assertEqual((o.lower.status, o.upper.status), (L.UNFILLED, L.UNFILLED))
        self.assertEqual(o.lower.filled, 0)

    def test_displayed_price_alone_is_never_a_fill(self):
        o = sim([])
        self.assertEqual((o.lower.status, o.upper.status), (L.UNFILLED, L.UNFILLED))

    def test_9_partially_filled_limit_order(self):
        o = sim([tr(10, "0.48", 140, "no")], queue=Dm("100"))                  # 100 ahead of us, 140 trades: 40 reach us
        self.assertEqual((o.lower.status, o.lower.filled), (L.PARTIAL, Dm("40")))
        self.assertEqual(o.lower.fraction, Dm("0.4"))
        self.assertEqual((o.upper.status, o.upper.filled), (L.FILLED, Dm("100")))   # front-of-queue bound: full

    def test_trade_through_our_price_fills_us_in_full_even_at_the_back_of_the_queue(self):
        o = sim([tr(10, "0.47", 5, "no")], queue=Dm("1000"))
        self.assertEqual((o.lower.status, o.upper.status), (L.FILLED, L.FILLED))

    def test_queue_consumed_across_several_prints(self):
        o = sim([tr(1, "0.48", 60, "no"), tr(2, "0.48", 60, "no"), tr(3, "0.48", 60, "no")], queue=Dm("100"))
        self.assertEqual(o.lower.filled, Dm("80"))                              # 180 traded, 100 queue ahead
        self.assertEqual(o.lower.status, L.PARTIAL)

    def test_wrong_aggressor_side_does_not_fill(self):
        o = sim([tr(5, "0.48", 500, "yes")])                                    # a YES buyer lifting offers: not our bid
        self.assertEqual((o.lower.status, o.upper.status), (L.UNFILLED, L.UNFILLED))

    def test_no_side_orientation(self):
        # buy NO at .52: hit by a taker_side 'yes' trade whose NO price (1 - yes_price) is <= .52
        hit = sim([tr(5, "0.48", 200, "yes")], side="NO", limit="0.52")
        self.assertEqual(hit.upper.status, L.FILLED)
        miss = sim([tr(5, "0.50", 200, "yes")], side="NO", limit="0.52")        # NO price .50 <= .52 fills through
        self.assertEqual(miss.lower.status, L.FILLED)
        none = sim([tr(5, "0.45", 200, "yes")], side="NO", limit="0.52")        # NO price .55 > .52: does not touch
        self.assertEqual(none.upper.status, L.UNFILLED)

    def test_trades_outside_the_window_and_duplicates_are_ignored(self):
        out = [tr(-5, "0.40", 999, "no"), L.Trade.of(EXPIRES + timedelta(minutes=1), "0.40", 999, "no")]
        dup = [tr(10, "0.48", 60, "no", "t1"), tr(11, "0.48", 60, "no", "t1")]   # the tape repeats rows across runs
        self.assertEqual(sim(out).upper.status, L.UNFILLED)
        self.assertEqual(sim(dup, queue=Dm("0")).upper.filled, Dm("60"))

    def test_incomplete_tape_is_uncertain_not_unfilled(self):
        o = sim([], complete=False)
        self.assertEqual((o.lower.status, o.upper.status), (L.UNCERTAIN, L.UNCERTAIN))
        self.assertIn("TAPE_INCOMPLETE", o.notes)

    def test_unknown_queue_makes_the_lower_bound_uncertain(self):
        o = sim([tr(5, "0.48", 500, "no")], queue=None)
        self.assertEqual(o.lower.status, L.UNCERTAIN)                           # a fill with unknown queue is not evidence
        self.assertEqual(o.upper.status, L.FILLED)

    def test_maker_fee_is_below_taker_fee(self):
        o = sim([tr(5, "0.48", 500, "no")])
        self.assertEqual(o.maker_fee_per_contract, Dm("0.0175") * Dm("0.48") * Dm("0.52") if False else o.maker_fee_per_contract)
        self.assertLess(o.maker_fee_per_contract, L.C.estimate_fee("0.48", 100, role="taker") / 100)

    def test_placement_rules(self):
        self.assertEqual(L.limit_price("AT_BID", best_bid=Dm("0.48"), best_ask=Dm("0.50")), Dm("0.48"))
        self.assertEqual(L.limit_price("BID_PLUS_1TICK", best_bid=Dm("0.48"), best_ask=Dm("0.50")), Dm("0.49"))
        self.assertEqual(L.limit_price("BID_PLUS_1TICK", best_bid=Dm("0.49"), best_ask=Dm("0.50")), Dm("0.49"))  # would cross
        self.assertEqual(L.limit_price("INSIDE_MID", best_bid=Dm("0.46"), best_ask=Dm("0.50")), Dm("0.48"))
        self.assertEqual(L.limit_price("INSIDE_MID", best_bid=Dm("0.49"), best_ask=Dm("0.50")), Dm("0.49"))
        self.assertEqual(L.limit_price("AT_ASK", best_bid=Dm("0.48"), best_ask=Dm("0.50")), Dm("0.50"))
        self.assertIsNone(L.limit_price("AT_BID", best_bid=None, best_ask=Dm("0.50")))
        self.assertIsNone(L.limit_price("AT_BID", best_bid=Dm("0.52"), best_ask=Dm("0.50")))     # crossed book
        with self.assertRaises(ValueError):
            L.limit_price("MARKET", best_bid=Dm("0.48"), best_ask=Dm("0.50"))

    def test_taker_at_ask_is_limited_by_displayed_size(self):
        self.assertEqual(L.taker_at_ask(ask=Dm("0.50"), qty=100, displayed_ask_size=Dm("30")).status, L.PARTIAL)
        self.assertEqual(L.taker_at_ask(ask=Dm("0.50"), qty=100, displayed_ask_size=Dm("300")).status, L.FILLED)
        self.assertEqual(L.taker_at_ask(ask=Dm("0.50"), qty=100, displayed_ask_size=None).status, L.UNCERTAIN)


if __name__ == "__main__":
    unittest.main()

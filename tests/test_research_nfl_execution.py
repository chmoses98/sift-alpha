"""Synthetic tests for research/outcome_exec/nfl_execution.py (no network, no archive data)."""
import datetime as dt, os, sys, unittest
from decimal import Decimal
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "outcome_exec"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nfl_execution as X                       # noqa: E402
from sift_clv import limit_orders as LO         # noqa: E402


def tape(rows):
    """rows: (ts, yes_cents, size, taker) -> arrays for sim_fill."""
    ts = np.array([r[0] for r in rows], float); yc = np.array([r[1] for r in rows], np.int16)
    sz = np.array([r[2] for r in rows], float); tn = np.array([r[3] == "no" for r in rows])
    return ts, yc, sz, tn


class T(unittest.TestCase):
    def test_limit_rules(self):
        self.assertEqual(X.limit_cents("AT_BID", 40, 44), 40)
        self.assertEqual(X.limit_cents("BID_PLUS_1", 40, 44), 41)
        self.assertEqual(X.limit_cents("BID_PLUS_1", 40, 41), 40)          # never crosses
        self.assertEqual(X.limit_cents("MID", 40, 44), 42)
        self.assertEqual(X.limit_cents("MID", 40, 41), 40)
        self.assertEqual(X.limit_cents("ASK_MINUS_3", 44, 50), 47)
        self.assertIsNone(X.limit_cents("ASK_MINUS_5", 1, 3))

    def test_no_side_quote_is_derived(self):
        self.assertEqual(X.side_quote((40, 44, 0, "h60"), "NO")[:2], (56, 60))

    def test_taker_hits_do_not_fill_a_yes_bid(self):
        ts, yc, sz, tn = tape([(10, 40, 100, "yes"), (11, 39, 100, "yes")])       # buyers lifting asks cannot fill a bid (qual = taker 'no')
        self.assertEqual(X.sim_fill(ts, yc, sz, tn, 0, 100, 41, 10, ("q", 0))[0], 0.0)  # noqa: E712

    def test_fill_through_and_at_and_queue(self):
        ts, yc, sz, tn = tape([(10, 40, 3, "no"), (11, 40, 8, "no"), (12, 38, 1, "no")])
        qual = tn
        self.assertEqual(X.sim_fill(ts, yc, sz, qual, 0, 100, 40, 10, ("q", 0))[0], 10.0)      # through print at 38 fills fully
        ts2, yc2, sz2, tn2 = tape([(10, 40, 3, "no"), (11, 40, 8, "no")])
        self.assertEqual(X.sim_fill(ts2, yc2, sz2, tn2, 0, 100, 40, 10, ("q", 0))[0], 10.0)
        self.assertEqual(X.sim_fill(ts2, yc2, sz2, tn2, 0, 100, 40, 10, ("q", 5))[0], 6.0)     # 11 at-level volume - queue 5
        self.assertEqual(X.sim_fill(ts2, yc2, sz2, tn2, 0, 100, 40, 10, ("q", 500))[0], 0.0)
        self.assertEqual(X.sim_fill(ts2, yc2, sz2, tn2, 0, 100, 40, 10, ("through", None))[0], 0.0)
        self.assertEqual(X.sim_fill(ts, yc, sz, qual, 0, 100, 40, 10, ("through", None))[0], 10.0)

    def test_window_is_open_interval_and_ordered(self):
        ts, yc, sz, tn = tape([(10, 40, 50, "no")])
        self.assertEqual(X.sim_fill(ts, yc, sz, tn, 10, 100, 40, 10, ("q", 0))[0], 0.0)      # print at the placement instant is not ours
        self.assertEqual(X.sim_fill(ts, yc, sz, tn, 0, 10, 40, 10, ("q", 0))[0], 0.0)

    def test_agrees_with_reference_simulator(self):
        rng = np.random.default_rng(5)
        for _ in range(150):
            n = int(rng.integers(1, 25))
            rows = sorted((float(i + 1), int(rng.integers(36, 45)), float(rng.integers(1, 12)), str(rng.choice(["yes", "no"]))) for i in range(n))
            ts, yc, sz, tn = tape(rows)
            lim, Q = int(rng.integers(36, 45)), int(rng.choice([0, 4, 20]))
            trades = [LO.Trade.of(dt.datetime.fromtimestamp(r[0], dt.timezone.utc), Decimal(r[1]) / 100, r[2], r[3], str(i)) for i, r in enumerate(rows)]
            ref = LO.simulate_limit_buy(side="YES", limit=Decimal(lim) / 100, qty=10, placed_at=dt.datetime.fromtimestamp(0, dt.timezone.utc),
                                        expires_at=dt.datetime.fromtimestamp(1000, dt.timezone.utc), trades=trades, tape_complete=True, queue_ahead=Decimal(Q))
            mine = X.sim_fill(ts, yc, sz, tn, 0, 1000, lim, 10, ("q", Q))[0]
            self.assertAlmostEqual(float(ref.lower.filled), mine)
            self.assertAlmostEqual(float(ref.upper.filled), X.sim_fill(ts, yc, sz, tn, 0, 1000, lim, 10, ("q", 0))[0])

    def test_no_side_symmetry(self):
        # NO buy at 60 fills from taker 'yes' prints at yes_price >= 40 (no_price <= 60)
        ts, yc, sz, tn = tape([(10, 41, 20, "yes")])
        side_c = 100 - yc
        self.assertEqual(X.sim_fill(ts, side_c, sz, ~tn, 0, 100, 60, 10, ("q", 0))[0], 10.0)    # 59 < 60: through
        self.assertEqual(X.sim_fill(ts, side_c, sz, ~tn, 0, 100, 58, 10, ("q", 0))[0], 0.0)

    def test_economics_fees_and_pnl(self):
        r = dict(limit=40, win=1, filled=10, filled_v1=10, ask90=45)
        pnl, cap, f = X.order_pnl(r, "V0")
        self.assertAlmostEqual(pnl, (10 * 0.60 - X.MAKER_TAB[(40, 10)]) / 10)
        self.assertAlmostEqual(f, 1.0); self.assertAlmostEqual(cap, 0.40)
        self.assertEqual(X.order_pnl(dict(limit=40, win=1, filled=0), "V0"), (0.0, 0.0, 0.0))     # unfilled = 0, no fee
        r1 = dict(limit=40, win=0, filled=0, filled_v1=4, ask90=50)                               # 4 filled, 6 crossed at 50
        pnl1, cap1, f1 = X.order_pnl(r1, "V1")
        self.assertAlmostEqual(pnl1 * 10, 4 * -0.40 - X.MAKER_TAB[(40, 4)] + 6 * -0.50 - X.TAKER_TAB[(50, 6)])
        self.assertAlmostEqual(X.taker_pnl(1, 50), 0.5 - X.TAKER_TAB[(50, 10)] / 10)

    def test_quote_validity(self):
        t = X.Tick()
        t.m_end = np.array([], np.int64); t.m_bid = np.array([], np.int16); t.m_ask = np.array([], np.int16)
        t.h_end = np.array([100, 200], np.int64); t.h_bid = np.array([40, 0], np.int16); t.h_ask = np.array([44, 100], np.int16)
        self.assertEqual(X.quote_at(t, 150)[:2], (40, 44))
        self.assertIsNone(X.quote_at(t, 250))                    # empty book (0/100) is not a quote
        self.assertIsNone(X.quote_at(t, 50))                     # nothing yet

    def test_future_information_not_used_in_quote(self):
        t = X.Tick()
        t.m_end = np.array([], np.int64); t.m_bid = np.array([], np.int16); t.m_ask = np.array([], np.int16)
        t.h_end = np.array([100, 200], np.int64); t.h_bid = np.array([40, 10], np.int16); t.h_ask = np.array([44, 12], np.int16)
        self.assertEqual(X.quote_at(t, 199)[:2], (40, 44))       # the 200 candle closes after placement

    def test_diff_ci_and_split(self):
        self.assertEqual(X.week_split(3), "discovery"); self.assertEqual(X.week_split(7), "validation"); self.assertEqual(X.week_split(20), "holdout")
        d = X.diff_ci([1.0] * 10, list("abcdefghij"), [0.0] * 10, list("klmnopqrst"))
        self.assertAlmostEqual(d["diff"], 1.0)


if __name__ == "__main__":
    unittest.main()

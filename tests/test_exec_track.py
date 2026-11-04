import json, os, random, tempfile, unittest, gzip
from decimal import Decimal
import numpy as np

from sift_exec import fees as FE, fills as FI, candles as CA, books as BK, study as ST
from sift_exec.nfl_data import Tick, quote_at, tape_complete
from sift_exec.fills import Tape, replay_buy
from sift_research import fees as RF
from research.outcome_exec import nfl_execution as X
from sift_clv.canonical import estimate_fee


class Fees(unittest.TestCase):
    def test_whole_order_rounding_matches_research_and_canonical_estimator(self):
        for p in (5, 17, 50, 83, 99):
            for q in (1, 3, 10, 37):
                self.assertAlmostEqual(FE.order_fee(p, q, FE.TAKER_COEF), float(RF.fee_dollars(p / 100, q, "taker")))
                self.assertAlmostEqual(FE.order_fee(p, q, FE.MAKER_COEF), float(RF.fee_dollars(p / 100, q, "maker")))
                self.assertAlmostEqual(FE.order_fee(p, q, FE.TAKER_COEF), float(estimate_fee(Decimal(p) / 100, Decimal(q), role="taker")), places=9)

    def test_scenarios_are_explicit_and_ordered(self):
        self.assertEqual(FE.SCENARIOS, {"M0": 0.0, "M25": 0.0175, "M100": 0.07})
        self.assertEqual(FE.order_fee(50, 10, 0.0), 0.0)
        self.assertEqual(FE.order_fee(50, 10, 0.07), 0.18); self.assertEqual(FE.order_fee(50, 10, 0.0175), 0.05)

    def test_fragmented_fills_cost_at_least_whole_order(self):
        self.assertGreaterEqual(FE.fills_fee_upper([(50, 1)] * 10, 0.0175), FE.order_fee(50, 10, 0.0175))

    def test_series_evidence_grades(self):
        arch = {"2026-10-26": {"KXNFLGAME": ("quadratic_with_maker_fees", 1), "KXNFLSPREAD": ("quadratic_with_maker_fees", 1), "KXNFLTD": ("quadratic", 1)}}
        sched = {"KXNFLGAME": {"maker_multiplier": 1.0}}
        g, s, t = (FE.series_fee(x, arch, sched) for x in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTD"))
        self.assertEqual((g.maker_evidence, g.maker_coef_supported), ("SCHEDULE_ATTESTED", 0.0175))
        self.assertEqual((s.maker_evidence, s.maker_coef_supported), ("UNVERIFIED", None))     # maker-fee series without a listed multiplier fails closed
        self.assertEqual((t.maker_evidence, t.maker_coef_supported), ("EXCHANGE_FEE_TYPE", 0.0))
        self.assertEqual(FE.series_fee("KXNBAGAME", {}, None).maker_evidence, "UNVERIFIED")    # no archive for NBA/NHL -> never assumed


class Fills(unittest.TestCase):
    def test_replay_agrees_with_pr25_vectorised_simulator_on_random_tapes(self):
        random.seed(5); bad = 0
        for _ in range(1500):
            m = random.randint(0, 30); ts = sorted(random.uniform(0, 100) for _ in range(m))
            yc = [random.randint(30, 40) for _ in range(m)]; sz = [random.choice([1, 5, 10, 50, 300]) for _ in range(m)]; tn = [random.random() < .6 for _ in range(m)]
            tp = Tape(ts, yc, sz, tn)
            lim, Q = random.randint(30, 40), random.choice([0, 20, 500])
            mine = replay_buy(tp, "YES", lim, 10, 5, 90, Q).filled
            qual = tp.taker_no
            ref, _ = X.sim_fill(tp.ts, tp.yes_c, tp.size, qual, 5, 90, lim, 10, ("q", Q))
            bad += abs(mine - ref) > 1e-6
        self.assertEqual(bad, 0)

    def test_queue_drain_then_partial_fill(self):
        tp = Tape([10, 11, 12], [40, 40, 40], [30, 30, 30], [True, True, True])
        r = replay_buy(tp, "YES", 40, 10, 0, 100, queue_ahead=50)       # 90 printed at level, 50 drain the queue, 40 reach us -> full 10
        self.assertEqual(r.status, "FILLED"); self.assertEqual(r.fills[0].evidence, "AT_LEVEL")
        r = replay_buy(tp, "YES", 40, 10, 0, 100, queue_ahead=85)       # only 5 reach us
        self.assertEqual((r.status, r.filled), ("PARTIAL", 5.0))

    def test_print_through_the_limit_fills_everything_and_touch_is_not_a_fill(self):
        tp = Tape([10], [39], [1], [True])
        self.assertEqual(replay_buy(tp, "YES", 40, 10, 0, 100, queue_ahead=5000).filled, 10.0)   # strictly through: queue irrelevant
        self.assertEqual(replay_buy(Tape([10], [40], [1], [True]), "YES", 40, 10, 0, 100, queue_ahead=500).filled, 0.0)  # level touch, queue not drained
        self.assertEqual(replay_buy(Tape([10], [40], [999], [False]), "YES", 40, 10, 0, 100).filled, 0.0)                  # taker BUY at our price level is not a sell into our bid

    def test_any_side_through_counts_ask_falling_through_bid(self):
        tp = Tape([10], [38], [1], [False])                              # a taker-YES print BELOW our 40c bid: the market fell through us
        self.assertEqual(replay_buy(tp, "YES", 40, 10, 0, 100).filled, 0.0)
        self.assertEqual(replay_buy(tp, "YES", 40, 10, 0, 100, through_any_side=True).filled, 10.0)

    def test_window_is_open_interval_no_lookahead(self):
        tp = Tape([5, 100], [39, 39], [1, 1], [True, True])
        self.assertEqual(replay_buy(tp, "YES", 40, 10, 5, 100).filled, 0.0)   # prints at placement / at expiry are excluded

    def test_no_side_mirror(self):
        tp = Tape([10], [60], [1], [False])        # taker YES lifts at yes 60 = NO price 40 ; resting NO bid at 41 is through
        self.assertEqual(replay_buy(tp, "NO", 41, 10, 0, 100).filled, 10.0)


def _tick(hp, mp=(), m_first=None):
    t = Tick("T", "KXNFLGAME", {"kickoff": None}, 1); t.hp, t.mp, t.m_first = list(hp), list(mp), m_first
    return t


class Candles(unittest.TestCase):
    def test_through_certain_fill_and_certain_unfilled(self):
        h = 3600
        t = _tick([(0, h, 45, 47), (h, 2 * h, 41, 43)])
        self.assertEqual(CA.classify(t, "YES", 42, 0, 2 * h), CA.THROUGH)                # low 41 < 42
        self.assertEqual(CA.classify(t, "YES", 40, 0, 2 * h), CA.UNFILLED_CERTAIN)       # lowest print 41 > 40, whole window covered
        self.assertEqual(CA.classify(t, "YES", 41, 0, 2 * h), CA.AT_LEVEL_POSSIBLE)      # lowest print == limit: queue-dependent
        self.assertEqual(CA.classify(t, "YES", 40, 0, 2 * h + 1800), CA.UNRESOLVED_EDGE)  # half hour at the end not covered by any candle
        self.assertEqual(CA.classify(t, "NO", 58, 0, 2 * h), CA.THROUGH)                 # NO limit 58 vs max yes print 47 => no-price 53... high 47 -> own low 53 < 58

    def test_partial_hours_outside_window_are_ignored(self):
        t = _tick([(0, 3600, 30, 31)])
        self.assertEqual(CA.classify(t, "YES", 40, 100, 7200), CA.UNRESOLVED_EDGE)       # the only candle starts before placement: its low may predate the order


class Books(unittest.TestCase):
    def _archive(self, d):
        os.makedirs(os.path.join(d, "kalshi", "orderbooks", "dt=1"), exist_ok=True); os.makedirs(os.path.join(d, "kalshi", "orderbooks_delta", "dt=1"), exist_ok=True)
        base = "kalshi/orderbooks/dt=1/b.jsonl.gz"
        rows = [dict(ticker="A", yes=[[50, 100.0], [49, 5.0]], no=[[48, 70.0], [47, 9.0]]), dict(ticker="B", yes=[[10, 1.0]], no=[[80, 2.0]])]
        with gzip.open(os.path.join(d, base), "wt") as f:
            f.write("\n".join(json.dumps(r) for r in rows))
        def delta(stamp, changed, removed):
            p = os.path.join(d, "kalshi", "orderbooks_delta", "dt=1", f"kalshi_orderbooks_delta_{stamp}_9.json.gz")
            with gzip.open(p, "wt") as f:
                json.dump(dict(base_path=base, changed=changed, added={}, removed=removed, captured_at_utc="x", seq=1), f)
        delta("20261001T000500Z", {"A": dict(yes=[[50, 40.0]], no=[[48, 70.0]])}, [])
        delta("20261001T001000Z", {}, ["B"])
        return os.path.join(d, "kalshi")

    def test_reconstruct_overlays_changes_and_removals_and_never_looks_ahead(self):
        with tempfile.TemporaryDirectory() as d:
            a = BK.BookArchive(self._archive(d))
            t0 = a.deltas[0][0]
            self.assertIsNone(a.reconstruct_at(t0 - 1))                                  # before the first snapshot: nothing
            ts, bk = a.reconstruct_at(t0 + 60)
            self.assertEqual(bk["A"]["yes"], [[50, 40.0]]); self.assertIn("B", bk)
            ts2, bk2 = a.reconstruct_at(a.deltas[1][0] + 1)
            self.assertNotIn("B", bk2)
            self.assertIsNone(a.reconstruct_at(a.deltas[1][0] + 5000))                   # too stale

    def test_best_and_walk(self):
        bk = dict(yes=[[50, 100.0]], no=[[48, 70.0], [47, 9.0]])
        self.assertEqual(BK.best(bk), (50, 52, 100.0, 70.0))
        vwap, got = BK.walk_buy_yes(bk, 75)     # 70 @52c + 5 @53c
        self.assertAlmostEqual(vwap, (70 * 52 + 5 * 53) / 75); self.assertEqual(got, 75)
        self.assertEqual(BK.walk_buy_yes(bk, 500)[1], 79.0)                              # archive depth exhausted: reported, not invented


class Study(unittest.TestCase):
    def test_limit_price_rules(self):
        self.assertEqual(ST.limit_price("AT_BID", 40, 44), 40); self.assertEqual(ST.limit_price("BID_PLUS_1", 40, 41), 40)
        self.assertEqual(ST.limit_price("ASK_MINUS_2", 40, 44), 42); self.assertIsNone(ST.limit_price("ASK_MINUS_5", 40, 5))

    def test_equal_exposure_fallback_equals_wait_when_nothing_fills(self):
        r = dict(limit=40, ask=44, bid=40, close_ask=45, close_bid=43, win=1, filled=0.0, filled_lo=0.0, filled_hi=0.0, fills=[])
        ev = ST.evaluate([r], 0.0175)
        self.assertAlmostEqual(ev["v_mark_fb"][0], ev["v_mark_wait"][0]); self.assertEqual(ev["v_mark_nb"][0], 0.0)

    def test_full_fill_saves_close_ask_minus_limit_less_fee_difference(self):
        r = dict(limit=40, ask=44, bid=40, close_ask=45, close_bid=43, win=1, filled=10.0, filled_lo=10.0, filled_hi=10.0, fills=[(40, 10.0, "AT_LEVEL")])
        ev = ST.evaluate([r], 0.0175)
        exp = (45 - 40) - (100 * FE.order_fee(40, 10, 0.0175) - 100 * FE.order_fee(45, 10, 0.07)) / 10
        self.assertAlmostEqual(ev["v_mark_fb"][0] - ev["v_mark_wait"][0], exp)
        # payoff cancels at equal exposure: mark- and settlement-based differences are identical
        self.assertAlmostEqual(ev["v_settle_fb"][0] - ev["v_settle_wait"][0], ev["v_mark_fb"][0] - ev["v_mark_wait"][0])

    def test_bounds_use_filled_lo_hi(self):
        r = dict(limit=40, ask=44, bid=40, close_ask=45, close_bid=43, win=1, filled=0.0, filled_lo=0.0, filled_hi=10.0, fills=[])
        lo, hi = ST.evaluate([r], 0.0175, which="lo"), ST.evaluate([r], 0.0175, which="hi")
        self.assertGreater(hi["v_mark_fb"][0], lo["v_mark_fb"][0])


class NoOrderCapability(unittest.TestCase):
    def test_sift_exec_has_no_client_or_order_call(self):
        root = os.path.join(os.path.dirname(__file__), "..", "sift_exec")
        for fn in os.listdir(root):
            if fn.endswith(".py"):
                with open(os.path.join(root, fn)) as fh:
                    src = fh.read().lower()
                for bad in ("requests", "urllib", "create_order", "place_order", "api_key", "private_key", "http.client"):
                    self.assertNotIn(bad, src, fn)


if __name__ == "__main__":
    unittest.main()

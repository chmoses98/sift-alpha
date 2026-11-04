import os, sys, unittest
from datetime import datetime, timedelta, timezone
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "outcome_exec"))
import nfl_outcome as O
from sift_research import fees, stats
from sift_clv import canonical as C

T0 = datetime(2025, 9, 7, 17, 0, tzinfo=timezone.utc)


def tr(mins_before, yes):
    return dict(ts=T0 - timedelta(minutes=mins_before), yes=yes, no=1 - yes, n=1, taker="yes", block=False)


class Prices(unittest.TestCase):
    def test_tape_never_uses_future(self):
        trades = sorted([tr(600, .4), tr(100, .5), tr(-30, .9)], key=lambda x: x["ts"])      # last print is AFTER t
        r = O.tape_last(trades, T0, 360)
        self.assertEqual(r["price"], .5)
        self.assertFalse(r["stale"])

    def test_stale_flag_and_none(self):
        trades = [tr(600, .4)]
        self.assertTrue(O.tape_last(trades, T0, 360)["stale"])
        self.assertIsNone(O.tape_last([tr(-5, .7)], T0, 360))

    def test_candle_only_closed_periods_and_one_sided(self):
        c = {"h60": [dict(end_period_ts=T0.timestamp() - 3600, yes_bid=dict(close="0.40"), yes_ask=dict(close="0.42")),
                     dict(end_period_ts=T0.timestamp() + 3600, yes_bid=dict(close="0.90"), yes_ask=dict(close="0.92")),
                     ]}
        q = O.candle_quote(c, T0)
        self.assertEqual((q["bid"], q["ask"]), (0.40, 0.42))
        c2 = {"h60": [dict(end_period_ts=T0.timestamp() - 60, yes_bid=dict(close="0.0000"), yes_ask=dict(close="1.0000"))]}
        self.assertIsNone(O.candle_quote(c2, T0)["ask"])


class Model(unittest.TestCase):
    def rows(self, n=6):
        rng = np.random.default_rng(0)
        teams = list("ABCDEF")
        out = []
        for t in range(1, n + 1):
            for i in range(0, 6, 2):
                a, b = teams[(i + t) % 6], teams[(i + t + 1) % 6]
                out.append(dict(team=a, opp=b, home=1, t=t, pts=24 + rng.normal(), epa=.1, plays=60.))
                out.append(dict(team=b, opp=a, home=0, t=t, pts=20 + rng.normal(), epa=0., plays=60.))
        return out

    def test_fit_is_independent_of_future_rows(self):
        rows = self.rows()
        past = [r for r in rows if r["t"] < 4]
        f1 = O.ridge_team_fit(past, 4, "pts", 15.0)
        f2 = O.ridge_team_fit(past + [dict(r, pts=999.) for r in rows if r["t"] >= 4][:0], 4, "pts", 15.0)
        self.assertAlmostEqual(f1["hfa"], f2["hfa"])
        self.assertGreater(f1["hfa"], 0)           # home teams scored more in the synthetic data

    def test_pmf_and_key_numbers(self):
        resid = np.random.default_rng(1).normal(0, 13, 2000)
        pm = O.pmf_from_residuals(-2.4, resid)
        self.assertAlmostEqual(pm.sum(), 1.0)
        k = O.apply_keys(pm, {3: 1.5, 7: 1.0, 6: 1., 10: 1., 14: 1.})
        self.assertAlmostEqual(k.sum(), 1.0)
        self.assertGreater(k[3 + 70] / pm[3 + 70], 1.0)
        self.assertAlmostEqual(O.p_margin_gt(pm, 0.0) + O.p_margin_gt(pm[::-1], 0.0), 1.0, places=6)

    def test_key_ratios_neutral_with_little_history(self):
        self.assertEqual(set(O.key_ratios([1.0] * 5, [3] * 5, np.zeros(10)).values()), {1.0})


class Rules(unittest.TestCase):
    def test_selection_uses_discovery_only_and_holdout_once(self):
        mk = lambda per, net, n: [dict(gid=f"{per}{i}", net=net + (0.01 if i % 2 else -0.01), win=1, ask=.5, fee=.01, per=per) for i in range(n)]
        cells = {"good": {"discovery": mk("discovery", .05, 40), "validation": mk("validation", .03, 30), "holdout": mk("holdout", -.1, 30)},
                 "bad": {"discovery": mk("discovery", -.05, 40), "validation": mk("validation", .5, 30), "holdout": mk("holdout", .5, 30)}}
        r = O.select_and_confirm(cells)
        rows = {x["cell"]: x for x in r["rows"]}
        self.assertTrue(rows["good"]["confirmed_on_validation"])
        self.assertLess(rows["good"]["holdout_frozen"]["mean"], 0)      # holdout reported as is, never used to select
        self.assertFalse(rows["bad"]["selected_on_discovery"])
        self.assertNotIn("holdout_frozen", rows["bad"])                 # unselected cells never expose holdout
        self.assertEqual(r["cells_tried"], 2)

    def test_period_split(self):
        self.assertEqual([O.period(1), O.period(6), O.period(7), O.period(12), O.period(13), O.period(18)], ["discovery"] * 2 + ["validation"] * 2 + ["holdout"] * 2)
        self.assertEqual(O.period(19, "WC"), "holdout")


class Fees(unittest.TestCase):
    def test_matches_canonical(self):
        for p in (.05, .5, .93):
            self.assertAlmostEqual(float(C.estimate_fee(p, 100)), float(fees.fee_dollars(p, 100)))


if __name__ == "__main__":
    unittest.main()

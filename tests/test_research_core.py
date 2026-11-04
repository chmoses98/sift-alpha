import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
import numpy as np
from sift_clv import canonical as C
from sift_research import fees, stats, decision as D, shadow_orders as S

UTC = timezone.utc


class Fees(unittest.TestCase):
    def test_matches_canonical_estimator(self):
        for p in (0.01, 0.05, 0.33, 0.5, 0.9, 0.99):
            for n in (1, 7, 100):
                for role in ("taker", "maker"):
                    self.assertAlmostEqual(float(C.estimate_fee(p, n, role=role)), float(fees.fee_dollars(p, n, role)), places=9)

    def test_net_pnl_identity(self):
        self.assertAlmostEqual(float(fees.net_pnl_per_contract(0.5, 1)), 0.5 - 0.02, places=9)  # 0.07*.25=.0175 -> ceil 0.02


class Stats(unittest.TestCase):
    def test_cluster_bootstrap_covers_truth_and_is_deterministic(self):
        rng = np.random.default_rng(0)
        v = rng.normal(0.3, 1, 600); g = np.repeat(np.arange(150), 4)
        a = stats.cluster_bootstrap(v, g); b = stats.cluster_bootstrap(v, g)
        self.assertEqual(a, b)
        self.assertLess(a["lo"], 0.3 + 0.1); self.assertGreater(a["hi"], 0.3 - 0.1)
        self.assertLess(a["p"], 0.01)

    def test_null_not_significant(self):
        rng = np.random.default_rng(3)
        r = stats.cluster_bootstrap(rng.normal(0, 1, 400), np.repeat(np.arange(100), 4))
        self.assertGreater(r["p"], 0.05)

    def test_multiplicity(self):
        h = stats.holm([0.01, 0.04, 0.03]); q = stats.benjamini_hochberg([0.01, 0.04, 0.03])
        self.assertTrue(np.allclose(h, [0.03, 0.06, 0.06])); self.assertTrue(np.allclose(q, [0.03, 0.04, 0.04]))
        self.assertTrue(np.all(q <= h + 1e-12))

    def test_wilson(self):
        lo, hi = stats.wilson(50, 100); self.assertLess(lo, 0.5); self.assertGreater(hi, 0.5)


EP = D.ExecParams(fill_prob={0: 0.15, 1: 0.3, 2: 0.45}, fill_prob_lo={0: 0.05, 1: 0.12, 2: 0.2}, adverse_selection=0.02)


class Decision(unittest.TestCase):
    def test_pass_when_no_edge(self):
        r = D.decide(D.Opportunity(p=0.50, p_se=0.03, bid=0.50, ask=0.52, hours_to_kickoff=48), EP)
        self.assertEqual(r["recommended"], D.PASS); self.assertEqual(r["status"], "RESEARCH_ONLY")

    def test_buy_now_with_large_edge_and_fee_included(self):
        r = D.decide(D.Opportunity(p=0.75, p_se=0.03, bid=0.50, ask=0.52, hours_to_kickoff=48), EP)
        b = [x for x in r["ranked"] if x["action"] == D.BUY_NOW][0]
        self.assertAlmostEqual(b["ev"], 0.75 - 0.52 - float(fees.fee_per_contract(0.52)), places=9)

    def test_adverse_selection_lowers_limit_ev(self):
        o = D.Opportunity(p=0.65, p_se=0.02, bid=0.50, ask=0.52, hours_to_kickoff=48)
        clean = D.ExecParams(fill_prob=EP.fill_prob, fill_prob_lo=EP.fill_prob_lo, adverse_selection=0.0)
        ev = lambda ep: [x for x in D.decide(o, ep)["ranked"] if x["action"] == D.LIMIT and x["limit"] == 0.5][0]["ev"]
        self.assertLess(ev(EP), ev(clean))

    def test_uncertainty_gate_blocks_marginal_edge(self):
        o = lambda se: D.Opportunity(p=0.58, p_se=se, bid=0.50, ask=0.52, hours_to_kickoff=48)
        self.assertEqual(D.decide(o(0.10), EP)["recommended"], D.PASS)

    def test_module_has_no_order_capability(self):
        for mod in (D, S):
            self.assertEqual(mod.STATUS, "RESEARCH_ONLY")
            src = open(mod.__file__).read().lower()
            for bad in ("requests", "urllib", "create_order", "place_order", "kalshi.com"):
                self.assertNotIn(bad, src.replace("never sent to an exchange", ""))


class Shadow(unittest.TestCase):
    def _p(self, **k):
        ko = datetime(2026, 11, 8, 18, tzinfo=UTC)
        base = dict(ticker="T-1", side="YES", action="LIMIT", limit=0.5, placed_at=ko - timedelta(hours=48), kickoff=ko, bid=0.49,
                    ask=0.52, p=0.6, p_se=0.03, model_version="m1", horizon="48h")
        base.update(k); return S.placed(**base)

    def test_must_be_placed_before_kickoff_and_idempotent(self):
        ko = datetime(2026, 11, 8, 18, tzinfo=UTC)
        with self.assertRaises(ValueError): self._p(placed_at=ko)
        a, b = self._p(), self._p(); self.assertEqual(a["decision_id"], b["decision_id"])
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "l.jsonl"); self.assertTrue(S.append(f, a)); self.assertFalse(S.append(f, b))

    def test_no_lookahead_and_never_filled(self):
        p = self._p()
        with self.assertRaises(ValueError): S.observed(p, evidence="FILLED", observed_at=datetime(2026, 11, 8, tzinfo=UTC))
        with self.assertRaises(ValueError): S.observed(p, evidence="TAPE_TOUCH", observed_at=datetime(2026, 11, 1, tzinfo=UTC))

    def test_evaluate_bounds(self):
        p = self._p(); t = datetime(2026, 11, 7, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "l.jsonl")
            S.append(f, p); S.append(f, S.observed(p, evidence="TAPE_TOUCH", observed_at=t))
            S.append(f, S.observed(p, evidence="TAPE_FILL_BOUND_UP", observed_at=t)); S.append(f, S.settled(p, win=1, settled_at=t))
            r = S.evaluate(f)["by_action"]["LIMIT"]
            self.assertEqual((r["touched"], r["fill_up"], r["fill_lo"]), (1, 1, 0)); self.assertAlmostEqual(r["pnl_up_cents"], 50.0); self.assertEqual(r["pnl_lo_cents"], 0.0)


if __name__ == "__main__":
    unittest.main()

"""Acquisition plan: reconciliation with the catalog, distinct counting, no invented prices, determinism (RESEARCH_ONLY)."""
import json
import unittest

from alpha_engine.foundation import acquisition as A
from alpha_engine.foundation.contract import OPS


class AcquisitionPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.inputs = A.build()

    def test_committed_artifacts_are_current(self):
        committed = json.loads((OPS / "acquisition_plan.json").read_text())
        fresh = json.loads(json.dumps(A._clean(self.plan) if hasattr(A, "_clean") else self.plan, sort_keys=True))
        self.assertEqual(committed["totals"], json.loads(json.dumps(fresh["totals"])))
        self.assertEqual([s["dataset"] for s in committed["roadmap"]], [s["dataset"] for s in fresh["roadmap"]])

    def test_totals_reconcile_with_the_map(self):
        t = self.plan["totals"]
        self.assertEqual((t["inputs"], t["archetypes"], t["missing_primary_slots"]), (1649, 170, 884))   # Phase 7: nfl.pass_run_split_epa_both_sides (NFL:team_total) and nfl.rush_yardage_tail (NFL:game_events) close 2 slots  # derived NBA/CBB engine (PR #94): 886 -> 884
        self.assertEqual(sum(s["missing_primary_inputs"] for s in self.plan["sports"].values()), t["missing_primary_inputs"])
        self.assertEqual(sum(s["missing_primary_slots"] for s in self.plan["sports"].values()), t["missing_primary_slots"])
        self.assertLessEqual(t["complete_with_archives"], t["complete_after_free"])
        self.assertLessEqual(t["complete_after_free"], t["complete_after_low_cost"])
        self.assertLessEqual(t["complete_after_all_priced"], t["missing_primary_inputs"])

    def test_roadmap_counts_each_input_once(self):
        prev = self.plan["totals"]["complete_with_archives"]
        for s in self.plan["roadmap"]:
            self.assertEqual(s["cumulative_complete"], prev + s["newly_complete"])
            prev = s["cumulative_complete"]
        tiers = [s["tier"] for s in self.plan["roadmap"]]
        self.assertEqual(tiers, sorted(tiers, key=["FREE", "LOW_COST", "HIGHER_COST"].index))

    def test_no_invented_prices(self):
        for r in self.plan["shortlist"]:
            if r["tier"] in ("LOW_COST", "HIGHER_COST"):
                self.assertIsNotNone(r["cheapest_monthly_usd"], r["dataset"])
            if r["tier"] == "FREE":
                self.assertEqual(r["cheapest_monthly_usd"], 0.0)
        for p in self.plan["providers"]:
            st = p["price"]["status"]
            self.assertIn(st, ("VERIFIED", "ESTIMATE", "UNKNOWN", "UNKNOWN_ENTERPRISE"))
            if st in ("UNKNOWN", "UNKNOWN_ENTERPRISE"):
                self.assertIsNone(p["price"]["monthly_usd"]); self.assertIsNone(p["price"]["annual_usd"])
            if st == "VERIFIED":
                self.assertTrue(p["price"]["evidence"])

    def test_training_ready_requires_build_and_pit(self):
        for k, r in self.inputs["inputs"].items():
            if r["tr"]["state"] == "TRAINING_READY":
                c = r["tr"]["c"]
                self.assertTrue(all(c[x] == "OK" for x in ("data", "verified", "built", "pit", "history")), k)
        self.assertEqual(self.plan["totals"]["training_ready_inputs"], sum(1 for r in self.inputs["inputs"].values() if r["tr"]["state"] == "TRAINING_READY"))

    def test_input_needs_reference_known_datasets(self):
        ds = self.inputs["datasets"]
        for r in self.inputs["inputs"].values():
            for _, _, opts in r["n"]:
                for d in opts:
                    self.assertIn(d, ds)

    def test_readiness_is_not_availability(self):
        # held data alone never makes an input training-ready
        r = A.readiness({"chain": ["OK", "OK", "OK", "MISSING", "MISSING", "MISSING", "MISSING", "MISSING"], "pit": "PIT_SAFE"},
                        {"TEAM_BOX": {"x"}}, {"x"}, {"x": {"history": {"first": "2015", "last": "2025"}}})
        self.assertEqual(r["state"], "DATA_HELD_NOT_BUILT")


if __name__ == "__main__":
    unittest.main()

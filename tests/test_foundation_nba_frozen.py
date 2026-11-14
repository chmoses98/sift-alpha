"""Tests for the frozen-incumbent NBA evaluation and challenger alpha-nba-avail-0.2 (RESEARCH_ONLY).

Pure helpers and the committed evaluation.json are always tested. The end-to-end re-run (byte-identical output) needs the
owner's nba-edge-finder clone with the pinned projection-data / main / data-injury-pit commits under $SIFT_REPOS_DIR and is
skipped cleanly when they are absent (CI has no clones).
"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import contract as C
from alpha_engine.foundation import nba_frozen as F

EVAL = F.OUT_DIR / "evaluation.json"
SUMM = F.OUT_DIR / "predictions_summary.json"


class PureHelpers(unittest.TestCase):
    def test_cond_pmf_array_offsets_folds_and_normalises(self):
        p = F.cond_pmf_array([0.2, 0.3, 0.5], lo=2, K=3)
        self.assertEqual(p.shape, (4,))
        np.testing.assert_allclose(p, [0, 0, 0.2, 0.8])
        q = F.cond_pmf_array([1.0, 1.0], lo=0, K=5)
        self.assertAlmostEqual(q.sum(), 1.0)

    def test_ladder_lookup(self):
        lad = {10.0: 0.7, 15.0: 0.4}
        self.assertEqual(F.ladder_sf(lad, 10), 0.7)
        self.assertIsNone(F.ladder_sf(lad, 12))
        self.assertIsNone(F.ladder_sf(None, 10))

    def test_pit_status_uses_only_rows_at_or_before_cutoff_and_most_severe_tie(self):
        av = pd.DataFrame(dict(game_id=["g"] * 4, entity_id=["a", "a", "b", "b"], team=["X"] * 4,
                               status=["questionable", "out", "probable", "out"], eff_ts=[100, 300, 200, 200], report=[""] * 4))
        st = F.pit_status(av, {"g": 250}).set_index("entity_id").status
        self.assertEqual(st["a"], "questionable")          # the OUT published at 300 is after the cutoff
        self.assertEqual(st["b"], "out")                   # same-time tie resolves to the most severe status
        self.assertEqual(len(F.pit_status(av, {"g": 50})), 0)

    def test_status_at_and_unlisting(self):
        rep = {("d", "T"): [(100, {"a": "questionable"}), (200, {"b": "out"})]}
        self.assertEqual(F.status_at(rep, "d", "T", "a", 50), "no_report")
        self.assertEqual(F.status_at(rep, "d", "T", "a", 150), "questionable")
        self.assertEqual(F.status_at(rep, "d", "T", "a", 250), "not_listed")

    def test_pool_and_recalibration(self):
        a = np.array([[0.5, 0.5, 0.0]]); b = np.array([[0.0, 0.5, 0.5]])
        np.testing.assert_allclose(F.pool_pmf(a, b, 0.7).sum(1), [1.0])
        np.testing.assert_allclose(F.pool_pmf(a, b, 1.0), a)
        p = np.array([0.1, 0.5, 0.9])
        np.testing.assert_allclose(F.recal_logit(p, 0.0, 1.0), p, atol=1e-9)
        self.assertTrue(np.all(np.abs(F.recal_logit(p, 0.0, 0.5) - 0.5) <= np.abs(p - 0.5) + 1e-12))

    def test_ece_and_crps(self):
        self.assertAlmostEqual(F.ece([0.5, 0.5], [0, 1]), 0.0)
        self.assertAlmostEqual(F.ece([0.9, 0.9], [0, 0]), 0.9)
        pm = np.array([[0.0, 1.0, 0.0]])
        self.assertAlmostEqual(float(F._crps_dense(pm, np.array([1]))[0]), 0.0)
        self.assertAlmostEqual(float(F._crps_dense(pm, np.array([2]))[0]), C.crps_pmf(pm[0], 2))

    def test_market_median_interpolates_bracketed_ladders_only(self):
        P = pd.DataFrame(dict(game_id=["g"] * 3 + ["h"], player_id=["p"] * 3 + ["q"], stat=["points"] * 4, k=[10, 15, 20, 10],
                              quote_class=["TWO_SIDED"] * 4, yes_bid=[0.79, 0.49, 0.19, 0.2], yes_ask=[0.81, 0.51, 0.21, 0.22]))
        med = F.market_median(P)
        self.assertAlmostEqual(med[("g", "p", "points")], 14.5)
        self.assertNotIn(("h", "q", "points"), med)        # never crosses 0.5 -> not bracketed

    def test_normal_sf(self):
        self.assertAlmostEqual(float(F.normal_sf(0.0, 0.0, 1.0)), 0.5)
        self.assertLess(float(F.normal_sf(3.0, 0.0, 1.0)), 0.01)

    def test_cohort_masks_are_disjoint_and_after_train(self):
        d = pd.Series(["2026-10-25", "2026-11-01", "2026-11-07", "2026-11-08", "2026-11-13"])
        m = F.cohort_masks(d)
        self.assertEqual(m[F.COH1].tolist(), [False, True, True, False, False])
        self.assertEqual(m[F.COH2].tolist(), [False, False, False, True, True])
        self.assertFalse(np.any(m[F.COH1] & m[F.COH2]))


class CommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid_and_identity(self):
        self.assertEqual(C.validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], "alpha-nba-avail-0.2")
        self.assertEqual(self.doc["status"], "RESEARCH_ONLY")
        self.assertEqual(self.doc["source_commits"][f"nba-edge-finder@{F.PD_BRANCH}"], F.PD_COMMIT)
        self.assertEqual(self.doc["source_commits"]["nba-edge-finder@main"], F.MAIN_COMMIT)

    def test_every_verdict_follows_the_preregistered_rule(self):
        heads = [r for r in self.doc["results"] if r["headline"]]
        self.assertEqual(len(heads), 16)
        np.testing.assert_allclose([r["p_holm"] for r in heads], C.holm([r["p_raw"] for r in heads]), atol=1e-6)
        for r in self.doc["results"]:
            self.assertGreaterEqual(r["p_holm"] + 1e-9, r["p_raw"])
            self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            if r["verdict"] == "VALIDATED_IMPROVEMENT":
                self.assertTrue(r["replicated"])
            self.assertLessEqual(r["ci95"][0], r["diff"] + 1e-6); self.assertGreaterEqual(r["ci95"][1], r["diff"] - 1e-6)

    def test_challenger_rows_are_test_only_and_references_are_frozen(self):
        for r in self.doc["results"]:
            if r["challenger_arm"].startswith(("C1", "C2")):
                self.assertIn(r["cohort"], (F.COH1, F.COH2, F.POOLED))
                self.assertIn(r["reference"], ("pf_frozen", "kalshi_t60_mid"))
        kinds = {d["dataset_id"]: d["kind"] for d in self.doc["data"]}
        self.assertNotIn("WALK_FORWARD_REPRODUCTION", kinds.values())
        self.assertEqual(kinds["pf_frozen_player_forecasts"], "PROSPECTIVE_CAPTURE")

    def test_overall_verdict_rule(self):
        v = self.doc["verdict"]
        pf = list(v["c2_vs_pf_frozen"].values()); mk = list(v["c2_vs_kalshi_t60_mid"].values())
        if v["overall"] == "VALIDATED_IMPROVEMENT":
            self.assertTrue(all(x == "VALIDATED_IMPROVEMENT" for x in pf + mk) and len(mk) == 4)
        elif v["overall"] == "IMPROVED_NOT_VALIDATED":
            self.assertIn("VALIDATED_IMPROVEMENT", pf); self.assertNotIn("NOT_IMPROVED", pf)
        self.assertTrue(v["retain_incumbent"])
        self.assertIn("INSUFFICIENT_EVIDENCE", v["evidence_sufficiency"]["challenger_vs_market"])

    def test_features_record_acceptance_and_rejection(self):
        f = {x["feature_id"]: x for x in self.doc["features"]}
        self.assertIn("REJECTED", f["f1_ladder_recalibration_market_listed_rungs"]["status"])
        for s, p in f["f2_linear_pool_pf_with_c1"]["fitted_parameters"].items():
            if not p["accepted"]:
                self.assertEqual(p["final_weight_on_pf"], 1.0)
        for c in self.doc["input_stage_claims"]:
            self.assertIn(c["stage"], C.STAGES); self.assertIn(c["outcome"], C.OUTCOMES)
            self.assertNotEqual(c["stage"], "VALIDATED_IMPROVEMENT")    # nothing here is validated against both references

    def test_leak_guards_passed(self):
        names = {c["name"]: c["passed"] for f in self.doc["features"] for c in f["checks"]}
        for n in ("leak_guard_forecast_generated_and_archived_le_tip_minus_60", "leak_guard_quote_board_le_tip_minus_60",
                  "leak_guard_status_effective_le_tip_minus_60", "leak_guard_box_features_strictly_earlier_dates"):
            self.assertTrue(names[n], n)

    def test_no_raw_rows_in_committed_outputs(self):
        for p in (EVAL, SUMM):
            txt = p.read_text()
            self.assertNotIn("espn:", txt)
            self.assertNotIn("player_name", txt)
            self.assertNotIn("KXNBAPTS-", txt)
            self.assertLess(len(txt), 400_000)


def _repo_ready():
    try:
        repo = F.repo_path()
        return repo.exists() and all(F.has_commit(repo, c) for c in (F.PD_COMMIT, F.MAIN_COMMIT, F.INJ_COMMIT))
    except Exception:
        return False


@unittest.skipUnless(_repo_ready(), "nba-edge-finder clone with pinned projection-data/main/data-injury-pit commits not available")
class Reproduction(unittest.TestCase):
    def test_rerun_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            S = F.run(out_dir=Path(d), verbose=False)
            Q = F.report(S)
            doc, summ = F.build_document(S, Q)
            C.write_json(Path(d) / "evaluation.json", doc); C.write_json(Path(d) / "predictions_summary.json", summ)
            self.assertEqual((Path(d) / "evaluation.json").read_bytes(), EVAL.read_bytes())
            self.assertEqual((Path(d) / "predictions_summary.json").read_bytes(), SUMM.read_bytes())


if __name__ == "__main__":
    unittest.main()

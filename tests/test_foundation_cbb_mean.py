"""CBB challenger alpha-cbb-mean-0.1: walk-forward isolation, ridge mechanics, coherent margin/total shifts, contract
probabilities and the committed evaluation. Synthetic fixtures run everywhere; the end-to-end re-run is skipped unless
the owner's clone and the extracted archives (including espn-lines-archive) are present (SIFT_CBB_ARCH_DIR)."""
import json
import os
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import cbb_mean as M
from alpha_engine.foundation import contract as C

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "CBB" / M.CHALLENGER_ID / "evaluation.json"
CONFS = ["Alpha", "Beta", "Gamma", "Delta"]
NET = {"Alpha": 4.0, "Beta": 1.0, "Gamma": -1.0, "Delta": -4.0}      # true conference net strength missing from the frozen means


def synth(n_days=6, per_day=60, seed=3, level=0.0, noise=8.0):
    rng = np.random.default_rng(seed); rows = []
    for d in range(n_days):
        for j in range(per_day):
            tip = pd.Timestamp("2026-11-03T23:00:00Z") + pd.Timedelta(days=d, minutes=3 * j)
            ch, ca = rng.choice(CONFS, 2, replace=False)
            th, ta = f"{ch[0]}{rng.integers(0, 6)}", f"{ca[0]}{rng.integers(0, 6)}"
            mu_h, mu_a = rng.normal(74, 5), rng.normal(70, 5)
            fh = mu_h + level + NET[ch] / 2 - NET[ca] / 2 + rng.normal(0, noise); fa = mu_a + level + NET[ca] / 2 - NET[ch] / 2 + rng.normal(0, noise)
            rows.append(dict(game_id=f"X{d}{j:03d}", tip=tip, obs_at=tip + pd.Timedelta(hours=8), slate=(tip - pd.Timedelta(hours=10)).strftime("%Y-%m-%d"),
                             conf_h=ch, conf_a=ca, home_tid=th, away_tid=ta, mu_h=mu_h, mu_a=mu_a, margin=mu_h - mu_a, total=mu_h + mu_a, msd=12.0, tsd=17.0,
                             fh=fh, fa=fa, y_m=fh - fa, y_t=fh + fa))
    return pd.DataFrame(rows)


class FitAndWalkForward(unittest.TestCase):
    def test_empty_training_is_the_no_change_prior(self):
        p = M.fit_arm(synth().iloc[:0], M.BLOCKS["CST"])
        self.assertEqual(p, M.empty_params())
        dh, da = M.team_shifts(synth(), p)
        self.assertFalse(dh.any() or da.any())

    def test_first_slate_unchanged_and_training_strictly_earlier(self):
        g = synth(); wf = M.walk_forward(g); days = sorted(wf)
        self.assertEqual(wf[days[0]]["_meta"]["n"], 0)
        inc = M.apply_arm(g, wf, "INC"); first = (g["slate"] == days[0]).to_numpy()
        for a in M.BLOCKS:
            x = M.apply_arm(g, wf, a)
            np.testing.assert_array_equal(x["m"][first], inc["m"][first]); np.testing.assert_array_equal(x["t"][first], inc["t"][first])
            np.testing.assert_array_equal(x["sm"], inc["sm"]); np.testing.assert_array_equal(x["st"], inc["st"])
        for d in days[1:]:
            self.assertLess(wf[d]["_meta"]["train_max_slate"], d)
            self.assertEqual(wf[d]["_meta"]["n"], int((g["slate"] < d).sum()))

    def test_future_outcomes_cannot_change_a_slate(self):
        g = synth(); d = sorted(g["slate"].unique())[3]
        g2 = g.copy(); late = g2["slate"] >= d; g2.loc[late, "fh"] += 40.0
        self.assertEqual(M.walk_forward(g)[d], M.walk_forward(g2)[d])

    def test_unarchived_final_is_excluded(self):
        g = synth(); days = sorted(g["slate"].unique())
        g.loc[g["slate"] == days[0], "obs_at"] = pd.Timestamp("2027-01-01T00:00:00Z")
        meta = M.walk_forward(g)[days[1]]["_meta"]
        self.assertEqual(meta["n"], 0); self.assertEqual(meta["n_not_yet_archived"], int((g["slate"] == days[0]).sum()))

    def test_recovers_conference_net_strength(self):
        p = M.fit_arm(synth(n_days=30, per_day=80), M.BLOCKS["C"])
        net = {c: p["conf_o"][c] - p["conf_d"][c] for c in CONFS}
        self.assertGreater(net["Alpha"] - net["Delta"], 5.5); self.assertLess(net["Alpha"] - net["Delta"], 9.5)
        self.assertGreater(net["Beta"], net["Gamma"])

    def test_level_reference_arm_recovers_a_scoring_level_and_leaves_margin_alone(self):
        g = synth(n_days=20, per_day=60, level=2.0)
        p = M.fit_arm(g, M.BLOCKS["LEVEL"])
        self.assertAlmostEqual(p["level"], 2.0, delta=0.5)
        dh, da = M.team_shifts(g, p)
        np.testing.assert_allclose(dh - da, 0.0, atol=1e-12)

    def test_slope_moves_margin_only(self):
        g = synth(); p = M.empty_params(); p["slope"] = 1.0
        dh, da = M.team_shifts(g, p)
        np.testing.assert_allclose(dh + da, 0.0, atol=1e-12)
        np.testing.assert_allclose(dh - da, g["margin"].to_numpy() / 10.0, atol=1e-12)

    def test_shifts_are_coherent_team_score_shifts(self):
        g = synth(); wf = M.walk_forward(g); x = M.apply_arm(g, wf, "CST"); d = sorted(wf)[-1]
        idx = (g["slate"] == d).to_numpy(); dh, da = M.team_shifts(g[idx], wf[d]["CST"])
        np.testing.assert_allclose(x["m"][idx], g.loc[idx, "margin"] + dh - da); np.testing.assert_allclose(x["t"][idx], g.loc[idx, "total"] + dh + da)

    def test_unseen_conference_and_missing_label_get_no_effect(self):
        g = synth(); p = M.fit_arm(g, M.BLOCKS["C"])
        new = g.iloc[:2].copy(); new["conf_h"] = ["Unseen", None]; new["conf_a"] = [None, "Unseen"]
        dh, da = M.team_shifts(new, p)
        np.testing.assert_allclose(dh, 0.0); np.testing.assert_allclose(da, 0.0)

    def test_conference_arm_beats_incumbent_on_synthetic_truth(self):
        g = synth(n_days=12, per_day=80); wf = M.walk_forward(g); c = M.apply_arm(g, wf, "C"); inc = M.apply_arm(g, wf, "INC")
        self.assertLess(np.abs(g["y_m"] - c["m"]).mean(), np.abs(g["y_m"] - inc["m"]).mean())

    def test_penalties_are_the_registered_constants(self):
        self.assertEqual(M.PEN, dict(level=60.0, conf=30.0, slope=30.0, team=50.0))
        self.assertEqual(M.ARMS, ["C", "CS", "CST"]); self.assertEqual(M.REF_ARMS, ["LEVEL", "STRETCH"])


class ContractProbabilities(unittest.TestCase):
    def test_winner_spread_total(self):
        rows = pd.DataFrame(dict(gi=[0] * 5, mtype=["WINNER", "WINNER", "MARGIN", "MARGIN", "TOTAL"], side=["home", "away", "home", "away", "none"], strike=[np.nan, np.nan, 4.5, -4.5, 150.5]))
        arr = dict(m=np.array([3.0]), sm=np.array([12.0]), t=np.array([148.0]), st=np.array([17.0]))
        p = M.contract_probs(rows, arr)
        self.assertAlmostEqual(p[0] + p[1], 1.0, places=12)
        self.assertAlmostEqual(p[2], float(1 - M.J.phi((4.5 - 3.0) / 12.0)), places=12)
        self.assertAlmostEqual(p[3], float(M.J.phi((4.5 - 3.0) / 12.0)), places=12)
        self.assertAlmostEqual(p[4], float(1 - M.J.phi((150.5 - 148.0) / 17.0)), places=12)

    def test_settlement(self):
        rows = pd.DataFrame(dict(gi=[0] * 5, mtype=["WINNER", "WINNER", "MARGIN", "MARGIN", "TOTAL"], side=["home", "away", "home", "away", "none"], strike=[np.nan, np.nan, 4.5, -4.5, 150.5]))
        g = pd.DataFrame(dict(y_m=[3.0], y_t=[151.0]))
        np.testing.assert_array_equal(M.settle(rows, g), [1.0, 0.0, 0.0, 1.0, 1.0])

    def test_tier_labels(self):
        self.assertEqual([M.tier("Big Ten Conference"), M.tier("Atlantic 10 Conference"), M.tier("Ivy League"), M.tier(None)], ["P", "M", "L", "L"])


class CommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid(self):
        self.assertEqual(C.validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], M.CHALLENGER_ID); self.assertEqual(self.doc["status"], "RESEARCH_ONLY")

    def test_every_check_has_a_basis_and_none_is_attested(self):
        checks = [c for f in self.doc["features"] for c in f["checks"]]
        self.assertGreater(len(checks), 20)
        for c in checks:
            self.assertEqual(c.get("basis"), "COMPUTED", c["name"]); self.assertIsInstance(c["passed"], bool)

    def test_every_verdict_follows_the_rule(self):
        hl = [r for r in self.doc["results"] if r["headline"]]
        self.assertGreater(len(hl), 0)
        for r, ph in zip(hl, C.holm([r["p_raw"] for r in hl])):
            self.assertAlmostEqual(r["p_holm"], ph, places=9)
        for r in self.doc["results"]:
            self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]))
            self.assertLessEqual(r["ci95"][0], r["ci95"][1])

    def test_wave_owned_reference_arms_are_never_headline(self):
        for r in self.doc["results"]:
            if r["arm"] in M.REF_ARMS + ["INC"]:
                self.assertFalse(r["headline"], r)
        self.assertTrue(all(k in self.doc["design"]["wave_separation"] for k in ("wave14", "wave15", "wave16", "untouched")))

    def test_no_raw_rows_or_identifiers(self):
        txt = EVAL.read_text()
        self.assertNotRegex(txt, r'"T\d{4}"'); self.assertNotRegex(txt, r'"G\d{6,}"'); self.assertNotIn("kalshi_ticker", txt)

    def test_overall_not_promoted_and_claims_wellformed(self):
        self.assertIn(self.doc["verdict"]["overall"], ("IMPROVED_NOT_VALIDATED", "INCONCLUSIVE", "NOT_IMPROVED"))
        for c in self.doc["input_stage_claims"]:
            self.assertTrue(c["input"].startswith("CBB:")); self.assertIn(c["stage"], ("CHALLENGER_INTEGRATED", "EVALUATED"))

    def test_point_in_time_checks_passed(self):
        names = {c["name"]: c["passed"] for f in self.doc["features"] for c in f["checks"]}
        for k in ("as_of_before_scheduled_tip_for_every_used_projection", "walk_forward_training_strictly_before_slate", "first_slate_is_the_incumbent_unchanged",
                  "final_first_observed_after_tip", "only_incumbent_records_read", "sample_ends_before_wave15_16_window", "espn_line_captured_before_tip",
                  "espn_line_oriented_by_team_id", "kalshi_quote_strictly_before_tip", "own_settlement_matches_kalshi_result", "kalshi_side_resolved_by_subject_team_id",
                  "standard_deviations_are_the_frozen_ones", "wave12_possession_table_finals_match_verified_finals", "checkpoint_tables_match_manifest_sha256"):
            self.assertTrue(names.get(k), k)

    def test_inputs_exist_in_the_catalog(self):
        cat = set(json.loads((EVAL.parents[2] / "pipeline_ledger.json").read_text())["inputs"])
        used = {c["input"] for c in self.doc["input_stage_claims"]} | {i for f in self.doc["features"] for i in f["catalog_inputs"]}
        self.assertEqual(sorted(used - cat), [])

    def test_cohorts_partition_the_sample(self):
        g = self.doc["games"]; self.assertEqual(g["cohort_1"] + g["cohort_2"], g["used"])
        r = next(r for r in self.doc["results"] if r["arm"] == "CST" and r["metric"] == "margin_nll" and r["cohort"] == "pooled" and r["reference"].startswith("incumbent"))
        self.assertEqual(r["n_clusters"], g["used"])


ARCH = os.environ.get("SIFT_CBB_ARCH_DIR")
REPO = C.repos_dir() / "cbb-edge-finder"


@unittest.skipUnless(ARCH and Path(ARCH, "projections-archive").is_dir() and Path(ARCH, M.ESPN_BRANCH).is_dir() and (REPO / M.CKPT / "finals.parquet").is_file(),
                     "owner archives / clone not present (CI): end-to-end re-run skipped")
class EndToEnd(unittest.TestCase):
    def test_rerun_is_byte_identical(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            M.run(Path(ARCH), REPO, Path(td))
            self.assertEqual(Path(td, "evaluation.json").read_bytes(), EVAL.read_bytes())


if __name__ == "__main__":
    unittest.main()

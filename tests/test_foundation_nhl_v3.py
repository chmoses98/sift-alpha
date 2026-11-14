"""NHL data-foundation slice alpha-nhl-joint-0.3: synthetic unit tests of the in-season / shot-xG / score-distribution helpers, a
contract check of the committed evaluation document (always runs, also in CI), and a data-digest check that only runs when the
owner's NHL clone is present under $SIFT_REPOS_DIR (skips cleanly otherwise). Set NHL_V3_FULL=1 to also re-run the full pipeline
and require a byte-identical evaluation.json (about 6 minutes; needs the pinned data-archive commit in the clone)."""
import json
import math
import os
import unittest
from pathlib import Path

import numpy as np

from alpha_engine.foundation import nhl_inseason as IS
from alpha_engine.foundation import nhl_joint as J
from alpha_engine.foundation import nhl_joint_v3 as M
from alpha_engine.foundation.contract import OUTCOMES, STAGES, VERDICTS, repos_dir, validate_evaluation, verdict_from

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "NHL" / M.CHALLENGER_ID / "evaluation.json"
CLONE = repos_dir() / "NHL-edge-finder" / "data" / "history"


class TestInSeasonHelpers(unittest.TestCase):
    def test_stamp_hours_both_formats(self):
        a = IS.stamp_hours("20261113T222323Z"); b = IS.stamp_hours("2026-11-13T22:23:23Z")
        self.assertAlmostEqual(a, b); self.assertAlmostEqual(IS.stamp_hours("20000101T010000Z"), 1.0)

    def test_first_available_keeps_earliest_capture_not_latest_revision(self):
        obs = [("k", "20261002T000000Z", {"v": 2}), ("k", "20261001T000000Z", {"v": 1}), ("j", "20261003T000000Z", {"v": 9})]
        out = IS.first_available(obs)
        self.assertEqual(out["k"], ("20261001T000000Z", {"v": 1})); self.assertEqual(out["j"][1]["v"], 9)

    def test_availability_masks(self):
        # team 1 plays days 10, 11, 13; team 2 plays days 10, 12. hours = day * 24 (+ offset)
        team = np.array([1, 2, 1, 2, 1]); day = np.array([10, 10, 11, 12, 13])
        freeze = day * 24.0 + 20.0
        avail = np.array([10 * 24 + 50.0,      # team 1 day-10 row captured at day 12 02:00: AFTER team 1's day-11 freeze -> state leak
                          10 * 24 + 30.0,      # team 2 day-10 row captured day 11 06:00: before team 2's day-12 freeze, before day-11 earliest freeze
                          11 * 24 + 30.0, 12 * 24 + 30.0, np.nan])
        so, lo = IS.availability_masks(team, day, avail, freeze)
        self.assertEqual(so.tolist(), [False, True, True, True, True])
        self.assertEqual(lo.tolist(), [False, True, True, True, True])   # row 0 is also late for the day-11 league mean
        # history rows (NaN stamps) are always usable
        so, lo = IS.availability_masks(team, day, np.full(5, np.nan), np.full(5, np.nan))
        self.assertTrue(so.all() and lo.all())

    def test_shot_geometry(self):
        d, a, miss = IS.shot_geometry([79.0, -79.0, 0.0, np.nan, 95.0], [0.0, 10.0, 0.0, 1.0, 5.0], ["O", "O", "N", "O", "O"])
        self.assertAlmostEqual(d[0], 10.0); self.assertAlmostEqual(a[0], 0.0)
        self.assertAlmostEqual(d[1], math.hypot(10, 10)); self.assertAlmostEqual(a[1], 45.0)
        self.assertAlmostEqual(d[2], 89.0); self.assertTrue(miss[3]); self.assertGreater(a[4], 90.0)   # behind the goal line

    def test_shot_xg_fit_recovers_distance_effect_and_blocks_carry_no_xg(self):
        rng = np.random.default_rng(3); n = 20000
        x = rng.uniform(30, 88, n); y = rng.uniform(-30, 30, n)
        dist = np.hypot(89 - x, y); p = 1 / (1 + np.exp(-(0.2 - 0.09 * dist)))
        goal = rng.random(n) < p
        kind = np.where(goal, "GOAL", np.where(rng.random(n) < 0.3, "BLOCK", "SOG")).astype(object)
        sh = {"kind": kind, "x": x, "y": y, "zone": np.full(n, "O", dtype=object), "shot_type": np.full(n, "wrist", dtype=object),
              "strength": np.full(n, "EV", dtype=object), "since_prev_s": np.full(n, np.nan)}
        m = IS.fit_shot_xg(sh, np.arange(n) < 15000)
        xg = IS.shot_xg(sh, m)
        self.assertTrue((xg[kind == "BLOCK"] == 0).all())
        hold = (np.arange(n) >= 15000) & (kind != "BLOCK")
        near, far = hold & (dist < 15), hold & (dist > 40)
        self.assertGreater(xg[near].mean(), 3 * xg[far].mean())
        self.assertAlmostEqual(xg[hold].sum() / goal[hold].sum(), 1.0, delta=0.12)

    def test_team_game_xg_aggregation(self):
        agg = IS.team_game_xg([7, 7, 7, 8], [1, 1, 0, 1], ["EV", "PP", "EV", "SH"], ["SOG", "GOAL", "BLOCK", "MISS"], [0.1, 0.3, 0.0, 0.05])
        self.assertAlmostEqual(agg[(7, 1)]["xf_all"], 0.4); self.assertAlmostEqual(agg[(7, 1)]["xf_pp"], 0.3)
        self.assertAlmostEqual(agg[(7, 1)]["hd_all"], 0.3); self.assertEqual(agg[(7, 1)]["goals_all"], 1.0)
        self.assertEqual(agg[(7, 0)]["att_all"], 1.0); self.assertAlmostEqual(agg[(8, 1)]["xf_sh"], 0.05)


class TestScoreDistribution(unittest.TestCase):
    def test_joint_pmf3_reduces_to_0_1_joint(self):
        lh = np.array([3.1, 2.4]); la = np.array([2.7, 3.3])
        a = M.joint_pmf3(lh, la, {"c3": 0.2, "theta_tie": 0.25, "theta_one_goal": -0.4, "delta": 0.01})
        b = J.joint_reg_pmf(lh, la, 0.2, 0.25, -0.4, 0.01)
        np.testing.assert_allclose(a, b, atol=1e-12); np.testing.assert_allclose(a.sum((1, 2)), 1.0)

    def test_two_goal_weight_and_kappa_move_the_right_mass(self):
        lh = np.array([3.4]); la = np.array([2.6]); k = J.K
        d = np.arange(k)[:, None] - np.arange(k)[None, :]
        base = M.joint_pmf3(lh, la, {})
        low2 = M.joint_pmf3(lh, la, {"theta_two_goal": -0.5})
        self.assertLess(low2[0][np.abs(d) == 2].sum(), base[0][np.abs(d) == 2].sum())
        self.assertGreater(low2[0][d > 0].sum() / low2[0][d != 0].sum(), 0.5)
        shr = M.joint_pmf3(lh, la, {"log_kappa": math.log(0.5)})
        self.assertLess(shr[0][d > 0].sum(), base[0][d > 0].sum())           # kappa < 1 pulls the favourite toward even
        even = M.joint_pmf3(lh, la, {"log_kappa": -50.0})
        self.assertAlmostEqual(even[0][d > 0].sum(), even[0][d < 0].sum(), places=9)
        tie_up = M.joint_pmf3(lh, la, {"tie_slope_mismatch": 2.0})
        self.assertGreater(tie_up[0][d == 0].sum(), base[0][d == 0].sum())

    def test_fit_joint3_recovers_two_goal_weight(self):
        rng = np.random.default_rng(5); n = 6000
        lh = rng.uniform(2.4, 3.6, n); la = rng.uniform(2.4, 3.6, n)
        P = M.joint_pmf3(lh, la, {"theta_two_goal": -0.6}).reshape(n, -1)
        idx = np.array([rng.choice(P.shape[1], p=p) for p in P]); rh, ra = idx // J.K, idx % J.K
        jp = M.fit_joint3(lh, la, rh, ra, ["theta_two_goal"])
        self.assertAlmostEqual(jp["theta_two_goal"], -0.6, delta=0.15)
        base = M.fit_joint3(lh, la, rh, ra, [])
        self.assertLess(jp["train_nll"], base["train_nll"])

    def test_overtime_home_intercept(self):
        self.assertAlmostEqual(float(M.ot_home_prob3([3.0], [3.0], 0.2, 0.03)[0]), 0.53)
        y = np.r_[np.ones(560), np.zeros(440)]; lam = np.full(1000, 3.0)
        k, h0, _ = M.fit_ot3(lam, lam, y, True)
        self.assertAlmostEqual(0.5 + h0, 0.56, delta=0.01)
        self.assertEqual(M.fit_ot3(lam, lam, y, False)[1], 0.0)

    def test_check_carries_basis(self):
        c = M.check("x", 1 == 1, "d")
        self.assertEqual(c["basis"], "COMPUTED"); self.assertEqual(M.check("y", True, "d", "ATTESTED")["basis"], "ATTESTED")
        with self.assertRaises(AssertionError):
            M.check("z", True, "d", "BY_CONSTRUCTION")

    def test_encompassing_identifies_the_informative_forecast(self):
        rng = np.random.default_rng(2); n = 4000
        z = rng.normal(0, 0.6, n); y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
        good = 1 / (1 + np.exp(-z)); noise = 1 / (1 + np.exp(-rng.normal(0, 0.6, n)))
        e = M.encompassing(noise, good, y, np.arange(n), n_boot=50)
        self.assertGreater(e["b_market"], 0.7); self.assertLess(abs(e["b_model"]), 0.3)


@unittest.skipUnless(EVAL.exists(), "evaluation.json not generated")
class TestCommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid(self):
        self.assertEqual(validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], "alpha-nhl-joint-0.3"); self.assertEqual(self.doc["status"], "RESEARCH_ONLY")

    def test_every_check_has_a_basis_and_none_is_attested(self):
        checks = [c for f in self.doc["features"] for c in f["checks"]] + self.doc["design"]["prospective_checks"] + self.doc["design"]["kalshi_checks"]
        self.assertGreater(len(checks), 25)
        for c in checks:
            self.assertIn(c.get("basis"), ("COMPUTED", "ATTESTED"), c["name"])
            self.assertEqual(c["basis"], "COMPUTED", c["name"])
            self.assertTrue(any(ch.isdigit() for ch in c["detail"]), c["name"] + ": a computed check states the number it computed")

    def test_verdicts_follow_rule(self):
        for r in self.doc["results"]:
            self.assertIn(r["verdict"], VERDICTS)
            self.assertEqual(r["verdict"], verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            if r["cohort"] == "2026" or r["reference"].startswith(("market", "prospective")):
                self.assertNotEqual(r["verdict"], "VALIDATED_IMPROVEMENT")  # single cohort can never replicate
        self.assertTrue(any(r.get("headline") for r in self.doc["results"]))
        self.assertTrue(self.doc["verdict"]["retain_incumbent"])

    def test_baselines_and_families_present(self):
        refs = {r["reference"] for r in self.doc["results"]}
        for ref in (M.REF_02, M.REF_01, M.REF_V1, M.REF_SIM2, M.REF_MKT, M.P_V1, M.P_V2, M.P_OA, M.P_02, M.P_MKT):
            self.assertIn(ref, refs)
        for ref in (M.REF_02, M.REF_V1, M.REF_SIM2):
            fams = {r["market_family"] for r in self.doc["results"] if r["reference"] == ref and r["cohort"] == "pooled"}
            self.assertEqual(fams, set(M.HEAD))

    def test_selection_is_validation_only_and_post_hoc_candidate_is_flagged(self):
        sel = self.doc["design"]["selection"]
        for s in sel["team"]:
            self.assertEqual(s["accepted"], s["val_deviance_with"] < s["val_deviance_base"])
        for s in sel["joint"]:
            self.assertEqual(s["accepted"], s["val_nll_with"] < s["val_nll_base"])
            self.assertEqual(s["post_hoc"], s["candidate"] in M.POST_HOC_CANDIDATES)
        self.assertIn("post_hoc_note", sel)
        self.assertLessEqual(sel["joint_combined"]["val_nll_combined"], sel["joint_combined"]["val_nll_base"])

    def test_inseason_coverage_is_recorded(self):
        cov = self.doc["inseason_2026_27_coverage"]
        self.assertEqual(cov["team_games"], 2 * cov["final_games"])
        self.assertLessEqual(cov["moneypuck_usable_for_team_state"], cov["moneypuck_team_games_archived"])
        self.assertLessEqual(cov["moneypuck_team_games_archived"], cov["team_games"])
        arms = {(r["market_family"], r["arm"]) for r in self.doc["prospective"]["in_season_vs_arms"]}
        self.assertIn(("regulation_score", "frozen_pre_season_ratings"), arms); self.assertIn(("moneyline", "own_shot_xg_in_season"), arms)

    def test_claims_valid_and_nothing_promoted(self):
        for c in self.doc["input_stage_claims"]:
            self.assertIn(c["stage"], STAGES); self.assertIn(c["outcome"], OUTCOMES); self.assertTrue(c["input"].startswith(("NHL:nhl.", "NHL:m.")))
            self.assertNotIn(c["stage"], ("VALIDATED_IMPROVEMENT", "PRODUCTION_APPROVED", "PRODUCTION_ACTIVE"))

    def test_market_is_reference_only(self):
        self.assertNotIn("market", " ".join(self.doc["design"]["fitted_parameters"]["team_names"]))
        self.assertTrue(self.doc["market_loss_diagnosis_2025"]["oracle_starter_model_minus_market"]["oracle_not_pit"])

    def test_no_raw_rows_or_personal_data(self):
        txt = EVAL.read_text()
        for bad in ('"player_name"', '"player_id"', '"ticker"', '"sweater"', '"shooter_id"', "dailyfaceoff_raw/dt="):
            self.assertFalse(bad in txt, bad)
        self.assertLess(len(txt), 2_000_000)


@unittest.skipUnless(CLONE.exists(), "owner NHL clone not present ($SIFT_REPOS_DIR/NHL-edge-finder)")
class TestAgainstClone(unittest.TestCase):
    def test_input_digests_match_committed(self):
        doc = json.loads(EVAL.read_text()); d = {x["dataset_id"]: x for x in doc["data"]}
        self.assertEqual(J.files_digest(sorted((CLONE / "nhl").glob("games_*.parquet"))), d["nhl_games"]["sha256_of_files"])
        self.assertEqual(J.files_digest(sorted(f for f in (CLONE / "players").glob("shots_*.parquet") if "2026" not in f.name)), d["nhl_shot_events"]["sha256_of_files"])

    @unittest.skipUnless(os.environ.get("NHL_V3_FULL") == "1", "full re-run only with NHL_V3_FULL=1 (about 6 minutes)")
    def test_full_rerun_byte_identical(self):
        before = EVAL.read_bytes(); M.run(log=lambda *_: None)
        self.assertEqual(EVAL.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

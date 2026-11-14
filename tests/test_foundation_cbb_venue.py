"""CBB challenger alpha-cbb-venue-prior-0.1: walk-forward isolation, arm mechanics, contract probabilities and the
committed evaluation. Synthetic fixtures run everywhere; the end-to-end re-run is skipped unless the owner's clone and
extracted archives are present (SIFT_CBB_ARCH_DIR)."""
import json
import os
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import cbb_venue_prior as M
from alpha_engine.foundation import contract as C

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "CBB" / M.CHALLENGER_ID / "evaluation.json"


def synth(n_days=6, per_day=40, seed=5, neutral_shift=-4.0, sd_scale=1.3):
    rng = np.random.default_rng(seed); rows = []
    for d in range(n_days):
        for j in range(per_day):
            tip = pd.Timestamp("2026-11-03T23:00:00Z") + pd.Timedelta(days=d, minutes=4 * j)
            neu = j % 5 == 0; m = rng.normal(3, 8); t = rng.normal(145, 8)
            ym = m + (neutral_shift if neu else 0.0) + rng.normal(0, 12 * sd_scale); yt = t + rng.normal(0, 17)
            rows.append(dict(game_id=f"G{d}{j:03d}", tip=tip, obs_at=tip + pd.Timedelta(hours=8), slate=(tip - pd.Timedelta(hours=10)).strftime("%Y-%m-%d"),
                             site="neutral" if neu else "home", margin=m, total=t, msd=12.0, tsd=17.0, y_m=ym, y_t=yt, hgs=d, ags=d,
                             net_h=rng.normal(0, 8), net_a=rng.normal(0, 8), ret_h=rng.uniform(.3, .7), ret_a=rng.uniform(.3, .7)))
    return pd.DataFrame(rows)


class FitAndWalkForward(unittest.TestCase):
    def test_empty_training_is_the_no_change_prior(self):
        p = M.fit_adjust(synth().iloc[:0])
        self.assertEqual((p["k_m"], p["k_t"], p["v_m"], p["b_prior"], p["b_ret"]), (1.0, 1.0, 0.0, 0.0, 0.0))

    def test_first_slate_unchanged_and_training_strictly_earlier(self):
        g = synth(); wf = M.walk_forward(g); days = sorted(wf)
        self.assertEqual(wf[days[0]]["n"], 0)
        inc = M.apply_arm(g, wf, "INC"); full = M.apply_arm(g, wf, "FULL"); first = (g["slate"] == days[0]).to_numpy()
        np.testing.assert_allclose(full["m"][first], inc["m"][first]); np.testing.assert_allclose(full["sm"][first], inc["sm"][first])
        for d in days[1:]:
            self.assertLess(wf[d]["train_max_slate"], d)
            self.assertEqual(wf[d]["n"], int((g["slate"] < d).sum()))

    def test_future_outcomes_cannot_change_a_slate(self):
        g = synth(); d = sorted(g["slate"].unique())[3]
        g2 = g.copy(); late = g2["slate"] >= d; g2.loc[late, "y_m"] += 50.0
        self.assertEqual(M.walk_forward(g)[d], M.walk_forward(g2)[d])

    def test_unarchived_final_is_excluded(self):
        g = synth(); days = sorted(g["slate"].unique())
        g.loc[g["slate"] == days[0], "obs_at"] = pd.Timestamp("2027-01-01T00:00:00Z")
        p = M.walk_forward(g)[days[1]]
        self.assertEqual(p["n"], 0); self.assertEqual(p["n_not_yet_archived"], int((g["slate"] == days[0]).sum()))

    def test_recovers_sd_inflation_and_neutral_offset(self):
        p = M.fit_adjust(synth(n_days=20, per_day=60))
        self.assertGreater(p["k_m"], 1.15); self.assertLess(p["v_m"], -1.0)
        self.assertAlmostEqual(M.fit_adjust(synth(n_days=20, per_day=60, sd_scale=1.0))["k_m"], 1.0, delta=0.06)

    def test_venue_offset_only_on_neutral_games(self):
        g = synth(); wf = M.walk_forward(g); v = M.apply_arm(g, wf, "V"); inc = M.apply_arm(g, wf, "INC")
        home = (g["site"] == "home").to_numpy()
        np.testing.assert_allclose(v["m"][home], inc["m"][home]); np.testing.assert_allclose(v["sm"], inc["sm"])

    def test_prior_and_roster_terms_fade_with_games_seen(self):
        g = synth(); x0 = M.features(g.assign(hgs=0, ags=0)); x30 = M.features(g.assign(hgs=30, ags=30))
        self.assertTrue((np.abs(x30) < np.abs(x0) * 0.01 + 1e-12).all())


class ContractProbabilities(unittest.TestCase):
    def test_home_away_complementary_and_winner_strike_zero(self):
        rows = pd.DataFrame(dict(gi=[0, 0, 0, 0], mtype=["WINNER", "WINNER", "MARGIN", "MARGIN"], side=["home", "away", "home", "away"], strike=[np.nan, np.nan, 4.5, -4.5]))
        arr = dict(m=np.array([3.0]), sm=np.array([12.0]))
        p = M.contract_probs(rows, arr)
        self.assertAlmostEqual(p[0] + p[1], 1.0, places=12)
        self.assertAlmostEqual(p[0], float(M.J.phi(3.0 / 12.0)), places=12)
        self.assertAlmostEqual(p[2], float(1 - M.J.phi((4.5 - 3.0) / 12.0)), places=12)

    def test_norm_nll_minimised_at_true_sd(self):
        rng = np.random.default_rng(1); y = rng.normal(0, 10, 20000)
        l = {s: M.norm_nll(y, 0.0, s).mean() for s in (8.0, 10.0, 12.0)}
        self.assertLess(l[10.0], l[8.0]); self.assertLess(l[10.0], l[12.0])


class CommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid(self):
        self.assertEqual(C.validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], M.CHALLENGER_ID); self.assertEqual(self.doc["status"], "RESEARCH_ONLY")

    def test_every_verdict_follows_the_rule(self):
        hl = [r for r in self.doc["results"] if r["headline"]]
        self.assertGreater(len(hl), 0)
        for r, ph in zip(hl, C.holm([r["p_raw"] for r in hl])):
            self.assertAlmostEqual(r["p_holm"], ph, places=9)
        for r in self.doc["results"]:
            self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]))
            self.assertLessEqual(r["ci95"][0], r["ci95"][1])

    def test_no_raw_rows_or_identifiers(self):
        txt = EVAL.read_text()
        self.assertNotRegex(txt, r'"T\d{4}"'); self.assertNotRegex(txt, r'"G\d{6,}"'); self.assertNotIn("kalshi_ticker", txt)

    def test_overall_not_promoted_and_claims_wellformed(self):
        self.assertIn(self.doc["verdict"]["overall"], C.VERDICTS)
        self.assertNotEqual(self.doc["verdict"]["overall"], "VALIDATED_IMPROVEMENT")
        for c in self.doc["input_stage_claims"]:
            self.assertTrue(c["input"].startswith("CBB:"))
            self.assertIn(c["stage"], ("CHALLENGER_INTEGRATED", "EVALUATED"))

    def test_point_in_time_checks_passed(self):
        names = {c["name"]: c["passed"] for f in self.doc["features"] for c in f["checks"]}
        for k in ("as_of_before_scheduled_tip_for_every_used_projection", "walk_forward_training_strictly_before_slate",
                  "extension_final_first_observed_after_tip_and_projection_before_tip", "frozen_margin_sd_equals_sigma_by_min_games_seen",
                  "checkpoint_tables_match_manifest_sha256", "own_settlement_matches_kalshi_result", "kalshi_side_resolved_by_subject_team_id"):
            self.assertTrue(names.get(k), k)


ARCH = os.environ.get("SIFT_CBB_ARCH_DIR")
REPO = C.repos_dir() / "cbb-edge-finder"


@unittest.skipUnless(ARCH and Path(ARCH, "projections-archive").is_dir() and (REPO / M.CKPT / "finals.parquet").is_file(),
                     "owner archives / clone not present (CI): end-to-end re-run skipped")
class EndToEnd(unittest.TestCase):
    def test_rerun_is_byte_identical(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            M.run(Path(ARCH), REPO, Path(td))
            self.assertEqual(Path(td, "evaluation.json").read_bytes(), EVAL.read_bytes())


if __name__ == "__main__":
    unittest.main()

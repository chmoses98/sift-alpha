"""NHL data-foundation slice alpha-nhl-joint-0.2: synthetic unit tests of the point-in-time goalie helpers, a contract check of
the committed evaluation document (always runs, also in CI), and a data-digest check that only runs when the owner's NHL clone
is present under $SIFT_REPOS_DIR (skips cleanly otherwise). Set NHL_V2_FULL=1 to also re-run the full pipeline and require a
byte-identical evaluation.json."""
import json
import math
import os
import unittest
from pathlib import Path

import numpy as np

from alpha_engine.foundation import nhl_goalie as NG
from alpha_engine.foundation import nhl_joint_v2 as V
from alpha_engine.foundation.contract import OUTCOMES, STAGES, VERDICTS, repos_dir, validate_evaluation, verdict_from

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "NHL" / V.CHALLENGER_ID / "evaluation.json"
CLONE = repos_dir() / "NHL-edge-finder" / "data" / "history"


class TestGoalieHelpers(unittest.TestCase):
    def test_league_ratio_strictly_earlier(self):
        day = np.array([1, 1, 2, 3]); num = np.array([10.0, 10.0, 1000.0, 5.0]); den = np.array([100.0, 100.0, 1.0, 50.0])
        r = NG.league_ratio_trailing(day, num, den, fallback=-1.0)
        self.assertEqual(r[0], -1.0)  # nothing earlier (den <= 50)
        self.assertAlmostEqual(r[2], 0.1)  # day-2 row sees only day 1, never itself
        self.assertAlmostEqual(r[3], 1020.0 / 201.0)

    def test_quality_state_decay_carry_and_lookup(self):
        player = np.array([7, 7, 7]); season = np.array([2021, 2021, 2022]); day = np.array([1, 5, 400])
        ga = np.array([3.0, 1.0, 9.0]); e = np.array([2.0, 2.0, 1.0]); toi = np.array([3600, 0, 3600])
        post = NG.goalie_quality_state(player, season, day, ga, e, toi, hl=1.0, carry=0.5)
        np.testing.assert_allclose(post[0], [3.0, 2.0]); np.testing.assert_allclose(post[1], [3.0, 2.0])  # toi 0: no update
        np.testing.assert_allclose(post[2], [3.0 * 0.5 * 0.5 + 9.0, 2.0 * 0.5 * 0.5 + 1.0])
        look = NG.QualityLookup(player, season, day, post, carry=0.5, prior=10.0)
        self.assertEqual(look.q(7, 1, 2021), 0.0)  # same-day row is never visible
        self.assertAlmostEqual(look.q(7, 6, 2021), math.log(13.0 / 12.0))
        self.assertAlmostEqual(look.q(7, 300, 2022), math.log((1.5 + 10) / (1.0 + 10)))  # season discount on lookup
        self.assertEqual(look.q(99, 6, 2021), 0.0)

    def test_starter_candidates_point_in_time(self):
        starts = {1: [(1, 2021, 10), (2, 2021, 10), (3, 2021, 11), (10, 2021, 12)]}
        out = NG.starter_candidates([("a", 1, 4, 2021), ("b", 1, 10, 2021)], starts)
        pl, X = out[0]
        self.assertEqual(pl, [11, 10])  # goalie 12 starts on day 10: invisible on day 4
        f = dict(zip(NG.CAND_FEATS, X[0])); self.assertAlmostEqual(f["share10"], 1 / 3); self.assertEqual(f["last1"], 1.0)
        self.assertEqual(f["g_b2b"], 1.0); self.assertAlmostEqual(f["log_days"], math.log1p(1))  # started day 3, game day 4
        self.assertNotIn(12, out[1][0])  # strictly earlier days only, even on the start day itself

    def test_conditional_logit_recovers_direction(self):
        rng = np.random.default_rng(1); b_true = np.array([2.0, -1.5]); groups = []
        for _ in range(3000):
            X = rng.normal(size=(3, 2)); p = NG.starter_probs(X, b_true); groups.append((X, int(rng.choice(3, p=p))))
        b = NG.fit_conditional_logit(groups)
        np.testing.assert_allclose(b, b_true, atol=0.2)
        self.assertLess(NG.starter_nll(groups, b), NG.starter_nll(groups, np.zeros(2)))

    def test_expected_goals_uses_xg_else_shots(self):
        day = np.arange(1, 9); ga = np.full(8, 3.0); sa = np.full(8, 30.0); xga = np.array([3.0] * 6 + [np.nan, np.nan]); toi = np.full(8, 3600)
        e, kx, ks = NG.expected_goals(day, ga, sa, xga, toi)
        self.assertTrue(np.all(np.isfinite(e))); self.assertAlmostEqual(e[0], 3.0)  # fallback ratio 1.0 before data
        self.assertAlmostEqual(e[7], 30.0 * ks[7])

    def test_auc_and_freeze_and_outcomes(self):
        self.assertAlmostEqual(V.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75)
        rows = [{"ticker": "T", "minutes_to_start": "75", "predicted_at_utc": "2026-10-01T10:00:00Z"},
                {"ticker": "T", "minutes_to_start": "61", "predicted_at_utc": "2026-10-01T10:14:00Z"},
                {"ticker": "T", "minutes_to_start": "20", "predicted_at_utc": "2026-10-01T10:55:00Z"}]
        self.assertEqual(V.freeze_rows(rows, "ticker")["T"]["minutes_to_start"], "61")
        res = {"home_final": "3", "away_final": "2", "home_team_id": "6", "last_period_type": "OT"}
        self.assertEqual(V.market_outcome("game_winner", 6, 0, res), 1); self.assertEqual(V.market_outcome("game_winner", 8, 0, res), 0)
        self.assertEqual(V.market_outcome("game_spread", 6, 1.5, res), 0); self.assertEqual(V.market_outcome("game_total", None, 4.5, res), 1)
        self.assertEqual(V.market_outcome("team_total", 8, 1.5, res), 1); self.assertEqual(V.market_outcome("game_overtime", None, None, res), 1)


@unittest.skipUnless(EVAL.exists(), "evaluation.json not generated")
class TestCommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid(self):
        self.assertEqual(validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], "alpha-nhl-joint-0.2"); self.assertEqual(self.doc["status"], "RESEARCH_ONLY")

    def test_verdicts_follow_rule(self):
        for r in self.doc["results"]:
            self.assertIn(r["verdict"], VERDICTS)
            self.assertEqual(r["verdict"], verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            if r["cohort"] == "2026" or r["reference"].startswith(("market", "prospective")):
                self.assertNotEqual(r["verdict"], "VALIDATED_IMPROVEMENT")  # single cohort can never replicate
        self.assertTrue(any(r.get("headline") for r in self.doc["results"]))
        self.assertTrue(self.doc["verdict"]["retain_incumbent"])

    def test_baselines_present(self):
        refs = {r["reference"] for r in self.doc["results"]}
        for ref in (V.REF_01, V.REF_V1, V.REF_SIM2, V.REF_MKT):
            self.assertIn(ref, refs)
        if self.doc["prospective"].get("status") == "EVALUATED":
            for ref in (V.P_V1, V.P_V2, V.P_MKT):
                self.assertIn(ref, refs)

    def test_oracle_flagged_and_claims_valid(self):
        orc = [a for a in self.doc["ablations"] if a["ablation_id"].startswith("i_")]
        self.assertEqual(len(orc), 1); self.assertTrue(orc[0]["oracle_not_pit"])
        for c in self.doc["input_stage_claims"]:
            self.assertIn(c["stage"], STAGES); self.assertIn(c["outcome"], OUTCOMES); self.assertTrue(c["input"].startswith(("NHL:nhl.", "NHL:m.")))
        self.assertNotIn(self.doc["input_stage_claims"][0]["stage"], ("VALIDATED_IMPROVEMENT", "PRODUCTION_APPROVED", "PRODUCTION_ACTIVE"))

    def test_no_raw_rows_or_personal_data(self):
        txt = EVAL.read_text()
        for bad in ('"player_name"', '"player_id"', '"ticker"', '"sweater"', "dailyfaceoff_raw"):
            self.assertFalse(bad in txt, bad)
        self.assertLess(len(txt), 2_000_000)


@unittest.skipUnless(CLONE.exists(), "owner NHL clone not present ($SIFT_REPOS_DIR/NHL-edge-finder)")
class TestAgainstClone(unittest.TestCase):
    def test_input_digests_match_committed(self):
        from alpha_engine.foundation import nhl_joint as J
        doc = json.loads(EVAL.read_text()); d = {x["dataset_id"]: x for x in doc["data"]}
        self.assertEqual(J.files_digest(sorted((CLONE / "nhl").glob("games_*.parquet"))), d["nhl_games"]["sha256_of_files"])
        self.assertEqual(J.files_digest(sorted((CLONE / "moneypuck").glob("shots_*.parquet"))), d["moneypuck_shots"]["sha256_of_files"])

    @unittest.skipUnless(os.environ.get("NHL_V2_FULL") == "1", "full re-run only with NHL_V2_FULL=1 (about 3 minutes)")
    def test_full_rerun_byte_identical(self):
        before = EVAL.read_bytes(); V.run(log=lambda *_: None)
        self.assertEqual(EVAL.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

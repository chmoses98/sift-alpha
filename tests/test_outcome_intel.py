import os, sys, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "outcome_intel"))
import audit_cfb as A
import incremental as I


def synth(n_games=90, per=12, seed=1, informative=True):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for _ in range(per):
            true = rng.uniform(0.15, 0.85)
            y = int(rng.random() < true)
            mid = float(np.clip(true + rng.normal(0, 0.10), .03, .97))          # market: noisy view of truth
            q = float(np.clip(true + rng.normal(0, 0.03), .03, .97)) if informative else float(rng.uniform(.1, .9))
            rows.append(dict(game=f"g{g}", t=f"2026-09-{1 + g // 4:02d}T{g % 4:02d}:00", mid=mid, q=q, y=y))
    return rows


class TestSettlementRederivation(unittest.TestCase):
    def test_spread_total_moneyline(self):
        # away SAC 17 @ home EMU 28 ; event code is AWAY+HOME
        self.assertEqual(A.rederive("KXNCAAFGAME-26AUG29SACEMU-SAC", 17, 28), "no")
        self.assertEqual(A.rederive("KXNCAAFGAME-26AUG29SACEMU-EMU", 17, 28), "yes")
        self.assertEqual(A.rederive("KXNCAAFSPREAD-26AUG29SACEMU-SAC8", 17, 28), "no")     # SAC must win by >7.5
        self.assertEqual(A.rederive("KXNCAAFSPREAD-26AUG29SACEMU-EMU8", 17, 28), "yes")    # EMU wins by 11 > 7.5
        self.assertEqual(A.rederive("KXNCAAFSPREAD-26AUG29SACEMU-EMU11", 17, 28), "yes")   # 11 > 10.5
        self.assertEqual(A.rederive("KXNCAAFSPREAD-26AUG29SACEMU-EMU12", 17, 28), "no")
        self.assertEqual(A.rederive("KXNCAAFTOTAL-26AUG29SACEMU-45", 17, 28), "yes")       # 45 > 44.5
        self.assertEqual(A.rederive("KXNCAAFTOTAL-26AUG29SACEMU-46", 17, 28), "no")

    def test_unparseable_and_missing_score_are_unknown(self):
        self.assertIsNone(A.rederive("GARBAGE", 1, 2))
        self.assertIsNone(A.rederive("KXNCAAFGAME-26AUG29SACEMU-SAC", None, 28))
        self.assertIsNone(A.side_of("ABAB", "AB"))                                          # ambiguous prefix+suffix

    def test_fee_lots(self):
        self.assertAlmostEqual(A.fee(0.5, 1), 0.02)
        self.assertAlmostEqual(A.fee(0.5, 100), 0.0175)


class TestIncremental(unittest.TestCase):
    def test_split_is_chronological_and_disjoint(self):
        rows = synth()
        tr, te = I.split_games(rows)
        self.assertFalse(tr & te)
        first = {}
        for r in rows:
            first[r["game"]] = min(first.get(r["game"], r["t"]), r["t"])
        self.assertLessEqual(max(first[g] for g in tr), min(first[g] for g in te))

    def test_positive_control_detects_real_information(self):
        res = I.incremental_test(synth(informative=True))
        self.assertEqual(res["status"], "OK")
        self.assertGreater(res["gain_vs_calibrated_market_logloss"]["lo"], 0)

    def test_noise_challenger_is_not_validated(self):
        res = I.incremental_test(synth(informative=False))
        self.assertLessEqual(res["gain_vs_calibrated_market_logloss"]["mean"], 0.002)

    def test_negative_control_shuffled_challenger_has_no_gain(self):
        res = I.negative_control(synth(informative=True))
        self.assertLess(res["gain_vs_calibrated_market_logloss"]["lo"], 0.001)

    def test_holdout_labels_never_used_in_fit(self):
        rows = synth()
        _, te = I.split_games(rows)
        flipped = [dict(r, y=1 - r["y"]) if r["game"] in te else r for r in rows]
        a, b = I.incremental_test(rows), I.incremental_test(flipped)
        self.assertEqual(a["coef_challenger"], b["coef_challenger"])

    def test_underpowered_is_reported_not_guessed(self):
        self.assertEqual(I.incremental_test(synth(n_games=5))["status"], "UNDERPOWERED")

    def test_holm_monotone_and_bounded(self):
        adj = I.holm([0.01, 0.04, 0.03])
        self.assertTrue(all(0 <= x <= 1 for x in adj))
        self.assertAlmostEqual(adj[0], 0.03)

    def test_logistic_recovers_coefficients(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=20000)
        y = (rng.random(20000) < I.sigmoid(0.3 + 1.2 * x)).astype(float)
        w = I.fit_logistic(np.column_stack([np.ones_like(x), x]), y, ridge=1e-3)
        self.assertAlmostEqual(w[0], 0.3, delta=0.08)
        self.assertAlmostEqual(w[1], 1.2, delta=0.08)


if __name__ == "__main__":
    unittest.main()

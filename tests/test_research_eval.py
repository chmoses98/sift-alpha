import random, unittest
from alpha_engine.research_eval import asof_join, brier, log_loss, calibration_bins, compare_to_market, feature_screen


class AsOf(unittest.TestCase):
    def test_never_uses_future_observation_and_reports_gaps(self):
        dec = [{"id": 1, "entity": "A", "decision_at": "2026-01-01T12:00:00Z"}, {"id": 2, "entity": "B", "decision_at": "2026-01-01T12:00:00Z"},
               {"id": 3, "entity": "C", "decision_at": "2026-01-01T12:00:00Z"}]
        obs = [{"entity": "A", "observed_at": "2026-01-01T11:00:00Z", "value": 1}, {"entity": "A", "observed_at": "2026-01-01T12:00:01Z", "value": 99},
               {"entity": "B", "observed_at": "2025-12-30T00:00:00Z", "value": 5}]
        out, rep = asof_join(dec, obs, max_age_minutes=24 * 60)
        self.assertEqual([r["feature"] for r in out], [1, None, None])
        self.assertEqual([r["status"] for r in out], ["OK", "STALE", "MISSING"])
        self.assertEqual(rep["coverage"], round(1 / 3, 4))

    def test_observation_exactly_at_decision_time_is_allowed_but_not_after(self):
        out, _ = asof_join([{"id": 1, "entity": "A", "decision_at": "2026-01-01T12:00:00Z"}], [{"entity": "A", "observed_at": "2026-01-01T12:00:00Z", "value": 7}])
        self.assertEqual(out[0]["feature"], 7)

    def test_naive_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            asof_join([{"id": 1, "entity": "A", "decision_at": "2026-01-01T12:00:00"}], [])


class Scores(unittest.TestCase):
    def test_scores(self):
        self.assertAlmostEqual(brier([1.0, 0.0], [1, 0]), 0)
        self.assertAlmostEqual(brier([0.5, 0.5], [1, 0]), 0.25)
        self.assertGreater(log_loss([0.9], [0]), log_loss([0.1], [0]))
        b = calibration_bins([0.05, 0.95, 1.0], [0, 1, 1])
        self.assertEqual(sum(r["n"] for r in b), 3)

    def test_group_bootstrap_does_not_call_noise_a_win(self):
        rng = random.Random(1)
        y, m, mod, g = [], [], [], []
        for ev in range(60):
            for _ in range(5):                 # 5 correlated rows per event
                p = rng.random(); y.append(1 if rng.random() < p else 0); m.append(p); mod.append(min(max(p + rng.uniform(-.05, .05), 0.01), 0.99)); g.append(ev)
        r = compare_to_market(mod, m, y, g, boot=300)
        self.assertEqual(r["n_groups"], 60)
        self.assertIn(r["verdict"], {"INCONCLUSIVE", "EXPLORATORY_MARKET_BETTER"})

    def test_real_edge_is_detected_as_exploratory_only(self):
        rng = random.Random(2)
        y, m, mod, g = [], [], [], []
        for ev in range(200):
            true = rng.random(); out = 1 if rng.random() < true else 0
            y.append(out); g.append(ev); mod.append(true); m.append(0.5)
        r = compare_to_market(mod, m, y, g, boot=300)
        self.assertEqual(r["verdict"], "EXPLORATORY_MODEL_BETTER")
        self.assertIn("not a validation", r["note"])


class Screen(unittest.TestCase):
    def test_insufficient_groups_is_not_a_finding(self):
        self.assertEqual(feature_screen([1, 2], [1, 2], ["a", "b"])["verdict"], "INSUFFICIENT_GROUPS")

    def test_never_returns_predictive(self):
        rng = random.Random(3); x = [rng.random() for _ in range(300)]; y = [v + rng.random() * .1 for v in x]; g = [i // 3 for i in range(300)]
        r = feature_screen(x, y, g, boot=200)
        self.assertEqual(r["verdict"], "EXPLORATORY_ASSOCIATION")
        self.assertIn("no causal", r["note"])


if __name__ == "__main__":
    unittest.main()

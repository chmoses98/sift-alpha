"""Unit tests for the pure helpers of alpha-nba-rate-0.4 (no repository data needed)."""
import unittest

import numpy as np

from alpha_engine.foundation import nba_rate_v4 as V


class WalkforwardSlope(unittest.TestCase):
    def test_uses_strictly_earlier_dates_and_min_rows(self):
        rng = np.random.default_rng(0)
        dates = np.repeat(np.array(["2026-10-20", "2026-10-21", "2026-10-22"]), 400)
        x = rng.normal(size=1200); z = -0.3 * x + rng.normal(scale=0.01, size=1200)
        s = V.walkforward_slope(dates, x, z, np.ones(1200, bool))
        self.assertTrue(np.all(s[:400] == 0.0))                     # nothing earlier than the first date
        self.assertAlmostEqual(float(s[400]), -0.3, places=2)
        z2 = z.copy(); z2[800:] = 99.0 * x[800:]                     # a later date's values never move an earlier slope
        s2 = V.walkforward_slope(dates, x, z2, np.ones(1200, bool))
        np.testing.assert_allclose(s2[:800], s[:800])

    def test_too_few_rows_gives_zero(self):
        d = np.array(["a"] * 10 + ["b"] * 10)
        self.assertTrue(np.all(V.walkforward_slope(d, np.arange(20.0), np.arange(20.0), np.ones(20, bool)) == 0))


class PoissonOffsetSlope(unittest.TestCase):
    def test_recovers_slope(self):
        rng = np.random.default_rng(1)
        x = rng.normal(scale=0.3, size=20000); off = np.log(np.full(20000, 8.0))
        y = rng.poisson(np.exp(off + 0.25 * x))
        self.assertAlmostEqual(V.poisson_offset_slope(y, off, x), 0.25, places=1)


class SimplexGrid(unittest.TestCase):
    def test_weights_valid(self):
        g = V.simplex_grid(0.1)
        self.assertEqual(len(g), 66)
        self.assertTrue(all(a >= 0 and b >= 0 and a + b <= 1.0 + 1e-9 for a, b in g))
        self.assertIn((0.0, 0.0), g)


if __name__ == "__main__":
    unittest.main()

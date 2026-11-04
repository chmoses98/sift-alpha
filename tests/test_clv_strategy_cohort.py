import unittest
from decimal import Decimal as D
from sift_clv import strategy_cohort as S

O = S.StratOutcome


def dec(game, t, fair, base_price, strat=None):
    d = {S.BASELINE: O(D(1), D(1), D(base_price), D("0.017"))}
    d.update(strat or {})
    return S.Decision(game, t, D(fair), d)


class CohortTests(unittest.TestCase):
    def test_unfilled_order_is_charged_the_baselines_forgone_value_not_zero(self):
        # fair 0.55, taker buys at 0.50 + fee .017 => baseline value +0.033. Resting order never fills.
        d = dec("g", 1, "0.55", "0.50", {"REST_AT_BID": O(D(0), D(0), D("0.48"), D("0.004"))})
        rows, ex = S.paired_deltas([d], "REST_AT_BID", "lo")
        self.assertAlmostEqual(rows[0][1], -3.3, places=3)          # forgone edge, in cents
        self.assertEqual(ex, 0)

    def test_filled_resting_order_gains_price_improvement_but_pays_its_own_fee(self):
        d = dec("g", 1, "0.55", "0.50", {"REST_AT_BID": O(D(1), D(1), D("0.48"), D("0.004"))})
        rows, _ = S.paired_deltas([d], "REST_AT_BID", "up")
        self.assertAlmostEqual(rows[0][1], (0.55 - 0.48 - 0.004 - (0.55 - 0.50 - 0.017)) * 100, places=3)

    def test_uncertain_is_excluded_and_counted_never_imputed(self):
        d = dec("g", 1, "0.55", "0.50", {"REST_AT_BID": O(None, D(1), D("0.48"))})
        rows, ex = S.paired_deltas([d], "REST_AT_BID", "lo")
        self.assertEqual((rows, ex), ([], 1))

    def test_fallback_buys_the_remainder_so_exposure_is_not_lost(self):
        d = dec("g", 1, "0.55", "0.50", {"MAKER_THEN_TAKER_FALLBACK": O(D("0.5"), D("0.5"), D("0.48"), D("0.004"), D("0.52"), D("0.017"))})
        self.assertEqual(S.missed_exposure_share([d], "MAKER_THEN_TAKER_FALLBACK"), 0.0)
        self.assertEqual(S.missed_exposure_share([dec("g", 1, "0.55", "0.50", {"REST_AT_BID": O(D(0), D(0), D("0.48"))})], "REST_AT_BID"), 1.0)

    def test_optimistic_bound_can_never_promote_a_strategy(self):
        cohort = []
        for i in range(40):                                # lower bound unfilled (loses), upper bound always fills at a better price
            cohort.append(dec(f"g{i}", i, "0.55", "0.50", {"REST_AT_BID": O(D(0), D(1), D("0.45"), D("0.004"))}))
        r = S.compare(cohort, strategies=["REST_AT_BID"])["strategies"]["REST_AT_BID"]
        self.assertGreater(r["up"]["pooled"]["mean_delta_cents_vs_baseline"], 0)
        self.assertLess(r["lo"]["pooled"]["mean_delta_cents_vs_baseline"], 0)
        self.assertEqual(r["verdict"], "NOT_DEMONSTRATED")

    def test_oos_verdict_requires_both_halves_above_zero_on_the_conservative_bound(self):
        good = [dec(f"g{i}", i, "0.55", "0.50", {"INSIDE_SPREAD": O(D(1), D(1), D("0.47"), D("0.004"))}) for i in range(0, 30)]
        # jitter so the interval is non-degenerate but positive
        for i, d in enumerate(good):
            good[i] = S.Decision(d.game, d.placed_at_epoch, d.fair + D(i % 3) / D(1000), d.outcomes)
        r = S.compare(good, strategies=["INSIDE_SPREAD"])["strategies"]["INSIDE_SPREAD"]
        self.assertEqual(r["verdict"], "HOLDS_OOS")
        bad_second = good[:15] + [dec(f"h{i}", 100 + i, "0.55", "0.50", {"INSIDE_SPREAD": O(D(0), D(0), D("0.47"))}) for i in range(15)]
        r2 = S.compare(bad_second, strategies=["INSIDE_SPREAD"])["strategies"]["INSIDE_SPREAD"]
        self.assertEqual(r2["verdict"], "NOT_DEMONSTRATED")

    def test_clusters_are_games_not_rows(self):
        rows = [("g1", 1.0, 0)] * 50 + [("g2", -1.0, 0)] * 50
        ci = S._cluster_ci(rows)
        self.assertIsNotNone(ci)
        self.assertIsNone(S._cluster_ci([("only", 1.0, 0)] * 100))      # one game cannot give an interval, however many rows


if __name__ == "__main__":
    unittest.main()

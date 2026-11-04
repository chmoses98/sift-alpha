import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dm

from sift_clv import canonical as C, historical as H

START = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


def obs(i, game, price, fee, contracts=100, gross=None, net_rec=None, close=("0.49", "0.51"), eligible=True):
    t = f"KXNFLSPREAD-G{game}-{i}"
    stake = Dm(price) * contracts + Dm(fee)
    return H.Obs(str(i), t, "YES", Dm(contracts), Dm(price), Dm(fee), stake, game, "spread", START,
                 C.Quote.of(t, *close, START - timedelta(minutes=2)) if close else None, eligible,
                 None if gross is None else Dm(gross), None if net_rec is None else Dm(net_rec))


class Historical(unittest.TestCase):
    def test_flat_market_fee_inclusive_basis_not_counted_as_movement(self):
        s = H.summarize([obs(1, "A", "0.50", "1.75"), obs(2, "B", "0.50", "1.75")])
        self.assertEqual(s["actual_execution_clv"]["mean"], 0.0)
        self.assertAlmostEqual(s["fee_adjusted_difference"]["mean"], -0.0175)
        self.assertEqual(s["fee_adjustment_count_max"], 1)

    def test_unverifiable_counted_not_dropped_silently(self):
        s = H.summarize([obs(1, "A", "0.50", "1", close=None), obs(2, "B", "0.50", "1", eligible=False),
                         obs(3, "C", "0.50", "1")])
        self.assertEqual(s["verified_clv_observations"], 1)
        self.assertEqual(s["unverifiable_by_reason"][C.NO_CLOSE], 1)
        self.assertEqual(s["unverifiable_by_reason"]["NOT_A_PREGAME_ENTRY"], 1)

    def test_net_counts_entry_fee_once_and_detects_v1_double_count(self):
        o = obs(1, "A", "0.40", "1.68", gross="0", net_rec="-41.68")   # stake 41.68; v1 net = 0 - 41.68 - 1.68
        o.net_recorded = Dm("-43.36")
        s = H.summarize([o])
        self.assertEqual(H.net_once(o), Dm("-41.68"))
        self.assertAlmostEqual(s["economics"]["recorded_minus_once"], -1.68)

    def test_identity_flags_fee_inclusive_price(self):
        o = obs(1, "A", "0.50", "1.75")
        o.price = (o.stake) / o.contracts      # someone stored the UI cost basis as the price
        self.assertEqual(H.money_identity(o), "STAKE_NE_PRICE_X_QTY_PLUS_FEES")
        self.assertEqual(H.summarize([o])["unverifiable_by_reason"][C.FILL_PRICE_FEE_INCLUSIVE], 1)

    def test_game_cluster_bootstrap_uses_games(self):
        r = H.cluster_bootstrap_mean({"A": [0.01, 0.01, 0.01], "B": [-0.01], "C": [0.0]}, reps=200)
        self.assertEqual(r["clusters"], 3)


if __name__ == "__main__":
    unittest.main()

import os, sys, unittest
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "outcome_intel"))
import audit_nfl as N
import status as S

G = dict(id="2025_01_DAL_PHI", away="DAL", home="PHI", ap=20, hp=24, day="2025-09-04", season=2025, week=1, type="REG",
         ko=datetime(2025, 9, 5, 0, 20, tzinfo=timezone.utc))


class TestNflDerivation(unittest.TestCase):
    def test_moneyline_spread_total_team_total(self):
        self.assertEqual(N.derive("KXNFLGAME", "KXNFLGAME-25SEP04DALPHI-PHI", None, G), "yes")
        self.assertEqual(N.derive("KXNFLGAME", "KXNFLGAME-25SEP04DALPHI-DAL", None, G), "no")
        self.assertEqual(N.derive("KXNFLSPREAD", "KXNFLSPREAD-25SEP04DALPHI-PHI3", 3.5, G), "yes")    # wins by 4 > 3.5
        self.assertEqual(N.derive("KXNFLSPREAD", "KXNFLSPREAD-25SEP04DALPHI-PHI4", 4.5, G), "no")
        self.assertEqual(N.derive("KXNFLTOTAL", "KXNFLTOTAL-25SEP04DALPHI-44", 43.5, G), "yes")       # 44 > 43.5
        self.assertEqual(N.derive("KXNFLTOTAL", "KXNFLTOTAL-25SEP04DALPHI-45", 44.5, G), "no")
        self.assertEqual(N.derive("KXNFLTEAMTOTAL", "KXNFLTEAMTOTAL-25SEP04DALPHI-DAL20", 20.5, G), "no")

    def test_tie_and_unknown_never_guessed(self):
        tie = dict(G, ap=20, hp=20)
        self.assertEqual(N.derive("KXNFLGAME", "KXNFLGAME-25SEP04DALPHI-PHI", None, tie), "tie")
        self.assertIsNone(N.derive("KXNFLSPREAD", "KXNFLSPREAD-25SEP04DALPHI-NYG3", 3.5, G))
        self.assertIsNone(N.derive("KXNFLPASSYDS", "KXNFLPASSYDS-25SEP04DALPHI-X", 200, G))

    def test_event_resolution_alias_and_date_rollover(self):
        gidx = {("2025-09-04", "DAL", "PHI"): G, ("2025-09-07", "JAX", "CAR"): dict(G, id="b")}
        teams = {"DAL", "PHI", "JAX", "CAR"}
        self.assertIs(N.resolve("KXNFLGAME-25SEP05DALPHI", gidx, teams), G)           # kalshi date is UTC next day
        self.assertEqual(N.resolve("KXNFLGAME-25SEP07JACCAR", gidx, teams)["id"], "b")  # JAC -> JAX alias
        self.assertIsNone(N.resolve("KXNFLGAME-25SEP20DALPHI", gidx, teams))

    def test_fee_100_lot(self):
        self.assertAlmostEqual(N.fee(0.5), 0.0175)


class TestStatus(unittest.TestCase):
    def cell(self, mean, lo, hi, games=60):
        return dict(status="OK", holdout_games=games, gain_vs_calibrated_market_logloss=dict(mean=mean, lo=lo, hi=hi))

    def test_all_branches(self):
        self.assertEqual(S.classify(self.cell(.02, .01, .03), 0.01, dict(mean=0, lo=-.001, hi=.001)), "VALIDATED_IMPROVEMENT")
        self.assertEqual(S.classify(self.cell(.02, .01, .03), 0.2, None), "PROMISING_INSUFFICIENT")
        self.assertEqual(S.classify(self.cell(0, -.004, .004), None, None), "NO_DEMONSTRATED_IMPROVEMENT")
        self.assertEqual(S.classify(self.cell(0, -.03, .03), None, None), "INCONCLUSIVE_UNDERPOWERED")
        self.assertEqual(S.classify(self.cell(.02, .01, .03, games=10), 0.001, None), "INCONCLUSIVE_UNDERPOWERED")
        self.assertEqual(S.classify(dict(status="UNDERPOWERED"), None, None), "INCONCLUSIVE_UNDERPOWERED")
        self.assertEqual(S.classify(None, None, None), "MISSING_DATA")

    def test_dirty_negative_control_blocks_validation(self):
        self.assertEqual(S.classify(self.cell(.02, .01, .03), 0.01, dict(mean=.02, lo=.01, hi=.03)), "PROMISING_INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()

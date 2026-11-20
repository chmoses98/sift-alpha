"""Regression tests for the CFB forward validation (research/cfb_forward_validation). Offline: no vault, no network."""
import gzip, hashlib, json, math, sys, unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FV = ROOT / "research" / "cfb_forward_validation"
sys.path.insert(0, str(FV))
import contracts_multi as CM  # noqa: E402

KEY = "26NOV07WKUMTU"  # WKU (away) at MTU (home)


class Parsing(unittest.TestCase):
    def test_sides_strikes_and_families(self):
        c = CM.parse(f"KXNCAAFSPREAD-{KEY}-MTU4", 3.5); self.assertEqual((c.family, c.side, c.strike), ("FG_spread", "home", 3.5))
        c = CM.parse(f"KXNCAAF1HTEAMTOTAL-{KEY}-WKU11", 10.5); self.assertEqual((c.family, c.side, c.strike, CM.quantity(c)), ("1H_team_total", "away", 10.5, "away_pts"))
        c = CM.parse(f"KXNCAAF1QTOTAL-{KEY}-11", 10.5); self.assertEqual((c.family, c.side, c.strike), ("1Q_total", None, 10.5))
        self.assertEqual(CM.parse(f"KXNCAAF1H-{KEY}-TIE", None).side, "tie")
        self.assertIsNone(CM.parse(f"KXNCAAFGAME-{KEY}-TIE", None))  # full game cannot tie
        self.assertIsNone(CM.parse(f"KXNCAAFSPREAD-{KEY}-MTU4", 4.5))  # ticker suffix and official floor_strike disagree -> dropped
        self.assertIsNone(CM.parse("KXNCAAFSPREAD-26SEP19AAAA-AA7", 6.5))  # undecidable side -> dropped, never guessed
        self.assertIsNone(CM.parse(f"KXNCAAF2QTOTAL-{KEY}-11", 10.5))  # unscored series

    def test_settlement_rules(self):
        s = lambda t, fs, h, a: CM.settle(CM.parse(t, fs), h, a)
        self.assertTrue(s(f"KXNCAAFSPREAD-{KEY}-MTU4", 3.5, 24, 20)); self.assertFalse(s(f"KXNCAAFSPREAD-{KEY}-MTU4", 3.5, 23, 20))
        self.assertTrue(s(f"KXNCAAFSPREAD-{KEY}-WKU4", 3.5, 20, 24)); self.assertFalse(s(f"KXNCAAFSPREAD-{KEY}-WKU4", 3.5, 24, 20))
        self.assertTrue(s(f"KXNCAAF1H-{KEY}-TIE", None, 7, 7)); self.assertFalse(s(f"KXNCAAF1H-{KEY}-MTU", None, 7, 7)); self.assertFalse(s(f"KXNCAAF1H-{KEY}-WKU", None, 7, 7))
        self.assertTrue(s(f"KXNCAAFTOTAL-{KEY}-45", 44.5, 24, 21)); self.assertFalse(s(f"KXNCAAFTOTAL-{KEY}-46", 45.5, 24, 21))
        self.assertTrue(s(f"KXNCAAFTEAMTOTAL-{KEY}-WKU21", 20.5, 30, 21)); self.assertFalse(s(f"KXNCAAFTEAMTOTAL-{KEY}-MTU31", 30.5, 30, 21))


class Probabilities(unittest.TestCase):
    def test_full_game_winner_pair_sums_to_one(self):
        for emp in (None, np.linspace(-30, 30, 201)):
            for mu in (-9.0, 0.0, 3.5, 17.0):
                h = CM.yes_prob(CM.parse(f"KXNCAAFGAME-{KEY}-MTU", None), mu, 16.0, emp); a = CM.yes_prob(CM.parse(f"KXNCAAFGAME-{KEY}-WKU", None), mu, 16.0, emp)
                self.assertAlmostEqual(h + a, 1.0, places=9)

    def test_period_winner_home_away_tie_sum_to_one(self):
        cs = [CM.parse(f"KXNCAAF1H-{KEY}-{t}", None) for t in ("MTU", "WKU", "TIE")]
        for emp in (None, np.round(np.linspace(-20, 20, 201))):
            p = [CM.yes_prob(c, 2.0, 11.0, emp) for c in cs]; self.assertAlmostEqual(sum(p), 1.0, places=9); self.assertGreater(p[2], 0)

    def test_ladders_are_monotonic_and_mirror(self):
        for fam, tail in (("KXNCAAFSPREAD", "MTU"), ("KXNCAAFSPREAD", "WKU"), ("KXNCAAF1HTEAMTOTAL", "WKU")):
            ps = [CM.yes_prob(CM.parse(f"{fam}-{KEY}-{tail}{n}", n - 0.5), 6.0 if "SPREAD" in fam else 14.0, 12.0) for n in range(1, 40)]
            self.assertTrue(all(x >= y for x, y in zip(ps, ps[1:])), fam + tail)
        ps = [CM.yes_prob(CM.parse(f"KXNCAAFTOTAL-{KEY}-{n}", n - 0.5), 50.0, 15.0) for n in range(20, 80)]; self.assertTrue(all(x >= y for x, y in zip(ps, ps[1:])))
        # P(home covers -k) = P(away does not cover +k... ) mirror: home by > 3.5 at mu equals away by > 3.5 at -mu
        h = CM.yes_prob(CM.parse(f"KXNCAAFSPREAD-{KEY}-MTU4", 3.5), 7.0, 16.0); a = CM.yes_prob(CM.parse(f"KXNCAAFSPREAD-{KEY}-WKU4", 3.5), -7.0, 16.0); self.assertAlmostEqual(h, a)
        rq = np.linspace(-25, 35, 201)  # skewed residuals: the away side must use the flipped distribution
        h = CM.yes_prob(CM.parse(f"KXNCAAFSPREAD-{KEY}-MTU4", 3.5), 7.0, 0, rq); a = CM.yes_prob(CM.parse(f"KXNCAAFSPREAD-{KEY}-WKU4", 3.5), -7.0, 0, -rq); self.assertAlmostEqual(h, a)

    def test_normal_values(self):
        self.assertAlmostEqual(CM.yes_prob(CM.parse(f"KXNCAAFTOTAL-{KEY}-50", 49.5), 49.5, 15.0), 0.5)
        self.assertAlmostEqual(CM.yes_prob(CM.parse(f"KXNCAAFSPREAD-{KEY}-MTU4", 3.5), 3.5 + 16.0, 16.0), 0.5 * (1 + math.erf(1 / math.sqrt(2))))


class Fees(unittest.TestCase):
    def test_per_order_rounding_depends_on_quantity(self):
        self.assertEqual(CM.fee_per_order(0.5, 1), 0.02); self.assertEqual(CM.fee_per_order(0.5, 10), 0.18); self.assertEqual(CM.fee_per_order(0.5, 100), 1.75)
        self.assertEqual(CM.fee_per_order(0.97, 1), 0.01); self.assertEqual(CM.fee_per_order(0.3, 10), 0.15)
        self.assertAlmostEqual(CM.fee_unrounded(0.5), 0.0175)
        for p in (0.03, 0.2, 0.5, 0.81):  # per-contract cost of rounding falls with size and never undercuts the formula
            per = [CM.fee_per_order(p, c) / c for c in (1, 10, 100)]; self.assertTrue(per[0] >= per[1] >= per[2] >= CM.fee_unrounded(p) - 1e-12)


class FrozenAndReport(unittest.TestCase):
    S = json.loads((FV / "frozen_specs.json").read_text())
    R = json.loads((FV / "forward_report.json").read_text())

    def test_specs_hash_and_scope(self):
        s = dict(self.S); h = s.pop("sha256"); self.assertEqual(hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest(), h)
        self.assertEqual(self.S["fit_seasons"], [2024, 2025]); self.assertEqual(self.S["last_2026_week_seen"], 5); self.assertEqual(self.R["frozen_specs_sha256"], h)
        self.assertEqual(self.S["market_recalibration_C"]["fit_weeks"], [1, 2, 3, 4, 5])

    def test_quotes_are_pre_kickoff_and_after_week_5(self):
        lead, n = [], 0
        with gzip.open(FV / "quotes_2026_wk6plus.jsonl.gz", "rt") as fh:
            for line in fh:
                q = json.loads(line); lead.append(q["lead_min"]); n += 1
                self.assertTrue(0 < q["yes_ask"] < 1 and 0 < q["no_ask"] < 1)
        self.assertGreaterEqual(min(lead), 15); self.assertLessEqual(max(lead), 1440); self.assertGreater(n, 50000)
        self.assertGreaterEqual(self.R["data_audit"]["quote_lead_minutes"]["min"], 15)

    def test_settlement_matches_official_and_matching_is_strict(self):
        a = self.R["data_audit"]; self.assertGreater(a["contracts_with_official_result"], 50000)
        self.assertLessEqual(a["official_disagree"], 5)  # one game where ESPN (51-42) and Kalshi (margin 3) disagree; the official result is used
        self.assertEqual(a["games_dropped_orientation_mismatch"], 0)
        import score_forward as SF
        self.assertNotEqual(SF.norm("Southern Illinois"), SF.norm("Northern Illinois")); self.assertGreaterEqual(SF.MATCH_MIN, 0.9)
        self.assertEqual(SF.norm("App State"), SF.norm("Appalachian St.")); self.assertEqual(SF.norm("Miami (FL)"), SF.norm("Miami"))

    def test_probability_integrity_on_real_ladders(self):
        for name, v in self.R["probability_integrity"].items():
            if name != "C_market_recal":  # C recalibrates each contract independently (documented)
                self.assertLess(v["fg_winner_max_abs_sum_minus_1"], 1e-9, name)

    def test_no_profit_claim(self):
        """Pins the forward conclusion: no frozen candidate is profitable on unseen weeks; the market beats every model on Brier."""
        self.assertEqual(self.R["label"], "RESEARCH_ONLY")
        for name, v in self.R["selection"].items():
            s = v["ALL"]
            if s["n"] >= 100:
                self.assertLess(s["net_roi"], 0, name); self.assertLess(s["net_roi_95ci_game_bootstrap"][0], 0, name)
        for fam, c in self.R["calibration"].items():
            for name in ("blend97_normal", "he_emp"):
                if name in c:
                    self.assertLess(c["market_mid"]["brier"], c[name]["brier"], (fam, name))


if __name__ == "__main__":
    unittest.main()

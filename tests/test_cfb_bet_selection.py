"""Regression tests for the CFB bet-selection study (research/cfb_bet_selection). No network, no vault: fixtures are real settled 2026 Kalshi contracts
(ticker, teams, final score, official floor_strike, official result) copied from the official-settlement archive."""
import json, math, sys, unittest
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "cfb_bet_selection")); sys.path.insert(0, str(ROOT))
import contracts as C
import evaluate as E
import audit_calibration as A

# (ticker, away, home, final_away, final_home, official floor_strike, official result)
SETTLED = [
    ("KXNCAAFGAME-26SEP12OREOKST-OKST", "Oregon", "Oklahoma State", 31, 39, None, "yes"),
    ("KXNCAAFGAME-26SEP12ALAUK-ALA", "Alabama", "Kentucky", 45, 17, None, "yes"),
    ("KXNCAAFGAME-26SEP12OREOKST-ORE", "Oregon", "Oklahoma State", 31, 39, None, "no"),
    ("KXNCAAFSPREAD-26SEP12ULMUAB-UAB5", "UL Monroe", "UAB", 20, 26, 4.5, "yes"),
    ("KXNCAAFSPREAD-26SEP12NDSUAFA-AFA7", "North Dakota State", "Air Force", 38, 32, 6.5, "no"),
    ("KXNCAAFSPREAD-26SEP12GASTKENN-GAST14", "Georgia State", "Kennesaw State", 31, 17, 13.5, "yes"),
    ("KXNCAAFSPREAD-26SEP12NDSUAFA-NDSU8", "North Dakota State", "Air Force", 38, 32, 7.5, "no"),
    ("KXNCAAFSPREAD-26SEP19DUQWSU-WSU55", "Duquesne", "Washington State", 7, 48, 54.5, "no"),
]
HOME_SIDE = {"OKST": True, "ALA": False, "ORE": False, "UAB": True, "AFA": True, "GAST": False, "NDSU": False, "WSU": True}


def qframe(rows):
    """rows: (side_home, thr, home_margin_pred, actual_home_margin, yes_ask, no_ask) -> frame shaped like evaluate.quotes output."""
    return pd.DataFrame([{"fam": "SPREAD", "game_id": i, "week": 2, "pg": 3, "side_home": s, "thr": t, "m": m, "mar": a, "yes_ask": y, "no_ask": n} for i, (s, t, m, a, y, n) in enumerate(rows)])


class Contracts(unittest.TestCase):
    def test_official_settlements(self):
        for tk, away, home, fa, fh, strike, result in SETTLED:
            p = C.parse_ticker(tk); sh = C.side_is_home(p["key"], p["abbr"])
            self.assertEqual(sh, HOME_SIDE[p["abbr"]], tk)
            if strike is not None: self.assertEqual(p["thr"], strike, tk)
            self.assertEqual(C.yes_wins(sh, fh, fa, p["thr"]), result == "yes", tk)

    def test_key_is_away_then_home(self):
        self.assertIs(C.side_is_home("26SEP19MSUND", "ND"), True); self.assertIs(C.side_is_home("26SEP19MSUND", "MSU"), False)
        self.assertIsNone(C.side_is_home("26SEP19AAAA", "AA"))  # undecidable -> dropped, never guessed

    def test_spread_is_strictly_greater_and_win_is_half_point(self):
        self.assertFalse(C.yes_wins(True, 27, 20, 7.5)); self.assertTrue(C.yes_wins(True, 28, 20, 7.5)); self.assertFalse(C.yes_wins(False, 28, 20, 1.5))
        self.assertTrue(C.yes_wins(True, 21, 20, -0.5)); self.assertFalse(C.yes_wins(True, 20, 21, -0.5)); self.assertTrue(C.yes_wins(False, 20, 21, -0.5))

    def test_probability_direction_and_symmetry(self):
        self.assertAlmostEqual(C.yes_prob(True, 7.5, 16, 7.5), 0.5); self.assertAlmostEqual(C.yes_prob(False, -7.5, 16, 7.5), 0.5)
        self.assertGreater(C.yes_prob(True, 10, 16, 3.5), 0.5); self.assertLess(C.yes_prob(False, 10, 16, 3.5), 0.25)
        self.assertAlmostEqual(C.yes_prob(True, 4, 16, -0.5) + C.yes_prob(False, 4, 16, -0.5), 1.0)  # WIN: the two team contracts are complements
        self.assertAlmostEqual(C.yes_prob(True, 0, 16, 16), 1 - 0.5 * (1 + math.erf(1 / math.sqrt(2))))

    def test_fee_and_pnl(self):
        self.assertAlmostEqual(C.fee(0.5), 0.0175); self.assertAlmostEqual(C.fee(0.3), 0.0147); self.assertAlmostEqual(C.fee(0.3, True), 0.02); self.assertAlmostEqual(C.fee(0.5, True), 0.02)
        self.assertAlmostEqual(C.pnl(True, 0.3, 0.0147), 0.6853); self.assertAlmostEqual(C.pnl(False, 0.3, 0.0147), -0.3147)


class EvaluateRule(unittest.TestCase):
    """evaluate.bets (PR #97, unchanged) must agree with the verified contract semantics."""

    def test_bets_match_contract_helpers(self):
        rows = [(True, 6.5, 14.0, 10, 0.40, 0.61), (False, 2.5, 14.0, -3, 0.30, 0.71), (True, 20.5, 3.0, 21, 0.20, 0.81), (False, 3.5, -9.0, 3, 0.45, 0.56)]
        b = E.bets(qframe(rows), "m", 16.0).set_index("game_id")
        for i, (s, t, m, a, y, n) in enumerate(rows):
            p = C.yes_prob(s, m, 16.0, t); ey, en = p - y - C.fee(y), 1 - p - n - C.fee(n); won_yes = (a if s else -a) > t
            if max(ey, en) < E.EDGE: self.assertNotIn(i, b.index); continue
            r = b.loc[i]; self.assertEqual(r.side, "YES" if ey >= en else "NO"); self.assertAlmostEqual(r.edge, max(ey, en)); self.assertEqual(bool(r.won), won_yes if r.side == "YES" else not won_yes)

    def test_win_probabilities_of_both_teams_sum_to_one(self):
        """Defect fixed in this PR: PR #97 used thr=-0.5 for both WIN sides, so the two probabilities summed to ~1.024."""
        q = pd.DataFrame([{"fam": "WIN", "game_id": 1, "week": 2, "pg": 3, "side_home": s, "thr": -0.5, "m": 4.0, "mar": 3, "yes_ask": 0.03, "no_ask": 0.99} for s in (True, False)])
        b = pd.concat([E.bets(q[q.side_home == s], "m", 16.0) for s in (True, False)]); self.assertAlmostEqual(float(b[b.side == "YES"].prob.sum()), 1.0)
        np.testing.assert_allclose(A.p_yes(q, q.m, 16.0).sum(), 1.0)

    def test_away_contract_uses_negated_home_margin(self):
        b = E.bets(qframe([(False, 6.5, -20.0, -7, 0.50, 0.51)]), "m", 16.0)  # away favoured by 20, wins by exactly 7 -> YES > 6.5 wins
        self.assertEqual((b.side.iloc[0], bool(b.won.iloc[0])), ("YES", True))

    def test_one_bet_per_game_family_and_summary_math(self):
        q = pd.concat([qframe([(True, t, 14.0, 10, a, 1.01 - a)]) for t, a in ((3.5, 0.5), (6.5, 0.4), (9.5, 0.3))]); b = E.bets(q, "m", 16.0)
        self.assertEqual(len(b), 1); s = E.summ(b); a = float(b.ask.iloc[0]); self.assertAlmostEqual(s["net_pnl_contracts"], round(C.pnl(bool(b.won.iloc[0]), a, C.fee(a)), 3))

    def test_audit_select_reproduces_evaluate_bets(self):
        q = qframe([(True, 6.5, 14.0, 10, 0.40, 0.61), (False, 2.5, 14.0, -3, 0.30, 0.71), (True, 20.5, 3.0, 21, 0.20, 0.81)])
        q["ticker"] = "T"; q["mid"] = (q.yes_ask + 1 - q.no_ask) / 2; q["y"] = (np.where(q.side_home, q.mar, -q.mar) > q.thr).astype(float)
        s = A.select(q, A.p_yes(q, q.m, 16.0)); b = E.bets(q, "m", 16.0)
        self.assertEqual(list(s.side), list(b.side)); np.testing.assert_allclose(s.edge, b.edge); self.assertEqual(list(s.won), list(b.won))
        t = A.summ(s); self.assertAlmostEqual(t["pnl_at_mid_no_fee"] - t["half_spread_cost"] - t["fee_cost"], t["net_pnl"], places=2)


class PointInTime(unittest.TestCase):
    def test_walk_forward_bias_uses_only_earlier_weeks(self):
        d = pd.DataFrame({"week": [2, 2, 3, 3, 4], "mar": [0.0, 0, 0, 0, 0], "p": [10.0, 10, 10, 10, 10]}); b1 = A.walk_forward_bias(d, "p")
        d2 = d.copy(); d2.loc[d2.week >= 3, "mar"] = 99.0; b2 = A.walk_forward_bias(d2, "p")
        self.assertEqual(b1[0], 0.0); self.assertAlmostEqual(b1[2], -20 / (2 + A.SHRINK_K)); self.assertEqual(b1[2], b2[2])  # week-3 correction ignores week>=3 outcomes
        self.assertNotEqual(b1[4], b2[4])

    def test_market_recalibration_never_scores_first_weeks_or_peeks(self):
        rng = np.random.default_rng(0); n = 400; q = pd.DataFrame({"week": np.repeat([2, 3, 4, 5], n // 4), "p": rng.uniform(.05, .95, n), "mid": rng.uniform(.05, .95, n)}); q["y"] = (rng.uniform(size=n) < q.mid).astype(float)
        p, coefs = A.walk_forward_market_recal(q, "p"); self.assertTrue(p[q.week <= 3].isna().all()); self.assertTrue(p[q.week >= 4].notna().all())
        q2 = q.copy(); q2.loc[q2.week == 5, "y"] = 1 - q2.y; p2, _ = A.walk_forward_market_recal(q2, "p"); np.testing.assert_allclose(p[q.week == 5], p2[q.week == 5])


class CommittedReport(unittest.TestCase):
    """Pins the audited conclusions so a later edit cannot silently change them."""
    R = json.loads((ROOT / "research/cfb_bet_selection/audit_report_2026.json").read_text())

    def test_settlement_audit_clean(self):
        s = self.R["settlement_audit"]; self.assertEqual(s["result_disagrees"], 0); self.assertEqual(s["spread_strike_mismatch"], 0); self.assertEqual(s["quote_after_official_close"], 0)
        self.assertEqual(s["with_official_settlement"], s["quoted_tickers"]); self.assertGreaterEqual(s["min_lead_minutes"], 15)
        for t in self.R["traces"]: self.assertEqual(t["evaluate_yes_wins"], t["official_result"] == "yes")

    def test_no_profit_claim_and_market_dominates(self):
        self.assertTrue(self.R["baseline_reproduces_evaluate_blend"]); self.assertEqual(self.R["label"], "RESEARCH_ONLY")
        for name, v in self.R["corrections_2026"].items(): self.assertLess(v["ALL"]["net_pnl"], 2 * v["ALL"]["net_pnl_se_game_clustered"], name)  # nothing is distinguishable from zero or better
        for fam, c in self.R["calibration_all_quoted_contracts"].items(): self.assertLess(c["scores"]["market_mid"]["brier"], c["scores"]["blend"]["brier"], fam)


if __name__ == "__main__":
    unittest.main()

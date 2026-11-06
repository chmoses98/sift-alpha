"""Offline tests: the nested search finds planted signal, does not invent signal from noise, never sees the test season; the audit separates market-derived inputs."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.input_research import coverage_audit as CA, marketfree as MF, search as SR

ROOT = Path(__file__).resolve().parents[1]


def table(signal: float, seed=0, n_per=250, seasons=range(2013, 2022)):
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        X = rng.normal(size=(n_per, 6))
        r = signal * X[:, 0] + 0.5 * signal * X[:, 3] + rng.normal(size=n_per) * 3
        d = pd.DataFrame(X, columns=[f"x{i}" for i in range(6)]); d["season"] = s; d["week"] = rng.integers(1, 18, n_per); d["r"] = r
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


GROUPS = {"a": ["x0", "x1"], "b": ["x2", "x3"], "c": ["x4", "x5"]}


class Search(unittest.TestCase):
    def run_search(self, signal, seed=0):
        d = table(signal, seed)
        r = d.r.to_numpy()
        res = SR.nested_search(d, r, GROUPS, range(2018, 2022), n_configs=12, seed=seed)
        return d, r, SR.summarize_gain(d, r, res["pred"], d.season.astype(str) + "-" + d.week.astype(str), n_boot=300), res

    def test_planted_signal_is_found_out_of_sample(self):
        d, r, g, res = self.run_search(2.0)
        self.assertGreater(g["pct_gain"], 5.0)
        self.assertEqual(g["seasons_positive"], len(g["seasons"]))

    def test_pure_noise_gains_nothing(self):
        d, r, g, res = self.run_search(0.0, seed=3)
        self.assertLess(g["pct_gain"], 1.0)

    def test_selection_never_uses_the_test_season(self):
        d = table(1.0)
        r = d.r.to_numpy().copy()
        r[d.season.to_numpy() == 2021] = 1e6          # poison the last season: it is the outer test season, so no fold may train/select on it
        res = SR.nested_search(d, r, GROUPS, [2021], n_configs=8)
        p = res["pred"][d.season.to_numpy() == 2021]
        self.assertTrue(np.all(np.abs(p) < 100))

    def test_forbidden_market_columns_are_rejected(self):
        d = table(1.0)
        d["total_line"] = 1.0
        with self.assertRaises(ValueError):
            SR.nested_search(d, d.r.to_numpy(), {"a": ["x0", "total_line"]}, [2021], n_configs=4)


class Audit(unittest.TestCase):
    def test_market_derived_classification(self):
        mk = lambda label, cat="team_strength": {"label": label, "category": cat}
        self.assertTrue(CA.is_market_derived("m.external_lines", mk("Sportsbook reference prices", "market_structure")))
        self.assertTrue(CA.is_market_derived("nfl.ratings", mk("Power ratings and market-implied team strength history")))
        self.assertFalse(CA.is_market_derived("nfl.ol", mk("Offensive-line continuity, pass-block/pressure rates", "availability")))
        self.assertFalse(CA.is_market_derived("m.rules_text", mk("Versioned rules", "market_structure")))      # contract definition, not a price
        self.assertFalse(CA.is_market_derived("m.strike_hit_rates", mk("Historical realized frequency by strike", "distribution")))

    def test_published_audit_covers_eight_sports(self):
        a = json.loads((ROOT / "research/audit/input_research/coverage_audit.json").read_text())
        self.assertEqual(sorted(a["readiness"]), sorted(CA.SPORTS))
        self.assertEqual(sum(len(v) for v in a["mechanism_matrix"].values()), 118)
        for s in CA.SPORTS:
            self.assertGreater(a["market_derived_inputs"][s]["market_derived_benchmark_only"], 0)

    def test_own_script_has_no_market_columns(self):
        MF.assert_market_free(MF.SCRIPT_FEATURES)


class PublishedSoccer(unittest.TestCase):
    def test_soccer_search_is_market_free_and_beats_its_null(self):
        r = json.loads((ROOT / "research/audit/input_research/experiments/search_soccer_v1.json").read_text())
        self.assertTrue(r["market_free"])
        MF.assert_market_free([c for g in r["groups"].values() for c in g])
        for t, s in r["studies"].items():
            self.assertGreater(s["nested_gain"]["pct_gain"], max(x["pct_gain"] for x in s["permutation_null"]) + 0.5, t)
            self.assertEqual(s["nested_gain"]["seasons_positive"], len(s["nested_gain"]["seasons"]), t)

    def test_odds_columns_are_never_loaded(self):
        from alpha_engine.input_research import search_soccer as SS
        for c in SS.KEEP:
            self.assertFalse(c.startswith(("B365", "PS", "Max", "Avg", "BW", "WH", "BF", "1XB", "AH")), c)


if __name__ == "__main__":
    unittest.main()

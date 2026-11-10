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
        self.assertFalse(CA.is_market_derived("nfl.ratings", mk("Power ratings and market-implied team strength history")))   # hybrid: usable only after a market-free rebuild
        from alpha_engine.input_research import market_dependency as MD
        self.assertEqual(MD.kind("nfl.ratings"), "hybrid_rebuild")
        self.assertEqual(MD.kind("nba.implied_team_totals"), "benchmark_only")
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


class CatalogCorrections(unittest.TestCase):
    def test_every_market_text_hit_is_classified(self):
        from alpha_engine.input_research import market_dependency as MD
        self.assertEqual(MD.classify_all()["unclassified_regex_hits"], [])

    def test_every_checklist_flag_is_adjudicated_with_a_reason(self):
        a = json.loads((ROOT / "research/audit/input_research/coverage_audit.json").read_text())
        self.assertEqual(sum(len(r["unadjudicated_missing"]) > 0 for rows in a["mechanism_matrix"].values() for r in rows), 0)
        adj = json.loads((ROOT / "research/input_research/gap_adjudication.json").read_text())
        self.assertEqual(adj["n_flags"], 85)
        for x in adj["adjudications"]:
            self.assertIn(x["verdict"], {"ATTACHED_EXISTING", "NEW_INPUT_ADDED", "COVERED_OTHER_CAT", "FALSE_POSITIVE"})
            self.assertGreater(len(x["reason"]), 20)
            if x["verdict"] in ("ATTACHED_EXISTING", "NEW_INPUT_ADDED"):
                self.assertTrue(x["attach"], (x["sport"], x["archetype"], x["category"]))

    def test_attachments_exist_in_the_catalog(self):
        from alpha_engine.input_research import catalog as C
        adj = json.loads((ROOT / "research/input_research/gap_adjudication.json").read_text())
        for x in adj["adjudications"]:
            cat = C.load(x["sport"])
            have = {i["id"] for i in cat["archetypes"][x["archetype"]]["inputs"]}
            from alpha_engine.input_research import completeness as CP
            det = set((CP.archetype_patches(x["sport"]).get(x["archetype"]) or {}).get("detach") or [])
            for att in x["attach"]:
                if att["id"] in det:   # deliberately detached later by a reviewed archetype patch (component of another input)
                    continue
                self.assertIn(att["id"], have, x)

    def test_unregistered_archetypes_are_published_and_marked_as_unregistered(self):
        for s in CA.SPORTS:
            d = json.loads((ROOT / f"research/audit/input_research/sport_{s}.json").read_text())
            for a, rec in d["unregistered_archetypes"].items():
                self.assertTrue(rec["contract_types"]); self.assertGreaterEqual(len(rec["inputs"]), 8); self.assertNotIn(a, d["archetypes"])

    def test_reconciliation_accounts_for_every_in_scope_series(self):
        r = json.loads((ROOT / "research/input_research/market_universe/reconciliation.json").read_text())
        u = json.loads((ROOT / "research/input_research/market_universe/universe_summary.json").read_text())
        for s, rows in r["sports"].items():
            self.assertEqual(sum(x["series"] for x in rows), u["by_sport"][s]["series"], s)

    def test_source_claims_are_measured_not_assumed(self):
        v = json.loads((ROOT / "research/input_research/source_verification.json").read_text())
        self.assertEqual(v["football_data"]["referee_name_completeness_by_league"]["E0"], 1.0)
        self.assertEqual(v["football_data"]["referee_name_completeness_by_league"]["SP1"], 0.0)
        self.assertEqual(v["nflverse"]["ftn_charting"]["earliest_ok_probed"], 2022)
        self.assertEqual(v["espn"]["classification"], "SNAPSHOT_ONLY")
        c = json.loads((ROOT / "research/input_research/catalog/SOCCER.json").read_text())
        self.assertIn("ONLY", c["inputs"]["soc.referee"]["free_sources"][0])

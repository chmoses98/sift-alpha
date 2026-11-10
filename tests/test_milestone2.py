"""Offline tests for milestone 2: verified computable inputs, leak-test machinery, merged market-free guard, #59-compatible ledger, scaled-search verdicts (RESEARCH_ONLY)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.features import audit, college, mlb, nba, nfl, nhl, soccer, tennis
from alpha_engine.features.core import prior_ewm
from alpha_engine.input_research import ledger as L, marketfree as MF, scaled_search as SS, search as SR

ROOT = Path(__file__).resolve().parents[1]


class Guard(unittest.TestCase):
    def test_merged_guard_rejects_both_labs_patterns(self):
        for c in ["implied_total", "closing_line", "consensus_total", "x_mkt_y", "spread_line", "kalshi_mid", "best_bid", "best_ask", "market_prob", "moneyline"]:
            with self.assertRaises(ValueError, msg=c):
                MF.assert_market_free([c])
        MF.assert_market_free(["epa_pre", "rest", "own_exp_team_pts", "elo_gap_pre", "pts_pre"])

    def test_postgame_columns_only_as_targets(self):
        with self.assertRaises(ValueError):
            MF.assert_market_free(["home_score"])
        MF.assert_market_free(["home_score"], allow_targets=["home_score"])

    def test_every_audited_feature_column_is_market_free(self):
        for mod, fn in ((nba, "specs"), (nhl, "specs"), (mlb, "specs"), (tennis, "specs"), (soccer, "specs"), (college, "specs_cbb"), (college, "specs_cfb"), (nfl, "specs")):
            cols = [c for s in getattr(mod, fn)() for c in s.columns]
            MF.assert_market_free(cols)


class Ledger(unittest.TestCase):
    def test_id_matches_lab59_scheme_and_is_idempotent(self):
        cfg = {"market": "X", "cfg": {"groups": ["a"], "alpha": 3.0}}
        self.assertEqual(L.exp_id(cfg), hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16])
        with tempfile.TemporaryDirectory() as d:
            led = L.Ledger(Path(d) / "l.jsonl")
            led.record(cfg, {"m": 1}); led.record(cfg, {"m": 2})
            self.assertEqual(len(led), 1)
            self.assertEqual(len(L.Ledger(Path(d) / "l.jsonl")), 1)
            self.assertEqual(led.get(cfg)["metrics"]["m"], 1)

    def test_nested_search_logs_every_configuration_and_marks_nulls(self):
        rng = np.random.default_rng(0)
        rows = []
        for s in range(2013, 2022):
            X = rng.normal(size=(200, 6)); d = pd.DataFrame(X, columns=[f"x{i}" for i in range(6)]); d["season"] = s; d["r"] = 2 * X[:, 0] + rng.normal(size=200) * 3; rows.append(d)
        d = pd.concat(rows, ignore_index=True); r = d.r.to_numpy()
        groups = {"a": ["x0", "x1"], "b": ["x2", "x3"], "c": ["x4", "x5"]}
        with tempfile.TemporaryDirectory() as td:
            led = L.Ledger(Path(td) / "l.jsonl")
            res = SR.nested_search(d, r, groups, range(2018, 2022), n_configs=10, seed=1, ledger=led, ctx={"market": "T"})
            n_real = len(led)
            self.assertEqual(n_real, res["n_configs"] * len(res["chosen"]))           # every configuration x every outer season that had enough history
            self.assertGreaterEqual(len(res["chosen"]), 2)
            self.assertEqual(sum(1 for x in led.rows.values() if x["metrics"]["picked"]), len(res["chosen"]))
            SR.permutation_null(d, r, groups, range(2018, 2022), d.season.astype(str), reps=1, n_configs=10, ledger=led, ctx={"market": "T"})
            self.assertGreater(len(led), n_real)
            self.assertTrue(any(x["config"].get("null") for x in led.rows.values()))

    def test_lab59_count_read_only(self):
        c = L.count_lab59()
        if c.get("available"):
            self.assertEqual(c["total"], sum(c["per_ledger"].values()))
            self.assertGreaterEqual(c["total"], 13362)


class LeakMachinery(unittest.TestCase):
    def test_perturbation_changes_outcomes_not_structure(self):
        df = pd.DataFrame({"game_id": range(10), "date": pd.date_range("2024-01-01", periods=10), "home_score": np.arange(10) + 5.0, "pa": np.arange(10) + 1, "home_rank": np.arange(10) + 1.0, "temp": 70.0})
        m = (df.date >= "2024-01-06").to_numpy()
        out = audit._perturb_df(df, m, np.random.default_rng(1))
        self.assertTrue((out.loc[~m] == df.loc[~m]).all().all())
        self.assertTrue((out.loc[m, "pa"] == df.loc[m, "pa"]).all() and (out.loc[m, "home_rank"] == df.loc[m, "home_rank"]).all())      # structure/pregame attributes protected
        self.assertFalse(np.allclose(out.loc[m, "home_score"], df.loc[m, "home_score"]))

    def test_cmp_flags_a_planted_leak(self):
        d = pd.DataFrame({"team": list("aaaaaa"), "y": [1., 2, 3, 4, 5, 6]})
        good = d.groupby("team").y.transform(lambda s: s.shift(1).expanding().mean())
        leaky = d.groupby("team").y.transform(lambda s: s.expanding().mean())          # includes the game's own outcome
        d2 = d.copy(); d2.loc[5, "y"] = 60.0                                           # perturb the last game only
        g2 = d2.groupby("team").y.transform(lambda s: s.shift(1).expanding().mean()); l2 = d2.groupby("team").y.transform(lambda s: s.expanding().mean())
        sel = np.ones(6, bool)
        self.assertEqual(audit._cmp(pd.DataFrame({"f": good}), pd.DataFrame({"f": g2}), ["f"], sel)[0], [])
        self.assertEqual(audit._cmp(pd.DataFrame({"f": leaky}), pd.DataFrame({"f": l2}), ["f"], sel)[0], ["f"])

    def test_prior_ewm_never_sees_own_row(self):
        d = pd.DataFrame({"t": ["a"] * 6, "x": [1., 2, 3, 4, 5, 100.]})
        p = prior_ewm(d, "t", "x", hl=3, min_periods=1)
        self.assertTrue(np.isnan(p.iloc[0]))
        self.assertLess(p.iloc[5], 5.0)           # the 100 in row 5 is not in its own feature

    def test_tennis_order_is_chronological_inside_a_tournament(self):
        # Sackmann lists tournaments final-first; chronological order must be round order, otherwise early rounds see later outcomes
        base = {"tourney_id": ["T"] * 3, "tourney_date": [20240101] * 3, "match_num": [300, 200, 100], "round": ["F", "SF", "R32"], "winner_id": [1, 1, 1], "loser_id": [2, 3, 4], "best_of": 3,
                "surface": "Hard", "tourney_level": "A", "draw_size": 32, "score": "6-4 6-4", "minutes": 90, "tour": "atp"}
        for who in ("winner", "loser"):
            for c in ("rank", "rank_points", "age", "ht", "hand", "seed", "entry"):
                base[f"{who}_{c}"] = np.nan
        for who in ("w", "l"):
            for c in ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced"):
                base[f"{who}_{c}"] = np.nan
        raw = {"atp": pd.DataFrame(base)}
        p = tennis._long(raw)
        r = p[p.pid == 1].sort_values(["date", "ord"])["round"].tolist()
        self.assertEqual(r, ["R32", "SF", "F"])


class Verdicts(unittest.TestCase):
    def res(self, m, gain, lo, hi, p, null, pos=7, halves=(1.0, 1.0)):
        return {"market": m, "status": "TESTED", "gain": {"pct_gain": gain, "ci_0.05": [lo, hi], "p": p, "seasons": list(range(7)), "seasons_positive": pos, "halves_pct": list(halves)}, "null_max_pct": null}

    def test_validated_needs_holm_cis_halves_and_null(self):
        rs = [self.res("A", 3.0, 0.1, 0.2, 0.0005, 0.05), self.res("B", 3.0, 0.1, 0.2, 0.04, 0.05), self.res("C", 0.5, -0.1, 0.1, 0.5, 0.4), self.res("D", -1.0, -0.3, -0.1, 0.01, 0.0), self.res("E", 3.0, 0.1, 0.2, 0.0004, 2.9)]
        SS.finalize(rs)
        v = {r["market"]: r["verdict"] for r in rs}
        self.assertEqual(v["A"], "VALIDATED")
        self.assertNotEqual(v["B"], "VALIDATED")      # nominal CI only after Holm over 5 markets (0.04*4 > 0.05)
        self.assertEqual(v["D"], "NO_GAIN")
        self.assertNotEqual(v["E"], "VALIDATED")      # the null gains almost as much: search overfitting, not signal


class Registry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.load(open(ROOT / "research/input_research/computable_inputs.json"))

    def test_every_catalog_input_has_exactly_one_status(self):
        rd = json.load(open(ROOT / "research/input_research/data_readiness.json"))
        self.assertEqual(set(self.d["inputs"]), set(rd["inputs"]))
        self.assertEqual(sum(self.d["totals"].values()), self.d["n_inputs"])
        self.assertEqual(self.d["n_non_market"], self.d["n_inputs"] - self.d["totals"]["EXCLUDED_BENCHMARK_ONLY"])

    def test_computed_means_verified(self):
        for k, v in self.d["inputs"].items():
            if not v["status"].startswith("COMPUTED"):
                continue
            self.assertTrue(v["leak_test"]["ok"], k)
            self.assertNotEqual(v["pit"], "final_postgame", k)
            for c, cv in v["coverage"].items():
                self.assertTrue(cv["present"] and cv["nunique"] > 1, f"{k}:{c}")
            self.assertEqual(v["leak_test"].get("unmoved_nonstatic", []), [], k)

    def test_postgame_observations_are_not_pregame_eligible(self):
        self.assertEqual(self.d["inputs"]["NFL:nfl.weather_pit"]["status"], "NOT_PREGAME_ELIGIBLE")
        self.assertEqual(self.d["inputs"]["MLB:mlb.umpire"]["status"], "NOT_PREGAME_ELIGIBLE")

    def test_not_computed_always_carries_a_reason(self):
        for k, v in self.d["inputs"].items():
            if v["status"] == "NOT_COMPUTED":
                self.assertTrue(v["reason"], k)

    def test_market_derived_inputs_never_computed(self):
        md = json.load(open(ROOT / "research/input_research/market_dependency.json"))
        for sp, ids in md["benchmark_only"].items():
            for i in ids:
                k = f"{sp}:{i}" if f"{sp}:{i}" in self.d["inputs"] else f"{sp}:{i}"
                if k in self.d["inputs"]:
                    self.assertEqual(self.d["inputs"][k]["status"], "EXCLUDED_BENCHMARK_ONLY", k)


if __name__ == "__main__":
    unittest.main()

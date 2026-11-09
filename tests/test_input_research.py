"""Input-research system: statistical engine honesty, point-in-time guarantees, catalog integrity and published-artifact invariants."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.input_research import catalog as C, nfl_features as nf, stats as S

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/audit/input_research"
SEAS = np.repeat(np.arange(2014, 2024), 200)
WEEK = np.tile(np.repeat(np.arange(20), 10), 10)
KEYS = np.array([f"{s}-{w}" for s, w in zip(SEAS, WEEK)])
TS = range(2018, 2024)


def _gain(y, X):
    p, _ = S.walk_forward_ridge(X, y, SEAS, TS)
    b1 = S.baseline_mean(y, SEAS, TS)
    test = ~np.isnan(p)
    boot = S.ClusterBoot(KEYS[test], n_boot=800)
    return S.gain_summary(boot, test, (y - b1) ** 2, (y - p) ** 2, SEAS, TS)


class StatsEngine(unittest.TestCase):
    def test_planted_signal_is_demonstrated(self):
        rng = np.random.default_rng(1)
        X = rng.normal(size=(2000, 4)); y = 2 * X[:, 0] + rng.normal(size=2000) * 5
        g = _gain(y, X)
        self.assertGreater(g["ci_0.05"][0], 0)
        self.assertEqual(S.verdict(g, g["p"]), "DEMONSTRATED_INCREMENTAL")

    def test_pure_noise_is_never_demonstrated(self):
        false_pos = 0
        for seed in range(8):
            rng = np.random.default_rng(100 + seed)
            X = rng.normal(size=(2000, 6)); y = rng.normal(size=2000) * 5
            g = _gain(y, X)
            false_pos += S.verdict(g, min(1.0, g["p"] * 8)) == "DEMONSTRATED_INCREMENTAL"
        self.assertEqual(false_pos, 0)

    def test_walk_forward_uses_only_past_seasons(self):
        rng = np.random.default_rng(2)
        X = rng.normal(size=(2000, 3)); y = X[:, 0] + rng.normal(size=2000)
        p1, _ = S.walk_forward_ridge(X, y, SEAS, TS)
        y2 = y.copy(); y2[SEAS >= 2020] += 1000.0      # corrupt the 2020+ outcomes
        p2, _ = S.walk_forward_ridge(X, y2, SEAS, TS)
        early = SEAS < 2020
        np.testing.assert_allclose(p1[early & ~np.isnan(p1)], p2[early & ~np.isnan(p2)])   # predictions up to 2019 cannot see 2020+ outcomes
        s2020 = SEAS == 2020
        np.testing.assert_allclose(p1[s2020], p2[s2020])                                    # 2020 is predicted from <2020 only

    def test_multiple_comparison_helpers(self):
        h = S.holm({"a": 0.01, "b": 0.04, "c": 0.5})
        self.assertAlmostEqual(h["a"], 0.03); self.assertAlmostEqual(h["b"], 0.08); self.assertEqual(h["c"], 0.5)
        q = S.benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.5})
        self.assertTrue(q["a"] <= q["b"] <= q["c"] <= 1.0)

    def test_devig_and_calibration(self):
        self.assertAlmostEqual(float(S.devig_two_way(-110, -110)), 0.5)
        self.assertAlmostEqual(float(S.devig_two_way(-200, 170) + S.devig_two_way(170, -200)), 1.0)
        rng = np.random.default_rng(3)
        p = rng.uniform(0.1, 0.9, 20000); y = (rng.uniform(size=20000) < p).astype(float)
        c = S.calibration_slope(p, y)
        self.assertAlmostEqual(c["slope"], 1.0, delta=0.08); self.assertAlmostEqual(c["intercept"], 0.0, delta=0.08)

    def test_gbm_available_or_skipped(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest("scikit-learn not installed")
        rng = np.random.default_rng(4)
        X = rng.normal(size=(2000, 3)); y = np.where(X[:, 0] > 0, 3.0, -3.0) + rng.normal(size=2000)    # a step a linear model cannot capture
        pg = S.walk_forward_gbm(X, y, SEAS, TS)
        pr, _ = S.walk_forward_ridge(X, y, SEAS, TS)
        m = ~np.isnan(pg)
        self.assertLess(np.mean((y - pg)[m] ** 2), np.mean((y - pr)[m] ** 2))


def _synthetic_games(n_games=40):
    teams = ["AAA", "BBB", "CCC", "DDD"]
    rows, tg = [], []
    rng = np.random.default_rng(5)
    for g in range(n_games):
        h, a = teams[g % 4], teams[(g + 1 + g // 4) % 4]
        if h == a:
            a = teams[(g + 2) % 4]
        gid = f"2024_{g:02d}_{a}_{h}"
        rows.append({"game_id": gid, "gameday": f"2024-09-{1 + g // 2:02d}" if g < 58 else "2024-10-30", "season": 2024, "home_team": h, "away_team": a, "home_qb_id": f"qb_{h}", "away_qb_id": f"qb_{a}"})
        for t in (h, a):
            r = {"game_id": gid, "posteam": t, "qb_id": f"qb_{t}", "qb_db": 30.0, "qb_epa_sum": float(rng.normal())}
            for m in nf.OFF_METRICS:
                r[m] = float(rng.normal())
            tg.append(r)
    return pd.DataFrame(rows), pd.DataFrame(tg)


class PointInTime(unittest.TestCase):
    def test_pregame_ratings_never_see_the_game_itself(self):
        games, tg = _synthetic_games()
        base = nf.rolling_ratings(games, tg).set_index("game_id")
        last = games.sort_values(["gameday", "game_id"]).iloc[-1]["game_id"]
        tg2 = tg.copy()
        mask = tg2["game_id"] == last
        for m in nf.OFF_METRICS:
            tg2.loc[mask, m] = tg2.loc[mask, m] + 1e6          # absurd outcome in the LAST game
        tg2.loc[mask, "qb_epa_sum"] = 1e6
        alt = nf.rolling_ratings(games, tg2).set_index("game_id")
        # features of every game (including the corrupted one) are unchanged: an outcome can only affect LATER games
        pd.testing.assert_frame_equal(base, alt)

    def test_outcome_changes_later_games_only(self):
        games, tg = _synthetic_games()
        order = games.sort_values(["gameday", "game_id"])["game_id"].tolist()
        first = order[0]
        tg2 = tg.copy()
        tg2.loc[tg2["game_id"] == first, "epa_pass"] += 5.0
        a = nf.rolling_ratings(games, tg).set_index("game_id"); b = nf.rolling_ratings(games, tg2).set_index("game_id")
        self.assertTrue((a.loc[first] .fillna(0) == b.loc[first].fillna(0)).all())          # the game itself: identical
        self.assertFalse(a.loc[order[-1]].fillna(0).equals(b.loc[order[-1]].fillna(0)))     # a later game: changed

    def test_market_columns_devig_and_push_handling(self):
        d = pd.DataFrame({"home_score": [27, 20, 24], "away_score": [20, 20, 17], "total": [47, 40, 41], "total_line": [44.5, 40.0, 41.0], "spread_line": [3.0, 0.0, 7.0],
                          "home_moneyline": [-150, 100, -300], "away_moneyline": [130, -120, 250], "over_odds": [-110, -110, -110], "under_odds": [-110, -110, -110],
                          "home_spread_odds": [-110, -110, -110], "away_spread_odds": [-110, -110, -110]})
        m = nf.market_columns(d)
        self.assertTrue(np.isnan(m.loc[1, "home_win"]) and np.isnan(m.loc[1, "over"]))        # tie / push excluded, not scored as a loss
        self.assertAlmostEqual(m.loc[0, "p_over_mkt"], 0.5)
        self.assertGreater(m.loc[0, "p_home_mkt"], 0.5)


class InjuryFeature(unittest.TestCase):
    def test_out_player_without_a_same_week_snap_row_keeps_prior_snap_share(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / "inj").mkdir(); (d / "snaps").mkdir()
            snaps = pd.DataFrame({"game_id": ["g"] * 3, "pfr_game_id": ["x"] * 3, "season": 2023, "game_type": "REG", "week": [1, 2, 3], "player": "OL One", "pfr_player_id": "OneOL00",
                                  "position": "T", "team": "AAA", "opponent": "BBB", "offense_snaps": 60, "offense_pct": [1.0, 1.0, 1.0], "defense_snaps": 0, "defense_pct": 0.0, "st_snaps": 0, "st_pct": 0.0})
            snaps.to_csv(d / "snaps" / "snap_2023.csv", index=False)
            inj = pd.DataFrame({"season": 2023, "game_type": "REG", "team": "AAA", "week": [4], "gsis_id": "00-1", "position": "T", "report_status": "Out"})
            inj["practice_status"] = "DNP"
            inj.to_csv(d / "inj" / "inj_2023.csv", index=False)
            players = pd.DataFrame({"gsis_id": ["00-1"], "pfr_id": ["OneOL00"]})
            out = nf.injury_features(d / "inj", d / "snaps", players)
            row = out[(out["week"] == 4) & (out["team"] == "AAA")].iloc[0]
            self.assertAlmostEqual(row["inj_ol"], 1.0)        # an Out starter who played 100% of snaps counts fully
            self.assertAlmostEqual(row["inj_total"], 1.0)


class RefreshWorkflowIsResearchOnly(unittest.TestCase):
    def test_workflow_is_read_only_artifact_only_and_bounded(self):
        import yaml
        raw = (ROOT / ".github/workflows/input-research-refresh.yml").read_text()
        wf = yaml.safe_load(raw)
        trig = wf.get("on") or wf.get(True)
        from alpha_engine.input_research.phase import predictive_paused
        # never on push / pull_request; while predictive experimentation is paused (catalog-completeness phase) there is no schedule at all
        self.assertEqual(sorted(trig), ["workflow_dispatch"] if predictive_paused() else ["schedule", "workflow_dispatch"])
        self.assertEqual(wf["permissions"], {"contents": "read"})                            # cannot push, deploy or write anything
        job = wf["jobs"]["refresh"]
        self.assertLessEqual(job["timeout-minutes"], 60)
        self.assertEqual(job["runs-on"], "ubuntu-latest")                                    # standard free runner
        steps = json.dumps(job["steps"]).lower()
        for bad in ("git push", "git commit", "gh pr", "gh workflow", "vercel", "deploy", "secrets.", "kalshi", "curl ", "orders"):
            self.assertNotIn(bad, steps, bad)
        self.assertIn("upload-artifact", steps)
        self.assertIn("retention-days", steps)

    def test_no_order_or_trading_imports_in_the_package(self):
        for f in (ROOT / "alpha_engine/input_research").glob("*.py"):
            src = f.read_text().lower()
            for bad in ("import kalshi", "place_order", "create_order", "api_key", "private_key", "bearer "):
                self.assertNotIn(bad, src, f.name)


class CatalogIntegrity(unittest.TestCase):
    def test_every_sport_catalog_valid_and_covers_registry(self):
        self.assertEqual(C.validate_all(), {})

    def test_all_eight_sports_present(self):
        for s in C.SPORTS:
            self.assertTrue((C.CATALOG_DIR / f"{s}.json").exists(), s)

    def test_catalog_has_no_evidence_claims(self):
        for s in C.SPORTS:
            blob = json.dumps(C.load(s)).lower()
            for bad in ("validated predictive", "proven edge", "guaranteed", "statistically significant edge"):
                self.assertNotIn(bad, blob, f"{s}: {bad}")

    def test_validator_rejects_thin_entries(self):
        doc = C.load("NFL")
        k = next(iter(doc["inputs"]))
        doc["inputs"][k]["rationale"] = "x"
        self.assertTrue(any("thin" in e for e in C.validate(doc, "NFL")))


@unittest.skipUnless((OUT / "index.json").exists(), "artifacts not generated")
class PublishedArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((OUT / "index.json").read_text())
        cls.docs = {s: json.loads((OUT / f"sport_{s}.json").read_text()) for s in cls.index["sports"]}
        cls.queue = json.loads((OUT / "queue.json").read_text())
        cls.reg = json.loads((ROOT / "research/audit/input_registry.json").read_text())["sports"]

    def test_status_is_research_only_and_all_sports_published(self):
        self.assertEqual(self.index["status"], "RESEARCH_ONLY")
        self.assertEqual(sorted(self.index["sports"]), sorted(C.SPORTS))

    def test_every_registry_family_is_listed_never_hidden(self):
        for s, d in self.docs.items():
            self.assertEqual(sorted(d["families"]), sorted(self.reg[s]["families"]), s)

    def test_no_family_claims_more_than_the_evidence_achieved(self):
        for s, d in self.docs.items():
            for f, v in d["families"].items():
                self.assertNotIn(v["level"], ("L3_TESTED_VS_KALSHI", "L4_PROSPECTIVELY_CONFIRMED"), f)
                if v["level"] != "L0_INVENTORY_ONLY":
                    self.assertTrue(v["evidence_paths"], f)
                else:
                    self.assertFalse(v["evidence_paths"], f)

    def test_l2_paths_are_near_close_line_benchmarks_and_say_so(self):
        for d in self.docs.values():
            for pid, p in d["paths"].items():
                if p["level"] == "L2_TESTED_VS_MARKET":
                    self.assertIn("not a kalshi price", p["benchmark"].lower())
                if p["level"] == "L1_TESTED_VS_BASELINE":
                    self.assertTrue(p["benchmark"].startswith("NO MARKET"))

    def test_every_tested_input_has_uncertainty_and_multiple_testing_fields(self):
        for d in self.docs.values():
            for p in d["paths"].values():
                for c, r in p["result"]["inputs"].items():
                    inc = r["incremental"]
                    self.assertIn("q_bh", inc); self.assertIn("ci95", inc); self.assertIn("verdict", inc)
                    self.assertGreaterEqual(inc["q_bh"], 0.0); self.assertLessEqual(inc["q_bh"], 1.0 + 1e-9)

    def test_demonstrated_verdicts_satisfy_the_gate(self):
        for d in self.docs.values():
            for p in d["paths"].values():
                for g, v in p["result"]["groups"].items():
                    if v["verdict"] == "DEMONSTRATED_INCREMENTAL":
                        self.assertLess(v["holm_p"], 0.05); self.assertGreater(min(v["halves"]), 0); self.assertGreater(v["ci95"][0], 0)

    def test_untested_inputs_are_flagged_untested(self):
        for d in self.docs.values():
            for a in d["archetypes"].values():
                for i in a["inputs"]:
                    self.assertEqual(i["tested"], bool(i["evidence"]))

    def test_non_registry_inputs_never_inherit_related_inputs_status(self):
        for s, d in self.docs.items():
            ids = C.registry_input_ids(s)
            for iid, i in d["inputs"].items():
                av = i["availability"]
                if iid not in ids:
                    self.assertFalse(av["exact_registry_match"], iid)
                    self.assertNotIn(av["overall"], ("PIT_ARCHIVED", "COLLECTED_NOT_PIT_ARCHIVED", "PARTIAL_OR_STALE", "DERIVED", "CODE_REFERENCE_ONLY"), iid)
                    self.assertFalse(av["model_use"].startswith("USED"), iid)

    def test_input_availability_is_never_fabricated_complete(self):
        for s, d in self.docs.items():
            for iid, i in d["inputs"].items():
                av = i["availability"]
                if av["overall"] == "COMPUTED_IN_RESEARCH_PATH":
                    self.assertIn("research_path", av); self.assertGreater(av["research_path"]["mean_coverage"], 0)
                else:
                    self.assertNotIn("research_path", av)

    def test_every_family_input_and_interaction_is_represented_on_the_dashboard_data(self):
        fam = inp = ix = 0
        for s, d in self.docs.items():
            cat = C.load(s)
            fam += len(d["families"])
            # every input the catalog defines is reachable through some blueprint or archetype shown by the dashboard
            self.assertEqual(sorted(d["inputs"]), sorted(k for k, v in cat["inputs"].items() if not v.get("retired")), s)   # retired inputs are kept in the catalog for traceability, never shown
            inp += len(d["inputs"])
            ix += sum(len(a["interactions"]) for a in d["archetypes"].values()) + sum(len(b["interactions"]) for b in d["blueprints"].values())
            reg_bps = C.registry_blueprints(s)
            for b, rec in d["blueprints"].items():
                self.assertTrue(rec["families"], f"{s}/{b}: blueprint with no family would be unreachable")
                self.assertEqual(sorted(rec["families"]), sorted(reg_bps[b]))
            for a, rec in d["archetypes"].items():
                for f in rec["families"]:
                    self.assertIn(a, d["families"][f]["archetypes"], f)
        self.assertEqual((fam, inp, ix), (275, 1640, 1351))     # documented totals (672 inputs at #53; +12 gap adjudication, +5 unregistered contract types = 691; +949 from the catalog-completeness review via completeness.integrate; interactions 679 -> 1351 after merging the reviews' interactions); a catalog change must update these consciously

    def test_every_path_states_its_claim_boundary_and_never_implies_a_kalshi_edge(self):
        for d in self.docs.values():
            for pid, p in d["paths"].items():
                self.assertTrue(p["claim_boundary"], pid)
                self.assertIn("kalshi", p["claim_boundary"].lower(), pid)
                blob = json.dumps(p).lower()
                for bad in ("beats kalshi", "edge over kalshi found", "profitable", "exploit"):
                    self.assertNotIn(bad, blob, pid)

    def test_headline_models_are_strict_pregame_and_partial_inputs_are_separated(self):
        for d in self.docs.values():
            for pid, p in d["paths"].items():
                r = p["result"]
                hm = r["headline_models"]
                best = hm.get("ridge_all") or hm.get("logit_all")
                self.assertTrue(best["pit_strict"], pid)
                self.assertTrue(r["partial_pit_inputs"], pid)
                for c, rec in r["inputs"].items():
                    self.assertEqual(rec["pit"] == "partial", c in r["partial_pit_inputs"], (pid, c))
                if best["verdict"] == "DEMONSTRATED_INCREMENTAL":
                    self.assertIsNotNone(best.get("ci_season_block")); self.assertGreater(best["ci_season_block"][0], 0)

    def test_unreliable_weights_are_flagged(self):
        for d in self.docs.values():
            for p in d["paths"].values():
                for c, rec in p["result"]["inputs"].items():
                    w = rec.get("weight") or {}
                    if "reliable" in w and w["reliable"]:
                        self.assertTrue(w["ci_excludes_zero"], c)
                        self.assertIn(rec["incremental"]["verdict"], ("DEMONSTRATED_INCREMENTAL", "SUGGESTIVE_UNCONFIRMED"), c)

    def test_provenance_records_hashes_and_unpinned_warning(self):
        prov = json.loads((OUT / "provenance.json").read_text())["provenance"]
        self.assertTrue(prov["files_are_unpinned_latest_release_assets"])
        self.assertGreater(len(prov["files"]), 30)
        self.assertTrue(all(len(v["sha256"]) == 64 for v in prov["files"].values()))
        self.assertIn("injury_report", prov["diagnostics"])

    def test_queue_is_ranked_and_makes_no_profit_claims(self):
        sc = [q["score"] for q in self.queue["items"]]
        self.assertEqual(sc, sorted(sc, reverse=True))
        blob = json.dumps(self.queue).lower()
        for bad in ("guaranteed", "profitable", "+ev"):
            self.assertNotIn(bad, blob)

    def test_market_benchmark_not_beaten_is_reported_not_hidden(self):
        # every L2 path's headline verdict is present, whatever it is
        for d in self.docs.values():
            for p in d["paths"].values():
                hm = p["result"]["headline_models"]
                best = hm.get("ridge_all") or hm.get("logit_all")
                self.assertIn(best["verdict"], ("DEMONSTRATED_INCREMENTAL", "SUGGESTIVE_UNCONFIRMED", "NOT_DEMONSTRATED", "WORSE_THAN_BASELINE"))


if __name__ == "__main__":
    unittest.main()

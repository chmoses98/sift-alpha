"""Tests for challenger alpha-nba-rate-0.3 (RESEARCH_ONLY): rate / level helpers, restored T-60 boards, lineage.

Pure helpers and the committed evidence files are always tested. The end-to-end re-run (byte-identical output) needs the
owner's nba-edge-finder clone with the pinned projection-data / main / data-archive commits under $SIFT_REPOS_DIR and is
skipped cleanly when they are absent (CI has no clones).
"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import contract as C
from alpha_engine.foundation import nba_frozen as F
from alpha_engine.foundation import nba_rate as N

EVAL = N.OUT_DIR / "evaluation.json"
SUMM = N.OUT_DIR / "predictions_summary.json"


class PureHelpers(unittest.TestCase):
    def test_decayed_sums_are_pregame_and_reset_per_player(self):
        X = np.array([[1.0], [2.0], [4.0], [8.0]]); pid = np.array([1, 1, 1, 2]); se = np.array([0, 0, 1, 1])
        pre, post = N.decayed_sums(X, pid, se, halflife=1.0)
        np.testing.assert_allclose(pre[:, 0], [0.0, 1.0, 2.5, 0.0])          # row i never sees itself; player 2 starts from zero
        np.testing.assert_allclose(post[:, 0], [1.0, 2.5, 5.25, 8.0])
        pre2, _ = N.decayed_sums(X, pid, se, halflife=np.inf, reset_season=True)
        np.testing.assert_allclose(pre2[:, 0], [0.0, 1.0, 0.0, 0.0])          # season change clears the within-season sum
        X2 = X.copy(); X2[2, 0] = 999.0                                         # changing a later game cannot change an earlier pre-game state
        np.testing.assert_allclose(N.decayed_sums(X2, pid, se, 1.0)[0][:3], pre[:3])

    def test_shrunk_rate(self):
        self.assertAlmostEqual(float(N.shrunk_rate(0.0, 0.0, 0.5, 30.0)), 0.5)
        self.assertAlmostEqual(float(N.shrunk_rate(30.0, 30.0, 0.5, 30.0)), 0.75)

    def test_online_level_uses_strictly_earlier_dates_only(self):
        d = ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03"]; g = [0, 0, 0, 0]
        a = np.array([10.0, 10.0, 30.0, 5.0]); f = np.array([8.0, 8.0, 10.0, 5.0])
        r = N.online_level(d, g, a, f, k=4.0)
        np.testing.assert_allclose(r, [1.0, 1.0, 24.0 / 20.0, 54.0 / 30.0])
        a2 = a.copy(); a2[3] = 500.0                                            # a future outcome must not move earlier rows
        np.testing.assert_allclose(N.online_level(d, g, a2, f, k=4.0)[:3], r[:3])
        ad = N.online_level(d, g, a, f, k=2.0, additive=True)
        np.testing.assert_allclose(ad, [0.0, 0.0, 4.0 / 4.0, 24.0 / 5.0])
        r2 = N.online_level(d, [0, 0, 1, 1], a, f, k=4.0)                       # a new group (season) starts again at 1
        self.assertEqual(r2[2], 1.0)
        nan = N.online_level(d, g, np.array([np.nan, 10.0, 30.0, 5.0]), f, k=4.0)
        self.assertAlmostEqual(nan[2], 14.0 / 12.0)                             # rows without an outcome are ignored

    def test_poisson_beta_recovers_a_planted_effect(self):
        rng = np.random.default_rng(0); x = rng.normal(size=20000); f = rng.uniform(5, 15, size=20000)
        y = rng.poisson(f * np.exp(0.1 * x))
        self.assertAlmostEqual(N.poisson_beta(y, f, x), 0.1, delta=0.01)

    def test_tilt_pmf_hits_target_mean_and_is_identity_at_own_mean(self):
        p = np.array([[0.1, 0.2, 0.4, 0.2, 0.1], [0.5, 0.3, 0.2, 0.0, 0.0]]); k = np.arange(5.0)
        t = N.tilt_pmf(p, np.array([2.5, 0.5]))
        np.testing.assert_allclose(t.sum(1), 1.0); np.testing.assert_allclose(t @ k, [2.5, 0.5], atol=1e-6)
        np.testing.assert_allclose(N.tilt_pmf(p, p @ k), p, atol=1e-9)
        self.assertEqual(t[1, 3], 0.0)                                          # zero-mass support stays zero

    def test_shift_pmf_moves_mean_exactly(self):
        lo, p = N.shift_pmf(100, [0.25, 0.5, 0.25], -2.3)
        self.assertAlmostEqual(float(np.sum(p)), 1.0)
        self.assertAlmostEqual(float(p @ (np.arange(len(p)) + lo)), 101.0 - 2.3)
        lo0, p0 = N.shift_pmf(100, [0.25, 0.5, 0.25], 0.0)
        self.assertEqual(lo0, 100); np.testing.assert_allclose(p0[:3], [0.25, 0.5, 0.25])

    def test_parse_board_ticker(self):
        a = N.parse_board_ticker("KXNBAPTS-26NOV10MIAUTA-UTADPETERSON22-30")
        self.assertEqual((a["date"], a["away"], a["home"], a["side"], a["code"], a["k"]), ("2026-11-10", "MIA", "UTA", "UTA", "UTADPETERSON22", 30))
        b = N.parse_board_ticker("KXNBASPREAD-26NOV01BKNIND-BKN10")
        self.assertEqual((b["side"], b["k"], b["code"]), ("BKN", 10, None))
        c = N.parse_board_ticker("KXNBATOTAL-26NOV01BKNIND-203")
        self.assertEqual((c["side"], c["k"]), (None, 203))
        self.assertEqual(N.parse_board_ticker("KXNBAGAME-26NOV01BKNIND-IND")["side"], "IND")
        self.assertIsNone(N.parse_board_ticker("KXNBA1H-26NOV01BKNIND-IND"))
        self.assertIsNone(N.parse_board_ticker("garbage"))

    def test_quote_class(self):
        self.assertEqual(N.quote_class("active", 10, 12), "TWO_SIDED")
        self.assertEqual(N.quote_class("active", None, 12), "ONE_SIDED")
        self.assertEqual(N.quote_class("initialized", 10, 12), "ONE_SIDED")
        self.assertEqual(N.quote_class("active", None, None), "NO_QUOTE")

    def test_board_delta_and_chain_rules(self):
        keep = lambda t: t.startswith("KXNBAPTS")
        board = {"KXNBAPTS-A": {"status": "active", "_quote_cents": {"yes_bid": 10, "yes_ask": 12}}}
        ok = N.apply_board_delta(board, {"removed": [], "added": {"KXNBAPTS-B": {"status": "active", "junk": 1}, "OTHER-X": {"status": "active"}},
                                         "changed": {"KXNBAPTS-A": {"_quote_cents": {"yes_bid": 11, "yes_ask": 12}, "volume_fp": "9"}}, "cleared": {}}, keep)
        self.assertTrue(ok); self.assertEqual(board["KXNBAPTS-A"]["_quote_cents"]["yes_bid"], 11)
        self.assertNotIn("OTHER-X", board); self.assertNotIn("junk", board["KXNBAPTS-B"]); self.assertNotIn("volume_fp", board["KXNBAPTS-A"])
        self.assertFalse(N.apply_board_delta(board, {"changed": {"KXNBAPTS-MISSING": {"status": "closed"}}}, keep))    # change to an absent ticker = broken chain
        N.apply_board_delta(board, {"removed": ["KXNBAPTS-B"]}, keep); self.assertNotIn("KXNBAPTS-B", board)
        self.assertTrue(N.chain_ok([1, 2, 3], ["p0", "b1", "b2"], ["b1", "b2", "b3"]))
        self.assertFalse(N.chain_ok([1, 3], ["p0", "b1"], ["b1", "b3"]))                                               # sequence gap
        self.assertFalse(N.chain_ok([1, 2], ["p0", "zz"], ["b1", "b2"]))                                               # parent hash mismatch
        self.assertTrue(N.chain_ok([], [], []))

    def test_unify_market_prefers_owner_snapshot_and_fills_only_missing_games(self):
        cols = dict(family="player_points", series="KXNBAPTS", tip_ts=0, obs_ts=0, player_id="p", team="A", side_team="A", stat="points", threshold=9.5, k=10.0,
                    comparator="gt", quote_class="TWO_SIDED", yes_bid=0.4, yes_ask=0.5, no_ask=0.6, support="x")
        pd_ = pd.DataFrame([dict(cols, ticker="t1", game_id="g1")])
        da = pd.DataFrame([dict(cols, ticker="t1", game_id="g1", source="data-archive_restored", n_deltas=0),
                           dict(cols, ticker="t2", game_id="g2", source="data-archive_restored", n_deltas=3)])
        M = N.unify_market(pd_, da)
        self.assertEqual(sorted(zip(M.ticker, M.source)), [("t1", "projection-data_T-60"), ("t2", "data-archive_restored")])

    def test_opponent_lookup_is_strictly_earlier(self):
        d = pd.DataFrame(dict(opp_team_id=[7, 7, 7], date=pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-05"])))
        tab = N.opponent_table(d, np.array([20.0, 10.0, 10.0]), np.array([10.0, 10.0, 10.0]), halflife=20.0, k_games=1.0)
        r = N.opponent_lookup(tab, [7, 7, 7, 9], pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-04", "2026-01-04"]))
        self.assertEqual(r[0], 1.0)                                              # nothing before its first game
        self.assertAlmostEqual(r[1], (1 * 2.0 + 1.0) / 2.0)                      # only the 01-01 game (allowed 2x expected), shrunk by one game
        self.assertEqual(r[1] > r[2] > 1.0, True); self.assertEqual(r[3], 1.0)   # unknown opponent -> neutral

    def test_results_replication_uses_the_cohorts_passed(self):
        R = N.Results(); rng = np.random.default_rng(1); n = 400
        cl = np.arange(n) // 4; a = rng.normal(-0.2, 1, n); z = np.zeros(n)
        m = {N.H1: np.arange(n) < 200, N.H2: np.arange(n) >= 200, N.HP: np.ones(n, bool)}
        R.add("player_points", ["NBA:player_points"], "m", "H_x", "ref", a, z, cl, m, cohorts=(N.H1, N.H2, N.HP))
        rows = R.finalize(); pooled = [r for r in rows if r["cohort"] == N.HP][0]
        self.assertTrue(pooled["replicated"]); self.assertEqual(pooled["verdict"], C.verdict_from(pooled["ci95"][0], pooled["ci95"][1], pooled["p_holm"], True))
        self.assertNotIn("_pair", pooled)


class CommittedEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text()); cls.lin = json.loads(N.LINEAGE_PATH.read_text())

    def test_contract_and_identity(self):
        self.assertEqual(C.validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], N.CHALLENGER_ID); self.assertEqual(self.doc["status"], "RESEARCH_ONLY")
        self.assertTrue(self.doc["verdict"]["retain_incumbent"])

    def test_every_row_obeys_the_promotion_rule(self):
        for r in self.doc["results"]:
            self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            if r["verdict"] == "VALIDATED_IMPROVEMENT":
                self.assertTrue(r["ci95"][1] < 0 and r["p_holm"] < 0.05 and r["replicated"])
        for a in self.doc["ablations"]:
            self.assertEqual(a["verdict"], C.verdict_from(a["ci95"][0], a["ci95"][1], a["p_holm"], a["replicated"]))
            self.assertEqual(a["decision"].startswith("eligible"), a["verdict"] == "VALIDATED_IMPROVEMENT")

    def test_overall_verdict_is_consistent_with_headline_rows_and_market(self):
        head = [r for r in self.doc["results"] if r.get("headline")]
        self.assertEqual(len(head), self.doc["design"]["headline_rows"])
        self.assertTrue(all(r["reference"] == "pf_frozen" and r["cohort"] == N.POOLED for r in head))
        all_val = all(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in head)
        worse = [r for r in self.doc["results"] if r["challenger_arm"] == N.ARM and r["reference"] == "kalshi_t60_mid" and r["cohort"] == N.POOLED and r["verdict"] == "NOT_IMPROVED"]
        if self.doc["verdict"]["overall"] == "VALIDATED_IMPROVEMENT":
            self.assertTrue(all_val and not worse)
        # nothing may be reported as beating the market unless a row says so
        beats = [r for r in self.doc["results"] if r["reference"] == "kalshi_t60_mid" and r["verdict"] == "VALIDATED_IMPROVEMENT"]
        self.assertEqual(beats, [])

    def test_checks_are_computed_and_passed(self):
        n = 0
        for f in self.doc["features"]:
            for c in f["checks"]:
                n += 1
                self.assertEqual(c["basis"], "COMPUTED", c["name"]); self.assertTrue(c["passed"], c["name"]); self.assertTrue(len(c["detail"]) > 20)
        self.assertGreaterEqual(n, 12)

    def test_no_raw_rows_and_market_restoration_counts(self):
        txt = EVAL.read_text() + SUMM.read_text() + N.LINEAGE_PATH.read_text()
        self.assertNotIn("espn:", txt); self.assertNotIn("KXNBA", txt.replace("KXNBAPTS-26NOV10MIAUTA", ""))
        mr = self.doc["design"]["market_restoration"]
        self.assertEqual(mr["of_those_with_projection_data_t60_rows"], 0)
        self.assertEqual(mr["games_after_2026_11_06"], mr["of_those_with_restored_board"] + mr["of_those_without_any_board"])
        self.assertEqual(mr["stats"]["chain_refused"], 0)
        self.assertGreater(mr["test_games_with_two_sided_prop_quotes"][N.COH2], 0)

    def test_bias_decomposition_adds_up_and_sign_is_stated(self):
        tp = self.doc["design"]["diagnosis"]["team_points"]
        for blk in [tp["all"], *tp["by_week"].values()]:
            self.assertAlmostEqual(sum(blk["parts"].values()), blk["forecast_minus_actual"], places=4)
            self.assertAlmostEqual(blk["mean_forecast"] - blk["mean_actual"], blk["forecast_minus_actual"], places=4)
        self.assertGreater(tp["all"]["forecast_minus_actual"], 0)                # the frozen model OVER-forecasts 2026-27 team points
        self.assertIn("positive", self.doc["design"]["diagnosis"]["sign_convention"])

    def test_lineage_artifact(self):
        L = self.lin
        self.assertEqual(L["status"], "RESEARCH_ONLY"); self.assertEqual(L["n_model_versions"], len(L["runs"]))
        self.assertEqual(L["n_revisions_found_in_repo"], L["n_model_versions"])
        self.assertEqual(L["n_forecast_code_changes"], sum(bool(r.get("forecast_code_changed")) for r in L["runs"]))
        self.assertEqual(L["n_segments"], L["n_forecast_code_changes"] + 1)
        segs = [r["segment"] for r in L["runs"]]; self.assertEqual(segs, sorted(segs))
        for r in L["runs"]:
            self.assertEqual(r["model_version"].split("+")[1], r["short_sha"]); self.assertTrue(r["commit"].startswith(r["short_sha"]))
            self.assertEqual(bool(r["forecast_code_changed"]), bool(r["model_files_changed_since_previous"]))
        self.assertEqual(sum(s["n_played_rows"] for s in L["segments"]), self.doc["design"]["cohort_sizes"][N.POOLED]["played_rows"] + self.doc["design"]["cohort_sizes"]["train"]["played_rows"])


class EndToEnd(unittest.TestCase):
    def test_rerun_is_byte_identical(self):
        repo = F.repo_path()
        if not (repo.exists() and all(F.has_commit(repo, c) for c in (F.PD_COMMIT, F.MAIN_COMMIT, N.DA_COMMIT))):
            self.skipTest("owner clone with pinned commits not present")
        with tempfile.TemporaryDirectory() as td:
            N.evaluate(repo, Path(td), verbose=False)
            self.assertEqual((Path(td) / "evaluation.json").read_bytes(), EVAL.read_bytes())
            self.assertEqual((Path(td) / "predictions_summary.json").read_bytes(), SUMM.read_bytes())
            self.assertEqual((Path(td) / "pf_version_lineage.json").read_bytes(), N.LINEAGE_PATH.read_bytes())


if __name__ == "__main__":
    unittest.main()

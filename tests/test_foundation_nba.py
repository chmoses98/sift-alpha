"""NBA availability challenger (alpha-nba-avail-0.1): unit tests on small synthetic fixtures (numpy + pandas only, no
access to the owner's repositories) plus a contract check of the committed evaluation document."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import contract as C
from alpha_engine.foundation import nba_availability as M

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "NBA" / M.CHALLENGER_ID / "evaluation.json"
SUMM = EVAL.with_name("predictions_summary.json")


def _box(rows):
    cols = ["game_id", "game_date_et", "season", "season_type", "team_id", "nba_id", "played", "minutes", "pts", "reb", "ast", "fg3m",
            "fga", "fta", "tov", "n_ot", "start_time_utc"]
    out = []
    for (g, d, team, pid, mins) in rows:
        out.append((g, d, "2025-26", "regular", team, pid, mins > 0, float(mins), int(mins // 2), int(mins // 6), int(mins // 8), int(mins // 12),
                    int(mins // 3), 2, 1, 0, d + "T23:00:00Z"))
    df = pd.DataFrame(out, columns=cols)
    df["date"] = pd.to_datetime(df.game_date_et)
    return df


class TickerParser(unittest.TestCase):
    def test_parses_series_game_player_strike(self):
        p = M.parse_prop_ticker("KXNBAPTS-25DEC01ATLDET-ATLDDANIELSSF-10")
        self.assertEqual((p["stat"], p["date"], p["away"], p["home"], p["team"], p["player_code"], p["strike"]),
                         ("pts", "2025-12-01", "ATL", "DET", "ATL", "DDANIELSSF", 10))
        p = M.parse_prop_ticker("KXNBA3PT-26APR05TORBOS-BOSJTATUM0-3")
        self.assertEqual((p["stat"], p["date"], p["team"], p["strike"]), ("fg3m", "2026-04-05", "BOS", 3))
        self.assertEqual(M.parse_prop_ticker("KXNBAREB-26MAY28OKCSAS-SASVWEMBANYAMA1-12")["home"], "SAS")

    def test_never_raises_and_rejects_foreign_shapes(self):
        for t in ["", "KXNBAGAME-26MAY22OKCSAS-OKC", "KXNBAPTS-26MAY22OKCSAS-OKCX", "KXNBAPTS-26XXX22OKCSAS-OKCSGA2-30", "KXNBAPTS-26MAY22ZZZQQQ-ZZZAB1-5",
                  "KXNBAPTS-26MAY22OKCSAS-OKCSGA2-x", None, 7]:
            self.assertIsNone(M.parse_prop_ticker(t))

    def test_name_normalisation(self):
        self.assertEqual(M.norm_name("Egor Dëmin"), M.norm_name("Egor Demin"))
        self.assertEqual(M.norm_name("Jaren Jackson Jr."), "jaren jackson")
        self.assertEqual(M.norm_name("Shai Gilgeous-Alexander"), "shai gilgeous alexander")


class PitReportSelection(unittest.TestCase):
    def setUp(self):
        self.games = pd.DataFrame({"game_id": ["g1", "g2", "g3"], "tip_utc": ["2026-02-01T00:00:00Z", "2026-02-01T02:00:00Z", "2026-02-03T00:00:00Z"]})
        r = [  # game, team, player, status, report time
            ("g1", 1, 10.0, "questionable", "2026-01-31T21:30:00Z"),
            ("g1", 1, 10.0, "out", "2026-01-31T22:30:00Z"),          # latest report at/before T-60 (23:00)
            ("g1", 1, 11.0, "probable", "2026-01-31T22:30:00Z"),
            ("g1", 1, 11.0, "doubtful", "2026-01-31T22:30:00Z"),      # duplicate -> most severe
            ("g1", 1, np.nan, "out", "2026-01-31T22:30:00Z"),         # unmatched player row
            ("g1", 2, np.nan, "not_yet_submitted", "2026-01-31T22:30:00Z"),
            ("g1", 1, 10.0, "available", "2026-01-31T23:30:00Z"),     # after the freeze: must be ignored
            ("g2", 3, 30.0, "out", "2026-01-31T22:30:00Z"),
            ("g2", 3, 30.0, "available", "2026-02-01T01:00:00Z"),     # exactly T-60 for g2
            ("g3", 5, 50.0, "out", "2026-02-01T00:00:00Z"),           # 47h before g3's cutoff: stale
        ]
        self.rows = pd.DataFrame(r, columns=["game_id", "team_id", "nba_id", "status", "report_time_utc"])

    def test_latest_report_at_or_before_freeze_only(self):
        sel, players, teams = M.select_pit_status(self.rows, self.games)
        st = {(g, i): s for g, i, s in zip(players.game_id, players.nba_id, players.status)}
        self.assertEqual(st[("g1", 10)], "out")          # not the later 'available'
        self.assertEqual(st[("g1", 11)], "doubtful")
        self.assertEqual(st[("g2", 30)], "available")    # report_time == tip-60 is admissible
        self.assertNotIn(("g3", 50), st)
        s = sel.set_index("game_id")
        self.assertTrue((s.report_ts[s.report_ts >= 0] <= s.cutoff_ts[s.report_ts >= 0]).all())
        self.assertEqual(int(s.loc["g3", "report_ts"]), -1)
        self.assertEqual(float(s.loc["g1", "lead_min"]), 90.0)
        self.assertEqual(teams.values.tolist(), [["g1", 2]])
        self.assertEqual(len(players), 3)

    def test_publication_time_after_freeze_is_excluded(self):
        rows = self.rows.copy()
        rows["published_utc"] = rows.report_time_utc
        rows.loc[rows.report_time_utc == "2026-02-01T01:00:00Z", "published_utc"] = "2026-02-01T01:00:04Z"   # 4 s late
        _, players, _ = M.select_pit_status(rows, self.games)
        st = {(g, i): s for g, i, s in zip(players.game_id, players.nba_id, players.status)}
        self.assertEqual(st[("g2", 30)], "out")

    def test_later_information_never_changes_the_selection(self):
        extra = pd.DataFrame([("g1", 1, 12.0, "out", "2026-02-01T00:30:00Z")], columns=self.rows.columns)
        a = M.select_pit_status(self.rows, self.games)[1]
        b = M.select_pit_status(pd.concat([self.rows, extra], ignore_index=True), self.games)[1]
        pd.testing.assert_frame_equal(a, b)


class MinutesRedistribution(unittest.TestCase):
    def test_conserves_240_expected_team_minutes(self):
        rng = np.random.default_rng(3)
        for gamma in (-0.5, 0.0, 1.0, 2.0):
            for _ in range(25):
                n = int(rng.integers(9, 16))
                m = rng.uniform(4, 38, n); p = rng.uniform(0.002, 0.998, n)
                out = M.redistribute_minutes(p, m, 240.0, gamma)
                if np.sum(p * 48.0) > 240.0:
                    self.assertAlmostEqual(float(np.sum(p * out)), 240.0, places=6)
                self.assertTrue((out <= 48.0 + 1e-12).all() and (out >= 0).all())

    def test_vacated_minutes_flow_to_remaining_players(self):
        m = np.array([36, 34, 32, 30, 28, 24, 20, 16, 12, 8.0])
        healthy = M.redistribute_minutes(np.full(10, 0.999), m, 240.0, 1.0)
        p = np.full(10, 0.999); p[0] = 0.002                                   # star ruled out
        star_out = M.redistribute_minutes(p, m, 240.0, 1.0)
        self.assertTrue((star_out[1:] > healthy[1:]).all())
        self.assertAlmostEqual(float(np.sum(p * star_out)), 240.0, places=6)
        self.assertTrue(np.all(np.diff(star_out[1:]) <= 1e-9))                 # ordering kept

    def test_unreachable_target_returns_cap(self):
        out = M.redistribute_minutes(np.full(4, 0.9), np.array([30, 30, 30, 30.0]), 240.0, 1.0)
        self.assertTrue(np.allclose(out, 48.0))


class PmfBuilder(unittest.TestCase):
    def test_nb_pmf_moments_and_poisson_limit(self):
        pm = M.nb_pmf([12.0], 0.2, 150)[0]; k = np.arange(151)
        mean = float(pm @ k); var = float(pm @ (k - mean) ** 2)
        self.assertAlmostEqual(float(pm.sum()), 1.0, places=12)
        self.assertAlmostEqual(mean, 12.0, places=4)
        self.assertAlmostEqual(var, 12.0 + 0.2 * 144.0, places=2)
        po = M.nb_pmf([3.0], 0.0, 60)[0]
        self.assertAlmostEqual(float(po[0]), float(np.exp(-3.0)), places=10)

    def test_hurdle_mixture_and_coherent_ladder(self):
        p = np.array([0.25, 1.0]); rate = np.array([0.5, 0.5])
        scen = np.array([[20.0, 30.0, 40.0], [20.0, 30.0, 40.0]])
        unc, cond = M.build_pmf(p, rate, scen, 0.1, 80)
        self.assertTrue(np.allclose(unc.sum(1), 1.0) and np.allclose(cond.sum(1), 1.0))
        k = np.arange(81)
        self.assertAlmostEqual(float(cond[0] @ k), 15.0, places=3)                 # mean of the minutes mixture x rate
        self.assertAlmostEqual(float(unc[0] @ k), 0.25 * 15.0, places=3)
        self.assertAlmostEqual(float(unc[0, 0]), 0.75 + 0.25 * float(cond[0, 0]), places=12)
        np.testing.assert_allclose(unc[1], cond[1])
        ladder = np.array([M.sf_at(cond[[1]], [s])[0] for s in (0, 5, 10, 15, 20, 25, 30)])
        self.assertEqual(ladder[0], 1.0)
        self.assertTrue(np.all(np.diff(ladder) < 0))                               # whole strike ladder is monotone
        self.assertAlmostEqual(float(M.sf_at(cond[[1]], [10])[0]), float(cond[1, 10:].sum()), places=12)
        self.assertAlmostEqual(C.crps_pmf(unc[0], 0), float(M.crps_rows(unc[[0]], [0])[0]), places=12)

    def test_mass_above_support_is_folded(self):
        pm = M.nb_pmf([40.0], 0.1, 20)[0]
        self.assertAlmostEqual(float(pm.sum()), 1.0, places=12)
        self.assertGreater(pm[-1], 0.9)


class PopulationAndFits(unittest.TestCase):
    def _fixture(self, target_minutes):
        rows = []
        for i in range(6):                                   # six earlier team games
            d = f"2026-01-{10 + i:02d}"
            rows += [(f"g{i}", d, 1, 100, 30 + i), (f"g{i}", d, 1, 101, 0 if i >= 3 else 20), (f"g{i}", d, 1, 102, 10)]
        rows += [("gT", "2026-01-20", 1, 100, target_minutes), ("gT", "2026-01-20", 1, 102, 12)]   # 101 absent from the box
        return _box(rows)

    def test_population_keeps_absent_players_and_ignores_target_outcome(self):
        outs = []
        for tm in (0, 44):
            pg = self._fixture(tm)
            pop = M.attach_features(M.build_population(pg), pg, M.player_states(pg, [2.0]))
            t = pop[pop.game_id == "gT"].set_index("nba_id")
            self.assertEqual(sorted(t.index), [100, 101, 102])                     # 101 (no box row) is still projected
            self.assertFalse(bool(t.loc[101, "y_play"])); self.assertEqual(float(t.loc[101, "y_min"]), 0.0)
            self.assertEqual(float(t.loc[100, "y_min"]), float(tm))
            self.assertTrue((t.state_date < t.date).all())
            outs.append(t[["em_2.0", "S_pts", "S_minutes", "use_share", "n_win"] + [f"b{i}" for i in range(M.WINDOW)]])
        pd.testing.assert_frame_equal(outs[0], outs[1])                            # features identical whatever happens in gT
        bits = outs[0].loc[[101], [f"b{i}" for i in range(M.WINDOW)]].to_numpy(float)
        self.assertEqual(bits[0, :6].tolist(), [0, 0, 0, 1, 1, 1])                 # most recent game first
        self.assertTrue(np.isnan(bits[0, 6:]).all())
        p_flat = M.a0_prob(bits, 1.0, 0.0, 0.7)[0]; p_rec = M.a0_prob(bits, 0.5, 0.0, 0.7)[0]
        self.assertAlmostEqual(p_flat, 0.5); self.assertLess(p_rec, p_flat)
        self.assertAlmostEqual(M.a0_prob(bits, 1.0, 6.0, 0.7)[0], (3 + 6 * 0.7) / 12)

    def test_fit_logit_recovers_base_rate(self):
        rng = np.random.default_rng(1)
        x = rng.normal(1.0, 1.5, 600); y = (rng.random(600) < 0.57).astype(float)
        a, b = M.fit_logit(x, y)
        self.assertAlmostEqual(float(np.mean(1 / (1 + np.exp(-(a + b * x))))), float(y.mean()), places=3)


class CommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid(self):
        self.assertEqual(C.validate_evaluation(self.doc), [])
        self.assertEqual(self.doc["challenger_id"], "alpha-nba-avail-0.1")
        self.assertEqual(self.doc["sport"], "NBA")
        self.assertTrue(self.doc["verdict"]["retain_incumbent"])

    def test_every_verdict_follows_the_preregistered_rule(self):
        self.assertGreater(len(self.doc["results"]), 50)
        for r in self.doc["results"]:
            self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            self.assertAlmostEqual(r["diff"], r["challenger"] - r["reference_value"], places=4)
            if not r["headline"]:
                self.assertEqual(r["p_holm"], 1.0)
        head = [r for r in self.doc["results"] if r["headline"]]
        self.assertTrue(all(r["cohort"] == "test_pooled" for r in head))
        for r, ph in zip(head, C.holm([r["p_raw"] for r in head])):
            self.assertAlmostEqual(r["p_holm"], ph, places=6)
        for a in self.doc["ablations"]:
            self.assertEqual(a["verdict"], C.verdict_from(a["ci95"][0], a["ci95"][1], a["p_holm"], a["replicated"]))

    def test_stage_claims_do_not_outrun_ablations(self):
        ok = {c for a in self.doc["ablations"] if a["verdict"] == "VALIDATED_IMPROVEMENT" for c in a["catalog_inputs"]}
        bad = {c for a in self.doc["ablations"] if a["verdict"] != "VALIDATED_IMPROVEMENT" for c in a["catalog_inputs"]}
        for c in self.doc["input_stage_claims"]:
            if c["stage"] == "VALIDATED_IMPROVEMENT":
                self.assertIn(c["input"], ok); self.assertNotIn(c["input"], bad)
        for d in self.doc["data"]:
            self.assertEqual(d["rights_tier"], "UNRESOLVED_INTERNAL_ONLY")

    def test_no_raw_rows_in_committed_outputs(self):
        for path in (EVAL, SUMM):
            txt = path.read_text()
            self.assertNotIn('"nba_id"', txt); self.assertNotIn('"player_name"', txt); self.assertNotIn("KXNBAPTS-", txt)
        s = json.loads(SUMM.read_text())
        self.assertEqual({r["status"] for r in s["play_rate_by_t60_status"]}, set(M.STATUS_ORDER))


if __name__ == "__main__":
    unittest.main()

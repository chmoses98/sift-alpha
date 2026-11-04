"""Tests for the CBB / soccer / tennis outcome-intelligence audits: leakage, time windows, settlement derivation, dedup, controls."""
import os, sys, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "outcome_intel"))
import incremental as I
import cbb_common as C
import cbb_audit as CB
import soccer_audit as SO
try:
    import tennis_audit as TE
except Exception:       # tennis module optional while it is being built
    TE = None


def synth(n_games=90, per=10, seed=3, informative=True):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for _ in range(per):
            true = rng.uniform(0.15, 0.85)
            y = int(rng.random() < true)
            mid = float(np.clip(true + rng.normal(0, 0.10), .03, .97))
            q = float(np.clip(true + rng.normal(0, 0.03), .03, .97)) if informative else float(rng.uniform(.1, .9))
            rows.append(dict(game=f"g{g}", t=f"2026-09-{1 + g // 4:02d}T{g % 4:02d}:00", mid=mid, q=q, y=y))
    return rows


class TestCBBSettlementDerivation(unittest.TestCase):
    def row(self, mt, per="FULL", side=None, strike=None, d="greater"):
        return dict(mt=mt, per=per, side=side, strike=strike, dirn=d)

    def test_winner_home_away_tie(self):
        self.assertEqual(CB.derive_y(self.row("WINNER", side="home"), (70, 60), None), 1)
        self.assertEqual(CB.derive_y(self.row("WINNER", side="away"), (70, 60), None), 0)
        self.assertEqual(CB.derive_y(self.row("WINNER", side="tie", per="1H"), None, dict(first_half_home=30, first_half_away=30, final_home=70, final_away=60)), 1)
        self.assertEqual(CB.derive_y(self.row("WINNER", side="tie", per="1H"), (70, 60), dict(first_half_home=31, first_half_away=30, final_home=70, final_away=60)), 0)

    def test_tied_half_winner_is_not_a_binary_for_home_or_away(self):
        per = dict(first_half_home=30, first_half_away=30, final_home=70, final_away=60)
        self.assertIsNone(CB.derive_y(self.row("WINNER", side="home", per="1H"), (70, 60), per))

    def test_margin_and_total_are_strict_inequalities_on_half_points(self):
        self.assertEqual(CB.derive_y(self.row("MARGIN", side="home", strike=9.5), (70, 60), None), 1)
        self.assertEqual(CB.derive_y(self.row("MARGIN", side="home", strike=10.5), (70, 60), None), 0)
        self.assertEqual(CB.derive_y(self.row("MARGIN", side="away", strike=-0.5 + 0.0), (70, 60), None), 0)
        self.assertEqual(CB.derive_y(self.row("TOTAL", strike=129.5), (70, 60), None), 1)
        self.assertEqual(CB.derive_y(self.row("TOTAL", strike=130.5), (70, 60), None), 0)

    def test_second_half_includes_overtime(self):
        per = dict(first_half_home=30, first_half_away=35, final_home=85, final_away=80, overtime_home=10, overtime_away=5)
        # 2H points = final - 1H = 55 vs 45 (OT included, as the Kalshi rules say)
        self.assertEqual(CB.derive_y(self.row("TOTAL", per="2H", strike=99.5), (85, 80), per), 1)
        self.assertEqual(CB.derive_y(self.row("TOTAL", per="2H", strike=100.5), (85, 80), per), 0)

    def test_missing_scores_never_default_to_a_result(self):
        self.assertIsNone(CB.derive_y(self.row("WINNER", side="home"), None, None))
        self.assertIsNone(CB.derive_y(self.row("WINNER", per="1H", side="home"), (70, 60), None))
        self.assertIsNone(CB.derive_y(self.row("TEAM_TOTAL", side="home", strike=50.5, d="less"), (70, 60), None))

    def test_scalar_result_is_not_binary(self):
        self.assertIsNone(CB.kalshi_y("scalar"))
        self.assertIsNone(CB.kalshi_y(""))
        self.assertEqual(CB.kalshi_y("yes"), 1)


class TestCBBTimeWindow(unittest.TestCase):
    def mk(self, cap, start="2026-11-03T00:00:00+00:00", yb=0.4, ya=0.45, tk="T1"):
        return dict(tk=tk, cap=cap, start=start, gid=1, yb=yb, ya=ya, fam="SPREAD", mt="MARGIN", sstat="parsed")

    def test_only_pre_tip_quote_in_window_is_picked_and_post_tip_never(self):
        rows = [self.mk("2026-11-02T00:00:00+00:00"),       # 24h before
                self.mk("2026-11-02T23:30:00+00:00"),       # 0.5h before  -> CLOSE
                self.mk("2026-11-03T00:10:00+00:00", yb=0.9, ya=0.95)]   # post-tip: leakage if used
        picked, cnt = CB.pick_quotes(rows)
        self.assertEqual({p["h"] for p in picked}, {"H24", "CLOSE"})
        self.assertTrue(all(C.pdt(p["cap"]) < C.pdt(p["start"]) for p in picked))
        self.assertTrue(all(p["yb"] < 0.5 for p in picked))

    def test_latest_in_window_wins_and_one_row_per_ticker_horizon(self):
        rows = [self.mk("2026-11-02T00:00:00+00:00", yb=0.3, ya=0.35), self.mk("2026-11-01T22:00:00+00:00", yb=0.1, ya=0.15)]
        picked, _ = CB.pick_quotes(rows)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["yb"], 0.3)

    def test_wide_or_one_sided_quotes_are_dropped(self):
        picked, cnt = CB.pick_quotes([self.mk("2026-11-02T00:00:00+00:00", yb=0.1, ya=0.4)])
        self.assertEqual(picked, [])
        picked, cnt = CB.pick_quotes([self.mk("2026-11-02T00:00:00+00:00", yb=0.0, ya=0.05)])
        self.assertEqual(picked, [])

    def test_model_prob_recompute_matches_normal_formula(self):
        r = dict(sstat="parsed", mt="MARGIN", per="FULL", side="away", strike=3.5, mu={"v": (10.0, 12.0, 150.0, 16.0)})
        self.assertAlmostEqual(CB.recompute_model_prob(r, "v"), C.phi((-10.0 - 3.5) / 12.0))
        r2 = dict(sstat="parsed", mt="TOTAL", per="FULL", side=None, strike=140.5, mu={"v": (10.0, 12.0, 150.0, 16.0)})
        self.assertAlmostEqual(CB.recompute_model_prob(r2, "v"), C.phi((150.0 - 140.5) / 16.0))
        self.assertIsNone(CB.recompute_model_prob(dict(r, sstat="unsupported_series"), "v"))


class TestSoccerDerivationAndDedup(unittest.TestCase):
    def p(self, fam, per="regulation", side=None, line=None, desc=""):
        return dict(fam=fam, sem=dict(period=per, side=side, line=line, description=desc))

    def test_families(self):
        self.assertEqual(SO.derive(self.p("match_result_3way", side="draw"), (1, 1), {}), 1)
        self.assertEqual(SO.derive(self.p("match_result_3way", side="home"), (1, 1), {}), 0)
        self.assertEqual(SO.derive(self.p("total_goals", line="2.5"), (2, 1), {}), 1)
        self.assertEqual(SO.derive(self.p("total_goals", line="3.5"), (2, 1), {}), 0)
        self.assertEqual(SO.derive(self.p("team_total", side="away", line="0.5"), (2, 0), {}), 0)
        self.assertEqual(SO.derive(self.p("handicap", side="away", line="1.5"), (0, 2), {}), 1)
        self.assertEqual(SO.derive(self.p("handicap", side="home", line="1.5"), (2, 1), {}), 0)
        self.assertEqual(SO.derive(self.p("btts"), (1, 1), {}), 1)
        self.assertEqual(SO.derive(self.p("btts"), (2, 0), {}), 0)
        self.assertEqual(SO.derive(self.p("exact_score", desc="Exact score 2-1 (home-away)"), (2, 1), {}), 1)

    def test_first_half_uses_only_period_score_never_full_time(self):
        self.assertEqual(SO.derive(self.p("first_half_result", per="first_half", side="draw"), (3, 0), {"first_half": (0, 0)}), 1)
        self.assertIsNone(SO.derive(self.p("first_half_result", per="first_half", side="draw"), (3, 0), {}))

    def test_unknown_family_not_derived(self):
        self.assertIsNone(SO.derive(self.p("first_to_score", per="including_extra_time", side="home"), (1, 0), {}))

    def test_matchday_suffix_stripped_for_result_join(self):
        self.assertEqual(SO.base_fixture("fx:ger.bundesliga:2026-27:ger.freiburg:ger.schalke:matchday_5"), "fx:ger.bundesliga:2026-27:ger.freiburg:ger.schalke")

    def rec(self, as_of, q=0.5, ko="2026-10-10T15:00:00Z", mkt="2026-10-10T10:00:00Z", yb=0.4, ya=0.45, y=1, yd=1, tk="T"):
        return dict(tk=tk, hz="T-24h", mf="m", eng="e", fam="total_goals", as_of=as_of, ko=ko, mkt_as_of=mkt, yb=yb, ya=ya, q=q, y=y, yd=yd)

    def test_dedupe_keeps_latest_pre_kickoff_by_time_only(self):
        a = self.rec("2026-10-10T09:00:00Z", q=0.2, y=0, yd=0)
        b = self.rec("2026-10-10T10:00:00Z", q=0.7, y=0, yd=0)
        best = SO.select_rows([a, b], __import__("collections").Counter())
        self.assertEqual(len(best), 1)
        self.assertEqual(list(best.values())[0]["q"], 0.7)

    def test_post_kickoff_prediction_or_quote_rejected_and_disagreeing_settlement_dropped(self):
        import collections
        cnt = collections.Counter()
        self.assertEqual(SO.select_rows([self.rec("2026-10-10T15:30:00Z")], cnt), {})
        self.assertEqual(SO.select_rows([self.rec("2026-10-10T10:00:00Z", mkt="2026-10-10T16:00:00Z")], cnt), {})
        self.assertEqual(SO.select_rows([self.rec("2026-10-10T10:00:00Z", y=1, yd=0)], cnt), {})
        self.assertEqual(SO.select_rows([self.rec("2026-10-10T10:00:00Z", yb=0.1, ya=0.5)], cnt), {})
        self.assertGreaterEqual(cnt["settlement_vs_derived_disagree"], 1)


class TestControlsAndStatus(unittest.TestCase):
    def test_positive_and_negative_controls_behave(self):
        rows = synth(informative=True)
        c = C.run_challenger(rows)
        self.assertEqual(c["status"], "OK")
        self.assertGreater(c["gain_vs_calibrated_market_logloss"]["mean"], 0)       # genuine signal detected
        self.assertLess(abs(c["negative_control_gain"]["mean"]), 0.02)              # shuffled challenger: ~0
        self.assertGreater(c["positive_control_gain"]["lo"], 0)

    def test_noise_challenger_is_not_validated(self):
        c = C.run_challenger(synth(informative=False))
        st, _ = C.classify(c, C.holm_over({"a": c}).get("a"))
        self.assertNotEqual(st, "VALIDATED_IMPROVEMENT")

    def test_underpowered_is_never_called_negative(self):
        c = C.run_challenger(synth(n_games=15, per=4))
        st, why = C.classify(c, 1.0)
        self.assertIn(st, ("INCONCLUSIVE_UNDERPOWERED",))

    def test_holm_counts_untestable_cells(self):
        ok = C.run_challenger(synth(informative=True))
        under = dict(status="UNDERPOWERED")
        h1 = C.holm_over({"a": ok})["a"]
        h2 = C.holm_over({"a": ok, "b": under, "c": under})["a"]
        self.assertGreaterEqual(h2, h1)

    def test_significant_negative_control_blocks_a_claim(self):
        g = dict(mean=0.05, lo=0.01, hi=0.09, p=0.001, n=100, n_games=50)
        c = dict(status="OK", holdout_games=50, gain_vs_calibrated_market_logloss=g, negative_control_gain=dict(mean=0.04, lo=0.01, hi=0.07, p=0.01))
        st, _ = C.classify(c, 0.01)
        self.assertEqual(st, "INVALID_EVIDENCE")

    def test_chronological_holdout_has_no_game_overlap_and_is_later(self):
        rows = synth()
        tr, te = I.split_games(rows)
        self.assertFalse(tr & te)
        first = {}
        for r in rows:
            first[r["game"]] = min(first.get(r["game"], r["t"]), r["t"])
        self.assertLessEqual(max(first[g] for g in tr), min(first[g] for g in te))


if __name__ == "__main__":
    unittest.main()

"""Conformance suite for SIFT Alpha Universal Evaluation Standard v1 (sift-alpha-eval/1). Each test names the spec rule it
enforces. Stdlib unittest (the repo's CI runs `unittest discover`). No network."""
import copy
import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpha_eval import aggregate as A, coverage as COV, scoring as S
from alpha_eval.adapters import from_pure_forecast_v1
from alpha_eval.families import classify_contract
from alpha_eval.grading import grade_all
from alpha_eval.report import build_report, to_markdown
from alpha_eval.schema import (BLOCKED, FAMILIES, GRADED, PENDING, SCHEMA_VERSION, SPORTS, STATUSES, UNSUPPORTED,
                               SchemaError, forecast_from_row)
from alpha_eval.synthetic import generate

T0 = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def fc(i, p, *, hours=6, ev="BACKTEST", ind="sports_only", version="v1", sport="NBA", fam="game_winner", mid=None, gid=None, **kw):
    start = T0 + timedelta(hours=i)
    gid = gid or f"G{i}"
    mid = mid or f"KX{sport}GAME-{gid}"
    return dict(schema=SCHEMA_VERSION, forecast_id=f"{mid}|{hours}|{version}", sport=sport, event_id=gid, market_id=mid, native_family=fam,
                model_id="m", model_version=version, model_independence=ind, frozen_at=iso(start - timedelta(hours=hours)),
                event_start=iso(start), evidence_class=ev, scoring_type="BINARY", payload=dict(p_yes=p), **kw)


def out(i, y, *, mid=None, gid=None, sport="NBA", src="sports", after_h=3):
    gid = gid or f"G{i}"
    return dict(schema=SCHEMA_VERSION, market_id=mid or f"KX{sport}GAME-{gid}", event_id=gid, state="final",
                observed_at=iso(T0 + timedelta(hours=i + after_h)), source=src, value=y)


def qt(i, bid, ask, *, hours_before=6.1, mid=None, gid=None, sport="NBA"):
    gid = gid or f"G{i}"
    return dict(schema=SCHEMA_VERSION, market_id=mid or f"KX{sport}GAME-{gid}", observed_at=iso(T0 + timedelta(hours=i) - timedelta(hours=hours_before)),
                yes_bid=bid, yes_ask=ask)


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.F, cls.O, cls.Q, cls.X = generate()
        cls.g = grade_all(cls.F, cls.O, cls.Q, cls.X)
        cls.rows = {r["forecast_id"]: r for r in cls.g["rows"]}

    def test_every_forecast_accounted_exactly_once(self):                       # §3 no silent exclusion
        self.assertEqual(len(self.g["rows"]) + len(self.g["rejects"]), len(self.F))
        self.assertEqual(self.g["n_input_forecasts"], len(self.F))

    def test_every_dimension_has_status_and_reason(self):                       # §3 explicit reasons
        for r in self.g["rows"]:
            for dim in ("accuracy", "market", "economics", "clv"):
                self.assertIn(r[dim]["status"], STATUSES)
                self.assertTrue(r[dim]["reason"])

    def test_edge_cases_get_explicit_statuses(self):
        want = {"edge-pending": (PENDING, "EVENT_NOT_FINAL"), "edge-late-freeze": (BLOCKED, "FORECAST_NOT_FROZEN_BEFORE_EVENT_START"),
                "edge-market-leak": (BLOCKED, "SPORTS_ONLY_MODEL_DECLARES_MARKET_INPUT"), "edge-combo": (UNSUPPORTED, "COMBO_REQUIRES_JOINT_DISTRIBUTION"),
                "edge-binary-on-3way": (BLOCKED, "FORECAST_PAYLOAD_INVALID")}
        for fid, (st, why) in want.items():
            a = self.rows[fid]["accuracy"]
            self.assertEqual((a["status"], a["reason"]), (st, why), fid)
        dup = [r for r in self.g["rows"] if r["accuracy"]["reason"] == "DUPLICATE_FORECAST_ID"]
        self.assertEqual(len(dup), 1)

    def test_all_scoring_types_exercised_and_nonbinary_has_no_binary_brier(self):   # §3
        seen = set()
        for r in self.g["rows"]:
            a = r["accuracy"]
            if a["status"] == GRADED:
                seen.add(r["scoring_type"])
                if r["scoring_type"] != "BINARY":
                    self.assertNotIn("brier", a)
        self.assertEqual(seen, {"BINARY", "CONTINUOUS", "ORDINAL_PMF", "CATEGORICAL"})

    def test_nonbinary_not_paired_with_market_by_binary_score(self):
        for r in self.g["rows"]:
            if r["scoring_type"] != "BINARY" and r["accuracy"]["status"] == GRADED:
                self.assertEqual(r["market"]["status"], UNSUPPORTED)

    def test_accuracy_independent_of_prices(self):                              # §4 separate accuracy from value
        g2 = grade_all(self.F, self.O, [], [])
        a1 = {r["forecast_id"]: r["accuracy"] for r in self.g["rows"]}
        a2 = {r["forecast_id"]: r["accuracy"] for r in g2["rows"]}
        self.assertEqual(a1, a2)

    def test_report_covers_required_cuts_and_does_not_pool_evidence(self):      # §5 reports
        rep = build_report(self.g, kind="cumulative")
        sec = rep["by_evidence_class"]["BACKTEST"]
        for k in ("by_sport", "by_family", "by_model_version", "by_horizon", "by_calibration_bucket", "model_vs_market_primary_grid"):
            self.assertIn(k, sec)
        self.assertNotIn("PROSPECTIVE", rep["by_evidence_class"])
        self.assertIn("Accounting", to_markdown(rep))

    def test_daily_window_filters_events(self):
        d = build_report(self.g, kind="daily", date="2026-11-03")
        self.assertTrue(0 < d["n_in_window"] < len(self.F))
        c = build_report(self.g, kind="cumulative", date="2026-11-03")
        self.assertGreaterEqual(c["n_in_window"], d["n_in_window"])

    def test_synthetic_fills_never_claim_profit(self):                          # §4
        e = A.econ_cell(self.g["rows"])
        self.assertTrue(e["profitability_claim"].startswith("NO_PROFITABILITY_CLAIM"))
        self.assertEqual(e["hypothetical_all_rows_model_side"]["label"].split(",")[0], "QUOTED_HYPOTHETICAL")


class Integrity(unittest.TestCase):
    def test_schema_version_enforced_and_counted(self):
        bad = fc(1, .5); bad["schema"] = "other/9"
        g = grade_all([bad, fc(2, .5)], [out(2, 1)])
        self.assertEqual(len(g["rejects"]), 1)
        self.assertEqual(g["rejects"][0]["accuracy"]["status"], BLOCKED)
        with self.assertRaises(SchemaError):
            forecast_from_row(bad)

    def test_naive_timestamp_refused(self):
        r = fc(1, .5); r["frozen_at"] = "2026-11-01T10:00:00"
        self.assertEqual(len(grade_all([r], [])["rejects"]), 1)

    def test_outcome_observed_before_freeze_blocks(self):
        f = fc(1, .5)
        o = out(1, 1, after_h=-8)                       # outcome stamped before the forecast froze
        self.assertEqual(grade_all([f], [o])["rows"][0]["accuracy"]["reason"], "FORECAST_FROZEN_AFTER_OUTCOME_OBSERVED")

    def test_missing_model_version_blocked(self):
        f = fc(1, .5); f["model_version"] = ""
        self.assertEqual(grade_all([f], [out(1, 1)])["rows"][0]["accuracy"]["reason"], "MODEL_VERSION_MISSING")

    def test_pit_quote_join_never_uses_later_quote(self):                       # §4 point-in-time quotes
        f, o = fc(1, .7), out(1, 1)
        early = qt(1, .40, .44, hours_before=6.2)       # before freeze (6h) -> usable
        late = qt(1, .80, .84, hours_before=1.0)        # after freeze  -> must be ignored for the entry
        r = grade_all([f], [o], [early, late])["rows"][0]
        self.assertAlmostEqual(r["market"]["p_market"], .42)
        only_late = grade_all([f], [o], [late])["rows"][0]
        self.assertEqual(only_late["market"]["reason"], "NO_PIT_QUOTE_AT_FORECAST_TIME")

    def test_stale_and_one_sided_quotes_blocked_with_reason(self):
        f, o = fc(1, .7), out(1, 1)
        self.assertEqual(grade_all([f], [o], [qt(1, .4, .44, hours_before=9)])["rows"][0]["market"]["reason"], "PIT_QUOTE_TOO_OLD")
        self.assertEqual(grade_all([f], [o], [qt(1, 0, .44)])["rows"][0]["market"]["reason"], "PIT_QUOTE_ONE_SIDED_OR_CROSSED")

    def test_market_informed_and_undeclared_models_cannot_be_independent_evidence(self):   # §4
        o, q = out(1, 1), qt(1, .4, .44)
        mi = grade_all([fc(1, .7, ind="market_informed")], [o], [q])["rows"][0]["market"]
        self.assertEqual(mi["status"], GRADED); self.assertFalse(mi["independent"])
        und = grade_all([fc(1, .7, ind=None)], [o], [q])["rows"][0]
        self.assertEqual(und["accuracy"]["status"], GRADED)
        self.assertEqual(und["market"]["reason"], "MODEL_INDEPENDENCE_UNDECLARED")

    def test_positive_disagreement_alone_is_not_a_verdict(self):               # §2
        rows = [fc(i, .9, gid=f"G{i}") for i in range(60)]
        outs = [out(i, i % 2) for i in range(60)]
        qs = [qt(i, .48, .52) for i in range(60)]
        g = grade_all(rows, outs, qs)
        cell = A.market_cell(g["rows"])
        self.assertGreater(cell["mean_signed_disagreement_model_minus_market"], .3)
        self.assertEqual(A.verdict_for(cell), "MARKET_BETTER")

    def _edge_sample(self, ev, ind, n=150):
        import random
        rng = random.Random(3)
        F, O, Q = [], [], []
        for i in range(n):
            t = rng.uniform(.05, .95)
            y = int(rng.random() < t)
            F.append(fc(i, min(max(t, .03), .97), ev=ev, ind=ind)); O.append(out(i, y))
            Q.append(qt(i, .49, .51))                    # market uninformed (0.50)
        return grade_all(F, O, Q)

    def test_model_better_needs_prospective_sports_only_and_adjusted_p(self):
        g = self._edge_sample("BACKTEST", "sports_only")
        grid = A.primary_grid(g["rows"])
        self.assertEqual(grid[0]["verdict"], "MODEL_BETTER_EXPLORATORY_NOT_CONFIRMED")
        gp = self._edge_sample("PROSPECTIVE", "sports_only")
        self.assertEqual(A.primary_grid(gp["rows"])[0]["verdict"], "MODEL_BETTER_CONFIRMED")
        gm = self._edge_sample("PROSPECTIVE", "market_informed")
        self.assertEqual(A.primary_grid(gm["rows"])[0]["verdict"], "MODEL_BETTER_EXPLORATORY_NOT_CONFIRMED")

    def test_insufficient_sample_blocks_verdict(self):
        g = self._edge_sample("PROSPECTIVE", "sports_only", n=10)
        self.assertEqual(A.primary_grid(g["rows"])[0]["verdict"], "INSUFFICIENT_SAMPLE")

    def test_multiple_comparison_adjustment_monotone(self):
        g = grade_all(*[x for x in generate()[:3]])
        grid = A.primary_grid(g["rows"])
        self.assertGreater(len(grid), 3)
        for c in grid:
            self.assertGreaterEqual(c["p_holm"] + 1e-9, c["p_raw"])
            self.assertEqual(c["n_comparisons_in_family"], len(grid))

    def test_correlated_alternates_collapse_to_one_unit_per_event(self):       # §4
        F, O, Q = [], [], []
        for i in range(40):
            gid = f"G{i}"
            for k, line in enumerate((1, 2, 3, 4, 5)):
                mid = f"KXNBATOTAL-{gid}-{line}"
                F.append(fc(i, .6, mid=mid, gid=gid, fam="total", line=line, line_role="ALTERNATE")); O.append(out(i, 1, mid=mid, gid=gid)); Q.append(qt(i, .4, .44, mid=mid, gid=gid))
        g = grade_all(F, O, Q)
        c = A.market_cell(g["rows"])
        self.assertEqual(c["n_paired_rows"], 200)
        self.assertEqual(c["n_collapsed_units"], 40)
        self.assertEqual(c["brier_delta_market_minus_model"]["n_clusters"], 40)
        self.assertTrue(all(r["family"] == "ALT_TOTAL" for r in g["rows"]))

    def test_hypothetical_roi_labelled_and_no_profit_claim_without_fills(self):  # §4
        F = [fc(i, .99) for i in range(60)]; O = [out(i, 1) for i in range(60)]; Q = [qt(i, .3, .34) for i in range(60)]
        g = grade_all(F, O, Q)
        e = A.econ_cell(g["rows"])
        self.assertGreater(e["hypothetical_all_rows_model_side"]["roi"]["ratio"], 1.0)      # huge hypothetical ROI
        self.assertTrue(e["profitability_claim"].startswith("NO_PROFITABILITY_CLAIM"))
        self.assertEqual(g["rows"][0]["economics"]["execution_class"], "QUOTED_HYPOTHETICAL")
        self.assertFalse(g["rows"][0]["economics"]["fill_verified"])
        self.assertEqual(g["rows"][0]["economics"]["verified_fill"]["reason"], "NO_VERIFIED_FILL")

    def test_fee_is_applied_to_hypothetical_cost(self):
        g = grade_all([fc(1, .99)], [out(1, 1)], [qt(1, .48, .52)])
        e = g["rows"][0]["economics"]
        self.assertAlmostEqual(e["price"], .52)
        self.assertAlmostEqual(e["fee"], 0.02)           # ceil_cent(0.07 * .52 * .48 * 100)/100 = 0.02
        self.assertAlmostEqual(e["pnl"], 1 - .52 - .02)

    def test_verified_fill_roi_separate_and_threshold_gated(self):
        n = 250
        F = [fc(i, .9) for i in range(n)]; O = [out(i, 1) for i in range(n)]; Q = [qt(i, .48, .52) for i in range(n)]
        X = [dict(schema=SCHEMA_VERSION, forecast_id=f"KXNBAGAME-G{i}|6|v1", market_id=f"KXNBAGAME-G{i}", side="YES", price=.52, count=1, fee=.02, is_taker=True,
                  filled_at=iso(T0 + timedelta(hours=i) - timedelta(hours=5))) for i in range(n)]
        g = grade_all(F, O, Q, X)
        e = A.econ_cell(g["rows"])
        self.assertEqual(e["verified_fills"]["n"], n)
        self.assertTrue(e["profitability_claim"].startswith("VERIFIED_FILL_EVIDENCE_POSITIVE_REQUIRES_PROSPECTIVE_REVIEW"))
        self.assertNotIn("PROFITABLE", e["profitability_claim"])
        g2 = grade_all(F, O, Q, X[:50])
        self.assertTrue(A.econ_cell(g2["rows"])["profitability_claim"].startswith("NO_PROFITABILITY_CLAIM"))

    def test_clv_is_signed_and_actual_fill_clv_is_separate(self):              # §2 CLV
        f, o = fc(1, .7), out(1, 1)
        entry = qt(1, .48, .52, hours_before=6.1)
        close_up = qt(1, .58, .62, hours_before=.2)
        r = grade_all([f], [o], [entry, close_up])["rows"][0]["clv"]
        self.assertEqual(r["side"], "YES")
        self.assertAlmostEqual(r["selection_clv"], .10); self.assertAlmostEqual(r["quoted_execution_clv"], .08)
        self.assertIsNone(r["actual_fill_clv"]); self.assertFalse(r["actual_fill_verified"])
        close_dn = qt(1, .38, .42, hours_before=.2)
        self.assertLess(grade_all([f], [o], [entry, close_dn])["rows"][0]["clv"]["selection_clv"], 0)
        fill = dict(schema=SCHEMA_VERSION, forecast_id=f["forecast_id"], market_id=f["market_id"], side="YES", price=.53, count=5, fee=.09, is_taker=True, filled_at=iso(T0))
        rf = grade_all([f], [o], [entry, close_up], [fill])["rows"][0]["clv"]
        self.assertAlmostEqual(rf["actual_fill_clv"], .07); self.assertTrue(rf["actual_fill_verified"])
        self.assertAlmostEqual(rf["quoted_execution_clv"], .08)                # quoted stays distinct from actual

    def test_clv_never_uses_post_start_quote(self):
        f, o = fc(1, .7), out(1, 1)
        post = dict(qt(1, .9, .94), observed_at=iso(T0 + timedelta(hours=1, minutes=5)))
        r = grade_all([f], [o], [qt(1, .48, .52), post])["rows"][0]["clv"]
        self.assertEqual(r["status"], BLOCKED); self.assertEqual(r["reason"], "NO_VALID_CLOSING_QUOTE")

    def test_signed_error_direction_preserved(self):                           # §2
        self.assertGreater(S.binary_row(.8, 0)["signed_error"], 0)
        self.assertLess(S.binary_row(.2, 1)["signed_error"], 0)
        self.assertGreater(S.continuous_row(30, 20)["signed_error"], 0)
        self.assertLess(S.ordinal_row({"1": .5, "2": .5}, 5)["signed_error"], 0)
        rel = S.reliability_summary([.9] * 50 + [.1] * 50, [1] * 25 + [0] * 25 + [1] * 25 + [0] * 25)   # both groups observe 0.5
        self.assertLess(rel["calibration_slope"], 0.9)
        self.assertEqual(rel["confidence_reading"], "OVERCONFIDENT")
        self.assertAlmostEqual(rel["signed_bias"], 0.0)

    def test_calibration_slope_readings(self):
        calibrated = S.reliability_summary([.9] * 100 + [.1] * 100, [1] * 90 + [0] * 10 + [1] * 10 + [0] * 90)
        self.assertEqual(calibrated["confidence_reading"], "ROUGHLY_CALIBRATED")
        under = S.reliability_summary([.6] * 100 + [.4] * 100, [1] * 90 + [0] * 10 + [1] * 10 + [0] * 90)
        self.assertEqual(under["confidence_reading"], "UNDERCONFIDENT")

    def test_calibration_buckets_keep_empty_buckets(self):
        b = S.calibration_buckets([.05, .95], [0, 1])
        self.assertEqual(len(b), 10); self.assertEqual(sum(x["n"] for x in b), 2)
        self.assertEqual(b[4]["n"], 0); self.assertIsNone(b[4]["signed_gap"])


class Scoring(unittest.TestCase):
    def test_binary_values(self):
        r = S.binary_row(.8, 1)
        self.assertAlmostEqual(r["brier"], .04); self.assertAlmostEqual(r["log"], -math.log(.8))

    def test_ordinal_crps_exact_for_point_mass(self):
        self.assertAlmostEqual(S.ordinal_row({"3": 1.0}, 5)["crps"], 2.0)
        self.assertAlmostEqual(S.ordinal_row({"3": 1.0}, 3)["crps"], 0.0)

    def test_ordinal_rejects_bad_pmf(self):
        with self.assertRaises(ValueError):
            S.ordinal_row({"1": .4, "2": .4}, 1)

    def test_categorical_multiclass_and_missing_category(self):
        r = S.categorical_row({"h": .5, "d": .3, "a": .2}, "h")
        self.assertAlmostEqual(r["brier_multiclass"], .25 + .09 + .04)
        with self.assertRaises(ValueError):
            S.categorical_row({"h": .5, "a": .5}, "d")

    def test_continuous_pinball_point_forecast_equals_abs_error(self):
        r = S.continuous_row(10, 14, {"0.25": 10, "0.5": 10, "0.75": 10})
        self.assertAlmostEqual(r["pinball_crps_approx"], 4.0)

    def test_ratio_ci_and_cluster(self):
        r = A.ratio_ci([1, 1, -1, 1], [2, 2, 2, 2], ["a", "a", "b", "b"])
        self.assertAlmostEqual(r["ratio"], .25); self.assertEqual(r["n_clusters"], 2)


class FamiliesAndCoverage(unittest.TestCase):
    def test_family_rules(self):
        self.assertEqual(classify_contract("NBA", "game_winner")["family"], "MONEYLINE")
        self.assertEqual(classify_contract("NFL", "SPREAD", line_role="ALTERNATE")["family"], "ALT_SPREAD")
        self.assertEqual(classify_contract("CBB", "TOTAL", line_role="ALTERNATE")["family"], "ALT_TOTAL")
        self.assertEqual(classify_contract("CFB", "team_total", line_role="ALTERNATE")["family"], "ALT_TEAM_TOTAL")
        self.assertEqual(classify_contract("NFL", "1H_TOTAL", "KXNFL1HTOTAL-X")["family"], "PERIOD")
        self.assertEqual(classify_contract("SOCCER", "match_result_3way")["allowed_scoring"], ("BINARY", "CATEGORICAL"))
        self.assertEqual(classify_contract("NFL", "parlay")["support"], "UNSUPPORTED")
        self.assertEqual(classify_contract("CURLING", "x")["reason"], "UNSUPPORTED_SPORT")
        self.assertEqual(classify_contract("MLB", "zzz_unknown_thing")["reason"], "UNCLASSIFIED_FAMILY")

    def test_every_inventoried_family_is_covered_exactly_once(self):           # §3 complete coverage
        root = Path(__file__).resolve().parent.parent
        inv = json.loads((root / "research/audit/master_inventory.json").read_text())
        m = COV.build()
        self.assertEqual(sum(r["native_families"] for r in m["families"]), len(inv["families"]))
        self.assertEqual({r["sport"] for r in m["families"]}, set(SPORTS))
        for r in m["families"]:
            self.assertIn(r["family"], FAMILIES)
            self.assertEqual(r["evaluator_scorable_native"] + r["evaluator_unsupported_native"], r["native_families"])
            if r["evaluator_unsupported_native"]:
                self.assertEqual(sum(r["unsupported_reasons"].values()), r["evaluator_unsupported_native"])

    def test_adoption_matrix_has_all_sports_with_blockers(self):
        m = COV.build()
        self.assertEqual(set(m["adoption"]), set(SPORTS))
        for a in m["adoption"].values():
            for k in ("producer", "existing", "gaps", "blockers", "integration"):
                self.assertTrue(a[k])

    def test_committed_matrix_is_current(self):
        root = Path(__file__).resolve().parent.parent
        p = root / "docs/alpha_eval/COVERAGE_MATRIX.md"
        if p.exists():
            self.assertEqual(p.read_text(), COV.to_markdown(COV.build()), "run: python -m alpha_eval coverage --out-dir docs/alpha_eval")


class Adapter(unittest.TestCase):
    ROW = {"as_of": "2026-10-11T15:00:00Z", "kickoff": "2026-10-11T17:00:00Z", "game_id": "g1", "player_id": "p1", "statistic": "receiving_yards",
           "sport": "nfl", "model_version": "X1", "conditional_on_playing": True,
           "feature_lineage": [{"class": "sports_only", "name": "a"}],
           "projection": {"mean": 61.0, "median": 58.0, "p10": 26.0, "p90": 99.0,
                          "thresholds": [{"at_least": 25.5, "probability": .78}, {"at_least": 50.5, "probability": .58}]}}

    def test_pure_forecast_adapts_to_continuous_plus_ladder_rungs(self):
        rows = from_pure_forecast_v1(self.ROW, evidence_class="BACKTEST")
        self.assertEqual([r["scoring_type"] for r in rows], ["CONTINUOUS", "BINARY", "BINARY"])
        self.assertTrue(all(r["group_id"] == "g1" for r in rows))
        self.assertTrue(all(forecast_from_row(r) for r in rows))
        self.assertEqual(rows[1]["line_role"], "LADDER_RUNG")
        self.assertEqual(rows[0]["model_independence"], "sports_only")

    def test_non_sports_lineage_marks_market_informed(self):
        r = copy.deepcopy(self.ROW); r["feature_lineage"].append({"class": "market", "name": "kalshi_mid"})
        rows = from_pure_forecast_v1(r, evidence_class="BACKTEST")
        self.assertEqual(rows[0]["model_independence"], "market_informed")
        self.assertEqual(rows[0]["market_inputs_used"], ["kalshi_mid"])


if __name__ == "__main__":
    unittest.main()

"""Derived-input engine (RESEARCH_ONLY): point-in-time behaviour on synthetic data and honesty rules on the committed artifact."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha_engine.derived import basketball as B  # noqa: E402
from alpha_engine.derived import registry as R  # noqa: E402
from alpha_engine.derived import verify as V  # noqa: E402


def synth(seasons=6, teams=8, seed=0):
    rng = np.random.default_rng(seed); box, sch, gid = [], [], 1000
    skill = rng.normal(0, 3, teams)
    for s in range(2020, 2020 + seasons):
        day = pd.Timestamp(f"{s - 1}-11-01")
        for rnd in range(6):
            for a in range(teams):
                for b in range(a + 1, teams):
                    gid += 1; day += pd.Timedelta(days=1); rows = []                         # one game per date: no team plays twice on a date
                    for tm, opp, ha in ((a, b, "home"), (b, a, "away")):
                        fga = int(rng.normal(60, 5)); fg3a = int(rng.normal(22, 4)); fgm = int(fga * rng.normal(0.45 + skill[tm] / 200, 0.04)); fg3m = min(fgm, int(fg3a * rng.normal(0.34, 0.06)))
                        fta = int(abs(rng.normal(18, 5))) + 1; ftm = int(fta * 0.72); pts = 2 * fgm + fg3m + ftm
                        rows.append(dict(game_id=gid, season=s, season_type=2, game_date=day.date(), team_id=tm + 1, opponent_team_id=opp + 1, team_home_away=ha, team_score=pts, field_goals_made=fgm, field_goals_attempted=fga,
                                         three_point_field_goals_made=fg3m, three_point_field_goals_attempted=fg3a, free_throws_made=ftm, free_throws_attempted=fta, offensive_rebounds=int(rng.normal(9, 2)), defensive_rebounds=int(rng.normal(25, 3)),
                                         assists=int(rng.normal(13, 3)), steals=int(rng.normal(6, 2)), blocks=int(rng.normal(3, 1)), fouls=int(rng.normal(17, 3)), fast_break_points=str(int(rng.normal(8, 3))), total_turnovers=int(rng.normal(12, 3)),
                                         turnovers=11, team_winner=False, opponent_team_score=0))
                    box += rows; ot = int(rows[0]["team_score"] % 13 == 0)
                    ls = lambda p: str([{"value": float(p // 2), "period": 1.0}, {"value": float(p - p // 2), "period": 2.0}] + ([{"value": 5.0, "period": 3.0}] if ot else []))
                    sch.append(dict(game_id=gid, neutral_site=bool(gid % 9 == 0), home_linescores=ls(rows[0]["team_score"]), away_linescores=ls(rows[1]["team_score"]), status_type_completed=True, status_period=2.0 + ot))
    return {"box": pd.DataFrame(box), "sched": pd.DataFrame(sch)}


class Engine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = synth(); cls.t = B.team_games(cls.raw, "CBB"); cls.f = B.features(cls.t, "CBB")

    def test_linescore_parser_orders_by_period_and_tolerates_missing(self):
        self.assertEqual(B.parse_linescores("[{'displayValue': '40', 'period': 2.0, 'value': 40.0}\n {'value': 39.0, 'period': 1.0}]"), [39.0, 40.0])
        self.assertEqual(B.parse_linescores(None), []); self.assertEqual(B.parse_linescores(float("nan")), [])

    def test_possessions_and_overtime_normalised_pace(self):
        r = self.t.iloc[0]
        self.assertAlmostEqual(r.poss_own, r.fga - r.oreb + r.tov + 0.44 * r.fta)
        self.assertAlmostEqual(r.poss, (r.poss_own + r.opp_poss_own) / 2)
        ot = self.t[self.t.ot_n == 1].iloc[0]; self.assertAlmostEqual(ot.pace, ot.poss * 40 / 45)

    def test_first_archived_date_has_no_information(self):
        first = self.f[self.f.date == self.f.date.min()]
        self.assertTrue(first.off_ortg_pre.isna().all() and first.exp_margin_pre.isna().all(), "nothing is known on the first archived date")
        later = self.f[self.f.season == self.f.season.max()].groupby("team").head(1)
        self.assertTrue(later.off_ortg_pre.notna().all(), "a later season opens on the prior-season target")

    def test_shrunk_matches_a_hand_computation(self):
        t = self.t; team, season = int(t.team.iloc[0]), int(t.season.max())
        g = t[(t.team == team) & (t.season == season)]; lg = B.league_pre(t, "pace"); got = B.shrunk(t, "pace", 8.0, 10.0, lg).loc[g.index]
        prev = t[(t.team == team) & (t.season == season - 1)].pace.mean(); v = g.pace.to_numpy(); n = 5
        w = 0.5 ** ((n - 1 - np.arange(n)) / 8.0); ew = (w * v[:n]).sum() / w.sum()
        self.assertAlmostEqual(got.iloc[n], (n * ew + 10 * prev) / (n + 10), places=9); self.assertAlmostEqual(got.iloc[0], prev, places=9)

    def test_outcome_shuffle_after_cut_never_changes_earlier_or_same_day_features(self):
        cols = sorted({c for s in R.specs() if s["sport"] == "CBB" for c in s["columns"]})
        p = V.pit_test(self.raw, "CBB", self.t, self.f, cols)
        bad = [c for c, v in p["columns"].items() if not v["identical_on_or_before_cut"]]
        self.assertEqual(bad, []); self.assertEqual(p["rows_missing_after_replay"], 0)
        moved = [c for c, v in p["columns"].items() if v["share_moved_after_cut"] > 0]
        self.assertGreater(len(moved), len(cols) * 0.8, "the replay must actually reach the features (non-vacuous)")

    def test_a_leaky_feature_is_caught(self):
        orig = B.features
        try:
            B.features = lambda t, sport: orig(t, sport).assign(leak=t.pts.to_numpy())          # deliberately expose the game's own score
            p = V.pit_test(self.raw, "CBB", self.t, B.features(self.t, "CBB"), ["leak"])
        finally:
            B.features = orig
        self.assertFalse(p["columns"]["leak"]["identical_on_or_before_cut"], "an own-game leak must fail the replay")

    def test_walk_forward_uses_only_earlier_seasons(self):
        df = pd.DataFrame({"season": [1, 1, 2, 2, 3, 3], "y": [1.0, 1.0, 5.0, 5.0, 9.0, 9.0]})
        out = B.walk_forward(df, lambda tr: tr.y.mean(), lambda m, cur: np.full(len(cur), m), window=5, min_seasons=1)
        self.assertTrue(np.isnan(out[0])); self.assertEqual(out[2], 1.0); self.assertEqual(out[4], 3.0)


class Artifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.loads((ROOT / "research/audit/derived_inputs.json").read_text()); cls.ci = json.loads((ROOT / "research/input_research/computable_inputs.json").read_text())["inputs"]

    def test_research_only_and_every_computed_input_passed_every_check(self):
        self.assertEqual(self.d["status"], "RESEARCH_ONLY")
        for sp in self.d["sports"].values():
            self.assertTrue(sp["independent_check"]["ok"]); self.assertEqual(sp["pit_test"]["rows_missing_after_replay"], 0)
        for i in self.d["inputs"]:
            if i["status"].startswith("COMPUTED"):
                self.assertTrue(i["pit_test"]["ok"], i["id"]); self.assertLess(i["pit_test"]["max_abs_diff_on_or_before_cut"], 1e-6, i["id"]); self.assertGreaterEqual(i["coverage"]["min"], 0.5, i["id"])

    def test_full_is_never_claimed_with_missing_parts(self):
        for i in self.d["inputs"]:
            if i["level"] == "FULL":
                self.assertEqual(i["missing"], [], i["id"])
            else:
                self.assertTrue(i["missing"], f"{i['id']}: a partial input must say what is missing")

    def test_catalog_inputs_exist_and_the_certified_ledger_is_not_written(self):
        ids = R.load_catalog_ids(ROOT)
        for i in self.d["inputs"]:
            key = f"{i['sport']}:{i['id']}"
            if i["kind"] == "catalog":
                self.assertIn((i["sport"], i["id"]), ids); self.assertEqual(i["ledger_promotion"], "PENDING_FOUNDATION_REPLAY")
                self.assertEqual(self.ci[key]["status"], i["previous_status"], f"{key}: the certified ledger must still hold the earlier status")
                self.assertNotEqual(self.ci[key].get("builder"), "alpha_engine.derived.basketball")
            else:
                self.assertNotIn((i["sport"], i["id"]), ids); self.assertNotIn(key, self.ci)
        self.assertTrue(self.d["accounting"]["certified_ledger_unchanged"])

    def test_predictive_evidence_and_adoption_are_separate_from_status(self):
        for i in self.d["inputs"]:
            self.assertIn(i["predictive"]["label"], {"BEATS_NAIVE_BASELINE_OOS", "MIXED_VS_NAIVE_BASELINE", "NO_GAIN_VS_NAIVE_BASELINE", "NOT_ASSESSED"})
            self.assertFalse(i["lineage"]["model_adoption"].get("shared_alpha_feature_consumed", False), "no projection model consumes these yet")
            self.assertTrue(i["lineage"]["raw"] and i["lineage"]["kalshi_families"], i["id"])
        acc = self.d["accounting"]; n_new = len(self.d["summary"]["catalog_newly_computed"])
        for a in (acc["certified"], acc["pending_promotion"]):
            self.assertEqual(a["not_computed"], a["calculation_only_no_raw_blocker"] + a["acquisition_gap_raw_class_absent"])
        self.assertEqual(acc["pending_promotion"]["verified_computed"] - acc["certified"]["verified_computed"], n_new)
        self.assertEqual(acc["certified"]["verified_computed"], sum(1 for v in self.ci.values() if v["status"].startswith("COMPUTED")))


if __name__ == "__main__":
    unittest.main()

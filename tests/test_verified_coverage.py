"""Verified coverage (RESEARCH_ONLY): the single authoritative matrix, what each verified status is allowed to mean, and the classification rules on synthetic replay evidence."""
import collections
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha_engine.input_research.data_foundation import report as RP  # noqa: E402
from alpha_engine.input_research.data_foundation import verified_coverage as VC  # noqa: E402

DF = ROOT / "research/input_research/data_foundation"
V = json.loads((DF / "verified_coverage.json").read_text())
ROWS = V["rows"]; REPLAYS = VC.load_replays()


def _tests(**kw):
    t = {"determinism": {"ok": True}, "coverage_replay": {"present": True, "min_coverage_new": 0.95, "max_abs_coverage_drift": 0.0, "constant_columns": [], "first_new": "2015-01-01", "last_new": "2025-01-01"},
         "truncation": [{"q": .5, "cut": "2020-01-01", "ok": True, "bad_columns": []}], "perturbation": [{"q": .5, "seed": 1, "cut": "2020-01-01", "ok": True, "bad_columns": []}], "own_game": {"ok": True, "bad_columns": [], "date": "2020-01-01"}, "vintage_dependence": {}}
    t.update(kw); return t


def _rp(tests, level="FULL", missing=()):
    return {"inputs": {"x": {"tests": tests, "level_claimed": level, "missing_claimed": list(missing)}}}


ROW = {"id": "x", "computed_prior": {"pit_class": "pregame_rolling"}}
PROV = {"ok": True}


class SingleMatrix(unittest.TestCase):
    def test_exactly_one_row_per_input_and_the_csv_is_the_same_matrix(self):
        keys = [r["key"] for r in ROWS]
        self.assertEqual(len(keys), 1649); self.assertEqual(len(set(keys)), 1649)
        with open(DF / "coverage_matrix.csv") as fh:
            c = list(csv.DictReader(fh))
        self.assertEqual(len(c), 1649)
        self.assertEqual({f"{x['sport']}:{x['input_id']}" for x in c}, set(keys))
        self.assertEqual(collections.Counter(x["verified_status"] for x in c), collections.Counter(r["verified_status"] for r in ROWS))
        self.assertEqual(len(list(DF.glob("coverage_matrix*"))), 1, "one authoritative coverage matrix")

    def test_buckets_follow_the_status(self):
        for r in ROWS:
            self.assertEqual(r["verified_bucket"], VC.HEADLINE[r["verified_status"]], r["key"])
        s = V["summary"]; self.assertEqual(sum(s["by_verified_bucket"].values()), 1649)
        self.assertEqual(s["verified_computable"], sum(s["by_verified_status"].get(k, 0) for k in VC.VERIFIED_COMPUTABLE))


class VerifiedMeansReplayed(unittest.TestCase):
    def test_verified_computed_statuses_exist_only_where_a_replay_exists_and_passed_every_test(self):
        for r in ROWS:
            if r["verified_status"] in ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY"):
                self.assertIn(r["sport"], REPLAYS, r["key"])
                t = REPLAYS[r["sport"]]["inputs"][r["id"]]["tests"]
                self.assertTrue(t["determinism"]["ok"] and all(x["ok"] for x in t["truncation"]) and all(x["ok"] for x in t["perturbation"]) and t["own_game"]["ok"], r["key"])
                self.assertFalse(any(v for v in (t.get("vintage_dependence") or {}).values()), r["key"])

    def test_full_requires_the_whole_definition(self):
        for r in ROWS:
            if r["verified_status"] == "VERIFIED_FULL":
                self.assertEqual(REPLAYS[r["sport"]]["inputs"][r["id"]]["missing_claimed"], [], r["key"])
                self.assertEqual(REPLAYS[r["sport"]]["inputs"][r["id"]]["level_claimed"], "FULL", r["key"])

    def test_unreplayed_sports_never_show_a_verified_computed_status(self):
        for r in ROWS:
            if r["sport"] not in REPLAYS and r["draft_status"].startswith("COMPUTED"):
                self.assertEqual(r["verified_status"], "CLAIMED_NOT_REPLAYED", r["key"])

    def test_data_in_hand_needs_real_columns_and_both_rounds_and_a_downgrade_in_any_round_wins(self):
        d1, d2 = VC.load_dih(), VC.load_dir_answers("data_in_hand_round2")
        for r in ROWS:
            if r["draft_status"] != "DATA_IN_HAND":
                continue
            v1 = (d1.get(r["key"]) or {}).get("verdict"); v2 = (d2.get(r["key"]) or {}).get("verdict")
            if r["verified_status"] == "DATA_IN_HAND_CONFIRMED":
                self.assertEqual(v2, "CONFIRMED", r["key"])
                if r["sport"] not in ("NBA", "NHL"):
                    self.assertEqual(v1, "CONFIRMED", r["key"])
                else:   # NBA/NHL: never confirmed on a table whose rows were not re-read this session
                    self.assertFalse(VC.UNMEASURED_TABLES.search(json.dumps(d2[r["key"]].get("columns_used")) + str(d2[r["key"]].get("reason")) + str(d2[r["key"]].get("history"))), r["key"])
            if "DOWNGRADED" in (v1, v2) and r["sport"] not in ("NBA", "NHL"):
                self.assertEqual(r["verified_bucket"], "FAILED", r["key"])
            if v2 == "DOWNGRADED":
                self.assertEqual(r["verified_bucket"], "FAILED", r["key"])
        self.assertEqual(len([r for r in ROWS if r["draft_status"] == "DATA_IN_HAND"]), 132)

    def test_every_drafted_blocked_input_has_two_blind_rechecks_and_confirmed_needs_both_to_agree(self):
        r1 = VC.load_blocked(); r2 = VC.load_dir_answers("blocked_recheck_policy", "answers_*.json")
        draft = [r for r in ROWS if r["draft_bucket"] == "BLOCKED"]
        self.assertEqual({r["key"] for r in draft}, set(r1)); self.assertEqual({r["key"] for r in draft}, set(r2))
        for r in draft:
            if r["verified_status"] == "BLOCKED_CONFIRMED":
                self.assertEqual(r1[r["key"]]["bucket"], "BLOCKED", r["key"]); self.assertIn(r2[r["key"]]["category"], ("BLOCKED_BY_POLICY", "BLOCKED_NO_SOURCE"), r["key"])
            if r["verified_status"] == "REQUIRES_COLLECTION":
                self.assertIn(r2[r["key"]]["category"], ("COLLECTABLE_PERMITTED", "PROSPECTIVE_ONLY", "NEEDS_OWNER_ACTION"), r["key"])
            if r2[r["key"]]["category"] == "COMPUTABLE_NOW":
                self.assertEqual(r["verified_bucket"], "UNVERIFIED", f"{r['key']}: a bare 'computable' claim without replay or columns must stay unverified")

    def test_the_bucket_sample_score_is_reproducible_from_committed_evidence(self):
        key = json.loads((DF / "verification/bucket_sample/key.json").read_text()); ans = {}
        for f in (DF / "verification/bucket_sample").glob("answers_*.json"):
            ans.update(json.loads(f.read_text())["answers"])
        self.assertEqual(set(key), set(ans))
        self.assertEqual(sum(1 for k, a in key.items() if ans[k]["bucket"] == a["claimed_bucket"]), 72)
        self.assertEqual(len(key), 95)


class ClassificationRules(unittest.TestCase):
    def test_a_clean_full_replay_is_verified_full(self):
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests()), PROV)[0], "VERIFIED_FULL")

    def test_partial_or_proxy_claims_are_never_promoted_to_full(self):
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(), "PARTIAL"), PROV)[0], "VERIFIED_PARTIAL")
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(), "PROXY"), PROV)[0], "VERIFIED_PROXY")
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(), "FULL", ["a component is not implemented"]), PROV)[0], "VERIFIED_PARTIAL")

    def test_a_failed_determinism_or_perturbation_test_fails_the_replay(self):
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(determinism={"ok": False})), PROV)[0], "REPLAY_FAILED")
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(perturbation=[{"q": .5, "seed": 1, "cut": "c", "ok": False, "bad_columns": ["a"]}])), PROV)[0], "REPLAY_FAILED")

    def test_truncation_failure_is_only_a_caveat_for_schedule_structure_columns(self):
        sched = [{"q": .5, "cut": "c", "ok": False, "bad_columns": ["games_left_pre"]}]; other = [{"q": .5, "cut": "c", "ok": False, "bad_columns": ["off_epa_pre"]}]
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(truncation=sched)), PROV)[0], "REPLAYED_PIT_CAVEAT")
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(truncation=other)), PROV)[0], "REPLAY_FAILED")

    def test_dependence_on_a_forbidden_pregame_field_is_quarantined_never_full(self):
        for f in ("raw.home_rank", "games.temp", "schedule.weather_condition", "schedule.home_lineup", "schedule.home_plate_ump_id"):
            self.assertEqual(VC.assess_computed(ROW, _rp(_tests(vintage_dependence={f: ["x"]})), PROV)[0], "PIT_QUARANTINED", f)
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(role_fields_own_date={"goalies.starter": {"bad_columns": ["sv_pre"], "date": "d"}})), PROV)[0], "PIT_QUARANTINED")
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(vintage_dependence={"some.unlisted_field": ["x"]})), PROV)[0], "REPLAYED_PIT_CAVEAT")

    def test_an_own_game_failure_without_a_vintage_explanation_fails(self):
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests(own_game={"ok": False, "bad_columns": ["a"], "date": "d"})), PROV)[0], "REPLAY_FAILED")

    def test_low_coverage_or_ledger_mismatch_limits_the_claim(self):
        low = _tests(); low["coverage_replay"]["min_coverage_new"] = 0.3
        self.assertEqual(VC.assess_computed(ROW, _rp(low), PROV)[0], "VERIFIED_PARTIAL")
        self.assertEqual(VC.assess_computed(ROW, _rp(_tests()), {"ok": False})[0], "VERIFIED_PARTIAL")

    def test_no_replay_means_claimed_not_replayed(self):
        self.assertEqual(VC.assess_computed(ROW, None, None)[0], "CLAIMED_NOT_REPLAYED")


class BlockedCombination(unittest.TestCase):
    def test_rules(self):
        c = VC.combine_blocked
        self.assertEqual(c({"bucket": "BLOCKED"}, {"category": "BLOCKED_BY_POLICY"})[0], "BLOCKED_CONFIRMED")
        self.assertEqual(c({"bucket": "REQUIRES_COLLECTION"}, {"category": "BLOCKED_BY_POLICY"})[0], "BLOCKED_BY_POLICY")
        self.assertEqual(c({"bucket": "REQUIRES_COLLECTION"}, {"category": "BLOCKED_NO_SOURCE"})[0], "BLOCKED_CONTESTED")
        self.assertEqual(c({"bucket": "BLOCKED"}, {"category": "COLLECTABLE_PERMITTED"})[0], "BLOCKED_CONTESTED")
        self.assertEqual(c({"bucket": "REQUIRES_COLLECTION"}, {"category": "NEEDS_OWNER_ACTION"})[0], "REQUIRES_COLLECTION")
        self.assertEqual(c({"bucket": "REQUIRES_COLLECTION"}, {"category": "COMPUTABLE_NOW"})[0], "BLOCKED_CONTESTED")
        self.assertEqual(c({"bucket": "BLOCKED"}, None)[0], "BLOCKED_CONTESTED")


class PitRepair(unittest.TestCase):
    def test_every_quarantined_spec_is_marked_final_postgame_by_the_framework_and_is_not_pregame_eligible(self):
        from alpha_engine.features import audit as FA
        from alpha_engine.features import pit_policy as PP
        q = PP.load_quarantine(); self.assertGreaterEqual(len(q), 15)
        seen = set()
        for sp, cfg in FA.SPORTS.items():
            for sc in FA._specs(sp, cfg):
                if f"{sp}:{sc.catalog_id}" in q:
                    seen.add(f"{sp}:{sc.catalog_id}"); self.assertEqual(sc.pit, "final_postgame", sc.catalog_id)
                    st, _ = FA.classify(sc, {c: {"present": True, "coverage": 1.0, "nunique": 5} for c in sc.columns}, {"ok": True, "unmoved_nonstatic": []}, set())
                    self.assertEqual(st, "NOT_PREGAME_ELIGIBLE", sc.catalog_id)
        self.assertEqual(seen, set(q))

    def test_quarantine_file_covers_every_replayed_dependence_on_a_forbidden_field(self):
        from alpha_engine.features import pit_policy as PP
        q = PP.load_quarantine()
        for sp, rp in REPLAYS.items():
            for iid, r in rp["inputs"].items():
                t = r["tests"]
                dep = [f for f, b in (t.get("vintage_dependence") or {}).items() if b and PP.classify(f)] + [f for f, x in (t.get("role_fields_own_date") or {}).items() if x["bad_columns"] and PP.classify(f)]
                if dep:
                    self.assertIn(f"{sp}:{iid}", q, f"{sp}:{iid} depends on {dep}")

    def test_observed_weather_never_satisfies_a_pregame_weather_need(self):
        from alpha_engine.input_research.data_foundation import audit as A2, evidence as EV2
        reg = EV2.resolve_all()
        rec = {"label": "x", "category": "c", "mechanism": "m", "measurement": "m" * 130, "pregame_knowable": "yes", "raw_data": ["game-time temperature and wind"], "provenance": {"sources": [{"name": "nflverse", "access": "free"}], "verified": True}, "free_sources": []}
        row = A2.assess("NFL", rec, reg, {"needs": [{"need": "WEATHER_OBS", "datasets": ["env.weather_observed"]}], "rationale": "x" * 50}, {"id": "nfl.t", "archetypes": [], "computed": None, "collection": None})
        self.assertEqual([x["satisfied_by"] for x in row["requirements"] if x["need"] == "WEATHER_OBS"], ["env.weather_forecast_pit"])
        post = A2.assess("NFL", {**rec, "pregame_knowable": "no"}, reg, {"needs": [{"need": "WEATHER_OBS", "datasets": ["env.weather_observed"]}], "rationale": "x" * 50}, {"id": "nfl.t", "archetypes": [], "computed": None, "collection": None})
        self.assertEqual([x["satisfied_by"] for x in post["requirements"] if x["need"] == "WEATHER_OBS"], ["env.weather_observed"])


class ScoringProtocol(unittest.TestCase):
    def test_eighty_five_percent_agreement_is_documented_as_not_a_modelling_licence(self):
        doc = (ROOT / "docs/DATA_FOUNDATION.md").read_text()
        self.assertIn("not a licence to start predictive modelling", doc)
        self.assertIn("not human expert verification", doc.lower().replace("**", ""))
        self.assertIn("PAUSED", doc)


if __name__ == "__main__":
    unittest.main()

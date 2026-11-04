import copy
import json
import unittest
from pathlib import Path

from alpha_engine import cfb_q1_ablation as ab
from alpha_engine import cfb_q1_chain as chain
from alpha_engine import verification_engine as ve

OUT = Path(__file__).resolve().parents[1] / "research" / "audit" / "verification"


def E(vc, col="X", mu="UNKNOWN", **kw):
    return {"verification_class": vc, "collection": col, "model_use": mu, "evidence": kw.get("ev", []), "code": kw.get("code", {}), "label": "l", "note": "n"}


class Status(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(ve.input_status(E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED")), "VERIFIED")
        self.assertEqual(ve.input_status(E("COLLECTED_UNVERIFIED_PIT")), "COLLECTED_UNVERIFIED")
        self.assertEqual(ve.input_status(E("COLLECTED_UNVERIFIED_PIT", mu="NOT_COLLECTED")), "COLLECTED_UNUSED")
        self.assertEqual(ve.input_status(E("STALE_OR_PARTIAL")), "STALE")
        self.assertEqual(ve.input_status(E("MISSING", "SOURCE_AVAILABLE_NOT_COLLECTED")), "MISSING")
        self.assertEqual(ve.input_status(E("MISSING", "NO_RELIABLE_SOURCE")), "UNSUPPORTED")
        for vc in ("CODE_REFERENCE_ONLY", "UNKNOWN", "DERIVED", "WHATEVER"):
            self.assertEqual(ve.input_status(E(vc)), "UNKNOWN")

    def test_validated_requires_verified_collection(self):
        self.assertEqual(ve.input_status(E("VERIFIED_COLLECTION", mu="USED"), validated=True), "VERIFIED")        # no lineage -> not promoted
        self.assertEqual(ve.input_status(dict(E("VERIFIED_COLLECTION", mu="USED"), _transform_state="PASS"), validated=True), "VALIDATED_PREDICTIVE")
        # a predictive result never upgrades unverified/missing collection
        for vc in ("COLLECTED_UNVERIFIED_PIT", "MISSING", "UNKNOWN", "STALE_OR_PARTIAL"):
            self.assertNotEqual(ve.input_status(E(vc), validated=True), "VALIDATED_PREDICTIVE")

    def test_unrecorded_stage_is_unknown_never_pass(self):
        st = ve.input_stages(E("UNKNOWN"))
        self.assertTrue(all(st[k]["state"] != "PASS" for k in ("source", "archive", "timestamp", "transform", "consumption")))
        self.assertEqual(ve.first_failure(st)["stage"], "source")

    def test_unverified_pit_fails_timestamp_stage(self):
        st = ve.input_stages(E("COLLECTED_UNVERIFIED_PIT", "COLLECTED_NOT_PIT_ARCHIVED", ev=["doc:x"]))
        self.assertEqual(st["timestamp"]["state"], "FAIL")


class Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx, cls.rec, cls.tasks, cls.summ = ve.run(write=False)

    def test_denominators_reproduce_committed_readiness(self):
        r = self.rec
        self.assertEqual((r["essential_links"], r["essential_links_verified"], r["families_with_all_essentials_verified"]), (1762, 775, 5))
        self.assertTrue(r["committed_essential_readiness"]["agrees_with_recount"])
        self.assertEqual((r["families_master_inventory"], r["families_market_specs"]), (275, 278))
        self.assertEqual(len(r["spec_only_not_in_master_inventory"]), 3)
        self.assertEqual(r["unclassified_links"], 0)

    def test_no_family_dropped_and_overlay_never_adds_essentials(self):
        self.assertEqual(len(self.ctx["fams"]), 278)
        for k, f in self.ctx["fams"].items():
            for r in f["inputs"]:
                if r["origin"] == "overlay":
                    self.assertNotEqual(r["tier"], "E", k)
        self.assertEqual(sum(f["essential_total"] for f in self.ctx["fams"].values()), 1762)

    def test_no_validated_predictive_without_ablation_survivor(self):
        self.assertEqual(self.summ["totals"]["validated_predictive_links"], 0)

    def test_every_status_is_a_known_status(self):
        for v in self.ctx["inputs"].values():
            self.assertIn(v["status"], ve.STATUSES)

    def test_committed_outputs_match_regeneration(self):
        for name, obj in (("summary.json", self.summ),):
            self.assertEqual(json.loads((OUT / name).read_text()), json.loads(json.dumps(obj, sort_keys=True)), f"{name} stale: rerun python -m alpha_engine.verification_engine")
        self.assertEqual(json.loads((OUT / "repair_tasks.json").read_text())["n"], len(self.tasks))

    def test_repair_tasks_reference_real_failures_and_keep_blockers_open(self):
        for t in self.tasks:
            self.assertEqual(t["state"], "OPEN")
            self.assertIn(t["status"], ve.STATUSES)
            self.assertNotIn(t["status"], ("VERIFIED", "VALIDATED_PREDICTIVE"))
            self.assertTrue(t["families_affected"])

    def test_cfb_q1_chain_records_gaps_not_hides_them(self):
        c = chain.build(self.ctx)
        self.assertIn("REGISTRY_GAP", c["factor_status_counts"])
        self.assertEqual(c["projection"]["state"], "RESEARCH_WALK_FORWARD")
        by = {x["factor"]: x for x in c["factors"]}
        kick = by["Kicker accuracy by distance / effective range"]
        self.assertEqual(kick["inputs"][0]["status"], "MISSING")
        self.assertNotEqual(by["Historical first-quarter scoring distribution"]["factor_status"], "VERIFIED")


def g(i, start, h, a, hq, aq):
    return {"event_id": f"e{i}", "start_time_utc": start, "home_team_id": h, "away_team_id": a, "home": h, "away": a,
            "home_periods": [hq, 0, 0, 0], "away_periods": [aq, 0, 0, 0], "neutral_site": False}


class Ablation(unittest.TestCase):
    def games(self):
        out = []
        for i in range(120):
            out.append(g(i, f"2026-09-{1 + i // 8:02d}T{10 + i % 8:02d}:00Z", f"T{i % 10}", f"T{(i * 3 + 1) % 10}", 7 if i % 3 else 3, 3 if i % 2 else 7))
        return out

    def test_future_result_never_changes_earlier_predictions(self):
        a = ab.predict_rows(self.games())
        gs = self.games(); gs[-1]["home_periods"] = [99, 0, 0, 0]
        b = ab.predict_rows(gs)
        for ra, rb in zip(a[:-1], b[:-1]):
            for v in ab.VARIANTS:
                self.assertEqual(ra[v], rb[v])
        for v in ab.VARIANTS:                      # own result never enters own prediction
            self.assertEqual(a[-1][v], b[-1][v])

    def test_pure_noise_is_not_validated(self):
        import random
        rng = random.Random(1)
        rows = [{"actual": rng.choice([0, 3, 7, 10, 14]), "start_time_utc": f"2026-{9 + i // 140:02d}-{1 + (i // 5) % 28:02d}T12:00Z", "home": f"H{i % 9}", "away": f"A{i % 7}", **{v: 8.0 + rng.uniform(-1, 1) for v in ab.VARIANTS}} for i in range(400)]
        res = ab.ablate(rows)
        for v, e in res["variants"].items():
            self.assertNotEqual(e.get("verdict"), "VALIDATED_PREDICTIVE", v)

    def test_oracle_variant_is_validated_and_small_n_is_insufficient(self):
        import random
        rng = random.Random(2)
        rows = []
        for i in range(400):
            a = rng.choice([0, 3, 7, 10, 14]); r = {"actual": a, "start_time_utc": f"2026-{9 + i // 140:02d}-{1 + (i // 5) % 28:02d}T12:00Z", "home": f"H{i % 9}", "away": f"A{i % 7}"}
            for v in ab.VARIANTS: r[v] = 8.0
            r["V5_team_only_total"] = a + rng.uniform(-0.5, 0.5)
            rows.append(r)
        self.assertEqual(ab.ablate(rows)["variants"]["V5_team_only_total"]["verdict"], "VALIDATED_PREDICTIVE")
        self.assertEqual(ab.ablate(rows[:50])["variants"]["V5_team_only_total"]["verdict"], "INSUFFICIENT_DATA")

    def test_committed_ablation_has_no_promotion(self):
        d = json.loads((OUT / "CFB_quarter_total_ablation.json").read_text())
        self.assertIn("NOT_EVALUABLE", d["market_baseline"])
        self.assertNotIn("VALIDATED_PREDICTIVE", [e.get("verdict") for e in d["variants"].values()])



class ReviewRegressions(unittest.TestCase):
    """Adversarial regressions for PR #32 review findings 1-5."""

    @classmethod
    def setUpClass(cls):
        cls.ctx, _, _, _ = ve.run(write=False)

    # 1 -- outcomes
    def test_1_sport_level_settlement_never_passes_a_family_outcome(self):
        self.assertFalse([k for k, f in self.ctx["fams"].items() if f["stages"]["outcomes"]["state"] == "PASS"])
        f = self.ctx["fams"]["CBB/TOTAL"]          # sport-level m.settlement_truth is VERIFIED_COLLECTION here
        self.assertEqual(f["stages"]["outcomes"]["state"], "PARTIAL")
        self.assertIn("NO family-specific outcome join", f["stages"]["outcomes"]["why"])

    def test_1_outcome_pass_requires_join_evidence_and_verified_rules(self):
        s = {"sport": "CBB", "drivers": {"m.settlement_truth": "E", "m.rules_text": "E"}}
        v = {"verification_class": "VERIFIED_COLLECTION"}
        inputs = {"CBB:m.settlement_truth": v, "CBB:m.rules_text": v}
        ok = {"outcome_joins": {"CBB/X": {"verified": True, "evidence_ref": "reports/x.json"}}}
        self.assertEqual(ve.outcomes_stage("CBB/X", s, inputs, ok)["state"], "PASS")
        self.assertEqual(ve.outcomes_stage("CBB/X", s, inputs, {})["state"], "PARTIAL")
        bad = {"outcome_joins": {"CBB/X": {"verified": True}}}                               # no evidence_ref
        self.assertEqual(ve.outcomes_stage("CBB/X", s, inputs, bad)["state"], "PARTIAL")
        inputs2 = {"CBB:m.settlement_truth": v, "CBB:m.rules_text": {"verification_class": "COLLECTED_UNVERIFIED_PIT"}}
        self.assertEqual(ve.outcomes_stage("CBB/X", s, inputs2, ok)["state"], "PARTIAL")      # unverified rules block PASS

    # 2 -- projection
    def test_2_repo_reported_readiness_is_never_pass(self):
        for k, f in self.ctx["fams"].items():
            if f["projection"]["state"].startswith("REPO_REPORTED"):
                self.assertEqual(f["stages"]["projection"]["state"], "PARTIAL", k)
        self.assertEqual(self.ctx["fams"]["NBA/player_points"]["stages"]["projection"]["state"], "PARTIAL")

    def test_2_projection_pass_needs_every_condition(self):
        full = {"state": "X", "independently_reproduced": True, "output_ref": "o", "fresh_asof": "t"}
        self.assertEqual(ve.projection_stage(full, "PASS")["state"], "PASS")
        for drop in ("independently_reproduced", "output_ref", "fresh_asof"):
            p = dict(full); p[drop] = None
            self.assertNotEqual(ve.projection_stage(p, "PASS")["state"], "PASS", drop)
        self.assertNotEqual(ve.projection_stage(full, "PARTIAL")["state"], "PASS")           # wrong/unproven market mapping

    # 3 -- mapping
    def test_3_missing_rules_linkage_cannot_pass_vacuously(self):
        mi = {"series_sample": ["KX1"], "observed": {"state": "OBSERVED_NOW"}, "settlement": {"status": "SAMPLED_CONTRACT_TEXT", "text": "resolves to Yes if more than 3"}}
        f = {"sport": "SOCCER", "status": "SPECIFIED", "drivers": {}}                         # rules_text not linked at all
        self.assertNotEqual(ve.market_mapping_stage("SOCCER/x", f, mi, {}, None)["state"], "PASS")
        self.assertEqual(self.ctx["fams"]["SOCCER/player_goalscorer"]["stages"]["market_mapping"]["state"], "FAIL")

    def test_3_pass_needs_identity_rules_and_orientation(self):
        mi = {"series_sample": ["KX1"], "observed": {"state": "OBSERVED_NOW"}, "settlement": {"status": "SAMPLED_CONTRACT_TEXT", "text": "If more than 3, the market resolves to Yes."}}
        f = {"sport": "NBA", "status": "SPECIFIED", "drivers": {"m.rules_text": "E"}}
        inputs = {"NBA:m.rules_text": {"verification_class": "VERIFIED_COLLECTION"}}
        self.assertEqual(ve.market_mapping_stage("NBA/x", f, mi, inputs, None)["state"], "PASS")
        no_orient = dict(mi, settlement={"status": "SAMPLED_CONTRACT_TEXT", "text": "A market about points."})
        self.assertEqual(ve.market_mapping_stage("NBA/x", f, no_orient, inputs, None)["state"], "PARTIAL")
        no_ident = dict(mi, series_sample=[])
        self.assertEqual(ve.market_mapping_stage("NBA/x", f, no_ident, inputs, None)["state"], "PARTIAL")
        unver = {"NBA:m.rules_text": {"verification_class": "COLLECTED_UNVERIFIED_PIT"}}
        self.assertEqual(ve.market_mapping_stage("NBA/x", f, mi, unver, None)["state"], "PARTIAL")

    # 4 -- transform
    def test_4_code_reference_alone_is_not_a_transformation(self):
        e = E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED", code={"model_files": 9})
        self.assertEqual(ve.input_stages(e)["transform"]["state"], "UNKNOWN")
        self.assertTrue(all(i["stages"]["transform"]["state"] != "PASS" for i in self.ctx["inputs"].values()))

    def test_4_lineage_scope_and_completeness(self):
        e = E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED")
        full = {"scope": "PRODUCTION", "source_ref": "s", "feature_ref": "f", "model_ref": "m", "run_ref": "r"}
        self.assertEqual(ve.input_stages(e, full)["transform"]["state"], "PASS")
        self.assertEqual(ve.input_stages(e, dict(full, run_ref=None))["transform"]["state"], "UNKNOWN")      # no executed run
        self.assertEqual(ve.input_stages(e, dict(full, scope="RESEARCH"))["transform"]["state"], "PARTIAL")  # ablation script != production

    # 5 -- validated loophole
    def test_5_unused_or_unknown_consumption_never_validates(self):
        for mu in ("COLLECTED_UNUSED", "NOT_COLLECTED", "UNKNOWN", "USED_PARTIAL", "RESEARCH_ONLY"):
            e = E("VERIFIED_COLLECTION", "PIT_ARCHIVED", mu)
            self.assertNotEqual(ve.input_status(e, validated=True), "VALIDATED_PREDICTIVE", mu)
            self.assertFalse(ve.may_validate(e, True), mu)
        self.assertTrue(ve.may_validate(E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED"), True))
        self.assertFalse(ve.may_validate(E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED"), True, family_match=False))
        self.assertFalse(ve.may_validate(E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED"), False))

    def test_5_family_level_promotion_respects_unused(self):
        # the committed ablation has a SUGGESTIVE result on cfb.q_scoring (COLLECTED_UNUSED): it must stay unpromoted
        row = [r for r in self.ctx["fams"]["CFB/quarter_total"]["inputs"] if r["input"] == "cfb.q_scoring"][0]
        self.assertEqual(row["status"], "COLLECTED_UNUSED")

    def test_5_cluster_and_team_guards(self):
        import random
        rng = random.Random(3)
        # a gain that exists in ONE team's games only must not validate (leave-one-team-out guard)
        rows = []
        for i in range(400):
            a = rng.choice([0, 3, 7, 10, 14]); r = {"actual": a, "start_time_utc": f"2026-{9 + i // 140:02d}-{1 + (i // 5) % 28:02d}T12:00Z", "home": f"H{i % 9}", "away": f"A{i % 7}"}
            for v in ab.VARIANTS: r[v] = 8.0
            if i % 9 == 0: r["V5_team_only_total"] = a                                    # perfect only when team H0 is home
            rows.append(r)
        self.assertNotEqual(ab.ablate(rows)["variants"]["V5_team_only_total"]["verdict"], "VALIDATED_PREDICTIVE")
        self.assertTrue(ab.ablate(rows)["dependence_aware"])


class ReviewRound2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx, cls.rec, _, cls.summ = ve.run(write=False)

    def test_verified_collection_with_unknown_chain_is_not_chain_complete(self):
        for s in self.summ["sports"].values():
            self.assertEqual(s["essential_chain_complete"], 0)
            self.assertGreaterEqual(s["essential_collection_verified"], s["essential_chain_complete"])

    def test_lineage_is_required_for_validated(self):
        e = E("VERIFIED_COLLECTION", "PIT_ARCHIVED", "USED")
        self.assertFalse(ve.may_validate(e, True, transform_state="UNKNOWN"))
        self.assertFalse(ve.may_validate(e, True, transform_state="PARTIAL"))
        self.assertTrue(ve.may_validate(e, True, transform_state="PASS"))

    def test_forged_ablation_verdict_is_rederived_not_trusted(self):
        good = json.loads((OUT / "CFB_quarter_total_ablation.json").read_text())
        for v in good["variants"].values():
            if "verdict" in v:
                self.assertEqual(ve.rederive_ablation_verdict(good, "V5_team_only_total"), "NOT_ELIGIBLE")
        forged = json.loads(json.dumps(good)); forged["variants"]["V5_team_only_total"]["verdict"] = "VALIDATED_PREDICTIVE"
        self.assertEqual(ve.rederive_ablation_verdict(forged, "V5_team_only_total"), "NOT_ELIGIBLE")
        passing = json.loads(json.dumps(good)); e = passing["variants"]["V5_team_only_total"]
        e.update({"mae_improvement_ci_bonferroni": [0.1, 0.4], "chronological_halves_mean": [0.2, 0.1], "team_jackknife_min_mean": 0.05, "n_week_clusters": 12})
        self.assertEqual(ve.rederive_ablation_verdict(passing, "V5_team_only_total"), "ELIGIBLE")
        for k, bad in (("n_week_clusters", 3), ("team_jackknife_min_mean", -0.01), ("chronological_halves_mean", [0.2, -0.1]), ("compared_to", "V2_opp_defense")):
            t = json.loads(json.dumps(passing)); t["variants"]["V5_team_only_total"][k] = bad
            self.assertEqual(ve.rederive_ablation_verdict(t, "V5_team_only_total"), "NOT_ELIGIBLE", k)
        t = json.loads(json.dumps(passing)); t["dependence_aware"] = False
        self.assertEqual(ve.rederive_ablation_verdict(t, "V5_team_only_total"), "NOT_ELIGIBLE")

    def test_all_committed_outputs_match_regeneration(self):
        ctx, rec, tasks, summ = ve.run(write=False)
        c = chain.build(ctx)
        for name, obj in (("summary.json", summ), ("inputs.json", {"schema_version": "verification-1.0", "inputs": ctx["inputs"]}),
                          ("families.json", {"schema_version": "verification-1.0", "families": ctx["fams"]}),
                          ("repair_tasks.json", {"schema_version": "verification-1.0", "n": len(tasks), "tasks": tasks}),
                          ("CFB_quarter_total_chain.json", c)):
            self.assertEqual(json.loads((OUT / name).read_text()), json.loads(json.dumps(obj)), f"{name} stale")

    def test_reconciliation_text_is_computed_not_hardcoded(self):
        txt = " ".join(self.rec["reconciliation_notes"])
        self.assertIn(str(self.rec["inputs_sport_rows_in_collection_status"]), txt)
        self.assertIn(f"{self.rec['essential_links_verified']}/{self.rec['essential_links']}", txt)


if __name__ == "__main__":
    unittest.main()

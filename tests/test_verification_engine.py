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
        self.assertEqual(ve.input_status(E("VERIFIED_COLLECTION", mu="USED"), validated=True), "VALIDATED_PREDICTIVE")
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
        rows = [{"actual": rng.choice([0, 3, 7, 10, 14]), **{v: 8.0 + rng.uniform(-1, 1) for v in ab.VARIANTS}} for _ in range(400)]
        res = ab.ablate(rows)
        for v, e in res["variants"].items():
            self.assertNotEqual(e.get("verdict"), "VALIDATED_PREDICTIVE", v)

    def test_oracle_variant_is_validated_and_small_n_is_insufficient(self):
        import random
        rng = random.Random(2)
        rows = []
        for _ in range(400):
            a = rng.choice([0, 3, 7, 10, 14]); r = {"actual": a}
            for v in ab.VARIANTS: r[v] = 8.0
            r["V5_team_only_total"] = a + rng.uniform(-0.5, 0.5)
            rows.append(r)
        self.assertEqual(ab.ablate(rows)["variants"]["V5_team_only_total"]["verdict"], "VALIDATED_PREDICTIVE")
        self.assertEqual(ab.ablate(rows[:50])["variants"]["V5_team_only_total"]["verdict"], "INSUFFICIENT_DATA")

    def test_committed_ablation_has_no_promotion(self):
        d = json.loads((OUT / "CFB_quarter_total_ablation.json").read_text())
        self.assertIn("NOT_EVALUABLE", d["market_baseline"])
        self.assertNotIn("VALIDATED_PREDICTIVE", [e.get("verdict") for e in d["variants"].values()])


if __name__ == "__main__":
    unittest.main()

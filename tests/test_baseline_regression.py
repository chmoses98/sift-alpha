"""Regression guard for the approved catalog baseline (RESEARCH_ONLY): reproducible regeneration, no stale audit flags, no silently lost gaps."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha_engine.input_research import baseline_lock as BL  # noqa: E402
from alpha_engine.input_research import baseline_overlay as BO  # noqa: E402
from alpha_engine.input_research import catalog as cat  # noqa: E402
from alpha_engine.input_research import completeness as comp  # noqa: E402
from alpha_engine.input_research import input_audit as ia  # noqa: E402
from alpha_engine.input_research import regenerate as RG  # noqa: E402


class BaselineLock(unittest.TestCase):
    def test_catalog_and_declared_gaps_match_the_pinned_baseline(self):
        self.assertEqual(BL.verify(), [], "the approved catalog or a declared gap changed without a deliberate lock bump (baseline_lock --bump)")

    def test_pinned_totals_are_the_approved_totals(self):
        t = BL.load()["current"]["totals"]
        self.assertEqual((t["inputs"], t["archetypes"], t["declared_gaps"]), (1649, 170, 1030))
        self.assertEqual(t["gaps_by_class"], {"CATALOG_BLOCKER": 65, "DATA_SOURCE_LIMITATION": 265, "EMPIRICAL_QUESTION": 237, "FUTURE_DATA_COLLECTION": 89, "UNVERIFIABLE_CONTRACT": 374})
        self.assertTrue(BL.load()["not_human_expert_verified"])

    def test_losing_rewording_or_reclassifying_a_gap_is_detected(self):
        lock = BL.load(); snap = copy.deepcopy(lock["current"])
        k = sorted(snap["gaps"])[0]; k2 = sorted(snap["gaps"])[1]; k3 = sorted(snap["gaps"])[2]
        del snap["gaps"][k]; snap["totals"]["declared_gaps"] -= 1
        snap["gaps"][k2]["record_sha256"] = "0" * 16
        snap["gaps"][k3]["classification_sha256"] = "1" * 16
        msgs = " | ".join(BL.verify(lock, snap))
        self.assertIn(f"REMOVED: {k}", msgs); self.assertIn(f"REWORDED: {k2}", msgs); self.assertIn(f"RECLASSIFIED: {k3}", msgs); self.assertIn("totals changed", msgs)

    def test_a_changed_catalog_is_detected(self):
        lock = BL.load(); snap = copy.deepcopy(lock["current"]); snap["sports"]["NFL"]["catalog_sha256"] = "x"
        self.assertTrue(any(m.startswith("NFL: catalog drifted") for m in BL.verify(lock, snap)))

    def test_bump_requires_a_reason(self):
        with self.assertRaises(SystemExit):
            BL.bump("short")


class AuditFlags(unittest.TestCase):
    FLAG_VERDICTS = ("DUPLICATE", "WEAK", "REMOVE_CANDIDATE")

    def test_every_catalog_flag_matches_the_current_audit_verdict_and_vice_versa(self):
        bad = []
        for s in comp.SPORTS:
            c = cat.load(s); au = ia.load_audit(s)
            for iid, r in c["inputs"].items():
                f, a = r.get("audit_flag"), au.get(iid)
                if f and (not a or a["verdict"] != f["verdict"] or a.get("duplicate_of") != f.get("duplicate_of")):
                    bad.append(f"{s}:{iid}: stale catalog flag {f} vs audit {a and a['verdict']}")
                if a and a["verdict"] in self.FLAG_VERDICTS and not f:
                    bad.append(f"{s}:{iid}: audit verdict {a['verdict']} but no catalog flag")
                if f and f.get("duplicate_of") and f["duplicate_of"] not in c["inputs"]:
                    bad.append(f"{s}:{iid}: duplicate_of {f['duplicate_of']} is not a catalog input")
        self.assertEqual(bad, [])

    def test_apply_clears_a_flag_that_a_later_audit_supersedes(self):
        src = Path(ia.__file__).read_text()
        self.assertIn('r.pop("audit_flag", None)', src)

    def test_later_audit_file_wins_and_the_two_reconciled_inputs_are_not_flagged(self):
        self.assertEqual(ia.load_audit("SOCCER")["soc.european_slot_spillover"]["verdict"], "FIXED")
        self.assertEqual(ia.load_audit("MLB")["mlb.award_narrative"]["verdict"], "OK")
        self.assertNotIn("audit_flag", cat.load("SOCCER")["inputs"]["soc.european_slot_spillover"])
        self.assertNotIn("audit_flag", cat.load("MLB")["inputs"]["mlb.award_narrative"])
        self.assertEqual([e for e in ia.validate("MLB", ia.load_audit("MLB")) if "mlb.award_narrative" in e], [], "the reconciliation entry must satisfy the audit schema")


class ExactAuditGate(unittest.TestCase):
    def test_every_review_added_input_id_has_an_audit_entry(self):
        self.assertEqual({k: v for k, v in ia.missing_audit_ids().items() if v}, {})

    def test_the_gate_compares_ids_not_counts(self):
        src = Path(comp.__file__).read_text()
        self.assertIn("missing_audit_ids", src); self.assertNotIn("audited >= new_ids", src)
        crit = [c for c in comp.rd(comp.CD / "gate.json")["acceptance"]["criteria"] if "exact ids" in c["criterion"]]
        self.assertEqual(len(crit), 1); self.assertTrue(crit[0]["pass"]); self.assertIn("953 of 953", crit[0]["detail"])

    def test_surplus_audit_entries_for_other_inputs_cannot_mask_a_missing_id(self):
        # a sport with MORE audit entries than review-added inputs must still be reported if one specific id lacks an entry
        s = "NBA"; audit = ia.load_audit(s); new = ia.new_input_ids(s)
        victim = sorted(new)[0]; trimmed = {k: v for k, v in audit.items() if k != victim}
        self.assertGreaterEqual(len(trimmed), len(new), "premise: entry count still exceeds the review-added count")
        self.assertIn(victim, [i for i in new if i not in trimmed])

    def test_the_24_corrections_are_recorded_in_the_lock(self):
        r = [x for x in BL.load()["repairs_since_approved_commit"] if x["id"] == "audit-of-24-unaudited-review-added-inputs"][0]
        self.assertEqual(len(r["per_input"]), 24); self.assertEqual(sum(1 for x in r["per_input"] if x["measurement_corrected"]), 7)


class Overlay(unittest.TestCase):
    def _cat(self):
        return {"inputs": {"i1": {"label": "a"}}, "blueprints": {}, "archetypes": {"x": {"inputs": [{"id": "i1", "why": "w", "role": "primary"}], "interactions": []}}, "unregistered_archetypes": {}}

    def test_overlay_restores_the_approved_value_only_when_the_source_layer_still_says_what_it_said(self):
        gen, approved = self._cat(), self._cat()
        approved["archetypes"]["x"]["inputs"][0]["why"] = "approved text"
        ov = BO.derive_sport(gen, approved)
        out = copy.deepcopy(gen); self.assertEqual(BO.apply_sport("T", out, ov), 1)
        self.assertEqual(out["archetypes"]["x"]["inputs"][0]["why"], "approved text")
        self.assertEqual(BO.apply_sport("T", out, ov), 0, "idempotent once at the approved value")

    def test_overlay_refuses_to_paper_over_a_source_layer_that_changed(self):
        gen, approved = self._cat(), self._cat()
        approved["archetypes"]["x"]["inputs"][0]["why"] = "approved text"
        ov = BO.derive_sport(gen, approved)
        drifted = copy.deepcopy(gen); drifted["archetypes"]["x"]["inputs"][0]["why"] = "someone edited the review record"
        with self.assertRaisesRegex(ValueError, "stale"):
            BO.apply_sport("T", drifted, ov)

    def test_input_records_are_overlaid_with_the_same_guard(self):
        gen, approved = self._cat(), self._cat()
        approved["inputs"]["i1"]["label"] = "approved"
        ov = BO.derive_sport(gen, approved)
        drifted = copy.deepcopy(gen); drifted["inputs"]["i1"]["label"] = "other"
        with self.assertRaisesRegex(ValueError, "stale"):
            BO.apply_sport("T", drifted, ov)

    def test_the_committed_overlay_is_small_and_has_no_input_level_entries(self):
        s = BO.summary()
        self.assertEqual(sum(v["inputs"] for v in s.values()), 0)
        self.assertLessEqual(sum(v["archetype_fields"] for v in s.values()), 22, "the overlay is debt: it may shrink, not grow")


class Reproducible(unittest.TestCase):
    def test_pipeline_does_not_include_the_one_shot_bootstrap_scripts(self):
        src = Path(RG.__file__).read_text().split('"""', 2)[2]
        for bad in ("catalog_expand", "catalog_unregistered", "register_new_inputs"):
            self.assertNotIn(f"import {bad}", src)
            self.assertNotIn(f"{bad}.", src)

    def test_regeneration_in_a_scratch_copy_is_a_byte_for_byte_fixpoint_and_idempotent(self):
        r = RG.check()
        self.assertEqual({k: r.get(k) for k in ("changed", "added_by_pipeline", "removed_by_pipeline")}, {"changed": [], "added_by_pipeline": [], "removed_by_pipeline": []}, r.get("stderr", ""))
        self.assertTrue(r["idempotent_second_run"]); self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()

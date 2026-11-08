"""Catalog-completeness gate tests (RESEARCH_ONLY). The gate must be hard to satisfy by accident and impossible to satisfy by code alone."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_engine.input_research import catalog as cat, completeness as C, phase, tracker  # noqa: E402

RULES = C.rd(C.RULES)
LED = C.ledger_by_archetype()


def first_record():
    for s in C.SPORTS:
        for k, r in C.load_reviews(s).items():
            if LED.get((s, k)):
                return s, k, r
    return None


class PauseGuard(unittest.TestCase):
    def test_predictive_experiments_are_paused_and_entry_points_refuse(self):
        self.assertTrue(phase.predictive_paused())
        for mod in ("scaled_search", "refresh", "game_experiment", "prop_experiment", "search_crosssport", "search_nfl_qb", "search_soccer"):
            src = (ROOT / f"alpha_engine/input_research/{mod}.py").read_text()
            self.assertIn(f"assert_predictive_allowed('{mod}')", src, mod)
        r = subprocess.run([sys.executable, "-m", "alpha_engine.input_research.scaled_search"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PAUSED", r.stderr + r.stdout)

    def test_existing_results_are_preserved(self):
        for f in ("research/audit/input_research/scaled_search_summary.json", "research/input_research/computable_inputs.json", "research/audit/input_research/progress.json"):
            self.assertTrue((ROOT / f).exists(), f)

    def test_no_override_flag_exists(self):
        src = (ROOT / "alpha_engine/input_research/phase.py").read_text()
        self.assertNotIn("os.environ", src); self.assertNotIn("getenv", src)


class GateIsNotSelfCertifying(unittest.TestCase):
    def test_gate_ceiling_and_no_code_written_approval(self):
        g = C.compute_gate()
        self.assertEqual(g["totals"]["archetypes"], sum(len(C.arch_keys(cat.load(s))) for s in C.SPORTS))
        self.assertFalse(g["approval"]["approved"])
        self.assertFalse((C.CD / "approval.json").exists() and C.rd(C.CD / "approval.json").get("approved") and not C.rd(C.CD / "approval.json").get("approved_by"))
        self.assertNotIn("COMPLETE", "|".join(C.STATUSES).replace("INCOMPLETE", ""))
        src = Path(C.__file__).read_text()
        self.assertNotIn('approval.json").write', src)
        self.assertNotIn("write_text(json.dumps({\"approved\": True", src)

    def test_every_archetype_has_exactly_one_row_and_every_row_has_a_status(self):
        g = C.compute_gate()
        self.assertEqual(len({(r["sport"], r["archetype"]) for r in g["rows"]}), len(g["rows"]))
        self.assertTrue(all(r["status"] in C.STATUSES for r in g["rows"]))
        self.assertEqual(sum(v["archetypes"] for v in g["by_sport"].values()), len(g["rows"]))

    def test_committed_gate_matches_recomputation(self):
        g = C.compute_gate()
        committed = C.rd(C.CD / "gate.json")
        self.assertEqual(committed["totals"], g["totals"], "gate.json is stale: python -m alpha_engine.input_research.completeness")
        self.assertEqual(C.rd(C.CD / "summary.json")["totals"], g["totals"])

    def test_no_authored_record_is_structurally_broken(self):
        g = C.compute_gate()
        bad = [(r["sport"], r["archetype"], r["problems"][:2]) for r in g["rows"] if r["status"] == "STRUCTURE_INCOMPLETE"]
        self.assertEqual(bad, [], "committed reviews must pass the structural gate (they may still await independent review)")

    def test_ready_requires_independent_review_without_open_blocker_or_major(self):
        g = C.compute_gate()
        for r in g["rows"]:
            if r["status"] == "READY_FOR_USER_APPROVAL":
                self.assertEqual(r["independent"], "CLEAR")
                self.assertEqual(r["open_findings"], 0)
                self.assertGreaterEqual(r["unresolved"], 1)
        wrap = lambda fs: {"reviewer": "x", "verdict": "REVISE", "rederivation_notes": "n" * 220, "findings": fs}
        rec = {"unresolved": [{"id": "u1"}]}
        st, openf = C.independent_state(wrap([{"severity": "MAJOR", "resolution": "OPEN"}, {"severity": "MINOR", "resolution": "OPEN"}]), rec)
        self.assertEqual((st, len(openf)), ("OPEN_FINDINGS", 1))
        self.assertEqual(C.independent_state(wrap([{"severity": "BLOCKER", "resolution": "RESOLVED: reworded stage 2 and added nba.garbage_ratings to the stage inputs"}]), rec)[0], "CLEAR")
        self.assertEqual(C.independent_state(wrap([{"severity": "BLOCKER", "resolution": "RESOLVED: fixed"}]), rec)[0], "OPEN_FINDINGS")          # too terse to count
        self.assertEqual(C.independent_state(wrap([{"severity": "MAJOR", "resolution": "DEFERRED_TO_UNRESOLVED:u1"}]), rec)[0], "CLEAR")
        self.assertEqual(C.independent_state(wrap([{"severity": "MAJOR", "resolution": "DEFERRED_TO_UNRESOLVED:nope"}]), rec)[0], "OPEN_FINDINGS")  # must point at a declared gap
        self.assertEqual(C.independent_state({"findings": [], "verdict": "REVISE"}, rec)[0], "NONE")                                              # no re-derivation, does not count
        self.assertEqual(C.independent_state(None)[0], "NONE")


class ValidatorCatchesShallowOrFalseClaims(unittest.TestCase):
    def setUp(self):
        fr = first_record()
        if not fr:
            self.skipTest("no committed reviews yet")
        self.s, self.k, self.rec = fr
        self.c = cat.load(self.s)
        self.rows = LED.get((self.s, self.k), [])

    def run_v(self, rec):
        return C.validate_review(self.s, self.k, rec, self.c, RULES, self.rows)

    def test_baseline_record_is_clean(self):
        self.assertEqual(self.run_v(self.rec), [])

    def test_fabricated_contract_quote_is_rejected(self):
        r = copy.deepcopy(self.rec)
        if not r["contract"].get("rules_evidence"):
            self.skipTest("record has no rules evidence")
        r["contract"]["rules_evidence"][0]["quote"] = "this sentence never appears in any Kalshi rule text at all"
        self.assertTrue(any("verbatim" in e for e in self.run_v(r)))

    def test_missing_taxonomy_category_is_rejected(self):
        r = copy.deepcopy(self.rec)
        del r["mechanism"]["category_coverage"]["officiating_rules"]
        self.assertTrue(any("officiating_rules" in e for e in self.run_v(r)))

    def test_unaudited_existing_input_is_rejected(self):
        r = copy.deepcopy(self.rec)
        r["input_audit"].pop(next(iter(r["input_audit"])))
        self.assertTrue(any("input_audit missing" in e for e in self.run_v(r)))

    def test_declaring_no_gaps_is_rejected(self):
        r = copy.deepcopy(self.rec)
        r["unresolved"] = []
        self.assertTrue(any("unresolved" in e for e in self.run_v(r)))

    def test_thin_stage_and_unknown_input_are_rejected(self):
        r = copy.deepcopy(self.rec)
        r["mechanism"]["stages"][0]["description"] = "minutes matter"
        r["mechanism"]["stages"][0]["input_ids"] = ["nope.does_not_exist"]
        errs = self.run_v(r)
        self.assertTrue(any("description must be" in e for e in errs) and any("unknown input" in e for e in errs))

    def test_gap_category_must_be_listed_unresolved(self):
        r = copy.deepcopy(self.rec)
        r["mechanism"]["category_coverage"]["environment"] = {"status": "GAP", "note": "x" * 80}
        r["unresolved"] = [u for u in r["unresolved"] if u.get("category") != "environment"]
        self.assertTrue(any("GAP must also appear" in e for e in self.run_v(r)))


class Boilerplate(unittest.TestCase):
    def test_copied_text_is_flagged_and_distinct_text_is_not(self):
        t = "the starting pitcher's pitch count is capped by the manager after the third time through the order so the outs distribution truncates near eighteen when run prevention is poor"
        mk = lambda txt: {"mechanism": {"stages": [{"id": "s1", "description": txt}]}, "interactions": []}
        f = C.similarity_flags("MLB", {"a": mk(t), "b": mk(t.replace("eighteen", "seventeen"))})
        self.assertIn("a", f)
        g = C.similarity_flags("MLB", {"a": mk(t), "b": mk("a goalkeeper facing many low quality shots saves a high share while expected goals conceded stays small which regresses to the mean over a season of matches played")})
        self.assertEqual(g, {})


class TrackerShowsTheGate(unittest.TestCase):
    def test_tracker_leads_with_pause_banner_and_gate(self):
        md = tracker.render(tracker.compute())
        self.assertIn("Predictive experimentation is PAUSED", md)
        self.assertLess(md.index("## Catalog completeness gate"), md.index("## P0 candidate-input catalog"))
        self.assertIn("PRELIMINARY, PAUSED", md)
        self.assertIn("none is declared complete", md)
        self.assertEqual(md, (ROOT / "docs/RESEARCH_TRACKER.md").read_text(), "docs/RESEARCH_TRACKER.md is stale: python -m alpha_engine.input_research.tracker")


if __name__ == "__main__":
    unittest.main()


class UniverseReconciliation(unittest.TestCase):
    """The PR #62 ledger is preserved; the overlay must reconcile exactly and every claim must be checkable against the sampled Kalshi rules."""

    def setUp(self):
        from alpha_engine.input_research import universe_review as U
        self.U = U
        self.asg = C.rd(ROOT / "research/input_research/market_universe/series_assignment.json")
        self.led = C.rd(C.LEDGER)

    def test_every_ledger_series_has_exactly_one_assignment(self):
        self.assertEqual(self.asg["total"], len(self.led["rows"]))
        self.assertEqual({r["ticker"] for r in self.asg["rows"]}, {r["ticker"] for r in self.led["rows"]})
        self.assertEqual(len(self.asg["rows"]), len({r["ticker"] for r in self.asg["rows"]}))

    def test_in_scope_series_land_in_a_catalog_archetype_and_out_of_scope_is_explicit(self):
        arch = {s: set(C.arch_keys(cat.load(s))) for s in C.SPORTS}
        for r in self.asg["rows"]:
            if r["scope"] == "IN_SCOPE":
                self.assertIn(r["final"], arch[r["sport"]], r["ticker"])
            if r["scope"] == "OUT_OF_SCOPE":
                self.assertTrue(r["final"].startswith("OUT_OF_SCOPE:"), r["ticker"])

    def test_assignment_matches_a_recomputation_from_the_reviewer_files(self):
        self.assertEqual(self.U.apply()["total"], self.asg["total"])
        again = {r["ticker"]: (r["final"], r["scope"]) for r in C.rd(ROOT / "research/input_research/market_universe/series_assignment.json")["rows"]}
        self.assertEqual(again, {r["ticker"]: (r["final"], r["scope"]) for r in self.asg["rows"]})

    def test_reviewer_files_validate_against_the_rules_text(self):
        for s in C.SPORTS:
            doc = self.U.load_universe(s)
            self.assertEqual(self.U.validate(s, doc), [], s)
            self.assertEqual(self.U.validate_rest(s), [], s)

    def test_basis_is_never_claimed_without_rules_text_and_never_denied_when_present(self):
        rules = C.rd(C.RULES)
        for r in self.asg["rows"]:
            if r["scope"] in ("IN_SCOPE", "OUT_OF_SCOPE") and r["sport"] in C.SPORTS:
                have = bool((rules.get(r["ticker"]) or {}).get("rules_primary"))
                self.assertEqual(r["basis"] == "RULES_TEXT", have, r["ticker"])

    def test_every_new_archetype_has_series_and_a_review(self):
        for s in C.SPORTS:
            c = cat.load(s)
            for name in c.get("unregistered_archetypes") or {}:
                k = "unreg:" + name
                self.assertIn(k, C.load_reviews(s), f"{s}:{k} has no review")


class CatalogIntegration(unittest.TestCase):
    def test_review_content_is_integrated_into_the_authoritative_catalog(self):
        for s in C.SPORTS:
            c = cat.load(s)
            for k, rec in C.load_reviews(s).items():
                a = C.arch_entry(c, k)
                for iid in rec.get("new_inputs") or {}:
                    self.assertIn(iid, c["inputs"], (s, k, iid))
                    self.assertIn(iid, {i["id"] for i in a["inputs"]}, (s, k, iid))
                have = {(tuple(sorted(x["inputs"])), x.get("form")) for x in a["interactions"]}
                for x in rec.get("interactions") or []:
                    self.assertIn((tuple(sorted(x["inputs"])), x["form"]), have, (s, k))
                self.assertTrue(a.get("mechanism_review"), (s, k))
            self.assertEqual(cat.validate(c, s), [], s)

    def test_acceptance_never_claims_approval_and_reports_exact_counts(self):
        g = C.rd(C.CD / "gate.json")
        ac = g["acceptance"]
        self.assertFalse(g["approval"]["approved"])
        self.assertIn("never approval", ac["note"].lower())
        self.assertEqual(ac["catalog_totals"]["TOTAL"]["inputs"], sum(len(cat.load(s)["inputs"]) for s in C.SPORTS))
        self.assertEqual(g["totals"]["archetypes"], sum(len(C.arch_keys(cat.load(s))) for s in C.SPORTS))

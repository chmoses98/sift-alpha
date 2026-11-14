"""Data-foundation audit (RESEARCH_ONLY): registry integrity, exactly-once coverage of every catalog input, and invariants that keep statuses honest."""
import collections
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha_engine.input_research import baseline_lock as BL  # noqa: E402
from alpha_engine.input_research import catalog as cat  # noqa: E402
from alpha_engine.input_research import market_dependency as MD  # noqa: E402
from alpha_engine.input_research.data_foundation import audit as A  # noqa: E402
from alpha_engine.input_research.data_foundation import datasets as DS  # noqa: E402
from alpha_engine.input_research.data_foundation import evidence as EV  # noqa: E402
from alpha_engine.input_research.data_foundation import report as RP  # noqa: E402
from alpha_engine.input_research.data_foundation import rules as RL  # noqa: E402
from alpha_engine.input_research.data_foundation import sources as SRC  # noqa: E402

DF = ROOT / "research/input_research/data_foundation"
AUDIT = json.loads((DF / "input_audit.json").read_text())
ROWS = AUDIT["rows"]


class Registry(unittest.TestCase):
    def test_every_dataset_is_well_formed_and_cites_known_sources_and_evidence(self):
        probes = EV.probes()
        for d, v in DS.DATASETS.items():
            self.assertIn(v["pit"], DS.PIT, d); self.assertIn(v["kind"], DS.KINDS, d)
            for s in v["sources"]:
                self.assertIn(s, SRC.SOURCES, f"{d}: unknown source {s}")
            for k in ("probe", "probe2"):
                if v["evidence"].get(k):
                    self.assertIn(v["evidence"][k], probes, f"{d}: unknown probe {v['evidence'][k]}")
            self.assertTrue(v["sports"], d)
        res = EV.resolve_all()
        self.assertTrue(all(not r["unknown_probe_ids"] for r in res.values()))
        self.assertTrue(all(r["access_status"] in EV.RANK for r in res.values()))

    def test_rules_only_reference_registered_datasets(self):
        for sp, m in RL.M.items():
            for need, ids in m.items():
                for i in ids:
                    self.assertIn(i, DS.DATASETS, f"{sp}/{need}: {i}")
        for need, ids in RL.X.items():
            for i in ids:
                self.assertIn(i, DS.DATASETS, need)

    def test_a_blocked_host_is_never_graded_as_proof_of_absence(self):
        res = EV.resolve_all()
        p = EV.probes()
        for d, r in res.items():
            ev = DS.DATASETS[d]["evidence"]
            pr = [p[ev[k]] for k in ("probe", "probe2") if ev.get(k) in p]
            if pr and all(x["result"] == "POLICY_DENIED" for x in pr) and DS.DATASETS[d]["kind"] is None and not r["rows_collected"]:
                self.assertEqual(r["access_status"], "FREE_BLOCKED_FROM_RUNNER", d)
                self.assertNotEqual(r["access_status"], "NO_FREE_SOURCE", d)

    def test_ledger_backed_datasets_are_collected_archives_with_measured_history(self):
        res = EV.resolve_all()
        for d in ("nba.injury_report_vintages", "nhl.shots_xy", "mlb.boxscore_player", "ten.matches", "cbb.games_espn"):
            self.assertEqual(res[d]["access_status"], "COLLECTED_ARCHIVE", d)
            self.assertEqual(res[d]["history"]["basis"], "MEASURED", d)
            self.assertTrue(res[d]["history"]["first"], d)


class Coverage(unittest.TestCase):
    def test_every_catalog_input_is_audited_exactly_once(self):
        keys = [r["key"] for r in ROWS]
        self.assertEqual(len(keys), len(set(keys)))
        expect = {f"{s}:{i}" for s in A.SPORTS for i in cat.load(s)["inputs"]}
        self.assertEqual(set(keys), expect)
        self.assertEqual(len(ROWS), 1649)
        self.assertEqual(len(ROWS), BL.load()["current"]["totals"]["inputs"])
        self.assertEqual(AUDIT["n_inputs"], 1649)

    def test_summary_counts_equal_the_rows_and_the_csv(self):
        s = json.loads((DF / "summary.json").read_text())
        self.assertEqual(s["by_status"], dict(collections.Counter(r["status"] for r in ROWS)))
        self.assertEqual(sum(s["by_bucket"].values()), 1649)
        lines = (DF / "coverage_matrix.csv").read_text().strip().splitlines()
        self.assertEqual(len(lines) - 1, 1649)
        self.assertEqual(s["paid_services_added"], 0)

    def test_every_row_has_status_bucket_requirements_provenance_and_evidence(self):
        for r in ROWS:
            self.assertIn(r["status"], A.STATUSES, r["key"]); self.assertEqual(r["bucket"], A.BUCKET[r["status"]], r["key"])
            self.assertIn(r["pit_verdict"], A.PIT_VERDICTS, r["key"])
            self.assertTrue(r["requirements"], r["key"]); self.assertTrue(r["provenance_sources"], r["key"])
            self.assertTrue(any(x["canonical"] for x in r["provenance_sources"]), f"{r['key']}: no provenance source normalised to a canonical source")
            self.assertTrue(r["evidence_grade"], r["key"]); self.assertIn(r["confidence"], ("HIGH", "MEDIUM", "LOW"), r["key"])
            self.assertIn(r["cost"], ("free", "free (key needed)", "paid"), r["key"])

    def test_computed_status_mirrors_the_earlier_milestone_and_benchmarks_mirror_market_dependency(self):
        comp = json.loads((ROOT / "research/input_research/computable_inputs.json").read_text())["inputs"]
        n_prior = sum(1 for v in comp.values() if v["status"] in A.COMPUTED)
        self.assertEqual(sum(1 for r in ROWS if r["computed_prior"]), n_prior, "every earlier computation stays recorded as evidence")
        for r in ROWS:
            if r["status"].startswith("COMPUTED"):
                self.assertTrue(r["computed_prior"], f"{r['key']}: COMPUTED status without an earlier computation")
        for r in ROWS:
            bench = MD.kind(r["id"]) == "benchmark_only"
            if bench:
                self.assertEqual(r["status"], "EXCLUDED_BENCHMARK_ONLY", r["key"])
            elif r["status"] == "EXCLUDED_BENCHMARK_ONLY":   # a market-derived input the catalog's list missed: allowed only as an explicit, rationalised reviewer override
                self.assertTrue(any("status set by reviewer" in f for f in r["flags"]) and r["reviewed"], f"{r['key']}: excluded without a reviewer override")


class HonestStatuses(unittest.TestCase):
    """Invariants that stop an optimistic status from being asserted without evidence. Reviewer overrides of `status` are allowed only with a rationale and are flagged."""

    def test_computable_without_an_earlier_computation_needs_every_dataset_collected(self):
        reg = EV.resolve_all()
        for r in ROWS:
            if r["status"] == "DATA_IN_HAND" and not any("status set by reviewer" in f for f in r["flags"]):
                for x in r["requirements"]:
                    if x["satisfied_by"]:
                        self.assertEqual(reg[x["satisfied_by"]]["access_status"], "COLLECTED_ARCHIVE", f"{r['key']}: {x['need']} -> {x['satisfied_by']}")
                self.assertIn(r["pit_verdict"], ("PIT_SAFE", "PIT_COARSE", "NOT_PREGAME_KNOWABLE", "NOT_APPLICABLE"), r["key"])

    def test_paid_or_no_source_never_lands_in_a_collectable_bucket(self):
        for r in ROWS:
            if r["cost"] == "paid" and not any("status set by reviewer" in f for f in r["flags"]):
                self.assertIn(r["bucket"], ("BLOCKED", "EXCLUDED"), r["key"])

    def test_blocked_and_prospective_rows_name_what_blocks_them(self):
        for r in ROWS:
            if r["status"].startswith("BLOCKED") or r["status"] == "COLLECT_PROSPECTIVE":
                self.assertTrue(r["blockers"] or r["flags"] or r["audit_flag"] or any("status set by reviewer" in f for f in r["flags"]) or r["depends_on"], f"{r['key']}: no stated reason")

    def test_final_only_history_is_never_called_safe_for_a_pregame_decision(self):
        for r in ROWS:
            if r["pregame_knowable"] != "no" and any(x["pit_sensitive"] and x["pit"] in ("FINAL_ONLY", "LIVE_SNAPSHOT") for x in r["requirements"]) and not r["reviewed"]:
                self.assertNotEqual(r["pit_verdict"], "PIT_SAFE", r["key"])


class Engine(unittest.TestCase):
    def _rec(self, **kw):
        base = {"label": "x", "category": "c", "mechanism": "m", "measurement": "m" * 130, "pregame_knowable": "yes", "raw_data": [], "provenance": {"sources": [{"name": "nflverse", "access": "free"}], "verified": True}, "free_sources": []}
        base.update(kw); return base

    def test_pregame_availability_from_weekly_final_designations_is_coarse_not_safe(self):
        reg = EV.resolve_all()
        r = A.assess("NFL", self._rec(raw_data=["weekly injury designations before kickoff"]), reg, None, {"id": "nfl.test_avail", "archetypes": [], "computed": None, "collection": None})
        self.assertEqual(r["pit_verdict"], "PIT_COARSE")

    def test_mlb_pregame_lineup_needs_vintages_so_history_is_prospective(self):
        reg = EV.resolve_all()
        r = A.assess("MLB", self._rec(raw_data=["confirmed starting lineup with posting time"], provenance={"sources": [{"name": "MLB Stats API", "access": "free"}], "verified": True}), reg, None, {"id": "mlb.test_lineup", "archetypes": [], "computed": None, "collection": None})
        self.assertEqual(r["status"], "COLLECT_PROSPECTIVE"); self.assertIn(r["pit_verdict"], ("PIT_LEAKY_FINAL_ONLY", "PIT_UNAVAILABLE_HISTORICALLY"))

    def test_catalog_provenance_caps_availability_when_it_says_paid(self):
        reg = EV.resolve_all()
        r = A.assess("NFL", self._rec(raw_data=["team scores"], provenance={"sources": [{"name": "PFF grades", "access": "paid"}], "verified": True}), reg, None, {"id": "nfl.test_paid", "archetypes": [], "computed": None, "collection": None})
        self.assertEqual(r["status"], "BLOCKED_PAID_ONLY")

    def test_post_game_quantities_are_not_treated_as_pregame_inputs(self):
        reg = EV.resolve_all()
        r = A.assess("NFL", self._rec(pregame_knowable="no", raw_data=["injury designations"]), reg, None, {"id": "nfl.test_post", "archetypes": [], "computed": None, "collection": None})
        self.assertEqual(r["pit_verdict"], "NOT_PREGAME_KNOWABLE")

    def test_derived_inputs_are_capped_by_their_upstream_inputs(self):
        rows = [{"key": "NFL:a", "sport": "NFL", "status": "COMPUTED_FULL", "bucket": "COMPUTABLE", "flags": [], "depends_on": ["b"]}, {"key": "NFL:b", "sport": "NFL", "status": "BLOCKED_PAID_ONLY", "bucket": "BLOCKED", "flags": [], "depends_on": []},
                {"key": "NFL:c", "sport": "NFL", "status": "DATA_IN_HAND", "bucket": "COMPUTABLE", "flags": [], "depends_on": ["NFL:c"]}]
        A.propagate_dependencies(rows)
        self.assertEqual(rows[0]["status"], "BLOCKED_PAID_ONLY"); self.assertEqual(rows[2]["status"], "DATA_IN_HAND", "a cycle must not loop or change the status")


class ReviewContract(unittest.TestCase):
    def setUp(self):
        self.reg = EV.resolve_all(); self.ids = {"a", "b"}

    def test_review_must_cover_every_input_and_each_fix_needs_a_rationale_and_known_datasets(self):
        good = {"verdicts": {"a": "OK", "b": "FIX"}, "overrides": {"b": {"rationale": "needs player tracking touches which no mapped dataset holds", "needs": [{"need": "TRACKING", "datasets": ["nba.tracking"]}]}}}
        self.assertEqual(A.validate_review("NBA", good, self.ids, self.reg), [])
        bad = [({"verdicts": {"a": "OK"}, "overrides": {}}, "cover exactly"), ({"verdicts": {"a": "OK", "b": "FIX"}, "overrides": {}}, "FIX needs an override"),
               ({"verdicts": {"a": "OK", "b": "OK"}, "overrides": {"b": {"rationale": "x" * 50}}}, "without a FIX"),
               ({"verdicts": {"a": "OK", "b": "FIX"}, "overrides": {"b": {"rationale": "short"}}}, "rationale"),
               ({"verdicts": {"a": "OK", "b": "FIX"}, "overrides": {"b": {"rationale": "x" * 50, "needs": [{"need": "TRACKING", "datasets": ["nope.nothing"]}]}}}, "unknown dataset"),
               ({"verdicts": {"a": "OK", "b": "FIX"}, "overrides": {"b": {"rationale": "x" * 50, "status": "GREAT"}}}, "unknown status")]
        for rv, frag in bad:
            self.assertTrue(any(frag in e for e in A.validate_review("NBA", rv, self.ids, self.reg)), frag)

    def test_proposed_datasets_are_validated_and_marked_documented(self):
        snap = dict(DS.DATASETS)
        try:
            ok = {"reviewer": "t", "new_datasets": [{"id": "nba.test_new", "title": "A proposed test dataset", "sources": ["nba_official"], "kind": "own_capture", "pit": "LIVE_SNAPSHOT"}]}
            self.assertEqual(A.register_proposed("NBA", ok), [])
            self.assertIn("proposed_by", DS.DATASETS["nba.test_new"]["notes"]); self.assertEqual(DS.DATASETS["nba.test_new"]["history"]["basis"], "DOCUMENTED")
            self.assertTrue(A.register_proposed("NBA", {"new_datasets": [{"id": "nfl.wrong_prefix", "title": "wrong sport prefix here", "sources": ["nba_official"], "kind": None, "pit": "EVENT_TIME"}]}))
            self.assertTrue(A.register_proposed("NBA", {"new_datasets": [{"id": "nba.bad_source", "title": "bad source id here ok", "sources": ["not_a_source"], "kind": None, "pit": "EVENT_TIME"}]}))
        finally:
            DS.DATASETS.clear(); DS.DATASETS.update(snap)


class VerificationProtocol(unittest.TestCase):
    def test_questions_never_contain_the_claims_and_the_sample_is_deterministic(self):
        q = json.loads((DF / "verification_sample.json").read_text()); k = json.loads((DF / "verification_answer_key.json").read_text())
        self.assertNotIn("claimed", json.dumps(q["inputs"]) + json.dumps(q["datasets"]))
        self.assertTrue(k["DO_NOT_OPEN_BEFORE_SUBMITTING"]); self.assertEqual({i["key"] for i in q["inputs"]}, set(k["inputs"]))
        rows = ROWS; reg = EV.resolve_all()
        q2, k2 = RP.verification_sample(rows, reg)
        self.assertEqual(q2["inputs"], q["inputs"])
        self.assertEqual(len({i["key"] for i in q["inputs"] if i["key"].startswith("NFL:")}) > 0, True)

    def test_scoring_flags_computable_inputs_the_verifier_rates_worse(self):
        key = {"inputs": {"NFL:a": {"claimed_bucket": "COMPUTABLE"}, "NFL:b": {"claimed_bucket": "BLOCKED"}}, "datasets": {"d": {}}}
        res = {"inputs": {"NFL:a": {"bucket": "BLOCKED"}, "NFL:b": {"bucket": "BLOCKED"}}, "datasets": {"d": {"status_confirmed": True}}}
        sc = RP.score(res, key)
        self.assertEqual(sc["bucket_agreement"], 0.5); self.assertEqual(sc["computable_rated_worse"], ["NFL:a"]); self.assertEqual(sc["dataset_replays_confirmed"], 1)


if __name__ == "__main__":
    unittest.main()

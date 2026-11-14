"""Operation Data Foundation: contract, pipeline ledger, market watch and loop-health tests (no network, no sport repos)."""
import json
import re
import unittest
from pathlib import Path

import numpy as np

from alpha_engine.foundation import contract as C
from alpha_engine.foundation import ledger as L
from alpha_engine.foundation import loop, market_watch

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "research/data_foundation_ops"


class ContractTests(unittest.TestCase):
    def test_verdict_rule_needs_ci_holm_and_replication(self):
        self.assertEqual(C.verdict_from(-0.02, -0.01, 0.01, True), "VALIDATED_IMPROVEMENT")
        self.assertEqual(C.verdict_from(-0.02, -0.01, 0.01, False), "IMPROVED_NOT_VALIDATED")
        self.assertEqual(C.verdict_from(-0.02, -0.01, 0.20, True), "INCONCLUSIVE")       # CI alone is not enough
        self.assertEqual(C.verdict_from(-0.02, 0.01, 0.01, True), "INCONCLUSIVE")
        self.assertEqual(C.verdict_from(0.01, 0.02, 0.01, True), "NOT_IMPROVED")

    def test_crps_pmf_exact_and_tail(self):
        self.assertAlmostEqual(C.crps_pmf([0, 0, 1.0], 2), 0.0)
        self.assertAlmostEqual(C.crps_pmf([1.0, 0, 0], 2), 2.0)
        self.assertAlmostEqual(C.crps_pmf([0.5, 0.5], 0), 0.25)
        self.assertGreater(C.crps_pmf([0.5, 0.5], 5), C.crps_pmf([0.5, 0.5], 1))            # realised value beyond the support is penalised

    def test_bootstrap_is_seeded_and_cluster_aware(self):
        d = np.r_[np.full(50, -0.1), np.full(50, 0.1)]; cl = np.arange(100) // 50
        a = C.paired_cluster_bootstrap(d, cl); b = C.paired_cluster_bootstrap(d, cl)
        self.assertEqual(a, b)
        self.assertLess(a["lo"], 0); self.assertGreater(a["hi"], 0)                         # two clusters: no false certainty from 100 rows
        self.assertEqual(a["n_clusters"], 2)

    def test_holm_monotone_and_bounded(self):
        h = C.holm([0.01, 0.04, 0.03])
        self.assertAlmostEqual(h[0], 0.03); self.assertAlmostEqual(h[2], 0.06); self.assertAlmostEqual(h[1], 0.06)
        self.assertTrue(all(0 <= x <= 1 for x in C.holm([0.9, 0.8])))

    def test_calibration_slope_detects_overconfidence(self):
        rng = np.random.default_rng(1); true = rng.uniform(0.2, 0.8, 20000); y = rng.random(20000) < true
        lo = np.log(true / (1 - true)); over = 1 / (1 + np.exp(-2 * lo))
        self.assertLess(C.calibration_slope(over, y)[1], 0.7)
        self.assertAlmostEqual(C.calibration_slope(true, y)[1], 1.0, delta=0.08)

    def test_validator_rejects_missing_and_bad_values(self):
        self.assertTrue(C.validate_evaluation({}))
        doc = {"schema": C.EVAL_SCHEMA, "status": "RESEARCH_ONLY", "sport": "NBA", "challenger_id": "x", "incumbent_id": "y", "source_commits": {},
               "data": [{"dataset_id": "d", "repo": "r", "path": "p", "rows": 1, "first": "a", "last": "b", "rights_tier": "t", "kind": "HISTORICAL_BACKFILL"}],
               "features": [{"feature_id": "f", "catalog_inputs": [], "description": "", "pit_rule": "", "checks": [C.check("n", True, "")]}],
               "design": {}, "results": [], "verdict": {"overall": "INCONCLUSIVE"}, "limitations": [], "input_stage_claims": [{"input": "NBA:x", "stage": "EVALUATED", "outcome": "OK"}]}
        self.assertEqual(C.validate_evaluation(doc), [])
        doc["verdict"]["overall"] = "PROFITABLE"; doc["data"][0]["kind"] = "LIVE"; doc["input_stage_claims"][0]["stage"] = "DONE"
        self.assertEqual(len(C.validate_evaluation(doc)), 3)

    def test_checks_must_say_how_they_were_obtained(self):
        self.assertEqual(C.check("n", C.ATTESTED, "design statement"), {"name": "n", "passed": True, "detail": "design statement", "basis": "ATTESTED"})
        self.assertEqual(C.check("n", 1 > 2, "")["basis"], "COMPUTED")
        doc = {"schema": C.EVAL_SCHEMA, "status": "RESEARCH_ONLY", "sport": "NBA", "challenger_id": "x", "incumbent_id": "y", "source_commits": {}, "data": [],
               "features": [{"feature_id": "f", "catalog_inputs": [], "description": "", "pit_rule": "", "checks": [{"name": "n", "passed": True, "detail": ""}]}],
               "design": {}, "results": [], "verdict": {"overall": "INCONCLUSIVE"}, "limitations": [], "input_stage_claims": []}
        self.assertEqual(len(C.validate_evaluation(doc)), 1)                       # no basis: rejected
        doc["features"][0]["checks"] = [{"name": "n", "passed": False, "detail": "", "basis": "ATTESTED"}]
        self.assertEqual(len(C.validate_evaluation(doc)), 1)                       # an attested check cannot fail

    def test_committed_evaluations_never_count_an_attested_check_as_verified(self):
        led = json.loads((OPS / "pipeline_ledger.json").read_text())
        for k, ch in led["challengers"].items():
            ev = json.loads((ROOT / ch["path"]).read_text())
            for f, src in zip(ch["features"], ev["features"]):
                att = [c["name"] for c in src["checks"] if c["basis"] == "ATTESTED"]
                self.assertEqual(f["checks_attested"], att, k)
                self.assertEqual(f["checks_passed"] + len(att) + len(f["checks_failed"]), f["checks_total"], k)


class StageLogicTests(unittest.TestCase):
    DS = {"a": {"access_status": "COLLECTED_ARCHIVE"}, "p": {"access_status": "PAID_ONLY"}, "c": {"access_status": "PROSPECTIVE_CAPTURE_ONLY"}}

    def chain(self, inp, dsets, claims=(), feats=()):
        oc, _ = L._chain(inp, dsets, self.DS, list(claims), list(feats)); return oc, L._at(oc)

    def test_built_verified_input_stops_before_challenger(self):
        oc, at = self.chain({"bucket": "FULL", "vstatus": "VERIFIED_FULL", "built": True}, ["a"])
        self.assertEqual(L.CHAIN[at], "FEATURE_BUILT"); self.assertEqual(oc[5], "MISSING")

    def test_paid_only_is_blocked_at_source(self):
        oc, at = self.chain({"bucket": "REQUIRES_COLLECTION", "vstatus": "REQUIRES_COLLECTION", "completeness_category": "NO_FREE_SOURCE"}, ["p"])
        self.assertEqual((L.CHAIN[at], oc[1]), ("IDENTIFIED", "BLOCKED"))

    def test_prospective_only_is_blocked_at_collection_not_missing(self):
        oc, at = self.chain({"bucket": "REQUIRES_COLLECTION", "vstatus": "REQUIRES_COLLECTION", "completeness_category": "PROSPECTIVE"}, ["c"])
        self.assertEqual((L.CHAIN[at], oc[2]), ("SOURCE_LOCATED", "BLOCKED"))

    def test_quarantined_and_downgraded_never_count_as_verified(self):
        for vs, want in (("PIT_QUARANTINED", "REJECTED"), ("DOWNGRADED_BY_VERIFIER", "FAILED")):
            oc, at = self.chain({"bucket": "DATA_IN_HAND", "vstatus": vs, "built": True}, ["a"])
            self.assertEqual((L.CHAIN[at], oc[3]), ("COLLECTED", want))                     # a built column does not skip a failed verification

    def test_evaluated_claim_is_not_a_validated_improvement(self):
        base = {"bucket": "FULL", "vstatus": "VERIFIED_FULL", "built": True}
        oc, at = self.chain(base, ["a"], [{"stage": "EVALUATED", "outcome": "OK", "challenger": "ch", "evidence": "e"}])
        self.assertEqual(L.CHAIN[at], "EVALUATED"); self.assertEqual(oc[7], "MISSING")
        oc, at = self.chain(base, ["a"], [{"stage": "EVALUATED", "outcome": "REJECTED", "challenger": "ch", "evidence": "e"}])
        self.assertEqual(L.CHAIN[at], "EVALUATED"); self.assertEqual(oc[7], "REJECTED")
        claim = {"stage": "VALIDATED_IMPROVEMENT", "outcome": "OK", "challenger": "ch", "evidence": "e"}
        oc, at = self.chain(base, ["a"], [{**claim, "overall": "VALIDATED_IMPROVEMENT"}])
        self.assertEqual(L.CHAIN[at], "VALIDATED_IMPROVEMENT")
        # a validated component metric inside a challenger that is not validated overall stays at EVALUATED
        oc, at = self.chain(base, ["a"], [{**claim, "overall": "IMPROVED_NOT_VALIDATED"}])
        self.assertEqual(L.CHAIN[at], "EVALUATED"); self.assertEqual(oc[7], "MISSING")
        # ... and so does a validated challenger on an input that is only partially verified
        oc, at = self.chain({**base, "vstatus": "VERIFIED_PARTIAL"}, ["a"], [{**claim, "overall": "VALIDATED_IMPROVEMENT"}])
        self.assertEqual(L.CHAIN[at], "EVALUATED"); self.assertEqual(oc[7], "MISSING")

    def test_challenger_claim_cannot_jump_an_unverified_input(self):
        oc, at = self.chain({"bucket": "REQUIRES_COLLECTION", "vstatus": "REQUIRES_COLLECTION"}, ["a"], [{"stage": "EVALUATED", "outcome": "OK", "challenger": "ch", "evidence": "e"}])
        self.assertEqual(L.CHAIN[at], "SOURCE_LOCATED")                                    # the gap at COLLECTED stays visible

    def test_production_track_is_separate_and_defaults_unknown(self):
        self.assertEqual(L._prod(None)[0], "UNKNOWN"); self.assertEqual(L._prod("USED")[0], "OK")
        self.assertEqual(L._prod("USED_PARTIAL")[0], "PARTIAL"); self.assertEqual(L._prod("NOT_USED (not collected)")[0], "MISSING")
        self.assertEqual(L._prod("UNKNOWN (no recorded model-use evidence)")[0], "UNKNOWN")


class LedgerArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.summary = L.build()
        cls.map = json.loads(L.MAP.read_text())

    def test_committed_artifacts_are_a_byte_identical_regeneration(self):
        for name, doc in (("pipeline_ledger.json", self.ledger), ("summary.json", self.summary)):
            self.assertEqual((OPS / name).read_text(), json.dumps(C._clean(doc), indent=1, sort_keys=True) + "\n", name + " is stale: run python -m alpha_engine.foundation.ledger")

    def test_totals_reconcile_to_the_market_input_map(self):
        r = self.map["reconciliation"]; t = self.ledger["totals"]
        self.assertTrue(self.ledger["reconciliation"]["ok"])
        self.assertEqual((t["archetypes"], t["inputs"], t["datasets"], t["queue_datasets"]), (r["archetypes"], r["distinct_inputs"], r["datasets"], r["queue_datasets"]))
        self.assertEqual(t["missing_primary_slots"], r["missing_primary_predictive_slots"])
        self.assertEqual(sum(t["at_counts_all_inputs"]), r["distinct_inputs"])

    def test_every_sport_and_market_count_adds_up(self):
        ins = self.ledger["inputs"]
        self.assertEqual(sum(s["archetypes"] for s in self.ledger["sports"].values()), 170)
        for name, s in self.ledger["sports"].items():
            pred = [v for v in ins.values() if v["sport"] == name and v["predictive"]]
            self.assertEqual(sum(s["at_counts"]), len(pred)); self.assertEqual(s["inputs_predictive"], len(pred))
            self.assertEqual(s["reached_counts"][0], len(pred))
            self.assertEqual(sum(s["production_active"].values()), len(pred))
            self.assertTrue(all(a >= b for a, b in zip(s["reached_counts"], s["reached_counts"][1:])))
        for k, mk in self.ledger["markets"].items():
            self.assertEqual(sum(mk["at_counts"]), mk["n_predictive"], k); self.assertEqual(sum(mk["at_counts_primary"]), mk["n_primary"], k)
            self.assertTrue(mk["next_action"])

    def test_every_input_has_a_stage_a_reason_and_a_next_action(self):
        for k, v in self.ledger["inputs"].items():
            self.assertEqual(len(v["chain"]), 8); self.assertTrue(set(v["chain"]) <= set(C.OUTCOMES), k)
            self.assertTrue(v["next_action"], k)
            if v["at"] < 7:
                self.assertEqual(v["stop"]["stage"], L.CHAIN[v["at"] + 1]); self.assertNotIn(v["stop"]["outcome"], ("OK", "PARTIAL")); self.assertTrue(v["stop"]["why"], k)
            self.assertEqual(v["production_approved"], "UNKNOWN")                          # no approval record exists; never implied

    def test_challenger_stages_exist_only_with_a_committed_evaluation(self):
        claimed = set()
        for p in self.ledger["evaluations"]:
            d = json.loads((ROOT / p).read_text()); self.assertEqual(C.validate_evaluation(d), [])
            claimed |= {c["input"] for c in d["input_stage_claims"]}
        for p in self.ledger.get("probes", []):          # input-information probes record EVALUATED claims without being challengers
            claimed |= {c["input"] for c in json.loads((ROOT / p).read_text())["input_stage_claims"]}
        for k, v in self.ledger["inputs"].items():
            if v["at"] >= 5:
                self.assertIn(k, claimed, f"{k} shows a challenger stage without an evaluation claim")
        for k, mk in self.ledger["markets"].items():
            for c in mk["challengers"]:
                self.assertIn(c, self.ledger["challengers"])

    def test_ledger_never_shows_validated_improvement_unless_the_whole_challenger_is_validated(self):
        overall = {ch["id"]: ch["verdict"]["overall"] for ch in self.ledger["challengers"].values()}
        for k, v in self.ledger["inputs"].items():
            if v["at"] == 7:
                self.assertEqual(v["chain"][3], "OK", f"{k}: validated although the input is not fully verified")
                self.assertTrue(any(overall.get(c) == "VALIDATED_IMPROVEMENT" for c in v["challengers"]), k)
            self.assertNotIn("production review", v["next_action"].lower() if v["at"] < 7 else "", k)
        for ch in self.ledger["challengers"].values():
            for r in ch["results"]:
                if not r["tested"]:
                    self.assertIsNone(r["p_holm"]); self.assertEqual(r["verdict"], "DESCRIPTIVE")

    def test_loop_breaks_only_a_stale_lock(self):
        import os, subprocess, sys, time
        from alpha_engine.foundation import loop
        self.assertFalse(loop.LOCK.exists(), "a loop pass is running; cannot test the lock")
        try:
            loop.LOCK.write_text(f"{os.getpid()} {int(time.time())}\n")
            self.assertFalse(loop._lock_is_stale(), "a live owner inside the time budget must keep its lock")
            dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
            loop.LOCK.write_text(f"{dead.pid} {int(time.time())}\n")
            self.assertTrue(loop._lock_is_stale(), "a lock whose owner is gone must be recoverable")
            loop.LOCK.write_text("")
            self.assertFalse(loop._lock_is_stale(), "a fresh legacy lock is judged by age alone")
            old = time.time() - sum(loop.STEP_TIMEOUT_S.values()) - 600
            os.utime(loop.LOCK, (old, old))
            self.assertTrue(loop._lock_is_stale())
        finally:
            loop.LOCK.unlink(missing_ok=True)

    def test_validated_improvement_requires_a_validated_result_row(self):
        for cid, ch in self.ledger["challengers"].items():
            d = json.loads((ROOT / ch["path"]).read_text())
            any_valid = any(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in d["results"]) or any(a.get("verdict") == "VALIDATED_IMPROVEMENT" for a in d.get("ablations", []))
            if d["verdict"]["overall"] == "VALIDATED_IMPROVEMENT" or any(c["stage"] == "VALIDATED_IMPROVEMENT" and c["outcome"] == "OK" for c in d["input_stage_claims"]):
                self.assertTrue(any_valid, cid)
            for r in d["results"]:
                if r.get("p_holm") is not None and r.get("replicated") is not None:
                    self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], bool(r["replicated"])), f"{cid} {r['market_family']} {r['metric']}")

    def test_queue_is_ranked_p0_first_with_no_composite_score(self):
        q = self.ledger["queue"]
        self.assertEqual([r["rank"] for r in q], list(range(1, len(q) + 1)))
        tiers = [r["tier"] for r in q]; self.assertEqual(tiers, sorted(tiers))
        self.assertTrue(all("score" not in r and "expected_gain" not in r for r in q))
        self.assertTrue(all(r["basis"] in ("EVIDENCE_BACKED", "HYPOTHESIS") for r in q))

    def test_no_raw_rows_or_private_fields_in_ops_artifacts(self):
        for p in OPS.rglob("*.json"):
            txt = p.read_text()
            self.assertLess(len(txt), 4_000_000, p)
            for bad in ("api_key", "apikey", "authorization", "bankroll", "password", "secret"):
                self.assertNotIn(bad, txt.lower(), f"{p}: {bad}")


class MarketWatchTests(unittest.TestCase):
    def test_new_series_are_unresolved_never_auto_assigned(self):
        assignment = {"rows": [{"ticker": "KXNBAPTS", "scope": "IN_SCOPE"}, {"ticker": "KXNHLGAME", "scope": "IN_SCOPE"}, {"ticker": "KXLAX", "scope": "OUT_OF_SCOPE"}]}
        series = [{"ticker": "KXNBAPTS", "title": "NBA points", "tags": ["Basketball"]}, {"ticker": "KXNBAPTSPRECISE", "title": "NBA Player Points Range", "tags": ["Basketball"]},
                  {"ticker": "KXDARTS1", "title": "Darts", "tags": ["Darts"]}]
        d = market_watch.diff(series, assignment, "2026-11-14T00:00:00Z")
        self.assertEqual((d["new_series_total"], d["new_series_in_scope"]), (2, 1))
        self.assertEqual(d["new_in_scope"][0]["status"], "UNRESOLVED_NOT_ASSIGNED_TO_AN_ARCHETYPE")
        self.assertEqual(d["in_scope_series_no_longer_listed"], ["KXNHLGAME"])              # disappearing in-scope series are reported, out-of-scope ones are not

    def test_committed_watch_counts_are_internally_consistent(self):
        d = json.loads((OPS / "market_watch.json").read_text())
        self.assertEqual(d["new_series_in_scope"], len(d["new_in_scope"])); self.assertEqual(sum(d["new_in_scope_by_sport"].values()), d["new_series_in_scope"])
        self.assertEqual(d["new_series_total"], d["new_series_in_scope"] + d["new_out_of_scope_count"])


class LoopHealthTests(unittest.TestCase):
    OK = {"step": "ledger", "status": "OK", "seconds": 1, "detail": [""]}

    def test_health_is_fail_closed(self):
        now = json.loads((OPS / "market_watch.json").read_text())["observed_utc"]
        nr = lambda n: {"step": n, "status": "NOT_REQUESTED", "seconds": 0, "detail": [""]}
        self.assertEqual(loop.finish([nr("market_watch"), nr("nba"), self.OK], now)["overall"], "HEALTHY")
        skipped = {"step": "nba", "status": "SKIPPED_SOURCE_UNAVAILABLE", "seconds": 0, "detail": [""]}
        h = loop.finish([nr("market_watch"), skipped, self.OK], now)
        self.assertEqual(h["overall"], "DEGRADED"); self.assertEqual(h["not_ok_steps"], ["nba:SKIPPED_SOURCE_UNAVAILABLE"])      # a skipped run is never healthy
        self.assertEqual(loop.finish([{"step": "nba", "status": "TIMED_OUT", "seconds": 9, "detail": [""]}, self.OK], now)["overall"], "DEGRADED")
        self.assertEqual(loop.finish([{"step": "ledger", "status": "FAILED", "seconds": 1, "detail": [""]}], now)["overall"], "FAILED")

    def test_stale_market_watch_degrades_health(self):
        h = loop.finish([self.OK], "2027-03-01T00:00:00Z")
        self.assertEqual(h["overall"], "DEGRADED"); self.assertTrue(h["stale"])

    def test_old_evaluation_data_degrades_health(self):
        now = json.loads((OPS / "market_watch.json").read_text())["observed_utc"]
        h = loop.finish([self.OK], now)
        self.assertEqual(set(h["evaluation_freshness"]), {"NBA", "CBB", "NHL"})
        newest = max(v["data_through"] for v in h["evaluation_freshness"].values())
        import datetime as dt
        later = (dt.date.fromisoformat(newest) + dt.timedelta(days=loop.EVAL_STALE_DAYS + 1)).isoformat() + "T00:00:00Z"
        self.assertTrue(any("evaluations read data only through" in x for x in loop.finish([self.OK], later)["stale"]))

    def test_every_step_has_a_hard_timeout(self):
        self.assertEqual(set(loop.STEP_TIMEOUT_S), {"market_watch", "ledger", *loop.CHALLENGERS})
        self.assertLessEqual(sum(loop.STEP_TIMEOUT_S.values()), 75 * 60)

    def test_refresh_workflow_is_manual_only_and_cannot_chain(self):
        y = (ROOT / ".github/workflows/data-foundation-refresh.yml").read_text()
        body = "\n".join(l for l in y.splitlines() if not l.lstrip().startswith("#"))
        on = body.split("\npermissions:")[0]
        self.assertIn("workflow_dispatch", on)
        for trig in ("schedule", "cron", "push:", "pull_request", "workflow_run", "repository_dispatch"):
            self.assertNotIn(trig, on, trig)
        self.assertRegex(body, r"permissions:\s*\n\s+contents: read")
        self.assertRegex(body, r"timeout-minutes: \d+"); self.assertIn("concurrency:", body)
        for bad in ("git push", "git commit", "gh workflow run", "workflow_dispatch --", "secrets."):
            self.assertNotIn(bad, body, bad)
        src = (ROOT / "alpha_engine/foundation/loop.py").read_text().split('"""', 2)[2]
        self.assertIsNone(re.search(r"git\s+(push|commit)|workflow run|dispatches", src))


if __name__ == "__main__":
    unittest.main()

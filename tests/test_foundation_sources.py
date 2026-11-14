"""Source acquisition board: reconciles to the pipeline ledger and never upgrades a rights tier (RESEARCH_ONLY)."""
import json
import unittest
from pathlib import Path

from alpha_engine.foundation import sources

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "research" / "data_foundation_ops"


class SourceBoard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads((OPS / "source_acquisition.json").read_text())
        cls.ledger = json.loads((OPS / "pipeline_ledger.json").read_text())

    def test_committed_file_is_the_deterministic_build(self):
        self.assertEqual(json.loads(json.dumps(sources.build(), sort_keys=True)), json.loads(json.dumps(self.doc, sort_keys=True)))

    def test_p0_slots_are_counted_once_and_reconcile_to_the_map(self):
        m = json.loads((ROOT / "research/input_research/market_input_map/map.json").read_text())
        missing = {(a, i) for a, i, role, cls, grp, cat in m["edges"]
                   if cls == "PREDICTIVE" and role == "primary" and cat not in ("FULL", "PARTIAL", "PROXY") and a.split(":")[0] in sources.P0}
        d = self.doc["p0_distinct"]
        self.assertEqual(d["missing_primary_slots"], len(missing))
        self.assertEqual(sum(d["by_sport"].values()), len(missing))
        self.assertLessEqual(d["archived_datasets_only"], d["with_an_archived_dataset"])
        self.assertLessEqual(d["with_an_archived_dataset"], d["missing_primary_slots"])
        # the per-dataset sum double counts; the distinct figure can never exceed it
        self.assertLessEqual(d["with_an_archived_dataset"], d["per_dataset_sum_previously_reported"])
        for r in self.doc["sources"]:
            self.assertLessEqual(r["p0_missing_primary_slots"], d["missing_primary_slots"], r["source"])
            self.assertLessEqual(r["p0_archived_slots"], r["archived_slots"], r["source"])

    def test_every_queue_dataset_is_behind_at_least_one_source_row(self):
        seen = {d for r in self.doc["sources"] for d in r["datasets"]}
        self.assertEqual(seen, {q["dataset"] for q in self.ledger["queue"]})

    def test_rights_tiers_are_copied_not_upgraded_and_terms_read_needs_the_document_itself(self):
        tiers = {q["rights_tier"] for q in self.ledger["queue"]}
        terms = json.loads((OPS / "provider_terms.json").read_text())
        direct = {s for p in terms["providers"] if p["terms_status"] == "READ_DIRECT" for s in p["sources"]}
        for p in terms["providers"]:
            reached = [d for d in p["documents"] if d.get("reached") and d.get("via") == "webfetch"]
            if p["terms_status"].startswith("READ_DIRECT"):
                self.assertTrue(reached, p["id"])                     # a "read" claim needs a fetched document
        for r in self.doc["sources"]:
            self.assertTrue(set(r["rights_tiers"]) <= tiers, r["source"])
            self.assertEqual(r["terms_read"], r["source"] in direct, r["source"])
            self.assertTrue(r["decision_needed"])
        self.assertEqual(self.doc["new_external_records_acquired"], 0)

    def test_reachability_only_comes_from_the_probe_file(self):
        probe = json.loads((OPS / "source_probe.json").read_text())
        probed = {s for h in probe["hosts"].values() for s in h["sources"]}
        for r in self.doc["sources"]:
            if r["source"] not in probed:
                self.assertEqual(r["reachability"], "NOT_PROBED", r["source"])
        self.assertEqual([r["rank"] for r in self.doc["sources"]], list(range(1, len(self.doc["sources"]) + 1)))


if __name__ == "__main__":
    unittest.main()

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

    def test_blocker_breakdown_sums_to_the_p0_queue(self):
        p0 = sum(q["missing_primary_slots"] for q in self.ledger["queue"] if q["tier"] == "P0")
        self.assertEqual(sum(self.doc["p0_slots_by_blocker"].values()), p0)

    def test_every_queue_dataset_is_behind_at_least_one_source_row(self):
        seen = {d for r in self.doc["sources"] for d in r["datasets"]}
        self.assertEqual(seen, {q["dataset"] for q in self.ledger["queue"]})

    def test_rights_tiers_are_copied_not_upgraded_and_no_terms_are_claimed_read(self):
        tiers = {q["rights_tier"] for q in self.ledger["queue"]}
        for r in self.doc["sources"]:
            self.assertTrue(set(r["rights_tiers"]) <= tiers, r["source"])
            self.assertFalse(r["terms_read"], r["source"])
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

"""Market & Input Map (RESEARCH_ONLY): exact reconciliation with the approved catalog and market_completeness, byte-for-byte
reproducibility of the committed artifacts, and the fail-closed rights / no-double-count rules."""
import csv
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha_engine.input_research.data_foundation import market_completeness as MC  # noqa: E402
from alpha_engine.input_research.data_foundation import market_input_map as MIM  # noqa: E402

OUT = ROOT / "research/input_research/market_input_map"
D = MIM.load()
M = MIM.build(D)
R = M["reconciliation"]


def rows(name):
    return list(csv.DictReader(io.StringIO((OUT / name).read_text())))


class Reconciliation(unittest.TestCase):
    def test_pinned_counts(self):
        self.assertEqual(R["archetypes"], 170)
        self.assertEqual(R["archetypes_by_kind"], {"registered": 118, "unregistered": 52})
        self.assertEqual(R["distinct_inputs"], 1649)
        self.assertEqual(R["catalog_edges_all_classes"], 4243)
        self.assertEqual(R["predictive_slots"], 3670)
        self.assertEqual(R["predictive_primary_slots"], 1276)
        self.assertEqual(R["missing_primary_predictive_slots"], 949)

    def test_matches_market_completeness_per_archetype(self):
        x = R["market_completeness_cross_check"]
        self.assertEqual((x["n_required_sum"], x["primary_missing_critical_sum"], x["n_primary_sum"]), (3670, 949, 1276))
        self.assertTrue(x["per_archetype_predictive_match"])
        self.assertTrue(x["per_archetype_missing_primary_match"])
        mc = {f"{r['sport']}:{r['archetype']}": r for r in D["mc"]["rows"]}
        got = Counter((e["a"], e["cat"]) for e in M["edges"] if e["cls"] == "PREDICTIVE")
        for k, r in mc.items():
            for cat in MC.PRED_KEYS:
                self.assertEqual(got.get((k, cat), 0), r[cat], (k, cat))

    def test_units_are_not_conflated(self):
        self.assertEqual(sum(R["edges_by_class"].values()), R["catalog_edges_all_classes"])
        self.assertEqual(R["edges_by_class"]["PREDICTIVE"], R["predictive_slots"])
        self.assertEqual(sum(R["distinct_inputs_by_bucket"].values()), 1649)
        self.assertEqual(R["distinct_inputs_referenced_by_an_archetype"] + len(R["distinct_inputs_with_no_archetype_edge"]), 1649)
        self.assertGreater(R["queue_slot_dataset_pairs"], R["queue_distinct_slots_covered"])      # overlap is real and is not reported as a slot total
        self.assertEqual(R["queue_distinct_slots_covered"], 949)

    def test_non_predictive_classes_never_in_predictive_denominator(self):
        for e in M["edges"]:
            iid = e["i"].split(":", 1)[1]
            if iid in MC.NON_PREDICTIVE_IDS or e["cat"] == "EXCLUDED_MARKET":
                self.assertNotEqual(e["cls"], "PREDICTIVE", e)
            else:
                self.assertEqual(e["cls"], "PREDICTIVE", e)

    def test_statuses_preserved_verbatim(self):
        vc = D["vc"]
        for k, i in M["inputs"].items():
            self.assertEqual((i["bucket"], i["vstatus"]), (vc[k]["verified_bucket"], vc[k]["verified_status"]))
            self.assertIn(i["bucket"], MIM.BUCKETS)

    def test_no_unmapped_records_hidden(self):
        self.assertEqual(R["unmapped_catalog_edges"], [])
        self.assertEqual(R["unresolved_dataset_references"], [])
        self.assertEqual(R["queue_slots_without_dataset"], [])
        self.assertEqual(R["series_in_scope_unmapped_to_archetype"], 0)
        self.assertEqual(len(R["distinct_inputs_with_no_archetype_edge"]), 35)
        self.assertTrue(R["queue_covers_every_missing_primary_slot"])


class Queue(unittest.TestCase):
    def test_each_dataset_once_and_known(self):
        ids = [q["dataset"] for q in M["queue"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(ids) <= set(M["datasets"]))
        self.assertEqual([q["rank"] for q in M["queue"]], list(range(1, len(ids) + 1)))

    def test_slot_lists_deduplicated_and_counts_consistent(self):
        for q in M["queue"]:
            self.assertEqual(len(q["slots"]), len({tuple(s) for s in q["slots"]}))
            self.assertEqual(q["missing_primary_slots"], len(q["slots"]))
            self.assertEqual(sum(q["missing_by_category"].values()), q["missing_primary_slots"])
            self.assertTrue(q["next_actions"] and q["next_actions"][-1].startswith("BUILD:"))
            if q["access_status"] == "COLLECTED_ARCHIVE":
                self.assertIsNone(q["slots_where_only_outstanding_dataset"])

    def test_order_uses_only_recorded_factors(self):
        tr = {t: i for i, t in enumerate(D["reg"]["tier_order"])}
        keys = [(q["access_rank"], -tr[q["rights_tier"]], q["pit_rank"], MIM.COST_ORDER.get(q["cost"], 9), -q["missing_primary_slots"], q["dataset"]) for q in M["queue"]]
        self.assertEqual(keys, sorted(keys))
        for q in M["queue"]:
            d = D["datasets"][q["dataset"]]
            self.assertEqual((q["access_rank"], q["pit_rank"], q["access_status"]), (d["access_rank"], d["pit_rank"], d["access_status"]))


class QueueGroups(unittest.TestCase):
    G = R["queue_groups"]

    def test_every_dataset_in_exactly_one_group_rank_preserved(self):
        self.assertEqual(sum(v["datasets"] for v in self.G["groups"].values()), len(M["queue"]))
        self.assertEqual(sorted(r for v in self.G["groups"].values() for r in v["ranks"]), list(range(1, len(M["queue"]) + 1)))
        for q in M["queue"]:
            self.assertEqual(q["action_group"], MIM.action_group(q))
            self.assertIn(q["rank"], self.G["groups"][q["action_group"]]["ranks"])

    def test_group_counts_exact_and_not_double_counted(self):
        self.assertEqual(self.G["distinct_slots"], 949)
        self.assertEqual(sum(v["slots_exclusive_to_group"] for v in self.G["groups"].values()) + self.G["slots_spanning_groups"], 949)
        self.assertEqual(sum(v["slot_dataset_pairs"] for v in self.G["groups"].values()), R["queue_slot_dataset_pairs"])
        for g, v in self.G["groups"].items():
            rows = [q for q in M["queue"] if q["action_group"] == g]
            self.assertEqual(v["distinct_slots"], len({tuple(s) for q in rows for s in q["slots"]}), g)
            self.assertEqual(sum(v["by_access_status"].values()), v["datasets"], g)

    def test_group_rules_use_recorded_fields_only(self):
        for q in M["queue"]:
            g, a, ok = q["action_group"], q["access_status"], q["rights_use_status"] == "RESEARCH_USE_PERMITTED"
            if g == "ARCHIVED_BUILD_NEXT": self.assertTrue(a == "COLLECTED_ARCHIVE" and ok)
            if g == "RIGHTS_APPROVAL_NEEDED": self.assertFalse(ok); self.assertNotIn(a, ("PAID_ONLY", "SAMPLE_ONLY", "NO_FREE_SOURCE", "PROSPECTIVE_CAPTURE_ONLY"))
            if g == "FREE_COLLECTION_POSSIBLE": self.assertTrue(ok and a != "COLLECTED_ARCHIVE")
            if g == "PROSPECTIVE_CAPTURE_REQUIRED": self.assertEqual(a, "PROSPECTIVE_CAPTURE_ONLY")
            if g == "BLOCKED_OR_PAID": self.assertIn(a, ("PAID_ONLY", "SAMPLE_ONLY", "NO_FREE_SOURCE"))
            self.assertEqual(q["also_needs_rights_approval"], (not ok) and g != "RIGHTS_APPROVAL_NEEDED")

    def test_pinned_group_counts(self):
        self.assertEqual({g: v["datasets"] for g, v in self.G["groups"].items()},
                         {"ARCHIVED_BUILD_NEXT": 1, "RIGHTS_APPROVAL_NEEDED": 86, "FREE_COLLECTION_POSSIBLE": 0, "PROSPECTIVE_CAPTURE_REQUIRED": 26, "BLOCKED_OR_PAID": 8})


class Rights(unittest.TestCase):
    def test_usable_only_when_cleared_and_collection_allowed(self):
        reg = {s["id"]: s for s in D["reg"]["sources"]}
        for sid, s in M["sources"].items():
            r = s["rights"]
            if r["use_status"] == "RESEARCH_USE_PERMITTED":
                self.assertTrue(r["research_cleared"] and r["collection_allowed"], sid)
            if r["commercial_cleared"]:
                self.assertIn(r["tier"], D["reg"]["commercial_cleared_tiers"])
        for did, d in M["datasets"].items():
            r = d["rights"]
            if r["use_status"] == "RESEARCH_USE_PERMITTED":
                self.assertTrue(all(M["sources"][s]["rights"]["use_status"] == "RESEARCH_USE_PERMITTED" for s in d["sources"]), did)
        self.assertTrue(reg)

    def test_unregistered_sources_fail_closed(self):
        self.assertEqual(M["sources"]["kalshi_api"]["rights"]["use_status"], "NOT_CLEARED_NO_REGISTRY_ENTRY")
        self.assertEqual(M["sources"]["nflverse"]["rights"]["use_status"], "WRAPPER_LICENCE_UPSTREAM_CAVEAT_NOT_CLEARED")
        self.assertFalse(M["sources"]["sackmann"]["rights"]["commercial_cleared"])


class Artifacts(unittest.TestCase):
    def test_regeneration_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as t:
            MIM.main(["--out", t])
            made = sorted(p.name for p in Path(t).iterdir())
            self.assertEqual(made, sorted(p.name for p in OUT.iterdir()))
            for n in made:
                self.assertEqual((Path(t) / n).read_bytes(), (OUT / n).read_bytes(), n)

    def test_csv_exports_reconcile(self):
        e = rows("market_input_edges.csv")
        self.assertEqual(len(e), 4243)
        self.assertEqual(sum(int(r["is_predictive_slot"]) for r in e), 3670)
        self.assertEqual(sum(int(r["is_missing_primary_slot"]) for r in e), 949)
        i = rows("distinct_inputs.csv")
        self.assertEqual(len(i), 1649)
        self.assertEqual(len({r["input_key"] for r in i}), 1649)
        self.assertEqual(sum(int(r["n_markets"]) for r in i), 4243)
        de = rows("dataset_input_edges.csv")
        self.assertEqual(len(de), R["dataset_input_edges"])
        self.assertEqual(len({(r["dataset_id"], r["input_key"], r["edge_type"], r["need"], r["trigger"]) for r in de}), len(de))
        q = rows("acquisition_queue.csv")
        self.assertEqual(len(q), R["queue_datasets"])
        self.assertEqual(len({r["dataset_id"] for r in q}), len(q))

    def test_baseline_inputs_untouched(self):
        meta = json.loads((OUT / "reconciliation.json").read_text())["inputs_sha256"]
        self.assertIn("research/input_research/baseline_lock.json", meta)
        for p, h in meta.items():
            self.assertEqual(MIM._sha(ROOT / p), h, p)


if __name__ == "__main__":
    unittest.main()

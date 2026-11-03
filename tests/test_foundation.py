import json, unittest
from pathlib import Path
from alpha_engine.taxonomy import KINDS, classify
from alpha_engine.audit_schema import SPORTS

A = Path(__file__).resolve().parents[1] / "research" / "audit"
J = lambda n: json.load(open(A / n))


class Foundation(unittest.TestCase):
    def test_all_eight_sports_present_with_families(self):
        m = J("master_inventory.json")
        self.assertEqual(sorted(m["sports"]), sorted(SPORTS))
        for sp, v in m["sports"].items():
            self.assertGreater(v["families"], 5, sp)

    def test_every_family_classified_or_listed_unclassified(self):
        m = J("master_inventory.json")
        for f in m["families"]:
            self.assertIn(f["canonical"]["kind"], KINDS)
            if f["canonical"]["kind"] == "unclassified":
                self.assertIn(f["id"], m["sports"][f["sport"]]["unclassified_families"])

    def test_counts_never_claim_observation_without_basis(self):
        for f in J("master_inventory.json")["families"]:
            o = f["observed"]
            self.assertIn(o["state"], {"OBSERVED_NOW", "OBSERVED_PRIOR_SNAPSHOT_ONLY", "OBSERVED_SETTLED_ONLY", "DEFINED_NOT_OBSERVED", "SERIES_LISTED_COUNTS_UNKNOWN", "EMPTY_ALL_STATUSES_AT_SWEEP"})
            self.assertTrue(o["basis"] and o["as_of"], f["id"])
            if o["state"] == "OBSERVED_NOW" and o["markets_now"] is not None:
                self.assertGreater(o["markets_now"], 0, f["id"])

    def test_registry_covers_every_family_and_references_defined_inputs(self):
        r, m = J("input_registry.json"), J("master_inventory.json")
        for f in m["families"]:
            fr = r["sports"][f["sport"]]["families"][f["id"]]
            defs = {**r["common_inputs"], **r["sports"][f["sport"]]["inputs"]}
            self.assertTrue(fr["inputs"], f["id"])
            for i, t in fr["inputs"].items():
                self.assertIn(i, defs); self.assertIn(t, "ECX")

    def test_status_never_claims_collected_without_evidence(self):
        s = J("collection_status.json")
        for sp, v in s["sports"].items():
            for i, r in v["inputs"].items():
                if r["collection"] in ("PIT_ARCHIVED", "COLLECTED_NOT_PIT_ARCHIVED", "PARTIAL_OR_STALE", "SOURCE_AVAILABLE_NOT_COLLECTED", "NO_RELIABLE_SOURCE"):
                    self.assertTrue(r["curated"] and r["evidence"], f"{sp}/{i}")
                if not r["curated"] and r["collection"] != "DERIVED":
                    self.assertIn(r["collection"], {"CODE_REFERENCE_ONLY", "NO_REFERENCE_FOUND"})
                    self.assertEqual(r["model_use"], "UNKNOWN")

    def test_gap_report_has_all_sports_and_known_findings(self):
        g = J("collection_gap_report.json")
        self.assertEqual(sorted(g["sports"]), sorted(SPORTS))
        tennis = {r["input"]: r for r in g["sports"]["TENNIS"]["top_gaps"]}
        self.assertEqual(tennis["ten.surface_rating"]["collection"], "PARTIAL_OR_STALE")

    def test_nba_unmapped_series_gap_is_recorded(self):
        fams = {f["native_family"]: f for f in json.load(open(A / "inventory" / "NBA.json"))["families"]}
        tickers = {s["ticker"] for s in fams["UNMAPPED_SERIES"]["series"]}
        self.assertIn("KXNBASTATLEADER", tickers)      # mapped upstream by nba-edge-finder PR #82 once merged
        self.assertNotIn("KXNBAPTSPROT", tickers)       # protected variants are grouped under their stat family

    def test_classifier_periods(self):
        self.assertEqual(classify("CFB", "quarter_total", "KXNCAAF3QTOTAL")["period"], "Q3")
        self.assertEqual(classify("NHL", "period_total", "KXNHL2PTOTAL")["period"], "P2")
        self.assertEqual(classify("MLB", "inning_total", "KXMLBF5TOTAL")["period"], "F5")


if __name__ == "__main__":
    unittest.main()


class CuratedEvidencePaths(unittest.TestCase):
    def test_every_cited_sift_alpha_evidence_file_exists_and_status_counts_are_consistent(self):
        import json, os, re
        from alpha_engine.collection_curated import CUR
        root = os.path.join(os.path.dirname(__file__), "..")
        cited = {e[len("doc:sift-alpha/"):] for sport in CUR.values() for v in sport.values() for e in v[3] if e.startswith("doc:sift-alpha/")}
        self.assertTrue(cited)
        for rel in cited:
            self.assertTrue(os.path.exists(os.path.join(root, rel)), rel)
        # regenerated gap report must agree with the curated table (no stale numbers on the dashboard)
        g = json.load(open(os.path.join(root, "research", "audit", "collection_gap_report.json")))
        st = json.load(open(os.path.join(root, "research", "audit", "collection_status.json")))
        for sp, v in g["sports"].items():
            n_ref = sum(1 for i in st["sports"][sp]["inputs"].values() if i["verification_class"] == "CODE_REFERENCE_ONLY")
            self.assertEqual(v["verification_counts"].get("CODE_REFERENCE_ONLY", 0), n_ref, sp)
        base = sum(1 for sp in st["sports"].values() for i in sp["inputs"].values()
                   if i["verification_class"] == "CODE_REFERENCE_ONLY" and not i.get("added_overnight"))
        self.assertEqual(base, 102)  # baseline code-reference-only: 104 -> 102 after live period-scoring verification (cfb.half_split, cbb.half_split reclassified, see research/audit/period_scoring_verification.json); newly added candidates are tracked separately

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
            self.assertIn(o["state"], {"OBSERVED_NOW", "OBSERVED_PRIOR_SNAPSHOT_ONLY", "DEFINED_NOT_OBSERVED", "SERIES_LISTED_COUNTS_UNKNOWN"})
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
        self.assertIn("KXNBAPTSPROT", tickers)

    def test_classifier_periods(self):
        self.assertEqual(classify("CFB", "quarter_total", "KXNCAAF3QTOTAL")["period"], "Q3")
        self.assertEqual(classify("NHL", "period_total", "KXNHL2PTOTAL")["period"], "P2")
        self.assertEqual(classify("MLB", "inning_total", "KXMLBF5TOTAL")["period"], "F5")


if __name__ == "__main__":
    unittest.main()

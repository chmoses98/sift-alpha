import csv, json, tempfile, unittest
from pathlib import Path
from alpha_engine.soccer_ambiguity import resolve
from alpha_engine.tennis_intervals import analyse
from alpha_engine.variant_audit import audit

A = Path(__file__).resolve().parents[1] / "research" / "audit"


class Lineage(unittest.TestCase):
    def test_variant_audit_flags_settlement_difference_but_ignores_quotes(self):
        b = {"ticker": "KXX-G-P-5", "rules_primary": "r", "rules_secondary": "fair price if inactive", "settlement_timer_seconds": 60, "yes_ask_dollars": "0.5"}
        v = {"ticker": "KXXPROT-G-P-5", "rules_primary": "r", "rules_secondary": "protected after first half", "settlement_timer_seconds": 90, "yes_ask_dollars": "0.1"}
        r = audit([b, v], "PROT", {"KXX"})["KXX"]
        self.assertEqual(r["paired"], 1); self.assertFalse(r["settlement_equivalent"])
        self.assertEqual(r["settlement_fields_differing"], ["rules_secondary", "settlement_timer_seconds"])
        v2 = dict(v, rules_secondary=b["rules_secondary"], settlement_timer_seconds=60)
        self.assertTrue(audit([b, v2], "PROT", {"KXX"})["KXX"]["settlement_equivalent"])

    def test_nba_prot_series_kept_separate_and_not_equivalent(self):
        eq = json.load(open(A / "variants" / "NBA_PROT_equivalence.json"))["pairs"]
        self.assertEqual(sorted(eq), ["KXNBA3PT", "KXNBAAST", "KXNBAPTS", "KXNBAREB"])
        for b, v in eq.items():
            self.assertGreater(v["paired"], 100); self.assertFalse(v["settlement_equivalent"], b)
        fams = {f["native_family"]: f for f in json.load(open(A / "inventory" / "NBA.json"))["families"]}
        for fam, prot in (("player_points", "KXNBAPTSPROT"), ("player_rebounds", "KXNBAREBPROT"), ("player_assists", "KXNBAASTPROT"), ("player_threes", "KXNBA3PTPROT")):
            s = {x["ticker"]: x for x in fams[fam]["series"]}
            self.assertEqual(s[prot]["variant"], "protected"); self.assertFalse(s[prot]["settlement_equivalent_to_base"])
            self.assertIn(prot[:-4], s)                      # base stays a separate identifier in the same family

    def test_tennis_thin_month_detection(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            w = csv.DictWriter(f, ["date", "genre", "vainqueur_id", "score"]); w.writeheader()
            for m, n in (("2026-03", 10), ("2026-04", 10), ("2026-05", 2), ("2026-06", 10)):
                for i in range(n):
                    w.writerow({"date": f"{m}-01 10:00:00", "genre": "wta", "vainqueur_id": "1" if i else "", "score": "6-4 6-4"})
        r = analyse(f.name)["wta"]
        self.assertEqual([m["month"] for m in r["months"] if m["thin"]], ["2026-05"])
        self.assertEqual(r["months"][0]["rows_with_winner_and_score"], 9)

    def test_tennis_artifact_documents_frozen_intervals(self):
        d = json.load(open(A / "sources" / "tennis_results_intervals.json"))
        self.assertEqual(d["status"], "REPLACEMENT_AVAILABLE_PARTIAL_NOT_INGESTED")
        self.assertEqual(d["tours"]["wta"]["unavailable_from_primary"]["from"], "2026-04-27")
        self.assertIn("2026-05", d["tours"]["wta"]["candidate_thin_months_inside_gap"])

    def test_soccer_ambiguity_classes(self):
        r = resolve(["KXAFCONGAME", "KXAFCONTOTAL", "KXAFCONSPREAD", "KXAFCON", "KXEPLPOY", "KXLSUCOACH", "KXUFLGAME", "KXSORONDO"])
        self.assertEqual(r["KXAFCONGAME"][0], "SOCCER_BY_GRAMMAR"); self.assertEqual(r["KXAFCON"][0], "SOCCER_BY_GRAMMAR")
        self.assertEqual(r["KXEPLPOY"][0], "SOCCER_BY_NAME"); self.assertEqual(r["KXLSUCOACH"][0], "NOT_SOCCER_BY_NAME")
        self.assertEqual(r["KXUFLGAME"][0], "NOT_SOCCER_BY_NAME"); self.assertEqual(r["KXSORONDO"][0], "UNRESOLVED")
        d = json.load(open(A / "resolutions" / "soccer_ambiguous.json"))
        self.assertEqual(d["total"], 134); self.assertEqual(sum(d["counts"].values()), 134)

    def test_sweep_queues_cover_all_identified_series(self):
        self.assertEqual(len(json.load(open(A.parents[1] / "kalshi_sweep" / "queues" / "mlb_queue.json"))["series"]), 215)
        self.assertEqual(len(json.load(open(A.parents[1] / "kalshi_sweep" / "queues" / "soccer_ambiguous_queue.json"))["series"]), 48)


if __name__ == "__main__":
    unittest.main()

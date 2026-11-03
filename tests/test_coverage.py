import json, unittest
from pathlib import Path
from alpha_engine.family_coverage import attach
from alpha_engine.timestamp_integrity import check

A = Path(__file__).resolve().parents[1] / "research" / "audit"


class Coverage(unittest.TestCase):
    def test_timestamp_check_counts_rows_updated_after_stamp(self):
        rows = [{"_observed_at_utc": "2026-11-02T00:00:00Z", "updated_time": "2026-11-02T00:01:00Z", "created_time": "2026-11-01T00:00:00Z", "open_time": "2026-10-31T00:00:00Z", "status": "settled", "result": ""},
                {"_observed_at_utc": "2026-11-02T00:00:00Z", "updated_time": "2026-10-31T00:00:00Z", "status": "active"}]
        r = check(rows)
        self.assertEqual((r["updated_after_stamp"], r["max_lag_seconds"], r["open_before_created"], r["settled_without_result"]), (1, 60.0, 1, 1))

    def test_attach_marks_unscanned_and_never_seen(self):
        self.assertEqual(attach("XYZ", [{"series": [{"ticker": "X"}]}])[0]["historical"]["state"], "NOT_SCANNED")
        h = attach("TENNIS", [{"series": [{"ticker": "KXNOSUCH"}], "markets_historical_archived_tier": 12}])[0]["historical"]
        self.assertEqual(h["state"], "NEVER_SEEN_IN_SCANNED_DAYS"); self.assertTrue(h["exists_per_other_evidence"]); self.assertIn("NOT evidence", h["absence_meaning"])
        h = attach("TENNIS", [{"series": [{"ticker": "KXNOSUCH"}]}])[0]["historical"]
        self.assertFalse(h["exists_per_other_evidence"])

    def test_family_historical_is_present_for_every_family_and_consistent(self):
        m = json.load(open(A / "master_inventory.json"))
        for f in m["families"]:
            h = f["historical"]; self.assertIn(h["state"], {"OBSERVED", "NEVER_SEEN_IN_SCANNED_DAYS", "NO_SERIES_LISTED", "NOT_SCANNED"}, f["id"])
            if h["state"] == "OBSERVED":
                self.assertLessEqual(h["first_seen"], h["last_seen"]); self.assertLessEqual(h["days_present"], h["snapshot_days"])
                self.assertLessEqual(h["snapshot_days"], h["calendar_days_in_span"])

    def test_nba_archive_gap_is_measured(self):
        h = next(f for f in json.load(open(A / "master_inventory.json"))["families"] if f["id"] == "NBA/game_winner")["historical"]
        self.assertEqual(h["snapshot_days"], 41); self.assertEqual(h["calendar_days_without_snapshot"], 5)

    def test_integrity_artifact_records_all_three_sports(self):
        d = json.load(open(A / "integrity" / "timestamp_integrity.json"))["sports"]
        self.assertEqual(sorted(d), ["CBB", "NBA", "NHL"]); self.assertGreater(d["NBA"]["updated_after_stamp"], 0)

    def test_soccer_context_lineage_numbers_are_internally_consistent(self):
        d = json.load(open(A / "lineage" / "soccer_context_lineage.json"))
        self.assertAlmostEqual(d["lineups"]["share_pre_kickoff"], d["lineups"]["fixtures_with_pre_kickoff_xi"] / d["lineups"]["fixtures"], places=3)
        self.assertAlmostEqual(d["weather"]["share_rows_after_kickoff"], d["weather"]["rows_captured_after_kickoff"] / d["weather"]["rows"], delta=0.02)

    def test_verification_class_present_and_soccer_context_corrected(self):
        s = json.load(open(A / "collection_status.json"))["sports"]["SOCCER"]["inputs"]
        self.assertEqual(s["soc.lineups_pit"]["verification_class"], "VERIFIED_COLLECTION")
        self.assertEqual(s["soc.injuries"]["verification_class"], "MISSING")
        self.assertEqual(s["soc.xg"]["verification_class"], "MISSING")


if __name__ == "__main__":
    unittest.main()


class Lineage2(unittest.TestCase):
    def test_record_vs_batch_findings(self):
        f = {(x["sport"], x["dir"]): x for x in json.load(open(A / "integrity" / "record_vs_batch_timing.json"))["findings"]}
        g = f[("NHL", "context/goalie_observations")]
        self.assertEqual(g["record_obs_later_than_batch_stamp"], g["records"]); self.assertGreater(g["record_minus_batch_seconds_max"], 60)
        self.assertEqual(f[("MLB", "availability/mlb")]["with_source_time"], 0)
        self.assertEqual(f[("NHL", "context/lines")]["source_time_after_observation"], 0)

    def test_tennis_options_ingest_nothing_incomplete_or_restricted(self):
        d = json.load(open(A / "sources" / "tennis_results_options.json"))
        self.assertTrue(len(d["options"]) >= 6)
        for o in d["options"]:
            self.assertNotIn(o["status"], {"INGESTED"}); self.assertTrue(o["licence"] and o["decision"])
        partial = next(o for o in d["options"] if o["status"] == "PARTIAL_CANDIDATE"); self.assertTrue(partial["decision"].startswith("NOT ingested"))

    def test_curated_corrections_and_conversions(self):
        s = json.load(open(A / "collection_status.json"))["sports"]
        self.assertEqual(s["NHL"]["inputs"]["nhl.lines"]["verification_class"], "VERIFIED_COLLECTION")
        self.assertEqual(s["CFB"]["inputs"]["cfb.injuries"]["verification_class"], "STALE_OR_PARTIAL")     # 35 injury rows of 3,085
        self.assertEqual(s["NBA"]["inputs"]["nba.starters_pit"]["verification_class"], "MISSING")  # expected_*_starters empty on 0/376 sampled records
        n = sum(1 for sp in s.values() for r in sp["inputs"].values() if r["verification_class"] == "CODE_REFERENCE_ONLY" and not r.get("added_overnight"))
        self.assertLessEqual(n, 123 + 12)      # 12 new MLB market-specific inputs start as code-reference-only

    def test_family_history_for_all_eight_sports_is_scanned_or_labelled(self):
        m = json.load(open(A / "master_inventory.json"))
        c = {f["sport"]: set() for f in m["families"]}
        for f in m["families"]: c[f["sport"]].add(f["historical"]["state"])
        for sp in ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "TENNIS"): self.assertIn("OBSERVED", c[sp], sp)
        self.assertIn("OBSERVED", c["SOCCER"])


class FieldEvidence(unittest.TestCase):
    def test_field_evidence_artifact_backs_the_new_statuses(self):
        d = {(c["sport"], c["input"]): c for c in json.load(open(A / "lineage" / "field_evidence.json"))["checks"]}
        self.assertEqual(d[("NHL", "nhl.pace")]["key_populated_share"], {"corsiPercentage": 1.0, "fenwickPercentage": 1.0})
        self.assertEqual(d[("NBA", "nba.starters_pit")]["key_populated_share"]["expected_home_starters"], 0.0)
        self.assertTrue(all(v == 0.0 for v in d[("SOCCER", "soc.xg")]["key_populated_share"].values()))
        s = json.load(open(A / "collection_status.json"))["sports"]
        self.assertEqual(s["NHL"]["inputs"]["nhl.pace"]["verification_class"], "VERIFIED_COLLECTION")
        self.assertEqual(s["SOCCER"]["inputs"]["soc.xg"]["verification_class"], "MISSING")


class Gaps(unittest.TestCase):
    def test_nba_rotation_and_starters_are_missing_by_code_not_by_chance(self):
        s = json.load(open(A / "collection_status.json"))["sports"]["NBA"]["inputs"]
        for i in ("nba.starters_pit", "nba.rotation", "nba.matchup_def"):
            self.assertEqual(s[i]["verification_class"], "MISSING", i); self.assertIn("shadow.py", " ".join(s[i]["evidence"]))

    def test_archive_gap_artifact_lists_dates(self):
        g = json.load(open(A / "lineage" / "historical_archive_gaps.json"))["sports"]
        self.assertEqual(g["SOCCER"]["missing_calendar_days"], ["2026-10-04", "2026-10-05", "2026-10-06"]); self.assertEqual(len(g["NBA"]["missing_calendar_days"]), 5)
        self.assertTrue(g["NFL"]["sampled_not_exhaustive"] and g["NFL"]["missing_calendar_days"] is None)
        self.assertIn("2026-08-11", g["MLB"]["missing_calendar_days"])


class MarketRecords(unittest.TestCase):
    def test_market_record_field_evidence_backs_volume_and_lifecycle(self):
        d = json.load(open(A / "lineage" / "market_record_fields.json"))["sports"]
        s = json.load(open(A / "collection_status.json"))["sports"]
        for sp in ("NBA", "NHL", "CBB"):
            self.assertEqual(d[sp]["populated_share_all"]["close_time"], 1.0); self.assertEqual(d[sp]["populated_share_all"]["rules_primary"], 1.0)
            for i in ("m.volume_oi", "m.lifecycle"):
                self.assertEqual(s[sp]["inputs"][i]["verification_class"], "VERIFIED_COLLECTION", (sp, i))

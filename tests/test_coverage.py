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
        rows = attach("MLB", [{"series": [{"ticker": "X"}]}])
        self.assertEqual(rows[0]["historical"]["state"], "NOT_SCANNED")

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

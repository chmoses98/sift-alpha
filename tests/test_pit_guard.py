import copy, json, os, tempfile, unittest
from pathlib import Path
from alpha_engine.pit_guard import weather_pregame, write_quarantine

REAL = [  # shape of real weather_snapshot_v1 rows (soccer-edge-finder data-archive, 2026-09-28)
    {"espn_event_id": "1", "captured_at": "2026-09-28T03:49:04.266109+00:00", "kickoff_utc": "2026-09-28T01:10:00+00:00", "hours_before_kickoff": -2.65, "temperature_2m": 14.0},
    {"espn_event_id": "2", "captured_at": "2026-10-16T14:00:00+00:00", "kickoff_utc": "2026-10-16T22:00:00+00:00", "hours_before_kickoff": 8.0, "temperature_2m": 13.6}]


class Guard(unittest.TestCase):
    def test_after_kickoff_is_quarantined_before_kept(self):
        ok, bad = weather_pregame(REAL)
        self.assertEqual([r["espn_event_id"] for r in ok], ["2"]); self.assertEqual(bad[0][1], "CAPTURED_AFTER_KICKOFF")

    def test_exactly_at_kickoff_allowed_but_min_lead_blocks_it(self):
        r = dict(REAL[1], captured_at="2026-10-16T22:00:00+00:00", hours_before_kickoff=0.0)
        self.assertEqual(len(weather_pregame([r])[0]), 1)
        ok, bad = weather_pregame([r], min_lead_minutes=30); self.assertEqual((len(ok), bad[0][1]), (0, "INSIDE_MIN_LEAD"))

    def test_mislabelled_lead_time_is_quarantined(self):
        r = dict(REAL[1], hours_before_kickoff=20.0)
        self.assertEqual(weather_pregame([r])[1][0][1], "STATED_LEAD_DISAGREES_WITH_TIMESTAMPS")

    def test_missing_or_naive_timestamps_quarantined_not_dropped_silently(self):
        ok, bad = weather_pregame([{"espn_event_id": "3"}, dict(REAL[1], captured_at="2026-10-16T14:00:00")])
        self.assertEqual((len(ok), [b[1] for b in bad]), (0, ["MISSING_OR_NAIVE_TIMESTAMP"] * 2))

    def test_input_not_mutated_and_ledger_is_separate_append_only(self):
        recs = copy.deepcopy(REAL); weather_pregame(recs); self.assertEqual(recs, REAL)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "q.jsonl"); n = write_quarantine(weather_pregame(REAL)[1], p); write_quarantine(weather_pregame(REAL)[1], p)
            self.assertEqual(n, 1); self.assertEqual(len(open(p).read().splitlines()), 2)

    def test_archive_report_matches_rule(self):
        d = json.load(open(Path(__file__).resolve().parents[1] / "research/audit/lineage/soccer_weather_pit_report.json"))
        self.assertEqual(d["usable"] + d["quarantined"], d["rows"]); self.assertFalse(d["raw_archive_modified"])
        self.assertEqual(d["quarantine_reasons"], {"CAPTURED_AFTER_KICKOFF": d["quarantined"]})


if __name__ == "__main__":
    unittest.main()

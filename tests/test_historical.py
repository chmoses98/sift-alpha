"""Adversarial checks for actual historical research audit logic."""
import copy
import json
import unittest

from alpha_engine.audits import audit_cfb, audit_mlb
from alpha_engine.pinned import load_manifest, source_url, verify_blob
from alpha_engine.review import independent_review
from pathlib import Path

CFB = {
    "schema": "cfb_control_prospective_settlement/1.0.0", "event_id": "original-game-1",
    "kickoff_utc": "2026-10-10T19:30:00Z",
    "capture": {
        "status": "CAPTURE_OK", "entry": {"captured_at": "2026-10-10T18:20:00Z", "price": 0.63},
        "window_opens_at": "2026-10-10T16:30:00Z", "window_closes_at": "2026-10-10T18:30:00Z",
    },
    "final_pregame": {"recorded_at": "2026-10-10T19:10:00Z", "data_quality": "HIGH"},
    "settled_at": "2026-10-10T23:30:00Z",
    "settlement": {"status": "SETTLED", "control_won": True, "control_points": 28, "opponent_points": 14},
}
MLB = {
    "2026-08-03": {
        "date": "2026-08-03", "outcome": "completed",
        "recordedAt": "2026-08-04T00:36:42Z",
        "eligibilityStatus": "ELIGIBLE_LEVEL_2", "runStatus": "COMPLETED",
    },
    "2026-08-31": {
        "date": "2026-08-31", "outcome": "rejected_ineligible",
        "recordedAt": "2026-08-31T21:43:11Z",
        "eligibilityStatus": "INELIGIBLE_MISSING_INPUT",
    },
}


class HistoricalTests(unittest.TestCase):
    def test_cfb_sample_uses_all_games_not_post_selected(self):
        a = audit_cfb([CFB])
        self.assertEqual(a["n_independent_games"], 1)
        self.assertEqual(a["brier_market_price"], 0.1369)
        self.assertFalse(a["promotion_eligible"])
        self.assertEqual(a["statistical_conclusion"], "DESCRIPTIVE_ONLY")

    def test_missing_quote_record_is_preserved_as_explicit_exclusion(self):
        no_quote = copy.deepcopy(CFB)
        no_quote["event_id"] = "second-game-no-quote"
        no_quote["capture"]["status"] = "PRICE_1_00"
        no_quote["capture"]["entry"] = None
        scored = audit_cfb([CFB, no_quote])
        self.assertEqual(scored["n_source_games"], 2)
        self.assertEqual(scored["n_independent_games"], 1)
        self.assertEqual(scored["n_excluded"], 1)
        self.assertEqual(scored["exclusion_counts"], {"no_usable_pregame_quote": 1})
        missing_ok = copy.deepcopy(CFB)
        missing_ok["capture"]["entry"] = None
        with self.assertRaises(ValueError):
            audit_cfb([missing_ok])

    def test_cfb_rejects_tampered_or_future_rows(self):
        for path, value in [
            (("capture", "entry", "captured_at"), "2026-10-10T20:00:00Z"),
            (("final_pregame", "recorded_at"), "2026-10-10T19:40:00Z"),
            (("settlement", "control_won"), False),
            (("capture", "entry", "price"), 1.2),
            (("settlement", "status"), "PENDING"),
        ]:
            sample = copy.deepcopy(CFB)
            target = sample
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.assertRaises(ValueError, msg=str(path)):
                audit_cfb([sample])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit_cfb([CFB, CFB])

    def test_mlb_cannot_convert_missing_to_eligible(self):
        summary = audit_mlb(MLB)
        self.assertEqual(summary["n_archived_dates"], 2)
        self.assertEqual(summary["n_eligible_completed_replays"], 1)
        self.assertFalse(summary["promotion_eligible"])
        corrupted = copy.deepcopy(MLB)
        corrupted["2026-08-31"]["outcome"] = "completed"
        with self.assertRaises(ValueError):
            audit_mlb(corrupted)

    def test_independent_verifier_rejects_undocumented_output_edits(self):
        inputs = {"cfb_prospective_settlements": [CFB], "mlb_replay_status": MLB}
        report = {"version": 1, "authority": "RESEARCH_ONLY", "studies": {
            "cfb_prospective_settlements": audit_cfb([CFB]),
            "mlb_replay_status": audit_mlb(MLB),
        }}
        self.assertTrue(independent_review(report, inputs)["passed"])
        forged = copy.deepcopy(report)
        forged["studies"]["cfb_prospective_settlements"]["observed_win_fraction"] = 0.85
        self.assertFalse(independent_review(forged, inputs)["passed"])
        forged = copy.deepcopy(report)
        forged["authority"] = "LIVE_TRADE"
        self.assertFalse(independent_review(forged, inputs)["passed"])

    def test_manifest_rejects_unpinned_and_non_allowlisted_sources(self):
        rows = load_manifest(Path("research/pinned_sources.json"))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(source_url(row).startswith("https://raw.githubusercontent.com/chmoses98/"))
            with self.assertRaises(ValueError):
                verify_blob(b"fabricated data", row)
        payload = json.loads(Path("research/pinned_sources.json").read_text())
        payload["sources"][0]["repo"] = "somebody/other"
        scratch = Path("tests/.bad_manifest.json")
        try:
            scratch.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                load_manifest(scratch)
        finally:
            scratch.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

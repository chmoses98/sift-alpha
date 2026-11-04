"""Offline end-to-end capture -> independently verified -> dashboard evidence."""
import copy
import json
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from alpha_engine.series_pagination import verify_capture, capture_series
from alpha_engine.series_inventory_bridge import audit_capture, append

SERIES = "KXNFLGAME"
NOW = "2026-11-02T18:00:00Z"


def fetch(url):
    if "cursor=" not in url:
        rows = [{"ticker": SERIES + "-A", "series_ticker": SERIES,
                 "event_ticker": SERIES + "-EVENT",
                 "rules_primary": "Team A wins", "rules_secondary": "Official final",
                 "cap_strike": 28.5, "yes_sub_title": "Over 28.5",
                 "close_time": "2026-11-02T23:00:00Z", "status": "open",
                 "result": ""}]
        cursor = "next"
    else:
        rows = [{"ticker": SERIES + "-B", "series_ticker": SERIES,
                 "event_ticker": SERIES + "-EVENT",
                 "rules_primary": "Team B wins", "rules_secondary": "Official final"}]
        cursor = None
    return json.dumps({"markets": rows, "cursor": cursor}).encode(), "Mon, 02 Nov 2026 18:00:00 GMT"


def matrix():
    return {"authority": "RESEARCH_ONLY_NOT_LIVE_COLLECTION",
            "live_capture_running": False, "all_market_families_certified": False,
            "family_rows": [], "missing_input_queue": []}


class BridgeTests(unittest.TestCase):
    def test_two_original_pages_become_dashboard_row_without_model_claims(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d, fetcher=fetch)
            row = audit_capture(d, m, "NFL")
            self.assertEqual(row["observed_denominator"], 2)
            self.assertEqual(len(row["observed_contracts"]), 2)
            self.assertEqual(len(row["source_page_sha256"]), 2)
            self.assertEqual(row["observed_contracts"][0]["rules_primary"], "Team A wins")
            self.assertEqual(row["observed_contracts"][0]["cap_strike"], 28.5)
            self.assertEqual(row["observed_contracts"][0]["yes_sub_title"], "Over 28.5")
            self.assertEqual(row["observed_contracts"][0]["close_time"], "2026-11-02T23:00:00Z")
            self.assertEqual(row["observed_contracts"][0]["status_at_receipt"], "open")
            self.assertEqual(row["observed_contracts"][0]["result_at_receipt_unverified"], "")
            self.assertEqual(row["observed_contracts"][1]["rules_secondary"], "Official final")
            self.assertEqual(row["market_collection_status"], "COLLECTED_VALID")
            self.assertEqual(row["model_usage_status"], "UNKNOWN")
            self.assertEqual(row["point_in_time_pregame_eligibility"], "UNKNOWN")
            self.assertIsNone(row["independently_valid_evaluations"])
            self.assertEqual(row["exact_settlement_rule_status"],
                             "LITERAL_RULES_CAPTURED_NOT_INDEPENDENTLY_VERIFIED")
            output = append(matrix(), row)
            self.assertEqual(len(output["family_rows"]), 1)
            self.assertEqual(output["missing_input_queue"][0]["denominator"], 2)
            self.assertFalse(output["live_capture_running"])
            self.assertFalse(output["all_market_families_certified"])
            with self.assertRaisesRegex(ValueError, "already added"):
                append(output, row)

    def test_partial_capture_cannot_claim_complete(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d, fetcher=fetch, max_pages=1)
            row = audit_capture(d, m, "NFL")
            self.assertEqual(row["observed_denominator"], 1)
            self.assertFalse(row["all_reported_pages_retrieved"])
            self.assertFalse(row["complete_series_or_market_tape"])
            self.assertIn("REMAINING_SERIES_PAGES", append(matrix(), row)["missing_input_queue"][0]["missing"])

    def test_tampered_source_or_manifest_rejected_before_dashboard(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d, fetcher=fetch)
            altered = copy.deepcopy(m)
            altered["observed_denominator"] = 999
            with self.assertRaises(ValueError):
                audit_capture(d, altered, "NFL")
            page = Path(d)/SERIES/m["pages"][0]["file"]
            page.write_bytes(b'{"markets":[]}')
            with self.assertRaises(ValueError):
                audit_capture(d, m, "NFL")

    def test_independent_verifier_enforces_aggregate_byte_budget(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d, fetcher=fetch)
            # A previously captured original can still fail a tighter
            # independent verification budget; no page hashes are altered.
            with patch("alpha_engine.series_pagination.MAX_TOTAL_BYTES", 1):
                with self.assertRaisesRegex(ValueError, "total response budget"):
                    verify_capture(d, m)

    def test_independent_verifier_rejects_cyclic_cursor_even_with_matching_hash(self):
        import hashlib
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d, fetcher=fetch)
            page = Path(d) / SERIES / m["pages"][1]["file"]
            payload = json.loads(page.read_bytes())
            payload["cursor"] = "next"  # same cursor as the first page
            raw = json.dumps(payload).encode()
            page.write_bytes(raw)
            m["pages"][1]["sha256"] = hashlib.sha256(raw).hexdigest()
            m["pages"][1]["bytes"] = len(raw)
            m["pages"][1]["next_cursor"] = "next"
            m["pagination"] = "INCOMPLETE_PAGE_LIMIT"
            m["all_reported_pages_retrieved"] = False
            with self.assertRaisesRegex(ValueError, "Cyclic verified pagination cursor"):
                verify_capture(d, m)

    def test_future_capture_clock_and_unsupported_sport(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d, fetcher=fetch)
            with self.assertRaises(ValueError):
                audit_capture(d, m, "NOT_A_SPORT")
            altered = copy.deepcopy(m)
            altered["captured_at_utc"] = "2099-01-01T00:00:00Z"
            with self.assertRaises(ValueError):
                audit_capture(d, altered, "NFL")


if __name__ == "__main__":
    unittest.main()

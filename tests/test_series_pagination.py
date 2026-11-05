"""Adversarial offline acceptance: previously one page, now bounded multi-page."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from alpha_engine.free_market_capture import capture
from alpha_engine.series_pagination import capture_series, verify_capture

NOW = "2026-11-02T18:00:00Z"
SERIES = "KXNFLGAME"


def payload(tickers, cursor=None):
    return json.dumps({
        "markets": [{"ticker": ticker, "series_ticker": SERIES} for ticker in tickers],
        "cursor": cursor,
    }, sort_keys=True).encode()


class MultiPageTests(unittest.TestCase):
    def test_real_defect_one_page_vs_two_page_and_independent_verify(self):
        def fetch(url):
            return (payload([SERIES + "-A"], "next") if "cursor=" not in url
                    else payload([SERIES + "-B"])), "Mon, 02 Nov 2026 18:00:00 GMT"
        with TemporaryDirectory() as d:
            old = capture(SERIES, NOW, d + "/old", fetcher=fetch)
            self.assertEqual(old["page_contract_count"], 1)
            self.assertEqual(old["pagination"], "INCOMPLETE_PAGE")
            new = capture_series(SERIES, NOW, d + "/new", fetcher=fetch)
            self.assertEqual(new["observed_denominator"], 2)
            self.assertEqual(new["n_pages"], 2)
            self.assertTrue(new["all_reported_pages_retrieved"])
            self.assertFalse(new["complete_series_or_market_tape"])
            self.assertFalse(new["pregame_or_forecast_join_verified"])
            self.assertEqual(verify_capture(d + "/new", new)["observed_denominator"], 2)
            self.assertEqual(len(list((Path(d)/"new"/SERIES).glob("*.page*.json"))), 2)
            with self.assertRaisesRegex(ValueError, "Rate limit"):
                capture_series(SERIES, "2026-11-02T18:01:00Z", d + "/new", fetcher=fetch)

    def test_page_cap_preserves_partial_and_denominator(self):
        with TemporaryDirectory() as d:
            def fetch(url):
                return payload([SERIES + ("-A" if "cursor=" not in url else "-B")],
                               "next" if "cursor=" not in url else "more"), None
            m = capture_series(SERIES, NOW, d, fetcher=fetch, max_pages=2)
            self.assertEqual(m["observed_denominator"], 2)
            self.assertFalse(m["all_reported_pages_retrieved"])
            self.assertEqual(m["pagination"], "INCOMPLETE_PAGE_LIMIT")
            self.assertFalse(verify_capture(d, m)["all_reported_pages_retrieved"])

    def test_duplicate_across_pages_fails_before_writing(self):
        with TemporaryDirectory() as d:
            def fetch(url):
                return payload([SERIES + "-A"], "next" if "cursor=" not in url else None), None
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                capture_series(SERIES, NOW, d, fetcher=fetch)
            self.assertFalse(list((Path(d)/SERIES).glob("*.json")))

    def test_cycle_and_wrong_series_and_cursor_limit(self):
        scenarios = [
            lambda url: (payload([SERIES + "-A"], "next"), None),
            lambda url: (payload(["KXNBAGAME-OTHER"]), None),
            lambda url: (payload([SERIES + "-A"], "x" * 2049), None),
        ]
        for scenario in scenarios:
            with self.subTest(scenario=scenario), TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    capture_series(SERIES, NOW, d, fetcher=scenario, max_pages=3)
                self.assertFalse(list((Path(d)/SERIES).glob("*.json")))

    def test_original_source_hash_and_denominator_adversarial(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d,
                fetcher=lambda url: (payload([SERIES + "-A"]), None))
            self.assertEqual(verify_capture(d, m)["observed_denominator"], 1)
            forged = copy.deepcopy(m)
            forged["observed_denominator"] = 2
            with self.assertRaisesRegex(ValueError, "Inflated"):
                verify_capture(d, forged)
            forged = copy.deepcopy(m)
            forged["all_reported_pages_retrieved"] = False
            with self.assertRaisesRegex(ValueError, "Inflated"):
                verify_capture(d, forged)
            forged = copy.deepcopy(m)
            forged["pages"][0]["next_cursor"] = "fake"
            with self.assertRaisesRegex(ValueError, "Cursor"):
                verify_capture(d, forged)
            page = Path(d)/SERIES/m["pages"][0]["file"]
            page.write_bytes(payload([SERIES + "-B"]))
            with self.assertRaisesRegex(ValueError, "tampered"):
                verify_capture(d, m)

    def test_independent_verifier_rejects_oversized_page_even_if_rehashed(self):
        # A forged stored page must not bypass the collector's 100-row bound.
        # Hash consistency alone is insufficient for a valid capture.
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d,
                fetcher=lambda url: (payload([SERIES + "-A"]), None))
            self.assertEqual(verify_capture(d, m)["observed_denominator"], 1)
            forged = copy.deepcopy(m)
            oversized = payload([SERIES + "-" + str(i) for i in range(101)])
            page = Path(d)/SERIES/m["pages"][0]["file"]
            page.write_bytes(oversized)
            forged["pages"][0]["sha256"] = hashlib.sha256(oversized).hexdigest()
            forged["pages"][0]["bytes"] = len(oversized)
            forged["pages"][0]["n_contracts"] = 101
            forged["observed_denominator"] = 101
            with self.assertRaisesRegex(ValueError, "denominator"):
                verify_capture(d, forged)

    def test_request_clock_cannot_bypass_receipt_rate_limit(self):
        with TemporaryDirectory() as d:
            m = capture_series(SERIES, NOW, d,
                fetcher=lambda url: (payload([SERIES + "-A"]), None))
            self.assertEqual(verify_capture(d, m)["observed_denominator"], 1)
            # Previously a caller could advance its supplied timestamp by six
            # minutes and immediately make another request. Real receipt time
            # must govern the rate limit, not the caller's claim.
            with self.assertRaisesRegex(ValueError, "Rate limit"):
                capture_series(SERIES, "2026-11-02T18:06:00Z", d,
                    fetcher=lambda url: (payload([SERIES + "-B"]), None))
            forged = copy.deepcopy(m)
            forged["pages"][0]["received_at_utc"] = "2026-11-02T17:59:59Z"
            with self.assertRaisesRegex(ValueError, "chronology"):
                verify_capture(d, forged)
            forged = copy.deepcopy(m)
            forged["captured_at_utc"] = "2099-01-01T00:00:00Z"
            with self.assertRaisesRegex(ValueError, "chronology"):
                verify_capture(d, forged)

    def test_future_requested_capture_rejected_before_storage(self):
        with TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "later than HTTP receipt"):
                capture_series(SERIES, "2099-01-01T00:00:00Z", d,
                    fetcher=lambda url: (payload([SERIES + "-A"]), None))
            self.assertFalse(list((Path(d)/SERIES).glob("*.json")))

    def test_bad_page_and_clock_do_not_invent_capture(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                capture_series(SERIES, NOW, d, fetcher=lambda url: (b"{}", None))
            self.assertFalse(list((Path(d)/SERIES).glob("*.json")))
            with self.assertRaises(ValueError):
                capture_series(SERIES, NOW, d, fetcher=lambda url: (payload([]), None), max_pages=100)
            self.assertFalse(list((Path(d)/SERIES).glob("*.json")))


if __name__ == "__main__":
    unittest.main()

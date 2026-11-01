"""Offline adversarial tests: opt-in public capture cannot imply live tape."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from alpha_engine.free_market_capture import capture, endpoint, MAX_BYTES

NOW = "2026-11-01T22:00:00Z"


def fetch(url):
    return json.dumps({"markets": [{"ticker": "KXNFLGAME-TEST"}],
                       "cursor": "next"}).encode(), "Sun, 01 Nov 2026 22:00:00 GMT"


class CaptureTests(unittest.TestCase):
    def test_one_page_immutable_and_rate_limited(self):
        with TemporaryDirectory() as d:
            m = capture("KXNFLGAME", NOW, d, fetcher=fetch)
            self.assertEqual(m["pagination"], "INCOMPLETE_PAGE")
            self.assertFalse(m["complete_series_or_market_tape"])
            self.assertFalse(m["actual_start_or_settlement_verified"])
            root = Path(d)/"KXNFLGAME"
            self.assertEqual(len(list(root.glob("*.manifest.json"))), 1)
            with self.assertRaises(ValueError):
                capture("KXNFLGAME", "2026-11-01T22:01:00Z", d, fetcher=fetch)
            self.assertEqual(len(list(root.glob("*.json"))), 2)
            capture("KXNFLGAME", "2026-11-01T22:05:00Z", d, fetcher=fetch)
            self.assertEqual(len(list(root.glob("*.manifest.json"))), 2)

    def test_fixed_public_endpoint_no_url_injection(self):
        self.assertIn("status=open", endpoint("KXNFLGAME"))
        for x in ("https://evil.example", "KXNFLGAME&limit=10000",
                  "KX", "kxnfl", "../KXNFL"):
            with self.assertRaises(ValueError):
                endpoint(x)

    def test_bad_data_does_not_persist(self):
        bad = [b"not-json", b"{}", b'{"markets":[{"ticker":"X"},{"ticker":"X"}]}',
               b'{"markets":[{"ticker":"X"}],"cursor":42}', b" "*(MAX_BYTES+1)]
        for raw in bad:
            with TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    capture("KXNFLGAME", NOW, d, fetcher=lambda _: (raw, None))
                self.assertFalse(list((Path(d)/"KXNFLGAME").glob("*.json")))

    def test_rollback_denied(self):
        with TemporaryDirectory() as d:
            capture("KXNFLGAME", NOW, d, fetcher=fetch)
            with self.assertRaises(ValueError):
                capture("KXNFLGAME", "2026-11-01T21:00:00Z", d, fetcher=fetch)


if __name__ == "__main__":
    unittest.main()

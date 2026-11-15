"""A quota refusal is distinguishable from a missing/altered archive, and still fails closed (offline)."""
import io
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from alpha_engine import hitter_archive_gate as gate


def _err(code, body=b"", headers=None):
    return HTTPError("https://api.github.com/x", code, "x", headers or {}, io.BytesIO(body))


class _Resp:
    def __init__(self, url, data):
        self.url, self.data = url, data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def geturl(self):
        return self.url
    def read(self, n):
        return self.data[:n]


class RateLimitTests(unittest.TestCase):
    url = "https://api.github.com/repos/o/r/git/trees/abc"

    def test_rate_limit_retried_then_succeeds(self):
        calls = []
        def opener(req, timeout):
            calls.append(req)
            if len(calls) == 1:
                raise _err(403, b'{"message":"API rate limit exceeded"}')
            return _Resp(self.url, b"{}")
        self.assertEqual(gate._fetch(self.url, 10, opener=opener, sleep=lambda s: None), b"{}")
        self.assertEqual(len(calls), 2)

    def test_persistent_rate_limit_raises_distinct_error(self):
        def opener(req, timeout):
            raise _err(429)
        with self.assertRaises(gate.SourceRateLimited):
            gate._fetch(self.url, 10, opener=opener, sleep=lambda s: None)

    def test_missing_archive_is_not_a_rate_limit(self):
        for code, body in ((404, b"Not Found"), (403, b"Resource not accessible")):
            def opener(req, timeout, code=code, body=body):
                raise _err(code, body)
            with self.assertRaises(HTTPError) as cm:
                gate._fetch(self.url, 10, opener=opener, sleep=lambda s: None)
            self.assertNotIsInstance(cm.exception, gate.SourceRateLimited)

    def test_main_fails_closed_with_distinct_exit_and_no_evidence(self):
        with patch.object(gate, "run", side_effect=gate.SourceRateLimited("quota")), \
             patch("pathlib.Path.write_text") as w:
            with self.assertRaises(SystemExit) as cm:
                gate.main()
        self.assertEqual(cm.exception.code, gate.EXIT_RATE_LIMITED)
        w.assert_not_called()

    def test_token_only_sent_to_api_github(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "t"}):
            self.assertEqual(gate._request(self.url).get_header("Authorization"), "Bearer t")
            raw = gate._request("https://raw.githubusercontent.com/o/r/c/p")
            self.assertIsNone(raw.get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()

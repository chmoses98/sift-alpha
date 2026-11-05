import unittest
from urllib.error import HTTPError

from alpha_engine import netretry as nr
from alpha_engine import verified_chains as vc


class R:
    def __init__(s, body, url="u"): s.b, s.u = body, url
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def geturl(s): return s.u
    def read(s, n): return s.b[:n]


def seq(items, calls):
    def op(req, timeout):
        calls.append(1); x = items[min(len(calls) - 1, len(items) - 1)]
        if isinstance(x, BaseException): raise x
        return R(x)
    return op


class Retry(unittest.TestCase):
    def test_503_between_bytes_is_retried(self):
        c = []
        out = nr.read_with_retry("r", 5, 10, opener=seq([HTTPError("u", 503, "between bytes timeout", {}, None), b"ok"], c), sleep=lambda s: None)
        self.assertEqual(out, b"ok"); self.assertEqual(len(c), 2)

    def test_bounded(self):
        c = []
        with self.assertRaises(HTTPError):
            nr.read_with_retry("r", 5, 10, opener=seq([HTTPError("u", 503, "x", {}, None)], c), sleep=lambda s: None)
        self.assertEqual(len(c), nr.ATTEMPTS)

    def test_permanent_4xx_and_redirect_not_retried(self):
        c = []
        with self.assertRaises(HTTPError):
            nr.read_with_retry("r", 5, 10, opener=seq([HTTPError("u", 404, "x", {}, None)], c), sleep=lambda s: None)
        self.assertEqual(len(c), 1)
        with self.assertRaises(ValueError):
            nr.read_with_retry("r", 5, 10, opener=lambda r, timeout: R(b"x", "https://evil"), expect_url="u", sleep=lambda s: None)

    def test_pinned_read_still_rejects_wrong_hash_after_retry(self):
        chain = {"repository": "o/r", "commit": "c"}
        entry = {"path": "p", "bytes": 3, "sha": "0" * 40}
        orig = vc.urlopen
        calls = []
        vc.urlopen = lambda req, timeout: (calls.append(1), R(b"abc", vc.source_url(chain, entry)))[1]
        try:
            with self.assertRaises(ValueError):
                vc.pinned_read(chain, entry)
        finally:
            vc.urlopen = orig
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

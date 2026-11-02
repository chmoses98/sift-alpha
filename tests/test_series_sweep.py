import copy, unittest
from alpha_engine.series_sweep import Sweeper, STATUSES


def make(pages, calls, fail429=0):
    """pages: {(series,status): [list_of_markets_page1, page2...]}; first `fail429` calls return 429."""
    n = {"c": 0}

    def fetch(s, st, cur):
        n["c"] += 1; calls.append((s, st, cur))
        if n["c"] <= fail429:
            return 429, {}, {"Retry-After": "1"}
        pg = pages.get((s, st), [[]]); i = int(cur or 0)
        return 200, {"markets": pg[i], "cursor": str(i + 1) if i + 1 < len(pg) else ""}, {}
    return fetch


def mk(t, ev, ot="2026-10-01T00:00:00Z"):
    return {"ticker": t, "event_ticker": ev, "open_time": ot, "title": t, "rules_primary": "r"}


class Sweep(unittest.TestCase):
    def test_paginates_and_counts(self):
        calls = []; st = {}
        pages = {("A", "open"): [[mk("A-1", "A-E1"), mk("A-2", "A-E1")], [mk("A-3", "A-E2")]]}
        ok = Sweeper(make(pages, calls), st, sleep=lambda s: None).run(["A"])
        self.assertTrue(ok)
        e = st["series"]["A"]["open"]
        self.assertEqual((e["markets"], e["complete"], e["event_count"]), (3, True, 2))
        self.assertEqual(sum(st["series"]["A"][s]["markets"] for s in STATUSES), 3)

    def test_429_backoff_then_success_and_waits(self):
        calls, waits, st = [], [], {}
        Sweeper(make({}, calls, fail429=2), st, sleep=waits.append, min_interval=0).run(["A"])
        self.assertEqual(st["rate_limited"], 2)
        self.assertEqual(waits[:2], [1.0, 1.0])

    def test_budget_stop_and_resume_without_refetching_done_pairs(self):
        pages = {("A", "open"): [[mk("A-1", "E")], [mk("A-2", "E")]], ("B", "open"): [[mk("B-1", "F")]]}
        calls1, st = [], {}
        done = Sweeper(make(pages, calls1), st, sleep=lambda s: None, max_requests=1).run(["A", "B"])
        self.assertFalse(done)
        self.assertEqual(st["series"]["A"]["open"]["cursor"], "1")   # saved mid-pagination
        calls2 = []
        done = Sweeper(make(pages, calls2), copy.deepcopy(st), sleep=lambda s: None, max_requests=100).run(["A", "B"])
        self.assertTrue(done)
        self.assertNotIn(("A", "open", None), calls2)                 # first page not refetched
        self.assertIn(("A", "open", "1"), calls2)

    def test_exhausted_429_retries_stop_without_marking_complete(self):
        calls, st = [], {}
        done = Sweeper(make({}, calls, fail429=99), st, sleep=lambda s: None, retries=2).run(["A"])
        self.assertFalse(done)
        self.assertFalse(st["series"]["A"]["open"]["complete"])

    def test_http_error_recorded_not_completed(self):
        st = {}
        Sweeper(lambda s, t, c: (404, {}, {}), st, sleep=lambda s: None).run(["A"])
        self.assertTrue(st["errors"]); self.assertFalse(st["series"]["A"]["open"]["complete"])


if __name__ == "__main__":
    unittest.main()

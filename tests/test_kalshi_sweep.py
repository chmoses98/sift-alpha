import copy, json, re, unittest
from pathlib import Path
import yaml
from kalshi_sweep.series_sweep import Sweeper, STATUSES

R = Path(__file__).resolve().parents[1]
W = yaml.safe_load(open(R / ".github/workflows/kalshi-series-sweep.yml"))
TXT = open(R / ".github/workflows/kalshi-series-sweep.yml").read()


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



class SweepWorkflow(unittest.TestCase):
    def test_manual_only_read_only_no_secrets(self):
        on = W.get("on") or W.get(True)
        self.assertEqual(list(on), ["workflow_dispatch"])
        self.assertEqual(W["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", TXT)
        self.assertNotRegex(TXT, r"\bschedule\b|cron")

    def test_inputs_are_choice_and_not_interpolated_into_shell(self):
        inp = (W.get("on") or W.get(True))["workflow_dispatch"]["inputs"]
        self.assertEqual(inp["queue"]["type"], "choice")
        for q in inp["queue"]["options"]:
            self.assertTrue((R / "kalshi_sweep/queues" / q).exists(), q)
        run = [s["run"] for s in W["jobs"]["sweep"]["steps"] if "run" in s][0]
        self.assertNotIn("${{", run)                    # inputs reach the shell only via env

    def test_bounded_and_serialised(self):
        j = W["jobs"]["sweep"]
        self.assertLessEqual(j["timeout-minutes"], 30)
        self.assertEqual(W["concurrency"]["cancel-in-progress"], False)
        self.assertIn("--max-requests", TXT); self.assertIn("--min-interval", TXT)

    def test_resumable_state_cache_and_artifact(self):
        uses = [s.get("uses", "") for s in W["jobs"]["sweep"]["steps"]]
        self.assertTrue(any(u.startswith("actions/cache") for u in uses)); self.assertTrue(any(u.startswith("actions/upload-artifact") for u in uses))
        self.assertIn("restore-keys", TXT)

    def test_queues_are_nonempty_unique_tickers(self):
        for f, n in (("mlb_queue.json", 215), ("soccer_ambiguous_queue.json", 48)):
            q = json.load(open(R / "kalshi_sweep/queues" / f))["series"]
            self.assertEqual((len(q), len(set(q))), (n, n)); self.assertTrue(all(re.fullmatch(r"[A-Z0-9-]+", t) for t in q), f)


class EndToEnd(unittest.TestCase):
    """Runs the real CLI (as the workflow does) against a local fake Kalshi: pagination, a 429, budget stop, resume."""
    def test_cli_stops_on_budget_then_resumes_from_state(self):
        import http.server, subprocess, sys, tempfile, threading, os
        hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query); hits.append((q["series_ticker"][0], q["status"][0], q.get("cursor", [""])[0]))
                if len(hits) == 1:
                    self.send_response(429); self.send_header("Retry-After", "0"); self.end_headers(); return
                pg = int(q.get("cursor", ["0"])[0]) if q["status"][0] == "open" else 0
                body = {"markets": [{"ticker": f"{q['series_ticker'][0]}-{pg}", "event_ticker": "E1", "open_time": "2026-10-01T00:00:00Z", "title": "t", "rules_primary": "r"}] if q["status"][0] == "open" else [],
                        "cursor": "1" if q["status"][0] == "open" and pg == 0 else ""}
                data = json.dumps(body).encode(); self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = dict(os.environ, KALSHI_BASE_URL=f"http://127.0.0.1:{srv.server_port}/markets")
        with tempfile.TemporaryDirectory() as d:
            q = os.path.join(d, "q.json"); st = os.path.join(d, "state.json"); json.dump({"series": ["AAA", "BBB"]}, open(q, "w"))
            run = lambda n: subprocess.run([sys.executable, "-m", "kalshi_sweep.series_sweep", q, st, "--max-requests", str(n), "--min-interval", "0"], cwd=R, env=env, capture_output=True, text=True)
            r1 = run(3); self.assertEqual(r1.returncode, 3, r1.stdout + r1.stderr)
            s1 = json.load(open(st)); self.assertEqual(s1["rate_limited"], 1); self.assertFalse(s1["series"]["AAA"]["settled"]["complete"] if "settled" in s1["series"]["AAA"] else False)
            r2 = run(200); self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            s2 = json.load(open(st)); self.assertTrue(all(s2["series"][s][k]["complete"] for s in ("AAA", "BBB") for k in ("open", "unopened", "closed", "settled")))
            self.assertEqual(s2["series"]["AAA"]["open"]["markets"], 2)
        srv.shutdown()

    def test_refuses_non_kalshi_base_url(self):
        import subprocess, sys, os, tempfile
        with tempfile.TemporaryDirectory() as d:
            q = os.path.join(d, "q.json"); json.dump({"series": ["A"]}, open(q, "w"))
            r = subprocess.run([sys.executable, "-m", "kalshi_sweep.series_sweep", q, os.path.join(d, "s.json"), "--max-requests", "1"], cwd=R, env=dict(os.environ, KALSHI_BASE_URL="https://evil.example/x"), capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0); self.assertIn("refusing", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

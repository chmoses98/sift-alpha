"""Access proposal under the owner's policy and the prospective-capture tooling (RESEARCH_ONLY). Nothing here may enable a workflow, change an environment or touch a restricted source."""
import gzip
import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DF = ROOT / "research/input_research/data_foundation"
AP = json.loads((DF / "network_access_proposal.json").read_text())
CAP = json.loads((DF / "capture_status.json").read_text())


class AccessProposal(unittest.TestCase):
    def test_nothing_is_changed_and_the_owners_narrow_list_is_the_allow_tier(self):
        self.assertIn("none", AP["changes_made"])
        allow = {x["host"] for x in AP["needs_new_host"] if x["tier"] == "ALLOW"}
        self.assertEqual(allow, {"en.wikipedia.org", "api.collegefootballdata.com", "archive-api.open-meteo.com", "historical-forecast-api.open-meteo.com", "api.weather.gov"})

    def test_held_hosts_and_restricted_sources_are_never_recommended(self):
        tiers = {x["host"]: x["tier"] for x in AP["needs_new_host"]}
        self.assertEqual(tiers["api.clubelo.com"], "HOLD_UNTIL_API_WORKS")
        self.assertEqual(tiers["understat.com"], "HOLD_PENDING_VERIFIED_TERMS"); self.assertEqual(tiers["www.barttorvik.com"], "HOLD_PENDING_VERIFIED_TERMS")
        text = " ".join(x["host"] for x in AP["not_recommended"]).lower()
        for h in ("baseballsavant", "sports-reference", "fbref", "transfermarkt", "fangraphs", "dailyfaceoff", "kenpom", "odds"):
            self.assertIn(h, text)
        for h in tiers:
            self.assertNotIn("sports-reference", h); self.assertNotIn("kenpom", h)

    def test_cost_is_zero_and_no_accounts_or_keys_are_handled_by_the_session(self):
        for x in AP["needs_new_host"]:
            self.assertNotIn("paid", x["cost"].lower().replace("no paid", ""), x["host"])
        doc = (ROOT / "docs/NETWORK_ACCESS_PROPOSAL.md").read_text()
        self.assertIn("creates no accounts", doc); self.assertIn("$0", doc)
        cfbd = [x for x in AP["needs_new_host"] if x["host"] == "api.collegefootballdata.com"][0]
        self.assertIn("OWNER must register", cfbd["condition"])


class CaptureProposal(unittest.TestCase):
    def test_nothing_is_scheduled_and_templates_are_inactive(self):
        self.assertTrue(CAP["nothing_scheduled_or_enabled"])
        for t in CAP["templates"]:
            self.assertTrue(t.endswith(".proposed"), t); self.assertTrue((ROOT / t).exists())
        wf = ROOT / ".github/workflows"
        self.assertFalse(any("capture" in f.name and "vintage" in f.name for f in wf.glob("*")), "no capture workflow may be activated in this repo")

    def test_measured_progress_matches_the_committed_branch_listing(self):
        br = json.loads((DF / "verification/capture_progress_branches.json").read_text())
        pit = [x for x in CAP["items"] if x["feed"].startswith("NBA availability")][0]["measured_progress"]["data-injury-pit branch"]
        self.assertEqual(pit["files"], br["nba_src:data-injury-pit"]["files"]); self.assertEqual(pit["distinct_dates"], br["nba_src:data-injury-pit"]["distinct_dates"])
        nhl = [x for x in CAP["items"] if x["feed"].startswith("NHL")][0]["measured_progress"]
        self.assertGreaterEqual(nhl["context/injuries"]["dates"], 40)

    def test_unauthorized_repos_are_reported_as_not_inspected_not_as_empty(self):
        for x in CAP["items"]:
            if x["repo"] in ("nfl-edge-finder", "edge-finder-api", "cfb-edge-finder / cbb-edge-finder"):
                self.assertIsNone(x["measured_progress"]); self.assertIn("NOT INSPECTED", x["status"])

    def test_the_empty_college_basketball_feed_is_not_promised(self):
        cbb = [x for x in CAP["items"] if x["feed"].startswith("College")][0]
        self.assertIn("empty", cbb["status"]); self.assertIn("CBB only after a non-empty feed is confirmed", cbb["proposal"])


class _H(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        _H.hits.append(self.path)
        if self.path.startswith("/ok"):
            body = json.dumps({"x": 1}).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(403); self.end_headers()

    def log_message(self, *a):
        pass


class CollectorBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_loader("capture_snapshot", loader=None)
        mod = importlib.util.module_from_spec(spec)
        exec(compile((ROOT / "docs/capture_workflows/capture_snapshot.py.proposed").read_text(), "capture_snapshot.py", "exec"), mod.__dict__)
        cls.mod = mod; cls.srv = HTTPServer(("127.0.0.1", 0), _H); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_stores_the_response_untouched_with_a_checksum_and_a_timestamped_path(self):
        import hashlib, tempfile
        with tempfile.TemporaryDirectory() as d:
            rec = self.mod.capture(Path(d), "feed_a", f"http://127.0.0.1:{self.port}/ok")
            self.assertEqual(rec["http"], 200); f = Path(d) / rec["file"]
            self.assertTrue(f.exists()); self.assertIn("dt=", rec["file"])
            raw = gzip.open(f, "rb").read(); self.assertEqual(hashlib.sha256(raw).hexdigest(), rec["sha256"]); self.assertEqual(json.loads(raw), {"x": 1})

    def test_a_403_is_recorded_once_never_retried_and_writes_no_file(self):
        import tempfile
        _H.hits.clear()
        with tempfile.TemporaryDirectory() as d:
            rec = self.mod.capture(Path(d), "feed_b", f"http://127.0.0.1:{self.port}/denied")
            self.assertEqual(rec["http"], 403); self.assertNotIn("file", rec); self.assertEqual(len(_H.hits), 1)
            self.assertEqual(list(Path(d).rglob("*.gz")), [])

    def test_the_collector_has_no_credentials_and_only_standard_library_imports(self):
        src = (ROOT / "docs/capture_workflows/capture_snapshot.py.proposed").read_text()
        for bad in ("Authorization", "api_key", "apikey", "token", "requests", "selenium", "BeautifulSoup"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()

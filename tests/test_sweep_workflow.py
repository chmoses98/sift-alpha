import json, re, unittest
from pathlib import Path
import yaml

R = Path(__file__).resolve().parents[1]
W = yaml.safe_load(open(R / ".github/workflows/kalshi-series-sweep.yml"))
TXT = open(R / ".github/workflows/kalshi-series-sweep.yml").read()


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
            self.assertTrue((R / "research/audit/sweep" / q).exists(), q)
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
            q = json.load(open(R / "research/audit/sweep" / f))["series"]
            self.assertEqual((len(q), len(set(q))), (n, n)); self.assertTrue(all(re.fullmatch(r"[A-Z0-9-]+", t) for t in q), f)


if __name__ == "__main__":
    unittest.main()

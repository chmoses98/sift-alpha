import hashlib, json, os, subprocess, tempfile, unittest
from alpha_engine.sweep_ingest import load, ingest
from kalshi_sweep.publish import publish

ST = {"requests_total": 4, "series": {"A": {k: {"complete": True, "markets": 3, "event_count": 1, "open_time_min": "2026-10-01T00:00:00Z", "open_time_max": "2026-10-02T00:00:00Z", "sample": {"ticker": "A-1", "title": "t", "rules_primary": "r"}} for k in ("open", "unopened", "closed", "settled")}}}


def git(d, *a):
    subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)


class Ingest(unittest.TestCase):
    def repo(self, d):
        git(d, "init", "-q"); git(d, "checkout", "-q", "-b", "sweep-data"); return d

    def test_raw_state_is_sha_verified_and_carries_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo(d); st = os.path.join(d, "_s.json"); q = os.path.join(d, "_q.json")
            json.dump(ST, open(st, "w")); json.dump({"series": ["A"]}, open(q, "w"))
            publish(st, q, d, env={"GITHUB_RUN_ID": "7", "GITHUB_SHA": "abc"})
            os.rename(q, os.path.join(d, "q_hold")); os.remove(st)
            git(d, "add", "sweeps", "index.jsonl"); git(d, "commit", "-q", "-m", "x")
            meta, rows, prov = load(d, "HEAD", "_q")
            self.assertEqual((meta["requests_total"], rows[0]["s"], prov["workflow_run_id"], prov["series_complete"]), (4, "A", "7", 1))
            self.assertEqual(rows[0]["open"]["markets"], 3)
            # tamper with the raw file -> ingest refuses
            f = [p for p in os.listdir(os.path.join(d, "sweeps", "_q")) if p.startswith("state_")][0]
            open(os.path.join(d, "sweeps", "_q", f), "a").write(" ")
            git(d, "commit", "-qam", "tamper")
            with self.assertRaises(ValueError):
                load(d, "HEAD", "_q")

    def test_seed_fallback_and_missing_queue(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo(d); os.makedirs(os.path.join(d, "seed"))
            json.dump({"meta": {"requests_total": 1}, "series": [{"s": "A"}], "provenance": {"job_id": "9"}}, open(os.path.join(d, "seed", "z.compact.json"), "w"))
            git(d, "add", "-A"); git(d, "commit", "-q", "-m", "s")
            meta, rows, prov = load(d, "HEAD", "z")
            self.assertIn("seed", prov["transport"]); self.assertEqual(prov["job_id"], "9")
            with self.assertRaises(FileNotFoundError):
                load(d, "HEAD", "nope")

    def test_committed_results_carry_provenance_from_the_data_branch(self):
        root = os.path.join(os.path.dirname(__file__), "..", "research", "audit", "sweep_results")
        for q in ("mlb", "soccer"):
            d = json.load(open(os.path.join(root, f"{q}.json")))
            self.assertIn("sweep-data branch", d["provenance"]["transport"]); self.assertEqual(len(d["provenance"]["data_branch_commit"]), 40)


if __name__ == "__main__":
    unittest.main()

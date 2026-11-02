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

    def test_partial_publish_does_not_displace_complete_state_or_seed(self):
        full = {"requests_total": 4, "series": {s: {k: {"complete": True, "markets": 1} for k in ("open", "unopened", "closed", "settled")} for s in ("A", "B")}}
        part = {"requests_total": 1, "series": {"A": {k: {"complete": k == "open", "markets": 1} for k in ("open", "unopened", "closed", "settled")}}}
        with tempfile.TemporaryDirectory() as d:
            self.repo(d); os.makedirs(os.path.join(d, "seed"))
            json.dump({"meta": {"requests_total": 9}, "series": [{"s": "SEED"}], "provenance": {"job_id": "9"}}, open(os.path.join(d, "seed", "_q.compact.json"), "w"))
            q = os.path.join(d, "_q.json"); json.dump({"series": ["A", "B"]}, open(q, "w"))
            def pub(state, run):
                st = os.path.join(d, "_s.json"); json.dump(state, open(st, "w")); publish(st, q, d, env={"GITHUB_RUN_ID": run})
            pub(part, "1")
            git(d, "add", "sweeps", "index.jsonl", "seed"); git(d, "commit", "-q", "-m", "a")
            self.assertEqual(load(d, "HEAD", "_q")[1][0]["s"], "SEED")               # only a partial publish exists -> seed still wins
            pub(full, "2"); pub(part, "3")
            git(d, "add", "sweeps", "index.jsonl"); git(d, "commit", "-q", "-m", "b")
            meta, rows, prov = load(d, "HEAD", "_q")
            self.assertEqual((meta["requests_total"], len(rows), prov["workflow_run_id"], prov["newest_publish_complete"]), (4, 2, "2", False))   # run 3 (partial) did not displace run 2

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

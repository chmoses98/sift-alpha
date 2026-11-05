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

    def test_real_run_41533525920_partial_is_verified_but_never_selected(self):
        """Run 41533525920 published 1/48 soccer series (complete=false). Its raw file verifies against its manifest, but ingest must keep the completed 48-series inventory."""
        raw = json.dumps({"requests_total": 5, "series": {"KXSOMETHING": {k: {"complete": k == "open", "markets": 0} for k in ("open", "unopened", "closed", "settled")}}}).encode()
        sha = hashlib.sha256(raw).hexdigest()
        seed_rows = [{"s": f"S{i}"} for i in range(48)]
        with tempfile.TemporaryDirectory() as d:
            self.repo(d); os.makedirs(os.path.join(d, "seed")); sd = os.path.join(d, "sweeps", "soccer_ambiguous_queue"); os.makedirs(sd)
            json.dump({"meta": {"requests_total": 194}, "series": seed_rows, "provenance": {"job_id": "41505499041"}}, open(os.path.join(d, "seed", "soccer_ambiguous_queue.compact.json"), "w"))
            fn = "state_20261102T234335Z_run41533525920.json"; open(os.path.join(sd, fn), "wb").write(raw)
            entry = {"published_utc": "2026-11-02T23:43:35Z", "file": fn, "state_sha256": sha, "workflow_run_id": "41533525920", "series_complete": 1, "series_queued": 48, "complete": False, "requests_total": 5, "queue": "soccer_ambiguous_queue"}
            open(os.path.join(d, "index.jsonl"), "w").write(json.dumps(entry) + "\n")
            json.dump(entry, open(os.path.join(sd, "latest.json"), "w"))
            git(d, "add", "-A"); git(d, "commit", "-q", "-m", "s")
            self.assertEqual(hashlib.sha256(open(os.path.join(sd, fn), "rb").read()).hexdigest(), entry["state_sha256"])   # manifest matches raw file
            meta, rows, prov = load(d, "HEAD", "soccer_ambiguous_queue")
            self.assertEqual((len(rows), meta["requests_total"], prov["file"]), (48, 194, "seed/soccer_ambiguous_queue.compact.json"))
            self.assertNotEqual(prov.get("workflow_run_id"), "41533525920")

    def test_committed_classifications_intact(self):
        root = os.path.join(os.path.dirname(__file__), "..", "research", "audit", "sweep_results")
        sm = json.load(open(os.path.join(root, "summary.json")))
        self.assertEqual((sm["mlb"]["series"], sm["mlb"]["complete"]), (215, 215))
        self.assertIn("KXMLBBGAME", sm["mlb"]["resolved_non_baseball"])
        so = sm["soccer"]
        self.assertEqual((so["series"], so["complete"]), (48, 48))
        self.assertEqual(so["classes"], {"NOT_SOCCER_BY_TITLE": 1, "EMPTY_NO_MARKETS_UNCONFIRMED": 24, "SOCCER_CONFIRMED_BY_TITLE": 23})
        self.assertEqual(so["not_soccer_by_title"], ["KXSORONDO"])
        for q, n in (("mlb", 215), ("soccer", 48)):
            self.assertEqual(len(json.load(open(os.path.join(root, f"{q}.json")))["series"]), n)


if __name__ == "__main__":
    unittest.main()

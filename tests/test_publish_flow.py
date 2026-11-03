"""Runs the workflow's actual publish shell steps against a local bare repo (insteadOf maps github.com to it)."""
import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
import yaml

R = Path(__file__).resolve().parents[1]
W = yaml.safe_load(open(R / ".github/workflows/kalshi-series-sweep.yml"))
STEPS = {s["name"].split(" (")[0]: s for s in W["jobs"]["publish"]["steps"] if "run" in s}
CHECKOUT = next(v for k, v in STEPS.items() if k.startswith("Check out")); COMMIT = next(v for k, v in STEPS.items() if k.startswith("Commit"))
STATE = {"requests_total": 3, "series": {"A": {k: {"complete": True, "markets": 1} for k in ("open", "unopened", "closed", "settled")}}}


def sh(cmd, cwd, env):
    return subprocess.run(["bash", "-e", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True)


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); d = self.d
        self.bare = os.path.join(d, "remote.git"); subprocess.run(["git", "init", "-q", "--bare", self.bare], check=True)
        self.home = os.path.join(d, "home"); os.makedirs(self.home)
        open(os.path.join(self.home, ".gitconfig"), "w").write(f'[url "{self.bare}"]\n\tinsteadOf = https://github.com/o/r.git\n[init]\n\tdefaultBranch = main\n')
        self.env = {**os.environ, "HOME": self.home, "GH_TOKEN": "SECRETTOKEN123", "REPO": "o/r", "QUEUE": "q.json", "GITHUB_RUN_ID": "1"}
        self.work = os.path.join(d, "w"); os.makedirs(self.work)
        os.makedirs(os.path.join(self.work, "state")); json.dump(STATE, open(os.path.join(self.work, "state", "sweep_state.json"), "w"))
        self.code = os.path.join(self.work, "code"); shutil.copytree(R / "kalshi_sweep", os.path.join(self.code, "kalshi_sweep"), ignore=shutil.ignore_patterns("__pycache__"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def publish(self, run_id, between=None):
        env = {**self.env, "GITHUB_RUN_ID": run_id}
        r = sh(CHECKOUT["run"], self.work, env); self.assertEqual(r.returncode, 0, r.stderr)
        r = sh("python3 -m kalshi_sweep.publish ../state/sweep_state.json kalshi_sweep/queues/mlb_queue.json ../data", self.code, env); self.assertEqual(r.returncode, 0, r.stderr)
        if between: between()
        r = sh(COMMIT["run"], os.path.join(self.work, "data"), env); self.assertEqual(r.returncode, 0, r.stderr); return r

    def remote_files(self):
        return subprocess.run(["git", "--git-dir", self.bare, "ls-tree", "-r", "--name-only", "sweep-data"], capture_output=True, text=True).stdout.split()

    def test_creates_orphan_branch_then_appends_and_leaks_no_credentials(self):
        r1 = self.publish("11"); r2 = self.publish("12")
        files = self.remote_files(); self.assertIn("index.jsonl", files); self.assertEqual(sum(f.endswith("latest.json") for f in files), 1)
        self.assertEqual(sum(f.startswith("sweeps/mlb_queue/state_") for f in files), 2)
        idx = subprocess.run(["git", "--git-dir", self.bare, "show", "sweep-data:index.jsonl"], capture_output=True, text=True).stdout.splitlines(); self.assertEqual(len(idx), 2)
        # nothing credential-like persisted anywhere
        for root, _, fs in os.walk(self.d):
            for f in fs:
                p = os.path.join(root, f)
                if "/objects/" in p: continue
                self.assertNotIn(b"SECRETTOKEN123", open(p, "rb").read(), p)
        import base64
        b64 = base64.b64encode(b"x-access-token:SECRETTOKEN123")
        for root, _, fs in os.walk(self.d):
            for f in fs:
                p = os.path.join(root, f)
                if "/objects/" in p: continue
                self.assertNotIn(b64, open(p, "rb").read(), p)
        for r in (r1, r2):
            self.assertNotIn("SECRETTOKEN123", r.stdout + r.stderr)

    def test_push_race_is_retried_with_rebase_and_both_commits_survive(self):
        self.publish("21")
        def competing():
            c = os.path.join(self.d, "other"); subprocess.run(["git", "clone", "-q", "-b", "sweep-data", self.bare, c], check=True)
            open(os.path.join(c, "other.txt"), "w").write("x"); subprocess.run(["git", "-C", c, "add", "-A"], check=True)
            subprocess.run(["git", "-C", c, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "-m", "competing"], check=True); subprocess.run(["git", "-C", c, "push", "-q", "origin", "sweep-data"], check=True)
        self.publish("22", between=competing)
        files = self.remote_files(); self.assertIn("other.txt", files); self.assertEqual(sum(f.startswith("sweeps/mlb_queue/state_") for f in files), 2)


if __name__ == "__main__":
    unittest.main()

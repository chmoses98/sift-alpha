import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from alpha_engine import cfb_q1_intel as q


def game(eid, start, h, a, hq, aq):
    return {"event_id": eid, "start_time_utc": start, "home": h, "away": a, "home_team_id": h, "away_team_id": a,
            "home_periods": [hq, 0, 0, 0], "away_periods": [aq, 0, 0, 0], "reconciliation": "RECONCILED",
            "regulation_periods": 4}


class WalkForward(unittest.TestCase):
    def test_result_not_used_before_it_is_final(self):
        gs = []
        # 40 filler games between teams T0..T7 on day 1 to seed league mean
        for i in range(40):
            gs.append(game(f"f{i}", "2026-09-01T10:00Z", f"T{i % 8}", f"T{(i + 1) % 8}", 7, 7))
        # day 2: both teams have 5 prior games each; game A starts 1h after game B finishes lag? test lag edge
        for i in range(8):
            gs.append(game(f"g{i}", f"2026-09-02T10:0{i}Z", "T0", "T1", 7, 7))
        wf = q.walk_forward(gs)
        for r in wf["rows"]:
            self.assertGreaterEqual(r["n_prior_home"], q.MIN_PRIOR)
        # games starting within RESULT_LAG_HOURS of each other must not see each other
        t0_counts = [r["n_prior_home"] for r in wf["rows"] if r["event_id"].startswith("g")]
        self.assertEqual(len(set(t0_counts)), 1, "same-day games inside the lag window must not leak")

    def test_future_outcome_changes_nothing(self):
        gs = [game(f"f{i}", f"2026-09-0{1 + i // 20}T10:00Z", f"T{i % 8}", f"T{(i + 3) % 8}", 7, 3) for i in range(60)]
        a = q.walk_forward(gs)["rows"]
        gs2 = [dict(g) for g in gs]
        gs2[-1]["home_periods"] = [99, 0, 0, 0]
        b = q.walk_forward(gs2)["rows"]
        self.assertEqual([r["model"] for r in a[:-1]], [r["model"] for r in b[:-1]])
        self.assertEqual(a[-1]["model"], b[-1]["model"], "a game's own result must not enter its prediction")

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfb"
            p.mkdir()
            (p / "x.jsonl").write_text(json.dumps(game("1", "2026-09-01T10:00Z", "A", "B", 7, 0)) + "\n")
            with self.assertRaises(ValueError):
                q.load_games(Path(d), {"cfb/x.jsonl": "0" * 64})
            good = hashlib.sha256((p / "x.jsonl").read_bytes()).hexdigest()
            self.assertEqual(len(q.load_games(Path(d), {"cfb/x.jsonl": good})), 1)

    def test_verdict_rule_requires_sample_and_positive_interval(self):
        rows = [{"actual": 10, "baseline": 10, "model": 10.5} for _ in range(50)]
        self.assertEqual(q.summarize(rows)["verdict"], "INSUFFICIENT_DATA")
        rows = [{"actual": 10, "baseline": 13, "model": 10} for _ in range(q.MIN_EVAL)]
        self.assertEqual(q.summarize(rows)["verdict"], "SUPPORTED")
        rows = [{"actual": 10, "baseline": 10, "model": 11} for _ in range(q.MIN_EVAL)]
        self.assertEqual(q.summarize(rows)["verdict"], "NOT_SUPPORTED")


class CommittedArtifact(unittest.TestCase):
    def test_artifact_is_consistent_and_makes_no_authority_claim(self):
        a = json.loads(Path("research/audit/intel/CFB_quarter_total_Q1.json").read_text())
        self.assertTrue(a["provenance"]["every_row_is_postgame"])
        self.assertEqual(len(a["provenance"]["data_commit"]), 40)
        v = a["validation"]
        self.assertEqual(v["n_eval"], len(a["walk_forward_rows"]))
        self.assertEqual(v["verdict"] == "SUPPORTED", v["mae_improvement_ci95"][0] > 0 and v["n_eval"] >= q.MIN_EVAL)
        # recompute metrics from rows
        rows = a["walk_forward_rows"]
        self.assertAlmostEqual(v["model_mae"], sum(abs(r["actual"] - r["model"]) for r in rows) / len(rows), places=3)


if __name__ == "__main__":
    unittest.main()

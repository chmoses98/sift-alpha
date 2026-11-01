"""Offline adversarial checks for pinned hitter archive inventory and PIT gating."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from alpha_engine import hitter_archive_gate as gate
from tests.test_research_repair import synthetic_report


def fixture():
    rows = []
    for i in range(31):
        rows.append({
            "marketTicker": f"KXMLBHIT-TEST-{i}",
            "hitterProjectionSnapshotId": f"{i:040x}",
            "marketFamily": "hitter_hits",
            "projectionStatus": "PROJECTED",
            "pricingStatus": "PRICED",
            "playerId": str(600000 + i),
            "gameId": 824235,
            "modelProbability": 0.3,
            "marketObservedAt": "2026-08-24T19:35:26.235Z",
            "projectionGeneratedAt": "2026-08-24T20:23:38Z",
            "snapshotGeneratedAt": "2026-08-24T20:27:37Z",
        })
    raw = ("\n".join(json.dumps(r) for r in rows) + "\n").encode()
    raw = raw[:-1] + b" " * (57692 - len(raw)) + b"\n"
    assert len(raw) == 57692
    sha = gate.git_hash("blob", raw)
    files = [{"path": f"2026-08-{i:02d}.jsonl", "mode": "100644", "type": "blob",
              "sha": f"{i:040x}", "size": 100} for i in range(1, 31)]
    files.append({"path": "2026-08-31.jsonl", "mode": "100644", "type": "blob",
                  "sha": "1" * 40, "size": 100})
    files[23]["sha"] = sha
    files[23]["size"] = len(raw)
    blob = b"".join(b"100644 " + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"])
                    for e in sorted(files, key=lambda x: x["path"]))
    tree_sha = gate.git_hash("tree", blob)
    return rows, raw, {"sha": tree_sha, "truncated": False, "tree": files}, sha, tree_sha


class HitterArchiveGateTests(unittest.TestCase):
    def test_archive_inventory_is_cryptographically_pinned(self):
        _, raw, tree, sha, tree_sha = fixture()
        with patch.object(gate, "TREE_SHA", tree_sha), patch.object(gate, "SNAPSHOT_SHA", sha):
            index = gate.tree_inventory(tree)
            self.assertEqual(index["2026-08-24"]["sha"], sha)
            self.assertEqual(gate.audit_snapshot(raw)["forecasts_generated_after_recorded_market_observation"], 31)
            for mutate in (
                lambda t: t["tree"][0].__setitem__("size", -1),
                lambda t: t["tree"][0].__setitem__("sha", "f" * 40),
                lambda t: t["tree"][0].__setitem__("path", t["tree"][1]["path"]),
                lambda t: t.__setitem__("truncated", True),
                lambda t: t["tree"].pop(),
            ):
                bad = copy.deepcopy(tree)
                mutate(bad)
                with self.subTest(mutate=str(mutate)), self.assertRaises(ValueError):
                    gate.tree_inventory(bad)

    def test_forecast_after_market_is_not_backfilled(self):
        _, raw, tree, sha, tree_sha = fixture()
        with patch.object(gate, "TREE_SHA", tree_sha), patch.object(gate, "SNAPSHOT_SHA", sha):
            self.assertEqual(gate.audit_snapshot(raw)["eligible_forecasts_at_recorded_market_observation"], 0)
            self.assertIsNone(gate.audit_snapshot(raw)["independently_valid_model_evaluations"])
            result = gate.analyze(synthetic_report(), tree, raw)
            self.assertEqual(result["repair_result"], "BLOCKED_NO_SAFE_HISTORICAL_REPAIR")
            self.assertEqual(result["historical_opportunity_rows_unchanged"], 138158)
            self.assertEqual(result["historical_model_evaluated_rows_unchanged"], 694)
            self.assertEqual(result["historical_hitter_hits_observed_unchanged"], 23295)
            self.assertFalse(result["source_accuracy_or_profitability_certified"])

    def test_modified_snapshot_rejected_even_if_json_valid(self):
        _, raw, _, sha, _ = fixture()
        with patch.object(gate, "SNAPSHOT_SHA", sha):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                gate.audit_snapshot(raw.replace(b"0.3", b"0.4", 1))
            with self.assertRaises(ValueError):
                gate.audit_snapshot(b"x" * 60001)

    def test_duplicate_ticker_future_snapshot_and_bad_probability_rejected(self):
        rows, _, _, _, _ = fixture()
        for mutate in (
            lambda x: x[1].__setitem__("marketTicker", x[0]["marketTicker"]),
            lambda x: x[1].__setitem__("hitterProjectionSnapshotId", x[0]["hitterProjectionSnapshotId"]),
            lambda x: x[1].__setitem__("snapshotGeneratedAt", "2026-08-24T20:00:00Z"),
            lambda x: x[1].__setitem__("modelProbability", 1.4),
            lambda x: x[1].__setitem__("playerId", ""),
            lambda x: x[1].__setitem__("marketObservedAt", "2026-08-25T19:35:26Z"),
        ):
            bad = copy.deepcopy(rows)
            mutate(bad)
            raw = ("\n".join(json.dumps(r) for r in bad) + "\n").encode()
            with patch.object(gate, "SNAPSHOT_SHA", gate.git_hash("blob", raw)):
                with self.subTest(mutate=str(mutate)), self.assertRaises(ValueError):
                    gate.audit_snapshot(raw)

    def test_missing_historical_date_and_denominator_manipulation_rejected(self):
        _, raw, tree, sha, tree_sha = fixture()
        report = synthetic_report()
        report["report"]["datesWithObservations"] = [
            f"2026-08-{i:02d}" for i in range(1, 21)
        ]
        with patch.object(gate, "TREE_SHA", tree_sha), patch.object(gate, "SNAPSHOT_SHA", sha):
            good = gate.analyze(report, tree, raw)
            self.assertEqual(good["historical_observation_dates"], 20)
            self.assertEqual(good["archive_dates_overlapping_historical_report"],
                             [f"2026-08-{i:02d}" for i in range(1, 21)])
            report["report"]["totalOpportunityRows"] -= 1
            with self.assertRaises(ValueError):
                gate.analyze(report, tree, raw)


if __name__ == "__main__":
    unittest.main()

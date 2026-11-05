"""Offline adversarial tests for real-source Tennis capture qualification."""
import gzip
import hashlib
import json
import unittest
from alpha_engine.tennis_capture import audit, validate_manifest


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def fixture():
    run_ids = ("20261025T004543Z", "20261025T005542Z", "20261025T010542Z")
    spec = {"schema_version": 1, "sport": "TENNIS", "repository": "chmoses98/Tennis-Edge-Finder",
            "commit": "a"*40, "max_total_bytes": 300000,
            "max_expanded_bytes_per_file": 4000000, "captures": []}
    contents = {}
    for i, run in enumerate(run_ids):
        started = f"2026-10-25T{('00:45:43','00:55:42','01:05:42')[i]}Z"
        finished = f"2026-10-25T{('00:48:00','00:57:16','01:07:18')[i]}Z"
        count = 2 if i == 0 else 1
        manifest = {"run_id": run, "started_at": started, "finished_at": finished,
                    "incomplete": [], "hourly_sweep": i == 0,
                    "client_stats": {"failures": 0},
                    "counts": {"open_markets": 2, "quotes_written": count,
                               "quotes_unchanged": 0 if i == 0 else 1}}
        rows = [{"run_id": run, "ticker": f"KXTENNIS-{name}",
                 "captured_at": started, "snapshot_kind": "full" if i == 0 else "changed",
                 "event_ticker": "KXTENNIS-MATCH", "series_ticker": "KXTENNIS",
                 "yes_bid_dollars": "0.40" if i < 2 else "0.42"}
                for name in (("A", "B") if i == 0 else ("A",))]
        base = f"tennis-edge-finder/data/kalshi/capture/2026-10-25/{run}"
        cap = {"run_id": run}
        for key, ext, raw in (("manifest", ".manifest.json", json.dumps(manifest).encode()),
                              ("quotes", ".quotes.jsonl.gz", gzip.compress(b"\n".join(json.dumps(r).encode() for r in rows)))):
            path = base + ext
            cap[key] = {"path": path, "sha": blob(raw), "bytes": len(raw)}
            contents[path] = raw
        spec["captures"].append(cap)
    return spec, contents


class TennisCaptureTests(unittest.TestCase):
    def test_complete_verified_sparse_prefix_and_authority(self):
        spec, contents = fixture()
        report, rows = audit(spec, lambda x: contents[x["path"]])
        self.assertEqual(report["n_observed_quote_rows"], 4)
        self.assertEqual(report["n_distinct_tickers_observed"], 2)
        self.assertEqual(report["observed_quote_change_counts"]["changed_direct_quotes_since_previous_observation"], 1)
        self.assertEqual(report["capture_reports"][0]["snapshot_kind"], "HOURLY_FULL")
        self.assertEqual(report["full_board_at_later_ticks"], "NOT_VERIFIED_REMOVALS_UNOBSERVED")
        self.assertTrue(all(x["quote_execution_authority"] == "NONE" for x in rows))

    def test_rejects_unpinned_source_and_size(self):
        spec, _ = fixture()
        spec["repository"] = "unknown/paid-api"
        with self.assertRaises(ValueError): validate_manifest(spec)
        spec, _ = fixture()
        spec["captures"][0]["quotes"]["bytes"] = 99999999
        with self.assertRaises(ValueError): validate_manifest(spec)

    def test_rejects_source_tamper(self):
        spec, contents = fixture()
        path = spec["captures"][0]["manifest"]["path"]
        contents[path] += b" "
        with self.assertRaises(ValueError): audit(spec, lambda x: contents[x["path"]])

    def test_rejects_incomplete_run_and_forged_full(self):
        for mutation in (lambda x: x.update(incomplete=[{"stage": "quotes"}]),
                         lambda x: x.update(hourly_sweep=False)):
            spec, contents = fixture()
            entry = spec["captures"][0]["manifest"]
            m = json.loads(contents[entry["path"]]); mutation(m)
            raw = json.dumps(m).encode()
            contents[entry["path"]] = raw
            entry.update(bytes=len(raw), sha=blob(raw))
            with self.assertRaises(ValueError): audit(spec, lambda x: contents[x["path"]])

    def test_rejects_future_row_and_forged_price(self):
        for mutation in (lambda x: x.update(captured_at="2026-10-25T04:00:00Z"),
                         lambda x: x.update(yes_bid_dollars="1.4"),
                         lambda x: x.update(snapshot_kind="full")):
            spec, contents = fixture()
            entry = spec["captures"][1]["quotes"]
            rows = [json.loads(x) for x in gzip.decompress(contents[entry["path"]]).splitlines()]
            mutation(rows[0])
            raw = gzip.compress(b"\n".join(json.dumps(x).encode() for x in rows))
            contents[entry["path"]] = raw
            entry.update(bytes=len(raw), sha=blob(raw))
            with self.assertRaises(ValueError): audit(spec, lambda x: contents[x["path"]])

    def test_rejects_count_disagreement(self):
        spec, contents = fixture()
        entry = spec["captures"][2]["manifest"]
        m = json.loads(contents[entry["path"]]); m["counts"]["quotes_written"] += 1
        raw = json.dumps(m).encode()
        contents[entry["path"]] = raw
        entry.update(bytes=len(raw), sha=blob(raw))
        with self.assertRaises(ValueError): audit(spec, lambda x: contents[x["path"]])

    def test_duplicate_ticker_rejected(self):
        spec, contents = fixture()
        entry = spec["captures"][0]["quotes"]
        rows = [json.loads(x) for x in gzip.decompress(contents[entry["path"]]).splitlines()]
        rows[1]["ticker"] = rows[0]["ticker"]
        raw = gzip.compress(b"\n".join(json.dumps(x).encode() for x in rows))
        contents[entry["path"]] = raw
        entry.update(bytes=len(raw), sha=blob(raw))
        with self.assertRaises(ValueError): audit(spec, lambda x: contents[x["path"]])


if __name__ == "__main__": unittest.main()

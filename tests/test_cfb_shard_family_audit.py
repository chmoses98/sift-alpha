"""Offline adversarial checks for CFB literal event-directory discovery."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from alpha_engine.cfb_shard_family_audit import (
    audit, append, check_manifest, hypotheses, tree_sha, verified_shards,
    verify_generic_pricer, PRICER_BLOB_SHA1,
)
from alpha_engine.market_family_registry import git_sha


def fixture():
    event = "KXNCAAF1QTOTAL-26OCT31AUBMISS"
    primary = "If the teams score more than 10.5 points in the 1st quarter, resolves Yes."
    secondary = "If not started within 48 hours resolves to fair price."
    data = {"artifact": "event_detail_shard", "event_ticker": event,
            "game_key": "26OCT30AUBMISS", "game_fingerprint": "test-fingerprint",
            "part": 1, "parts": 1, "market_count": 2, "event_market_count": 2,
            "event": {"event_ticker": event, "series_ticker": "KXNCAAF1QTOTAL"},
            "markets": [{
                "market_ticker": event + "-" + str(n), "event_ticker": event,
                "series_ticker": "KXNCAAF1QTOTAL", "family": "quarter_total",
                "period": "first_quarter", "strike_type": "greater",
                "market_type": "binary", "floor_strike": 10.5 + n,
                "rules_primary": primary, "rules_secondary": secondary,
                "updated_time": "2026-10-31T10:00:00Z",
            } for n in (1, 2)]}
    raw = json.dumps(data).encode()
    entry = {"name": event + ".json", "sha": git_sha(raw), "size": len(raw)}
    return entry, data, raw


class CfbShardTests(unittest.TestCase):
    def test_pinned_directory_tree_cannot_omit_or_change_file(self):
        manifest = json.loads(Path("research/cfb_aubmiss_event_shards.json").read_text())
        entries = check_manifest(manifest)
        self.assertEqual(len(entries), 27)
        self.assertEqual(tree_sha(entries), manifest["directory_tree_sha1"])
        for mutate in ("omit", "sha", "size", "balanced_size", "duplicate", "path"):
            x = copy.deepcopy(manifest)
            if mutate == "omit":
                x["files"].pop()
            elif mutate == "sha":
                x["files"][0]["sha"] = "f" * 40
            elif mutate == "size":
                x["files"][0]["size"] += 1
            elif mutate == "balanced_size":
                # A sum-only guard cannot detect compensating size edits.
                x["files"][0]["size"] += 1
                x["files"][1]["size"] -= 1
            elif mutate == "duplicate":
                x["files"][1] = x["files"][0].copy()
            else:
                x["directory"] = "another/directory"
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                check_manifest(x)

    def test_blob_tamper_and_truncation_rejected(self):
        manifest = json.load(open("research/cfb_aubmiss_event_shards.json"))
        # No network: loader is deliberately corrupted on the first file.
        with self.assertRaises(ValueError):
            verified_shards(manifest, lambda e: b"{}")
        with self.assertRaises(ValueError):
            verified_shards(manifest, lambda e: b"x" * (e["size"] + 1))

    def test_exact_tickers_period_and_rules_hashed_without_pit_claim(self):
        entry, data, raw = fixture()
        x = audit([(entry, data, hashlib.sha256(raw).hexdigest())])
        self.assertEqual(x["n_distinct_market_tickers"], 2)
        self.assertEqual(x["n_native_family_period_groups"], 1)
        row = x["rows"][0]
        self.assertEqual(row["market_collection_status"], "COLLECTED_VALID")
        self.assertEqual(row["model_usage_status"], "UNKNOWN")
        self.assertIsNone(row["observed_at_utc"])
        self.assertEqual(row["period"], "first_quarter")
        self.assertEqual(len(row["observed_contracts"]), 2)
        self.assertEqual(len(row["observed_contracts"][0]["rules_primary_sha256"]), 64)
        self.assertEqual(row["observed_contracts"][0]["rules_primary"], data["markets"][0]["rules_primary"])
        self.assertEqual(row["observed_contracts"][0]["rules_secondary"], data["markets"][0]["rules_secondary"])
        self.assertEqual(hashlib.sha256(row["observed_contracts"][0]["rules_primary"].encode()).hexdigest(),
                         row["observed_contracts"][0]["rules_primary_sha256"])
        self.assertFalse(x["actual_game_start_verified"])
        self.assertFalse(x["settlement_join_verified"])
        self.assertTrue(row["candidate_inputs"])
        self.assertEqual(row["candidate_inputs"][0]["evidence"],
                         "CAUSAL_HYPOTHESIS_NOT_EMPIRICALLY_VALIDATED")

    def test_hostile_identity_semantics_and_denominators(self):
        for mode in ("duplicate", "wrong_event", "wrong_series", "wrong_period",
                     "wrong_family", "missing_rule", "bad_count", "bad_strike",
                     "bad_market_type", "bad_page", "bad_game"):
            entry, data, raw = fixture()
            if mode == "duplicate":
                data["markets"][1]["market_ticker"] = data["markets"][0]["market_ticker"]
            elif mode == "wrong_event":
                data["markets"][0]["event_ticker"] = "BAD"
            elif mode == "wrong_series":
                data["markets"][0]["series_ticker"] = "BAD"
            elif mode == "wrong_period":
                data["markets"][0]["period"] = "full_game"
            elif mode == "wrong_family":
                data["markets"][0]["family"] = "game_spread"
            elif mode == "missing_rule":
                data["markets"][0]["rules_primary"] = ""
            elif mode == "bad_count":
                data["market_count"] = 3
            elif mode == "bad_strike":
                data["markets"][0]["floor_strike"] = True
            elif mode == "bad_market_type":
                data["markets"][0]["market_type"] = "scalar"
            elif mode == "bad_page":
                data["parts"] = 2
            else:
                data["game_key"] = "UNRELATED"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit([(entry, data, hashlib.sha256(raw).hexdigest())])

    def test_append_preserves_mlb_and_cbb_denominators_and_unknowns(self):
        entry, data, raw = fixture()
        base = {"schema_version": 2, "authority": "RESEARCH_ONLY_NOT_LIVE_COLLECTION",
                "live_capture_running": False, "all_market_families_certified": False,
                "family_rows": [
                    {"sport": "MLB", "family": "hitter_hits",
                     "observed_denominator": 23295, "source_reported_model_evaluated": 0},
                    {"sport": "CBB", "family": "winner", "observed_denominator": 12209}],
                "missing_input_queue": []}
        combined = append(base, audit([(entry, data, hashlib.sha256(raw).hexdigest())]))
        self.assertEqual(combined["family_rows"][0]["observed_denominator"], 23295)
        self.assertEqual(combined["family_rows"][0]["source_reported_model_evaluated"], 0)
        self.assertEqual(combined["family_rows"][1]["observed_denominator"], 12209)
        self.assertEqual(combined["cfb_event_shard_audit"]["n_distinct_market_tickers"], 2)
        self.assertFalse(combined["live_capture_running"])
        with self.assertRaises(ValueError):
            append(combined, audit([(entry, data, hashlib.sha256(raw).hexdigest())]))

    def test_model_lineage_rejects_forged_source_and_scope(self):
        # A fake source or a claimed all-routes certification is never evidence.
        with self.assertRaises(ValueError):
            verify_generic_pricer(lambda: b"def price_market(): pass")
        entry, data, raw = fixture()
        forged = {"source_git_blob_sha1": PRICER_BLOB_SHA1,
                  "verified_scope": "ALL_CFB_PRICERS",
                  "first_half_capability": "EXPLICIT_UNSUPPORTED_MARKET_FAMILY"}
        with self.assertRaises(ValueError):
            audit([(entry, data, hashlib.sha256(raw).hexdigest())],
                  model_evidence=forged)
        unverified = audit([(entry, data, hashlib.sha256(raw).hexdigest())])
        self.assertEqual(unverified["rows"][0]["generic_pricer_capability"], "UNKNOWN")
        self.assertIsNone(unverified["rows"][0]["generic_pricer_evidence"])

    def test_unknown_family_not_falsely_required_or_useful(self):
        self.assertEqual(hypotheses("unmapped_exotic", "first_quarter"), [])
        self.assertTrue(all(x["validated_predictive_impact"] is None
                            for x in hypotheses("quarter_total", "first_quarter")))


if __name__ == "__main__":
    unittest.main()

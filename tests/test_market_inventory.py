"""Market archive metadata audit: no invented record counts or unsafe access."""
import json
import unittest

from alpha_engine.market_inventory import api_url, check_manifest, inventory, summarize_listing


class MarketInventoryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = "research/kalshi_archive_sources.json"
        self.entries = check_manifest(json.loads(open(self.manifest, encoding="utf-8").read()))

    def test_every_sport_archive_path_verified_inventory_contract(self):
        self.assertGreaterEqual(len(self.entries), 16)
        self.assertEqual(set(x["sport"] for x in self.entries),
                         {"NFL", "CFB", "NBA", "MLB", "NHL", "SOCCER", "TENNIS", "CBB"})
        self.assertTrue(all(api_url(x).startswith("https://api.github.com/repos/chmoses98/") for x in self.entries))

    def test_file_counts_do_not_claim_market_rows_or_settlement(self):
        report = inventory(self.manifest, loader=lambda entry: [
            {"type":"dir","name":"dt=2026-10-25","size":0},
            {"type":"file","name":"snapshot.json.gz","size":100_000},
        ])
        self.assertEqual(len(report["sources"]), len(self.entries))
        self.assertEqual(report["authority"], "RESEARCH_ONLY")
        self.assertEqual(report["sources"][0]["immediate_file_count"], 1)
        self.assertEqual(report["sources"][0]["immediate_file_bytes"], 100000)
        self.assertTrue(report["sources"][0]["no_market_row_count_inferred"])
        self.assertEqual(report["sources"][0]["settlement_join"], "NOT_RUN")

    def test_rejects_github_metadata_over_1000_and_invalid_listing(self):
        row = self.entries[0]
        with self.assertRaises(ValueError):
            summarize_listing(row, [{"type":"file","name":"a","size":0}] * 1000)
        with self.assertRaises(ValueError):
            summarize_listing(row, {"message":"API rate limit"})
        with self.assertRaises(ValueError):
            summarize_listing(row, [{"type":"file","name":"a","size":-1}])

    def test_block_malicious_and_nonapproved_repo(self):
        valid = dict(self.entries[0])
        valid["repo"] = "other/owner"
        with self.assertRaises(ValueError):
            api_url(valid)
        valid = dict(self.entries[0])
        valid["path"] = "../../private"
        with self.assertRaises(ValueError):
            api_url(valid)
        valid = dict(self.entries[0])
        valid["branch"] = "main?token=secret"
        with self.assertRaises(ValueError):
            api_url(valid)

    def test_missing_archive_never_assumed_to_be_zero_records(self):
        report = inventory(self.manifest, loader=lambda entry: (_ for _ in ()).throw(FileNotFoundError("not available")))
        self.assertTrue(all(x["status"] == "UNVERIFIED_OR_UNAVAILABLE" for x in report["sources"]))
        self.assertFalse(any("immediate_file_count" in x for x in report["sources"]))


if __name__ == "__main__":
    unittest.main()

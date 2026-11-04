"""No retroactive count inflation or paid source substitution."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from alpha_engine.all_sport_evidence import manifest_entries, describe, read_pinned, run

class AllSportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads(Path("research/all_sport_metadata_pins.json").read_text())

    def test_complete_exact_eight_sport_coverage(self):
        src=manifest_entries(self.manifest)
        self.assertEqual(len(src),8)
        self.assertEqual({x["sport"] for x in src},
                         {"NFL","CFB","NBA","NHL","MLB","CBB","SOCCER","TENNIS"})
        for x in src:
            self.assertEqual(len(x["commit"]),40)

    def test_forged_source_and_fee_enabling_blocked(self):
        bad=copy.deepcopy(self.manifest)
        bad["sources"][0]["repo"]="evil/paid-api"
        with self.assertRaises(ValueError):
            manifest_entries(bad)
        bad=copy.deepcopy(self.manifest)
        bad["sources"][0]["max_bytes"]=10_000_000
        with self.assertRaises(ValueError):
            manifest_entries(bad)

    def test_bad_contract_denominator_is_rejected(self):
        sample={"n_markets":13,"n_events":3,"by_family":{"GAME_WINNER":10,"TOTAL":2}}
        with self.assertRaises(ValueError):
            describe("CBB",sample)
        sample["by_family"]["TOTAL"]=3
        self.assertEqual(describe("CBB",sample)["n_game_winner_contracts"],10)

    def test_mlb_status_requires_identity(self):
        with self.assertRaises(ValueError):
            describe("MLB",{"2026-10-20":{"date":"2026-10-19","outcome":"completed"}})

    def test_missing_ticker_data_not_misrepresented_as_success(self):
        x=describe("NFL",{"n_open":100,"observed_at":"2026-10-25T12:00:00Z","schema_version":"openset-1.0.0"})
        self.assertIn("n_open_contracts_in_observed_openset",x)
        self.assertNotIn("n_unique_settled_markets",x)

    def test_archive_digest_is_mandatory(self):
        file=self.manifest["sources"][0]
        with self.assertRaises(ValueError):
            read_pinned(file,downloader=lambda _:b'{"markets":999999}')

if __name__=="__main__":
    unittest.main()

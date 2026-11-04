"""Hostile, offline regression tests for the bounded MLB repair cycle."""
import copy
import json
import unittest
from unittest.mock import patch

from alpha_engine import research_repair as rr


def synthetic_report():
    # Small family count, exact historical global denominators. Synthetic
    # fixture is NEVER represented as original historical row-level data.
    return {"rowCount": 138158, "report": {
        "totalOpportunityRows": 138158, "uniqueGames": 353,
        "uniqueMarketTickers": 80526, "rowsLackingModelEvaluation": 137464,
        "rowsLackingTemporallyValidModelEvaluation": 137464,
        "rowsLackingExecutablePregamePrice": 0,
        "familyModelCoverage": {
            "hitter_hits": {"observed": 23295, "modelEvaluated": 0, "coverageRate": 0},
            "game_total": {"observed": 114863, "modelEvaluated": 694,
                           "coverageRate": 694 / 114863},
        },
        "familySettlementCoverage": {
            "hitter_hits": {"observed": 23295, "settled": 20000,
                            "coverageRate": 20000 / 23295},
            "game_total": {"observed": 114863, "settled": 100765,
                           "coverageRate": 100765 / 114863},
        },
        "settlementStatusCounts": {
            "SETTLED": 120765, "NOT_SETTLED": 17393,
            "SETTLEMENT_UNRESOLVED": 0,
        },
    }}


def witnesses():
    return {
        "historical_quality": json.dumps(synthetic_report()).encode(),
        "report_writer": b'''
def _load_universe(dates):
    evaluations = storage.read_partition("model_evaluations", dates)
    return evaluations
def main():
    return build_opportunity_rows([])
''',
        "research_join": b'''
def build_opportunity_rows(obs, evaluations):
    return ta.select_temporally_valid_evaluation(evaluations, obs)
''',
        "generic_adapter": b'''
_NEVER_MODELED_FAMILIES = {"hitter_hits": "not generic"}
''',
        "hitter_bridge": b'''
def load_hitter_board_lookup(date):
    return stage_artifact_exists("hitter_projection_board", date)
''',
        "model_ledger": b'''
def extend_full_universe_evaluations(observations):
    return _discovery_extension_fields(observations)
''',
    }


class ResearchRepairTests(unittest.TestCase):
    def test_source_manifest_is_exact_and_bounded(self):
        manifest = json.loads(open("research/mlb_repair_source_pins.json").read())
        self.assertEqual(set(rr.validate_manifest(manifest)), set(rr.EXPECTED))
        for mutate in (
            lambda m: m["sources"].pop(),
            lambda m: m["sources"][0].__setitem__("path", "data/private"),
            lambda m: m["sources"][0].__setitem__("blob_sha1", "0" * 40),
            lambda m: m["sources"][0].__setitem__("max_bytes", 9999999),
            lambda m: m.__setitem__("source_commit", "main"),
            lambda m: m["sources"].append(m["sources"][0]),
        ):
            changed = copy.deepcopy(manifest)
            mutate(changed)
            with self.subTest(mutate=str(mutate)), self.assertRaises(ValueError):
                rr.validate_manifest(changed)

    def test_corrupt_source_is_never_repaired_from_untrusted_bytes(self):
        manifest = json.loads(open("research/mlb_repair_source_pins.json").read())
        with self.assertRaisesRegex(ValueError, "Git blob witness mismatch"):
            rr.load_sources(manifest, downloader=lambda _: b"malicious")
        with self.assertRaisesRegex(ValueError, "oversized"):
            rr.load_sources(manifest, downloader=lambda s: b"x" * (s["max_bytes"] + 1))

    def test_actual_code_structure_required_not_just_comments(self):
        good = witnesses()
        proof = rr.code_diagnosis(good)
        self.assertIn("JOIN_GAP", proof["root_cause_certainty"])
        for name, bad in (
            ("report_writer", b'def _load_universe(d): return storage.read_partition("hitter_projection_snapshots", d)\ndef main(): return build_opportunity_rows([])'),
            ("research_join", b'def build_opportunity_rows(o,e): return e[-1]'),
            ("generic_adapter", b'_NEVER_MODELED_FAMILIES = {}'),
            ("hitter_bridge", b'def load_hitter_board_lookup(d): return {}'),
            ("model_ledger", b'def extend_full_universe_evaluations(x): return []'),
        ):
            changed = dict(good)
            changed[name] = bad
            with self.subTest(name=name), self.assertRaises(ValueError):
                rr.code_diagnosis(changed)

    def test_full_cycle_is_idempotent_and_does_not_invent_historical_forecasts(self):
        data = witnesses()
        original = copy.deepcopy(data)
        with patch.object(rr, "load_sources", return_value=(data, [{"id": "synthetic"}])):
            a = rr.run({})
            b = rr.run({})
        self.assertEqual(a, b)
        self.assertEqual(data, original)
        self.assertEqual(a["result"], "BLOCKED_NO_SAFE_HISTORICAL_REPAIR")
        self.assertEqual(a["after"]["model_evaluated_rows"], 694)
        self.assertEqual(a["after"]["opportunity_rows"], 138158)
        self.assertEqual(a["after"]["families"]["hitter_hits"], {"observed": 23295, "model_evaluated": 0})
        self.assertIsNone(a["after"]["independently_valid_evaluations"])
        self.assertEqual(a["historical_model_repair_performed"], False)
        self.assertEqual(a["coverage_change_rows"], 0)

    def test_denominator_and_future_forecast_fabrication_rejected(self):
        original = synthetic_report()
        after = {
            "opportunity_rows": 138158,
            "model_evaluated_rows": 694,
            "families": {
                "game_total": {"observed": 114863, "model_evaluated": 694},
                "hitter_hits": {"observed": 23295, "model_evaluated": 0},
            },
            "independently_valid_evaluations": None,
        }
        self.assertTrue(rr.independent_verify(original, after))
        for field, value in (
            ("opportunity_rows", 694),
            ("model_evaluated_rows", 138158),
            ("independently_valid_evaluations", 694),
        ):
            modified = copy.deepcopy(after)
            modified[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                rr.independent_verify(original, modified)
        modified = copy.deepcopy(after)
        modified["families"]["hitter_hits"]["model_evaluated"] = 23295
        with self.assertRaises(ValueError):
            rr.independent_verify(original, modified)

    def test_invalid_source_side_denominators_fail_before_repair(self):
        bad = witnesses()
        doc = json.loads(bad["historical_quality"])
        doc["report"]["rowsLackingModelEvaluation"] = 0
        bad["historical_quality"] = json.dumps(doc).encode()
        with patch.object(rr, "load_sources", return_value=(bad, [])):
            with self.assertRaises(ValueError):
                rr.run({})


if __name__ == "__main__":
    unittest.main()

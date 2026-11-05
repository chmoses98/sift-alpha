"""Offline adversarial coverage of the real-source Aug 19/20 overlap gate."""
import copy
import json
import unittest
from unittest.mock import patch

from alpha_engine import hitter_overlap_audit as overlap
from alpha_engine import hitter_archive_gate as gate


def report():
    return {"rowCount": 138158, "report": {
        "totalOpportunityRows": 138158, "uniqueGames": 353,
        "uniqueMarketTickers": 80526, "rowsLackingModelEvaluation": 137464,
        "rowsLackingTemporallyValidModelEvaluation": 137464,
        "rowsLackingExecutablePregamePrice": 0,
        "datesWithObservations": [f"2026-08-{i:02d}" for i in range(1, 21)],
        "familyModelCoverage": {
            "hitter_hits": {"observed": 23295, "modelEvaluated": 0, "coverageRate": 0},
            "game_total": {"observed": 114863, "modelEvaluated": 694, "coverageRate": 694 / 114863},
        },
        "familySettlementCoverage": {
            "hitter_hits": {"observed": 23295, "settled": 20000, "coverageRate": 20000 / 23295},
            "game_total": {"observed": 114863, "settled": 100765, "coverageRate": 100765 / 114863},
        },
        "settlementStatusCounts": {"SETTLED": 120765, "NOT_SETTLED": 17393,
                                   "SETTLEMENT_UNRESOLVED": 0},
    }}


def row(ticker="KXMLBHIT-TEST-1", forecast="2026-08-19T20:00:00Z",
        observed="2026-08-19T19:00:00Z", snapshot="2026-08-19T20:01:00Z"):
    return {"marketTicker": ticker, "hitterProjectionSnapshotId": "a" * 40,
            "marketFamily": "hitter_hits", "playerId": "691406", "gameId": 824235,
            "projectionStatus": "PROJECTED", "pricingStatus": "PRICED",
            "modelProbability": 0.3, "projectionGeneratedAt": forecast,
            "marketObservedAt": observed, "snapshotGeneratedAt": snapshot}


def fixture(rows19=None, rows20=None):
    a = (json.dumps(rows19 if rows19 is not None else row()) + "\n").encode()
    b = (json.dumps(rows20 if rows20 is not None else row(
        ticker="KXMLBHIT-TEST-2", forecast="2026-08-20T18:00:00Z",
        observed="2026-08-20T19:00:00Z", snapshot="2026-08-20T18:01:00Z")) + "\n").encode()
    pins = {"2026-08-19": (gate.git_hash("blob", a), len(a)),
            "2026-08-20": (gate.git_hash("blob", b), len(b))}
    return pins, {"2026-08-19": a, "2026-08-20": b}


class HitterOverlapTests(unittest.TestCase):
    def test_pinned_overlap_reconciles_without_claiming_repair(self):
        pins, blobs = fixture()
        with patch.object(overlap, "PINS", pins):
            x = overlap.analyze(report(), blobs)
            self.assertEqual(x["source_rows_examined"], 2)
            self.assertEqual(x["candidate_forecast_rows_at_embedded_quote_clock"], 1)
            self.assertEqual(x["days"]["2026-08-19"]["row_evidence"]["forecast_after_recorded_quote"], 1)
            self.assertEqual(x["days"]["2026-08-19"]["family_source_rows"]["hitter_hits"], 1)
            self.assertEqual(x["days"]["2026-08-19"]["family_non_candidate_rows"]["hitter_hits"], 1)
            self.assertEqual(x["days"]["2026-08-20"]["family_candidate_rows_at_embedded_quote_clock"]["hitter_hits"], 1)
            self.assertEqual(x["before"], x["after"])
            self.assertEqual(x["after"]["hitter_hits_evaluated"], 0)
            self.assertIsNone(x["independently_valid_historical_evaluations"])
            self.assertEqual(x["repair_result"], "BLOCKED_NO_SAFE_HISTORICAL_REPAIR")
            self.assertEqual(x, overlap.analyze(report(), blobs))

    def test_tamper_missing_extra_or_unbounded_sources_fail_closed(self):
        pins, blobs = fixture()
        with patch.object(overlap, "PINS", pins):
            for altered in (
                {"2026-08-19": blobs["2026-08-19"]},
                {**blobs, "2026-08-21": b"other"},
                {**blobs, "2026-08-19": blobs["2026-08-19"].replace(b"0.3", b"0.4")},
                {**blobs, "2026-08-19": blobs["2026-08-19"] + b" "},
            ):
                with self.assertRaises(ValueError):
                    overlap.analyze(report(), altered)
            with patch.object(overlap, "MAX_TOTAL_BYTES", 1):
                with self.assertRaises(ValueError):
                    overlap.analyze(report(), blobs)

    def test_timestamp_mismatch_and_invalid_identity_quarantined(self):
        for change in (
            {"marketObservedAt": "not-a-time"},
            {"snapshotGeneratedAt": "2026-08-19T19:30:00Z"},
            {"marketTicker": "OTHER-1"},
            {"modelProbability": 1.5},
            {"projectionStatus": "MISSING"},
            {"marketFamily": "not_a_market"},
        ):
            changed = {**row(), **change}
            pins, blobs = fixture(rows19=changed)
            with patch.object(overlap, "PINS", pins):
                x = overlap.analyze(report(), blobs)
                self.assertEqual(x["candidate_forecast_rows_at_embedded_quote_clock"], 1)
                self.assertEqual(x["after"]["evaluated_rows"], 694)
                self.assertEqual(x["after"]["hitter_hits_evaluated"], 0)

    def test_forged_historical_denominators_rejected(self):
        pins, blobs = fixture()
        bad = copy.deepcopy(report())
        bad["report"]["familyModelCoverage"]["hitter_hits"]["modelEvaluated"] = 100
        with patch.object(overlap, "PINS", pins), self.assertRaises(ValueError):
            overlap.analyze(bad, blobs)
        bad = report()
        bad["report"]["datesWithObservations"].pop()
        with patch.object(overlap, "PINS", pins), self.assertRaises(ValueError):
            overlap.analyze(bad, blobs)

    def test_duplicate_ticker_and_snapshot_ids_are_not_counted_as_candidates(self):
        first = row(observed="2026-08-19T21:00:00Z")
        second = dict(first)
        pins, blobs = fixture(rows19=first)
        raw = (json.dumps(first) + "\n" + json.dumps(second) + "\n").encode()
        pins["2026-08-19"] = (gate.git_hash("blob", raw), len(raw))
        blobs["2026-08-19"] = raw
        with patch.object(overlap, "PINS", pins):
            x = overlap.analyze(report(), blobs)
            counts = x["days"]["2026-08-19"]["row_evidence"]
            self.assertEqual(counts["duplicate_identity_rows"], 1)
            self.assertEqual(counts["candidate_at_recorded_quote_only"], 1)
            self.assertEqual(counts["not_candidate_at_recorded_quote"], 1)


if __name__ == "__main__":
    unittest.main()

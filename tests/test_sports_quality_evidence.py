"""Adversarial QA for real-sport historical evidence reports."""
import copy
import json
from pathlib import Path
import unittest
from alpha_engine.sports_quality_evidence import check_sources,read,audit_nba,audit_mlb

def mlb_fixture():
    # Synthetic opportunity rows, intentionally not unique games or bets.
    return {"rowCount": 200, "report": {
        "totalOpportunityRows": 200, "uniqueGames": 2, "uniqueMarketTickers": 70,
        "rowsLackingModelEvaluation": 190,
        "rowsLackingTemporallyValidModelEvaluation": 195,
        "rowsLackingExecutablePregamePrice": 0,
        "familyModelCoverage": {
            "hitter_hits": {"observed": 100, "modelEvaluated": 0, "coverageRate": 0},
            "game_total": {"observed": 100, "modelEvaluated": 10, "coverageRate": 0.1},
        },
        "familySettlementCoverage": {
            "hitter_hits": {"observed": 100, "settled": 70, "coverageRate": 0.7},
            "game_total": {"observed": 100, "settled": 70, "coverageRate": 0.7},
        },
        "settlementStatusCounts": {
            "SETTLED": 140, "NOT_SETTLED": 40, "SETTLEMENT_UNRESOLVED": 20,
        },
    }}

class DataEvidenceTests(unittest.TestCase):
 def test_frozen_sources_are_exactly_permitted_ones(self):
  m=json.loads(Path("research/sports_quality_evidence_sources.json").read_text())
  self.assertEqual(len(check_sources(m)),2)
  m["sources"][0]["repository"]="unapproved/charged"
  with self.assertRaises(ValueError):check_sources(m)

 def test_tampered_report_bytes_are_quarantined(self):
  m=json.loads(Path("research/sports_quality_evidence_sources.json").read_text())
  with self.assertRaises(ValueError):read(m["sources"][0],downloader=lambda _:b'{"counts":{"v1":{"entries":999999}}}')

 def test_wrong_team_roster_errors_not_hidden(self):
  x={"n_games":1,"counts":{
    "v1":{"entries":15,"entries_stale_third_team":5,"entries_stale_opponent":1,"box_wrong_team":2},
    "both":{"entries":13,"entries_stale_third_team":0,"entries_stale_opponent":0,"box_wrong_team":1}
   }}
  report=audit_nba(x)
  self.assertFalse(report["production_model_certified"])
  self.assertEqual(report["candidate_wrong_team_box_entries"],1)
  x["counts"]["both"]["box_wrong_team"]=-1
  with self.assertRaises(ValueError):audit_nba(x)

 def test_zero_mlb_model_forecast_coverage_not_called_validation(self):
  x=mlb_fixture()
  out=audit_mlb(x)
  self.assertEqual(out["unmodeled_families_with_100plus_observations"]["hitter_hits"]["market_observations"],100)
  self.assertEqual(out["opportunity_rows"],200)
  self.assertEqual(out["model_evaluated_rows"],10)
  self.assertEqual(out["model_evaluation_coverage_fraction"],0.05)
  self.assertEqual(out["rows_without_temporally_valid_model_evaluation"],195)
  self.assertEqual(out["settled_rows_reported"],140)
  self.assertEqual(out["unique_physical_games_reported_not_independently_verified"],2)
  self.assertFalse(out["executable_pregame_price_independently_verified"])
  self.assertFalse(out["model_accuracy_certified"])

 def test_mlb_global_denominator_and_family_totals_are_reconciled(self):
  changes=[
   lambda x: x["report"].__setitem__("totalOpportunityRows",201),
   lambda x: x.__setitem__("rowCount",199),
   lambda x: x["report"].__setitem__("rowsLackingModelEvaluation",189),
   lambda x: x["report"].__setitem__("rowsLackingTemporallyValidModelEvaluation",189),
   lambda x: x["report"].__setitem__("uniqueGames",201),
   lambda x: x["report"]["familyModelCoverage"]["game_total"].__setitem__("observed",99),
   lambda x: x["report"]["familyModelCoverage"]["game_total"].__setitem__("modelEvaluated",11),
   lambda x: x["report"]["familySettlementCoverage"]["hitter_hits"].__setitem__("observed",99),
   lambda x: x["report"]["settlementStatusCounts"].__setitem__("SETTLED",139),
   lambda x: x["report"]["settlementStatusCounts"].__setitem__("NOT_SETTLED",39),
   lambda x: x["report"]["familySettlementCoverage"]["game_total"].__setitem__("settled",71),
  ]
  for change in changes:
   x=mlb_fixture()
   change(x)
   with self.subTest(change=str(change)),self.assertRaises(ValueError):
    audit_mlb(x)

 def test_mlb_invalid_rates_missing_categories_and_unbounded_counts(self):
  changes=[
   lambda x: x["report"]["familyModelCoverage"]["game_total"].__setitem__("coverageRate",0.9),
   lambda x: x["report"]["familySettlementCoverage"]["game_total"].__setitem__("coverageRate",float("nan")),
   lambda x: x["report"]["familyModelCoverage"]["hitter_hits"].__setitem__("observed",-1),
   lambda x: x["report"]["familyModelCoverage"]["game_total"].__setitem__("modelEvaluated",True),
   lambda x: x["report"]["settlementStatusCounts"].__setitem__("VOID",1),
   lambda x: x["report"]["familySettlementCoverage"].pop("hitter_hits"),
   lambda x: x["report"].__setitem__("rowsLackingExecutablePregamePrice",201),
  ]
  for change in changes:
   x=mlb_fixture()
   change(x)
   with self.subTest(change=str(change)),self.assertRaises(ValueError):
    audit_mlb(x)

if __name__=="__main__":
 unittest.main()

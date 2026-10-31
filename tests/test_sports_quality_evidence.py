"""Adversarial QA for real-sport historical evidence reports."""
import copy
import json
from pathlib import Path
import unittest
from alpha_engine.sports_quality_evidence import check_sources,read,audit_nba,audit_mlb

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
  x={"report":{"familyModelCoverage":{"hitter_hits":{"observed":100,"modelEvaluated":0,"coverageRate":0}}}}
  out=audit_mlb(x)
  self.assertEqual(out["unmodeled_families_with_100plus_observations"]["hitter_hits"]["market_observations"],100)
  self.assertFalse(out["model_accuracy_certified"])
  x["report"]["familyModelCoverage"]["hitter_hits"]["coverageRate"]=0.9
  with self.assertRaises(ValueError):audit_mlb(x)

if __name__=="__main__":
 unittest.main()

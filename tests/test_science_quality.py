"""Adversarial game-truth/forecast-truth tests with no fabricated certification."""
import copy
import math
import unittest
from alpha_engine.science_quality import context, projection, research_eligibility

D="2026-10-25T18:00:00Z"
SRC=[
 {"id":"nba_official","original_provider":"nba", "rights_checked":True,"observed_at":"2026-10-25T17:30:00Z"},
 {"id":"scoreboard_independent","original_provider":"espn","rights_checked":True,"observed_at":"2026-10-25T17:35:00Z"},
]
GAME={
 "event_id":"gameA","sport":"NBA","home_team_id":"H","away_team_id":"A",
 "scheduled_start_at":"2026-10-25T20:00:00Z",
 "actual_start_bracket":{"lower_bound_utc":"2026-10-25T19:59:00Z",
                         "upper_bound_utc":"2026-10-25T20:01:00Z",
                         "independent_evidence_id":"synthetic_frozen_bracket"},
 "sources":SRC,
 "facts":[{"name":"player_roster_membership","subject_id":"p1","value":"H",
           "source_id":"nba_official","status":"CONFIRMED",
           "observed_at":"2026-10-25T17:35:00Z"}]
}
PROJECTION={
 "event_id":"gameA","sport":"NBA","player_id":"p1","player_team_id":"H",
 "model_version":"test-v1","model_sha256":"a"*64,"input_snapshot_sha256":"b"*64,
 "target_definition_verified":True,
 "published_at":"2026-10-25T17:55:00Z",
 "model_fit_at":"2026-10-25T16:00:00Z",
 "last_training_label_at":"2026-10-24T23:59:00Z",
 "latest_input_observed_at":"2026-10-25T17:45:00Z",
 "distribution":{"kind":"binary","p_yes":0.58},
 "backtest_holdout_verified":True,"calibration_evidence_id":"fixture_calibration"}
class ScienceTruthTests(unittest.TestCase):
 def test_structural_pass_does_not_imply_independent_certification(self):
    cg=context(GAME,D)
    pg=projection(PROJECTION,GAME,D)
    self.assertEqual(cg["state"],"STRUCTURE_PASS_UNCERTIFIED")
    self.assertEqual(pg["state"],"STRUCTURE_PASS_UNCERTIFIED")
    self.assertEqual(pg["scientific_certification"],"NOT_INDEPENDENTLY_ESTABLISHED")
    self.assertFalse(research_eligibility(cg,pg)["eligible_for_live_trading"])

 def test_future_observed_injury_is_quarantined(self):
    g=copy.deepcopy(GAME)
    g["facts"].append({"name":"injury_status","subject_id":"p1","value":"OUT",
                        "source_id":"nba_official","status":"CONFIRMED",
                        "observed_at":"2026-10-25T18:05:00Z"})
    self.assertEqual(context(g,D)["state"],"QUARANTINED")

 def test_stale_roster_or_unverified_starter_is_limited(self):
    g=copy.deepcopy(GAME)
    g["facts"][0]["status"]="ESTIMATED"
    self.assertEqual(context(g,D)["state"],"LIMITED")
    p=projection(PROJECTION,g,D)
    self.assertEqual(p["state"],"LIMITED")

 def test_invalid_athlete_team_and_conflicting_roster(self):
    p={**PROJECTION,"player_team_id":"A"}
    self.assertEqual(projection(p,GAME,D)["state"],"QUARANTINED")
    g=copy.deepcopy(GAME)
    g["facts"].append({**g["facts"][0],"value":"A"})
    self.assertEqual(context(g,D)["state"],"QUARANTINED")

 def test_unknown_actual_start_is_not_pregame_certified(self):
    g=copy.deepcopy(GAME)
    g["actual_start_bracket"]=None
    self.assertEqual(context(g,D)["state"],"LIMITED")
    self.assertEqual(context(GAME,"2026-10-25T20:00:00Z")["state"],"LIMITED")
    self.assertEqual(context(GAME,"2026-10-25T20:02:00Z")["state"],"QUARANTINED")

 def test_two_repackaged_sources_not_independent(self):
    g=copy.deepcopy(GAME)
    g["sources"][1]["original_provider"]="nba"
    self.assertEqual(context(g,D)["state"],"LIMITED")

 def test_unobserved_or_unlicensed_source_blocks_certification(self):
    g=copy.deepcopy(GAME)
    g["sources"][1]["rights_checked"]=False
    self.assertEqual(context(g,D)["state"],"LIMITED")
    g["sources"][0]["observed_at"]="2026-10-25T18:01:00Z"
    self.assertEqual(context(g,D)["state"],"QUARANTINED")

 def test_future_fit_feature_or_training_label_is_quarantined(self):
    for field,val in [
       ("model_fit_at","2026-10-25T18:01:00Z"),
       ("published_at","2026-10-25T18:01:00Z"),
       ("latest_input_observed_at","2026-10-25T18:01:00Z"),
       ("last_training_label_at","2026-10-25T17:00:00Z")]:
        p=copy.deepcopy(PROJECTION)
        p[field]=val
        if field=="last_training_label_at":
            p["model_fit_at"]="2026-10-25T16:00:00Z"
        self.assertEqual(projection(p,GAME,D)["state"],"QUARANTINED",field)

 def test_distributions_fail_closed_on_incoherence(self):
    for distribution in [
      {"kind":"binary","p_yes":float("nan")},
      {"kind":"binary","p_yes":1.3},
      {"kind":"categorical","probabilities":{"home":0.4,"away":0.5}},
      {"kind":"quantiles","values":{"0.1":20,"0.9":10}},
      {"kind":"quantiles","values":{"0.1":float("inf"),"0.9":2}},
      {"kind":"unknown"}]:
       p=copy.deepcopy(PROJECTION)
       p["distribution"]=distribution
       self.assertEqual(projection(p,GAME,D)["state"],"QUARANTINED",str(distribution))

 def test_no_data_unknown_no_source_and_missing_prediction_evidence(self):
    g=copy.deepcopy(GAME)
    g["sources"]=[]
    self.assertEqual(context(g,D)["state"],"QUARANTINED")
    p={**PROJECTION,"target_definition_verified":False,
        "backtest_holdout_verified":False,"calibration_evidence_id":None}
    self.assertEqual(projection(p,GAME,D)["state"],"LIMITED")
if __name__=="__main__":
 unittest.main()

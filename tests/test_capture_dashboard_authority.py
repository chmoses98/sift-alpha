"""Adversarial dashboard authority tests: synthetic rows, not market evidence."""
from copy import deepcopy
import pytest
from alpha_engine.series_inventory_bridge import append

def matrix():
    return {"authority":"RESEARCH_ONLY_NOT_LIVE_COLLECTION",
            "live_capture_running":False,"all_market_families_certified":False,
            "family_rows":[],"missing_input_queue":[]}

def row():
    return {"sport":"CFB","family":"CAPTURE:TEST@2026-11-03T00:00:00Z",
            "observation_scope":"OPT_IN_PUBLIC_OPEN_SERIES_PAGES_ONLY",
            "market_collection_status":"COLLECTED_VALID",
            "input_collection_status":"UNKNOWN","model_usage_status":"UNKNOWN",
            "model_version_and_calibration":"UNKNOWN","settlement_outcome_join":"UNKNOWN",
            "point_in_time_pregame_eligibility":"UNKNOWN","projected_outcome":None,
            "complete_series_or_market_tape":False,"observed_denominator":1,
            "denominator_unit":"distinct_tickers_in_this_verified_capture",
            "observed_contracts":[{"ticker":"SYNTHETIC"}],
            "all_reported_pages_retrieved":False,"source_page_sha256":["synthetic"]}

@pytest.mark.parametrize("key,value", [
    ("model_usage_status","USED_VALID"),
    ("input_collection_status","COLLECTED_VALID"),
    ("settlement_outcome_join","VERIFIED"),
    ("point_in_time_pregame_eligibility","VERIFIED"),
    ("projected_outcome",0.75),
    ("complete_series_or_market_tape",True),
    ("observed_denominator",2),
    ("denominator_unit","all_kalshi_contracts"),
])
def test_forged_capture_authority_rejected(key,value):
    forged=deepcopy(row())
    forged[key]=value
    with pytest.raises(ValueError):
        append(matrix(),forged)

def test_partial_capture_keeps_unknown_and_missing_queue():
    result=append(matrix(),row())
    assert result["family_rows"][0]["model_usage_status"]=="UNKNOWN"
    assert result["missing_input_queue"][0]["denominator"]==1
    assert result["live_capture_running"] is False

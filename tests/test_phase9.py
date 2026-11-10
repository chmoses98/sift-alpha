"""Phase 9 guards (RESEARCH_ONLY): rights decisions, market-semantics separation, FULL-promotion audit, inactive capture plan."""
import json
from pathlib import Path

import pytest

from alpha_engine.features import college_collect as CC
from alpha_engine.input_research.data_foundation import market_completeness as M, prospective_plan as PP, rights as RT, full_promotion_audit as FA
from alpha_engine.input_research.data_foundation import verified_coverage as VC

ROOT = Path(__file__).resolve().parents[1]
DF = ROOT / "research/input_research/data_foundation"
PHASE8 = {"CBB": ["cbb.ratings_fundamentals", "cbb.tempo", "cbb.rating_uncertainty", "cbb.ot_period_tie_chain", "cbb.blowout_garbage"],
          "CFB": ["cfb.off_ppa", "cfb.def_ppa", "cfb.drives", "cfb.td_per_scoring_trip", "cfb.scoring_trip_efficiency", "cfb.pass_rate", "cfb.script_adjusted_pass_attempts", "cfb.havoc", "cfb.goal_to_go_run_pass_mix"]}


def _rows():
    return json.loads((M.OUT / "market_completeness.json").read_text())["rows"]


def test_fourteen_phase8_inputs_retained_and_rights_unresolved():
    st = {r["key"]: r["verified_status"] for r in json.loads((DF / "verified_coverage.json").read_text())["rows"]}
    n = 0
    for sp, ids in PHASE8.items():
        for i in ids:
            assert st[f"{sp}:{i}"] == "VERIFIED_PARTIAL", i            # evidence retained, status unchanged
            assert RT.input_tier(f"{sp}:{i}") == "UNRESOLVED_INTERNAL_ONLY" and not RT.is_cleared(RT.input_tier(f"{sp}:{i}")), i
            n += 1
    assert n == 14
    assert json.loads((DF / "rights_registry.json").read_text())["retained_phase8_inputs_unresolved"] == PHASE8


def test_unresolved_collector_is_frozen_and_registry_never_clears_by_code_licence():
    with pytest.raises(RT.RightsFrozen):
        CC.main(["/nonexistent"])
    reg = RT.registry(); order = reg["tier_order"]
    for s in reg["sources"]:
        if s["id"].startswith(("sportsdataverse", "espn", "mlb", "nhl", "football", "nba")):
            assert s["tier"] == "UNRESOLVED_INTERNAL_ONLY" and s["collection_allowed"] is False, s["id"]
    assert RT.tier_of_source("some brand new source") == order[0]            # unmatched source fails closed
    assert RT.tier_of_sources(["openfootball_league_results", "espn_scoreboard"]) == order[0]   # weakest source decides
    assert RT.tier_of_source("openfootball_league_results") == "CLEARED_OPEN_LICENCE"
    assert not RT.is_cleared("WRAPPER_LICENCE_UPSTREAM_CAVEAT")


def test_every_built_input_gets_exactly_one_rights_tier():
    built = [r for r in json.loads((DF / "verified_coverage.json").read_text())["rows"] if r["verified_status"] in ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY")]
    tiers = {r["key"]: RT.input_tier(r["key"]) for r in built}
    assert all(t in RT.registry()["tier_order"] for t in tiers.values())
    unresolved_sources = [k for k in tiers if not RT.raw_sources_by_key().get(k)]
    assert not [k for k in unresolved_sources if tiers[k] != "UNRESOLVED_INTERNAL_ONLY"]


def test_rules_text_is_semantics_not_predictive_and_catalog_untouched():
    st = M.load_status(None); audit = {r["key"]: r for r in json.loads((DF / "input_audit.json").read_text())["rows"]}
    assert M.SEMANTIC_IDS == ("m.rules_text",)
    # Phase 10 (owner decision 1): settlement/operational metadata and the calibration benchmark also left the predictive denominator. Any OTHER market-derived input that is not benchmark-excluded would stay predictive; this pins that none is left.
    kept = set()
    for a in M.archetypes():
        for iid, _ in a["inputs"]:
            if iid.startswith("m.") and iid not in M.NON_PREDICTIVE_IDS and M.category(st[f"{a['sport']}:{iid}"], (audit.get(f"{a['sport']}:{iid}") or {}).get("full_definition_status")) != "EXCLUDED_MARKET": kept.add(iid)
    assert kept == set()
    assert M.SETTLEMENT_OPS_IDS == ("m.settlement_truth", "m.lifecycle", "m.stat_correction_risk", "m.stat_source_mismatch") and M.CALIBRATION_IDS == ("m.strike_hit_rates",)
    rows = _rows()
    assert sum(r["semantics_required"] for r in rows) == 144 and sum(r["semantics_primary"] for r in rows) == 134     # 134 primary + 10 context
    assert sum(r["settlement_ops_required"] for r in rows) == 64 and sum(r["settlement_ops_primary"] for r in rows) == 3
    assert sum(r["calibration_required"] for r in rows) == 23 and sum(r["calibration_primary"] for r in rows) == 0
    for r in rows:
        assert "m.rules_text" in r["input_categories"] or r["semantics_required"] == 0             # still listed in the archetype (catalog unchanged)
        assert r["n_inputs_listed"] == r["n_required"] + r["n_excluded_market_inputs"] + r["semantics_required"] + r["settlement_ops_required"] + r["calibration_required"]
        assert r["n_required"] == sum(r[k] for k in M.PRED_KEYS)                                   # predictive denominator excludes every market-metadata slot
        assert r["semantics_built"] == 0 and (r["semantics_completeness"] in (None, 0.0))            # captured-unverified is never counted as completeness
        assert r["independently_complete"] is False
    assert sum(r["n_required"] for r in rows) == 3899 - 144 - 80                                      # rules text, then 64 settlement/ops + 23 calibration minus 7 slots already benchmark-excluded


def test_research_and_commercial_clearance_are_separate_and_nflverse_stays_wrapper_only():
    reg = RT.registry()
    assert reg["tier_aliases"]["WRAPPER_ONLY"] == "WRAPPER_LICENCE_UPSTREAM_CAVEAT"
    assert RT.tier_of_source("nflverse pbp") == "WRAPPER_LICENCE_UPSTREAM_CAVEAT" and not RT.is_research_cleared("WRAPPER_LICENCE_UPSTREAM_CAVEAT") and not RT.is_commercial_cleared("WRAPPER_LICENCE_UPSTREAM_CAVEAT")
    assert RT.is_research_cleared("CLEARED_NONCOMMERCIAL_RESEARCH") and not RT.is_commercial_cleared("CLEARED_NONCOMMERCIAL_RESEARCH")      # CC BY-NC-SA is research only
    assert RT.is_research_cleared("CLEARED_OPEN_LICENCE") and RT.is_commercial_cleared("CLEARED_OPEN_LICENCE")
    for s in reg["sources"]:
        assert s["commercial_cleared"] <= s["research_cleared"]
    rows = _rows()
    assert all(r["built_commercial_cleared"] <= r["built_rights_cleared"] for r in rows)
    fd = next(s for s in reg["sources"] if s["id"] == "football_data_co_uk"); assert fd["tier"] == "UNRESOLVED_INTERNAL_ONLY" and "private individuals only" in fd["evidence"]


def test_rights_questions_ranking_is_deterministic():
    from alpha_engine.input_research.data_foundation import rights_questions as RQ
    assert json.loads(RQ.OUT.read_text()) == RQ.build()


def test_rights_and_prospective_accounting_reconciles():
    rows = _rows(); built = sum(r["FULL"] + r["PARTIAL"] + r["PROXY"] for r in rows)
    assert built == sum(r["built_rights_cleared"] + r["built_wrapper_licence_only"] + r["built_rights_unresolved"] for r in rows)
    assert sum(r["prospective_gap_slots"] for r in rows) == sum(r["PROSPECTIVE"] for r in rows)
    ev = json.loads((DF / "semantics_capture_evidence.json").read_text())["sports"]
    assert ev["NBA"]["state"] == "CAPTURED_UNVERIFIED" and ev["NHL"]["state"] == "CAPTURED_UNVERIFIED" and ev["NFL"]["state"] == "PARTIAL_CAPTURE_UNVERIFIED"
    assert M.sem_capture_state()["TENNIS"] == "NOT_CAPTURED"


def test_full_promotion_audit_matches_matrix_and_has_no_uncertified_full():
    a = json.loads((DF / "full_promotion_audit.json").read_text()); assert a == FA.build()      # deterministic
    vc = {r["key"]: r for r in json.loads((DF / "verified_coverage.json").read_text())["rows"]}
    rms = next(x for x in a["rows"] if x["key"] == "TENNIS:ten.retirement_margin_state")     # the one Phase 9 candidate: refused because the catalog says pregame_knowable = partial
    assert rms["status"] == "VERIFIED_PARTIAL" and rms["first_failed_stage"] == "S2" and "NOT_FULL" in rms["review"]
    assert vc["TENNIS:ten.retirement_margin_state"]["verified_status"] == "VERIFIED_PARTIAL"
    assert sum(r["verified_status"] == "VERIFIED_FULL" for r in vc.values()) == 58              # Phase 10 promotes exactly one: ten.tiebreak_base_rate_by_event (certification phase10_round1)
    certs = VC.load_full_certifications()
    for k, r in vc.items():
        if r["verified_status"] == "VERIFIED_FULL" and r["evidence"].get("promoted_from") == "VERIFIED_PARTIAL":
            assert r["id"] in certs and r["evidence"].get("full_certified")
    for x in a["rows"]:
        if x["status"] == "VERIFIED_PARTIAL":
            assert x["first_failed_stage"] != "PROMOTED"
            if x["first_failed_stage"] == "S5": assert x["review"]                  # an input that clears S1-S4 always carries a recorded reading
    assert set(FA.REVIEW) <= set(vc)


def test_capture_plan_is_inactive_and_never_duplicates_an_existing_supplier():
    p = json.loads((DF / "prospective_capture_plan.json").read_text()); assert p == PP.build()
    assert p["ACTIVE"] is False and p["nothing_scheduled_enabled_or_changed"] is True
    for f in p["feeds"]:
        if f["existing_supplier"] not in ("none", "not applicable", "none identified"):
            assert not f["action"].startswith(("NEW", "CREATE")), f["feed_dataset"]       # an existing supplier is verified / extended / scheduled by the owner, never duplicated
    assert p["primary_prospective_slots_total"] == p["primary_vintage_feed_slots"] + p["primary_non_vintage_slots"] + p["primary_news_only_slots"]
    wf = (ROOT / ".github/workflows")
    assert not any("prospective_plan" in f.read_text() for f in wf.glob("*.yml"))               # no workflow runs the plan

"""Fail-closed gates for extension inputs (builders added after the earlier milestone)."""
import copy
import json
from pathlib import Path

from alpha_engine.input_research.data_foundation import verified_coverage as VC

OK = {"ok": True}
GOOD = {"determinism": OK, "own_game": OK, "truncation": [OK, OK, OK], "perturbation": [OK, OK, OK], "pit_check_perturbation_not_vacuous": OK}


def test_missing_vacuity_check_fails():
    t = copy.deepcopy(GOOD); del t["pit_check_perturbation_not_vacuous"]
    assert "pit_check_perturbation_not_vacuous" in VC.pit_check_failures("x.y", t)


def test_failed_leak_check_fails_and_injuries_need_post_kickoff():
    t = copy.deepcopy(GOOD); t["pit_check_post_kickoff_injuries"] = {"ok": False}
    assert "pit_check_post_kickoff_injuries" in VC.pit_check_failures("x.y", t)
    assert "pit_check_post_kickoff_injuries" in VC.pit_check_failures("nfl.injuries_pit", GOOD)       # required for injuries even when absent


def test_no_cuts_or_failed_cut_fails():
    t = copy.deepcopy(GOOD); t["truncation"] = []
    assert "truncation" in VC.pit_check_failures("x.y", t)
    t = copy.deepcopy(GOOD); t["perturbation"] = [OK, {"ok": False}, OK]
    assert "perturbation" in VC.pit_check_failures("x.y", t)
    assert VC.pit_check_failures("x.y", GOOD) == []


def test_independent_gate_fail_closed():
    row = {"id": "a.b"}
    assert VC.independent_gate(row, ["c1"], {})[0] == "REQUIRES_COLLECTION"
    assert VC.independent_gate(row, ["c1"], {"a.b": {"c1": {"verdict": "MISMATCH"}}})[0] == "DOWNGRADED_BY_VERIFIER"
    assert VC.independent_gate(row, ["c1", "c2"], {"a.b": {"c1": {"verdict": "MATCH"}}})[0] == "REQUIRES_COLLECTION"        # c2 missing
    assert VC.independent_gate(row, ["c1"], {"a.b": {"c1": {"verdict": "PARTIAL_MATCH"}}})[0] == "REQUIRES_COLLECTION"
    assert VC.independent_gate(row, ["c1"], {"a.b": {"c1": {"verdict": "MATCH"}}})[0] is None


ROW = {"id": "x.y", "history": {"complete": True, "first": "2008", "last": "2026"}, "pit_verdict": "PIT_SAFE", "pregame_knowable": "yes"}
COLS = ["c1", "c2"]
CERT = {"catalog_clauses": [{"clause": "a", "columns": ["c1"], "implemented": True}, {"clause": "b", "columns": ["c2"], "implemented": True}], "builder_missing": [], "timing_rule": "strictly earlier", "source_use_rights": "NC"}
RPI = {"tests": {**GOOD, "truncation": [{**OK, "cut": i} for i in range(3)], "perturbation": [{**OK, "seed": i} for i in range(3)], "coverage_replay": {"min_coverage_new": 0.9, "constant_columns": [], "first_new": "2008-10-04", "last_new": "2026-04-16"}}}
EV = {"independent": {"c1": "MATCH", "c2": "MATCH"}}


def _cert(**ch):
    row = {**ROW, **ch.pop("row", {})}; cert = ch.pop("cert", CERT); rpi = ch.pop("rpi", RPI); ev = ch.pop("ev", EV); cols = ch.pop("cols", COLS)
    return VC.certify_extension_full(row, cols, rpi, "VERIFIED_FULL", dict(ev), cert)


def test_complete_input_can_be_certified_and_rights_are_separate():
    vs, ev = _cert()
    assert vs == "VERIFIED_FULL" and ev["full_certified"] and ev["source_use_rights"] == "NC"
    vs, ev = _cert(cert={**CERT, "source_use_rights": "unresolved"})
    assert vs == "VERIFIED_FULL"                                               # rights never decide the status


def test_incomplete_inputs_cannot_be_promoted():
    def p(**k): return _cert(**k)[0]
    assert p(cert=None) == "VERIFIED_PARTIAL"                                                       # no record
    assert p(cert={**CERT, "builder_missing": ["fitted model"]}) == "VERIFIED_PARTIAL"              # declared gap
    assert p(cert={**CERT, "catalog_clauses": CERT["catalog_clauses"][:1]}) == "VERIFIED_PARTIAL"   # clause/column mismatch
    assert p(cert={**CERT, "catalog_clauses": [{"clause": "a", "columns": ["c1", "c2"], "implemented": False}]}) == "VERIFIED_PARTIAL"
    assert p(cert={**CERT, "timing_rule": ""}) == "VERIFIED_PARTIAL"
    assert p(ev={"independent": {"c1": "MATCH"}}) == "VERIFIED_PARTIAL"                             # blind match missing for c2
    assert p(ev={"independent": {"c1": "MATCH", "c2": "PARTIAL_MATCH"}}) == "VERIFIED_PARTIAL"
    assert p(ev={**EV, "limits": ["min column coverage below 50%"]}) == "VERIFIED_PARTIAL"
    assert p(rpi=None) == "VERIFIED_PARTIAL"
    t = copy.deepcopy(RPI); del t["tests"]["pit_check_perturbation_not_vacuous"]; assert p(rpi=t) == "VERIFIED_PARTIAL"
    t = copy.deepcopy(RPI); t["tests"]["truncation"] = t["tests"]["truncation"][:2]; assert p(rpi=t) == "VERIFIED_PARTIAL"
    t = copy.deepcopy(RPI); t["tests"]["perturbation"][0]["ok"] = False; assert p(rpi=t) == "VERIFIED_PARTIAL"
    t = copy.deepcopy(RPI); t["tests"]["coverage_replay"]["min_coverage_new"] = 0.4; assert p(rpi=t) == "VERIFIED_PARTIAL"
    t = copy.deepcopy(RPI); t["tests"]["coverage_replay"]["first_new"] = "2012-01-01"; assert p(rpi=t) == "VERIFIED_PARTIAL"   # history shorter than required
    assert p(row={"pit_verdict": "PIT_CAVEAT"}) == "VERIFIED_PARTIAL"
    assert p(row={"pregame_knowable": "no"}) == "VERIFIED_PARTIAL"
    assert p(cols=["c1", "c2", "c3"]) == "VERIFIED_PARTIAL"                                          # an unverified extra column


def test_non_full_status_is_never_upgraded_by_certification():
    for vs in ("VERIFIED_PARTIAL", "REQUIRES_COLLECTION", "DOWNGRADED_BY_VERIFIER", "REPLAY_FAILED"):
        assert VC.certify_extension_full(ROW, COLS, RPI, vs, dict(EV), CERT)[0] == vs


def test_committed_matrix_full_extension_inputs_are_certified_with_evidence():
    V = json.loads((VC.DF / "verified_coverage.json").read_text())["rows"]
    exts = VC.load_ext_replays(); ids = {i for rp in exts.values() for i in rp["inputs"]}
    certs = VC.load_full_certifications()
    ext = [r for r in V if r["id"] in ids]
    assert ext
    audit = {a["id"]: a for a in json.loads((VC.DF / "input_audit.json").read_text())["rows"]}
    sp = {i: s for s, rp in exts.items() for i in rp["inputs"]}
    for r in ext:
        assert r["verified_status"] in ("VERIFIED_FULL", "VERIFIED_PARTIAL", "REQUIRES_COLLECTION", "REPLAY_FAILED", "DOWNGRADED_BY_VERIFIER", "PIT_QUARANTINED"), r["id"]
        if r["verified_status"] == "VERIFIED_FULL":
            assert r["evidence"].get("full_certified") and r["id"] in certs, r["id"]
            rpi = exts[sp[r["id"]]]["inputs"][r["id"]]      # independent recomputation of the gate from raw evidence agrees
            assert VC.certification_failures(audit[r["id"]], rpi["columns"], rpi, r["evidence"], certs[r["id"]]) == []


def test_exactly_the_reassessed_three_were_promoted_in_phase8():
    V = {r["id"]: r for r in json.loads((VC.DF / "verified_coverage.json").read_text())["rows"]}
    for i in ("nhl.loser_point_rate", "ten.major_winner_concentration", "ten.second_serve_vulnerability"):
        assert V[i]["verified_status"] == "VERIFIED_FULL"
    assert V["ten.home_slam_depth_prior"]["verified_status"] != "VERIFIED_FULL"       # 16% column coverage: a recorded limit


def test_ext_replays_have_required_pit_checks():
    for sp, rp in VC.load_ext_replays().items():
        for iid, v in rp["inputs"].items():
            assert VC.pit_check_failures(iid, v["tests"]) == [], iid

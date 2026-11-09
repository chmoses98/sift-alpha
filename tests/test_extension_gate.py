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


def test_committed_matrix_never_certifies_extension_inputs_as_full():
    V = json.loads((VC.DF / "verified_coverage.json").read_text())["rows"]
    ids = {i for rp in VC.load_ext_replays().values() for i in rp["inputs"]}
    ext = [r for r in V if r["id"] in ids]
    assert ext and all(r["verified_status"] != "VERIFIED_FULL" for r in ext)
    assert all(r["verified_status"] in ("VERIFIED_PARTIAL", "REQUIRES_COLLECTION", "REPLAY_FAILED", "DOWNGRADED_BY_VERIFIER", "PIT_QUARANTINED") for r in ext)


def test_ext_replays_have_required_pit_checks():
    for sp, rp in VC.load_ext_replays().items():
        for iid, v in rp["inputs"].items():
            assert VC.pit_check_failures(iid, v["tests"]) == [], iid

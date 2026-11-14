"""Phase 12: direct-API scaffold is inert without authorization, quota-bounded, key-safe; coverage inventory is derived and consistent; rights evidence preserved."""
import json
from datetime import date
from pathlib import Path

import pytest

from alpha_engine.collect import college_direct as CD
from alpha_engine.input_research.data_foundation import phase12_coverage as P12
from alpha_engine.input_research.data_foundation import rights as RT

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 11)


def auth(tmp_path, **kw):
    a = {"authorized": True, "monthly_call_cap": 1000, "max_share_of_cap": 0.1, "authorized_by": "owner", "date": "2026-11-11", "expires": "2026-12-31"}; a.update(kw)
    p = tmp_path / "auth.json"; p.write_text(json.dumps(a)); return p


def reqs(n=5):
    return CD.plan("cfb", [2024], ["/games/teams"])[:n]


def test_no_authorization_file_exists_in_repo_and_run_refuses():
    assert not CD.AUTH_FILE.exists()
    with pytest.raises(CD.Refusal): CD.load_authorization()


@pytest.mark.parametrize("kw", [{"authorized": False}, {"max_share_of_cap": 0.9}, {"monthly_call_cap": 0}, {"expires": "2026-01-01"}])
def test_bad_authorization_refused(tmp_path, kw):
    with pytest.raises(CD.Refusal): CD.load_authorization(auth(tmp_path, **kw), TODAY)


def test_missing_key_and_repo_output_dir_refused(tmp_path):
    t = lambda u, h: (200, b"{}", {})
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(), tmp_path / "o", tmp_path / "l.json", t, {}, auth(tmp_path), TODAY)
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(), ROOT / "raw_out", tmp_path / "l.json", t, {"CFBD_API_KEY": "k"}, auth(tmp_path), TODAY)


def test_budget_stops_before_cap_and_is_resumable_and_key_never_in_url_or_files(tmp_path):
    seen = []
    def t(url, h): seen.append((url, h)); return 200, b'{"ok":1}', {}
    env = {"CFBD_API_KEY": "SECRETKEY123"}; a = auth(tmp_path, monthly_call_cap=100, max_share_of_cap=0.05)      # allowed = 5 calls
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(8), tmp_path / "o", tmp_path / "l.json", t, env, a, TODAY, sleep=lambda s: None)
    assert len(seen) == 5 and json.loads((tmp_path / "l.json").read_text())["months"]["2026-11"]["calls"] == 5      # ledger v2 shape (main's probe module, PR #69)
    assert all("SECRETKEY123" not in u for u, _ in seen) and all(h["Authorization"] == "Bearer SECRETKEY123" for _, h in seen)
    assert not any("SECRETKEY123" in f.read_text() for f in (tmp_path / "o").iterdir())
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(8), tmp_path / "o", tmp_path / "l.json", t, env, a, TODAY, sleep=lambda s: None)     # files exist -> only new calls spend, and the cap is already reached
    assert len(seen) == 5


def test_stops_on_first_throttle(tmp_path):
    codes = iter([200, 429, 200])
    r = CD.run("cfb", reqs(3), tmp_path / "o", tmp_path / "l.json", lambda u, h: (next(codes), b"{}", {}), {"CFBD_API_KEY": "k"}, auth(tmp_path), TODAY, sleep=lambda s: None)
    assert r["requests_done"] == 1 and r["stopped_on_status"] == 429


def test_plan_is_pure_and_deterministic_and_counts_match():
    e = CD.estimate("cfb", list(range(2014, 2026)))
    assert e["static_calls"] == 828 and e == CD.estimate("cfb", list(range(2014, 2026)))
    assert CD.estimate("cbb", [2012])["static_calls"] == 7        # games, teams, players x 2 season types + rankings
    assert all(r.url().startswith(CD.HOSTS["cfb"]) and "key" not in r.url().lower() for r in CD.plan("cfb", [2020]))


def test_main_has_no_network_run_command():
    with pytest.raises(SystemExit): CD.main(["run", "--domain", "cfb", "--seasons", "2020"])


def test_serviceability_never_claims_availability_or_rules():
    s = CD.serviceability("cfb", [{"need": "AVAIL", "satisfied_by": "cfb.availability_snapshots"}, {"need": "EVENT", "satisfied_by": "cfb.pbp_cfbd"}])
    assert s["class"] == "PARTLY_SERVICEABLE" and s["unserved"][0]["need"] == "AVAIL"
    assert CD.serviceability("cfb", [{"need": "AVAIL", "satisfied_by": "cfb.availability_snapshots"}])["class"] == "NOT_SERVICEABLE"


def test_inventory_matches_market_completeness_and_is_checked_in():
    d = P12.build()
    assert d["primary_missing_slots"] == sum(d["primary_missing_by_sport"].values()) == sum(r["primary_missing_slots"] for r in d["inventory"])
    mc = json.loads((ROOT / "research/input_research/market_completeness/market_completeness.json").read_text())["rows"]
    assert d["primary_missing_slots"] == sum(r["primary_missing_critical"] for r in mc)
    cl = d["college_direct_api"]["missing_slots_by_class"]
    assert sum(cl.values()) == d["primary_missing_by_sport"]["CFB"] + d["primary_missing_by_sport"]["CBB"]
    assert len(d["top20_next"]) == 20
    assert P12.OUT.read_text() == json.dumps(d, indent=1, sort_keys=True) + "\n"        # regeneration check


def test_moneypuck_isolated_research_only_and_unlisted_unresolved():
    assert RT.tier_of_source("moneypuck_listed_downloads") == "CLEARED_NONCOMMERCIAL_RESEARCH"
    assert not RT.is_commercial_cleared("CLEARED_NONCOMMERCIAL_RESEARCH")
    assert RT.tier_of_source("moneypuck_unlisted") == "UNRESOLVED_INTERNAL_ONLY"
    n = P12.build()["nhl_moneypuck"]
    assert set(n["evidenced_listed_downloads"]) == {"playerData/seasonSummary/{year}/regular/teams.csv", "playerData/seasonSummary/{year}/regular/goalies.csv", "playerData/careers/gameByGame/all_teams.csv"}


def test_direct_api_tier_stays_collection_disallowed_and_separate_from_wrapper_and_original():
    reg = RT.registry(); by = {s["id"]: s for s in reg["sources"]}
    assert by["cfbd_cbbd_direct_api"]["collection_allowed"] is False
    assert RT.tier_of_source("sportsdataverse_cfbfastr") == "UNRESOLVED_INTERNAL_ONLY"      # wrapper path is not cleared by direct-API terms
    ev = reg["phase12_rights_evidence"]
    assert ev["exact_text_verified"] is False and len(ev["attempts"]) >= 4 and all(a["result"].startswith("BLOCKED") for a in ev["attempts"])

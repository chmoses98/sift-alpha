"""Fail-closed college direct-API probe, corrected CBB inventory, manual-only workflows, MoneyPuck non-commercial isolation."""
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from alpha_engine.collect import college_direct as CD
from alpha_engine.collect import moneypuck as MP

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 11)
INFO = json.dumps({"patronLevel": 0, "remainingCalls": 800}).encode()


def auth(tmp_path, **kw):
    a = {"authorized": True, "probe_authorized": True, "monthly_call_cap": 1000, "max_share_of_cap": 0.5, "authorized_by": "owner", "date": "2026-11-11", "expires": "2026-12-31",
         "shared_quota_remaining": 800, "quota_declared_on": "2026-11-11", "quota_reserve": 300}; a.update(kw)
    p = tmp_path / "a.json"; p.write_text(json.dumps(a)); return p


def run(tmp_path, transport, domain="cbb", env=None, **kw):
    return CD.probe(domain, tmp_path / "raw", tmp_path / "l.json", transport, {"CFBD_API_KEY": "SECRET"} if env is None else env, kw.pop("auth_path", None) or auth(tmp_path), TODAY, sleep=lambda s: None, repo_is_private=kw.pop("priv", True))


def test_cbb_inventory_corrected():
    seas = list(range(2014, 2026)); s = CD.cbb_event_strategies(seas); e = CD.estimate("cbb", seas)
    assert s["plays_by_game_fallback"] == 74400 and s["lineups_by_game_2024plus"] == 2 * 6200          # lineups only 2024-2025, not 12 seasons
    assert s["lineups_by_team_2024plus"] == 2 * 366 and s["plays_by_date"] == 12 * 161 and s["recommended_calls"] < 3000
    assert e["static_by_endpoint"]["/plays/date"] == 1935 and "/lineups/team?team={team}" in e["dependent_calls_estimate"]
    assert CD.estimate("cbb", [2022, 2023])["dependent_calls_estimate"].get("/lineups/team?team={team}") == 0
    assert "season numbering (ending year assumed)" in s["unverified"]


def test_probe_is_capped_and_plans_no_secret_in_url():
    for d in ("cfb", "cbb"):
        r = CD.probe_requests(d); assert 0 < len(r) <= CD.MAX_PROBE_CALLS and all("key" not in x.url().lower() for x in r)


@pytest.mark.parametrize("kw", [{"probe_authorized": False}, {"shared_quota_remaining": 100}, {"quota_declared_on": "2026-11-01"}, {"quota_reserve": 5}, {"max_share_of_cap": 0.9}])
def test_probe_refused_without_owner_authorization_or_quota_proof(tmp_path, kw):
    calls = []
    with pytest.raises(CD.Refusal): run(tmp_path, lambda u, h: calls.append(u) or (200, INFO, {}), auth_path=auth(tmp_path, **kw))
    assert not calls


def test_probe_refused_without_file_key_or_private_storage(tmp_path):
    t = lambda u, h: (200, INFO, {})
    with pytest.raises(CD.Refusal): CD.probe("cbb", tmp_path / "r", tmp_path / "l", t, {"CFBD_API_KEY": "k"}, tmp_path / "none.json", TODAY, repo_is_private=True)
    with pytest.raises(CD.Refusal): run(tmp_path, t, env={})
    with pytest.raises(CD.Refusal): run(tmp_path, t, priv=False)
    with pytest.raises(CD.Refusal): CD.probe("cbb", ROOT / "raw", tmp_path / "l", t, {"CFBD_API_KEY": "k"}, auth(tmp_path), TODAY, repo_is_private=True)


def test_probe_success_counts_calls_and_never_leaks_key(tmp_path):
    seen = []
    s = run(tmp_path, lambda u, h: (seen.append((u, h)) or 200, INFO if u.endswith("/info") else b"[1,2]", {}))
    assert s["calls_made"] == len(CD.probe_requests("cbb")) <= 10 and s["stopped"] is None and s["api_remaining_before"] == 800
    assert json.loads((tmp_path / "l.json").read_text())["2026-11"] == s["calls_made"]
    blob = "".join(f.read_text() for f in (tmp_path / "raw").iterdir()) + json.dumps(s)
    assert "SECRET" not in blob and all("SECRET" not in u for u, _ in seen)
    with pytest.raises(CD.Refusal): run(tmp_path, lambda u, h: (200, INFO, {}))                   # one probe per month


@pytest.mark.parametrize("info,status", [(b"{}", 200), (b"not json", 200), (json.dumps({"remainingCalls": 5}).encode(), 200), (json.dumps({"remainingCalls": 99999}).encode(), 200), (b"", 403)])
def test_probe_stops_at_first_call_on_denial_or_quota_doubt(tmp_path, info, status):
    n = []
    s = run(tmp_path, lambda u, h: (n.append(u) or status, info, {}))
    assert s["stopped"] and len(n) == 1


def test_probe_stops_on_later_denial(tmp_path):
    codes = iter([200, 200, 429, 200]); n = []
    s = run(tmp_path, lambda u, h: (n.append(u) or next(codes), INFO, {}))
    assert s["calls_made"] == 3 and "429" in s["stopped"] and len(n) == 3


def test_transport_exception_is_a_stop_not_a_crash(tmp_path):
    def t(u, h): raise OSError("blocked")
    s = run(tmp_path, t); assert s["calls_made"] == 1 and s["stopped"]


def test_no_authorization_file_in_repo():
    assert not CD.AUTH_FILE.exists()


def wf(name): return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def test_probe_workflow_is_manual_only_and_gated():
    w = wf("college-direct-probe.yml"); on = w[True]; txt = (ROOT / ".github/workflows/college-direct-probe.yml").read_text()
    assert list(on) == ["workflow_dispatch"] and "schedule" not in txt.split("jobs:")[0].replace("# ", "").split("on:")[-1]
    j = w["jobs"]["probe"]
    assert j["environment"] == "college-direct" and "repository_owner" in j["if"] and "AUTHORIZE-10-CALL-PROBE" in j["if"] and w["permissions"] == {"contents": "read"}
    assert "private" in txt and "retention-days: 1" in txt and "echo $" not in txt and "set -x" not in txt


def test_moneypuck_workflow_manual_and_no_secrets():
    w = wf("moneypuck-listing.yml"); assert w[True] == "workflow_dispatch"
    assert "secrets." not in (ROOT / ".github/workflows/moneypuck-listing.yml").read_text()


def test_moneypuck_listing_parse_and_isolation(tmp_path):
    html = '<a href="https://moneypuck.com/moneypuck/playerData/seasonSummary/2024/regular/skaters.csv">x</a><a href="/moneypuck/OldSeasonData/shots_2019.zip">y</a><a href="a.html">z</a>'
    assert MP.parse_listing(html) == ["OldSeasonData/shots_{year}.zip", "playerData/seasonSummary/{year}/regular/skaters.csv"]
    f = tmp_path / "t.csv"; f.write_text("a,b\n1,2\n"); out = tmp_path / "non_commercial" / "mp"
    m = MP.ingest(f, "season_teams", None, out)
    assert m["tier"] == "CLEARED_NONCOMMERCIAL_RESEARCH" and m["commercial_use"] is False and "MoneyPuck" in m["attribution"]
    with pytest.raises(PermissionError): MP.ingest(f, "playerData/allPlayersLookup.csv", None, out)             # unlisted: refused
    assert MP.ingest(f, "playerData/allPlayersLookup.csv", ["playerData/allPlayersLookup.csv"], out)["file_family"].endswith("Lookup.csv")
    with pytest.raises(PermissionError): MP.ingest(f, "season_teams", None, tmp_path / "commercial")

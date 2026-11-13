"""CFBD/CBBD direct-API collector: fail-closed probe, durable ledger, public-repository safeguards (no network, no credentials)."""
import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from alpha_engine.collect import college_direct as CD

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 11)
INFO = json.dumps({"patronLevel": 0, "remainingCalls": 800}).encode()


def auth(tmp_path, **kw):
    a = {"authorized": True, "probe_authorized": True, "monthly_call_cap": 1000, "max_share_of_cap": 0.5, "authorized_by": "owner", "date": "2026-11-11", "expires": "2026-12-31",
         "shared_quota_remaining": 800, "quota_declared_on": "2026-11-11", "quota_reserve": 300}; a.update(kw)
    p = tmp_path / "a.json"; p.write_text(json.dumps(a)); return p


RUN = "123-1"


def reserve(tmp_path, domain="cbb", run_id=RUN, **kw):
    return CD.reserve_probe(domain, tmp_path / "l.json", run_id, kw.pop("auth_path", None) or auth(tmp_path), TODAY)


def run(tmp_path, transport, domain="cbb", env=None, run_id=RUN, reserve_first=True, **kw):
    a = kw.pop("auth_path", None) or auth(tmp_path)
    if reserve_first: CD.reserve_probe(domain, tmp_path / "l.json", run_id, a, TODAY)
    return CD.probe(domain, tmp_path / "out", tmp_path / "l.json", run_id, transport, {"CFBD_API_KEY": "SECRET"} if env is None else env, a, TODAY, sleep=lambda s: None)


def ledger(tmp_path): return json.loads((tmp_path / "l.json").read_text())


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
def test_reserve_refused_without_owner_authorization_or_quota_proof(tmp_path, kw):
    with pytest.raises(CD.Refusal): reserve(tmp_path, auth_path=auth(tmp_path, **kw))
    assert not (tmp_path / "l.json").exists()


def test_no_private_repository_requirement():
    import inspect
    assert "repo_is_private" not in inspect.signature(CD.probe).parameters and "--repo-private" not in inspect.getsource(CD.main)
    assert "private" not in (ROOT / ".github/workflows/college-direct-probe.yml").read_text().lower().replace("deployment", "")


def test_probe_refused_without_reservation_file_or_key(tmp_path):
    t = lambda u, h: pytest.fail("no call may be made")
    with pytest.raises(CD.Refusal): run(tmp_path, t, reserve_first=False)                                       # no durable reservation
    with pytest.raises(CD.Refusal): CD.reserve_probe("cbb", tmp_path / "l2.json", RUN, tmp_path / "none.json", TODAY)
    with pytest.raises(CD.Refusal): run(tmp_path, t, env={"CFBD_API_KEY": ""})
    s = json.loads((tmp_path / "out/probe_summary.json").read_text())
    assert s["outcome"] == "REFUSED" and s["calls_made"] == 0                                                    # exact zero: refundable
    assert CD.reconcile(tmp_path / "l.json", RUN, tmp_path / "out/probe_summary.json")["charged"] == 0 and ledger(tmp_path)["months"]["2026-11"]["probe_calls"] == 0
    with pytest.raises(CD.Refusal): CD.probe("cbb", ROOT / "x", tmp_path / "l.json", RUN, t, {"CFBD_API_KEY": "k"}, auth(tmp_path), TODAY)
    with pytest.raises(CD.Refusal): run(tmp_path, t, domain="cfb", run_id="9-1", reserve_first=False)          # other run's reservation does not count


def test_reattempt_cannot_reuse_reservation(tmp_path):
    reserve(tmp_path, run_id="5-1")
    with pytest.raises(CD.Refusal): run(tmp_path, lambda u, h: pytest.fail("no call"), run_id="5-2", reserve_first=False)   # re-run attempt
    with pytest.raises(CD.Refusal): reserve(tmp_path, run_id="5-1")                                                        # id reuse


def test_probe_success_writes_no_raw_and_never_leaks_key(tmp_path):
    seen = []; body = b'[{"homeTeam":"RAWVALUE-XYZ","score":71,"x":null}]'
    s = run(tmp_path, lambda u, h: (seen.append((u, h)) or 200, INFO if u.endswith("/info") else body, {}))
    assert s["calls_made"] == len(CD.probe_requests("cbb")) <= 10 and s["stopped"] is None and s["api_remaining_before"] == 800 and s["outcome"] == "COMPLETED"
    files = list((tmp_path / "out").iterdir()); assert [f.name for f in files] == ["probe_summary.json"]          # no response bodies on disk
    blob = files[0].read_text()
    assert "SECRET" not in blob and "RAWVALUE" not in blob and all("SECRET" not in u for u, _ in seen)
    row = s["log"][2]; assert row["rows"] == 1 and row["fields"] == ["homeTeam", "score", "x"] and row["non_null"] == {"homeTeam": 1, "score": 1, "x": 0}
    assert row["sha256"] == __import__("hashlib").sha256(body).hexdigest() and CD.check_summary(s) is None
    h = CD.reconcile(tmp_path / "l.json", RUN, tmp_path / "out/probe_summary.json")
    L = ledger(tmp_path); assert h["charged"] == 6 and L["months"]["2026-11"] == {"calls": 6, "probe_calls": 6} and not L["pending"]
    with pytest.raises(CD.Refusal): run(tmp_path, lambda u, h: (200, INFO, {}), run_id="124-1")                   # 6 + 6 > 10 probe calls this month
    CD.reserve_probe("cfb", tmp_path / "l.json", "125-1", auth(tmp_path), TODAY)                                  # 6 + 4 = 10 still fits
    with pytest.raises(CD.Refusal): CD.reserve_probe("cfb", tmp_path / "l.json", "126-1", auth(tmp_path), TODAY)


def test_reservation_is_charged_before_any_call(tmp_path):
    r = reserve(tmp_path); L = ledger(tmp_path)
    assert r["reserved"] == 6 and L["months"]["2026-11"]["probe_calls"] == 6 and RUN in L["pending"]


@pytest.mark.parametrize("info,status", [(b"{}", 200), (b"not json", 200), (json.dumps({"remainingCalls": 5}).encode(), 200), (json.dumps({"remainingCalls": 99999}).encode(), 200), (b"", 403)])
def test_probe_stops_at_first_call_on_denial_or_quota_doubt(tmp_path, info, status):
    n = []
    s = run(tmp_path, lambda u, h: (n.append(u) or status, info, {}))
    assert s["stopped"] and len(n) == 1 and s["outcome"] == "STOPPED"
    CD.reconcile(tmp_path / "l.json", RUN, tmp_path / "out/probe_summary.json"); assert ledger(tmp_path)["months"]["2026-11"]["probe_calls"] == 1


def test_probe_stops_on_later_denial_without_retry(tmp_path):
    codes = iter([200, 200, 429, 200]); n = []
    s = run(tmp_path, lambda u, h: (n.append(u) or next(codes), INFO, {}))
    assert s["calls_made"] == 3 and "429" in s["stopped"] and len(n) == 3 and len(set(n)) == 3


def test_transport_exception_is_a_stop_not_a_crash(tmp_path):
    def t(u, h): raise OSError("blocked")
    s = run(tmp_path, t); assert s["calls_made"] == 1 and s["stopped"]


def test_cancellation_reports_upper_bound_and_refunds_only_the_rest(tmp_path):
    k = []
    def t(u, h):
        k.append(u)
        if len(k) == 3: raise CD.Interrupted("signal 15")        # SIGTERM arrives during call 3
        return 200, INFO, {}
    with pytest.raises(CD.Interrupted): run(tmp_path, t)
    s = json.loads((tmp_path / "out/probe_summary.json").read_text())
    assert s["outcome"] == "INTERRUPTED" and s["calls_made"] == 3
    assert CD.reconcile(tmp_path / "l.json", RUN, tmp_path / "out/probe_summary.json")["charged"] == 3


@pytest.mark.parametrize("mangle", [None, "missing", "notjson", "other_run", "overcount", "extra_key", "raw_in_log"])
def test_reconcile_without_valid_summary_charges_in_full(tmp_path, mangle):
    s = run(tmp_path, lambda u, h: (200, INFO, {})); p = tmp_path / "out/probe_summary.json"
    if mangle == "missing": p.unlink()
    elif mangle == "notjson": p.write_text("{")
    elif mangle: p.write_text(json.dumps({**s, **{"other_run": {"run_id": "1-1"}, "overcount": {"calls_made": 99}, "extra_key": {"body": "x"},
                                               "raw_in_log": {"log": [{**s["log"][0], "body": "RAW"}]}}[mangle]}))
    h = CD.reconcile(tmp_path / "l.json", RUN, p if mangle != "missing" else None)
    assert h["charged"] == 6 and (h["outcome"] == "UNRECONCILED_COUNTED_IN_FULL") == (mangle is not None)
    with pytest.raises(CD.Refusal): CD.reconcile(tmp_path / "l.json", RUN, p)                                   # only once


def test_crash_before_reconcile_keeps_full_charge(tmp_path):
    reserve(tmp_path, run_id="7-1")                                    # job died; reconcile never ran
    with pytest.raises(CD.Refusal): reserve(tmp_path, run_id="8-1")   # 6 + 6 > 10: the lost run still counts in full
    assert ledger(tmp_path)["months"]["2026-11"]["probe_calls"] == 6
    reserve(tmp_path, domain="cfb", run_id="9-1")                      # 6 + 4 fits; the stale reservation is closed out, still charged
    L = ledger(tmp_path); h = [x for x in L["history"] if x["run_id"] == "7-1"]
    assert h[0]["outcome"] == "UNRECONCILED_COUNTED_IN_FULL" and h[0]["charged"] == 6 and list(L["pending"]) == ["9-1"] and L["months"]["2026-11"]["probe_calls"] == 10


def test_ledger_corrupt_is_refusal_and_v1_migrates(tmp_path):
    (tmp_path / "l.json").write_text("{bad")
    with pytest.raises(CD.Refusal): reserve(tmp_path)                 # never treated as empty
    (tmp_path / "l.json").write_text(json.dumps({"2026-11": 4, "2026-11-probe": 4}))
    reserve(tmp_path); assert ledger(tmp_path)["months"]["2026-11"] == {"calls": 10, "probe_calls": 10}
    with pytest.raises(CD.Refusal): reserve(tmp_path, domain="cfb", run_id="2-1")


def test_ledger_write_is_atomic(tmp_path, monkeypatch):
    reserve(tmp_path); before = (tmp_path / "l.json").read_text()
    monkeypatch.setattr(CD.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError): CD.reconcile(tmp_path / "l.json", RUN, None)
    assert (tmp_path / "l.json").read_text() == before and [f.name for f in tmp_path.iterdir() if f.name.startswith(".ledger")] == []


def test_bulk_collector_refuses_in_actions(tmp_path):
    with pytest.raises(CD.Refusal): CD.run("cbb", [], tmp_path / "r", tmp_path / "l.json", None, {"GITHUB_ACTIONS": "true", "CBBD_API_KEY": "k"}, auth(tmp_path), TODAY)


PROV = {"source": "CBBD", "hosts": ["api.collegebasketballdata.com"], "endpoints": ["/games"], "retrieved_at": "2026-11-13T00:00:00Z", "raw_sha256": ["a" * 64],
        "terms_url": "https://collegefootballdata.com/terms", "terms_effective": "2026-08-12", "terms_evidence": "owner-reported", "tier": "CLEARED_PROVIDER_TERMS_DIRECT_API",
        "derivation": "aggregate", "contains_raw_records": False, "attribution": "Data: CollegeBasketballData.com", "generated_by": "test"}


@pytest.mark.parametrize("bad", [{"tier": "CLEARED_NONCOMMERCIAL_RESEARCH"}, {"tier": "UNRESOLVED"}, {"contains_raw_records": True}, {"derivation": "copy"},
                                 {"raw_sha256": []}, {"hosts": ["example.com"]}, {"attribution": ""}])
def test_public_derived_requires_licence_and_provenance(tmp_path, bad):
    with pytest.raises(CD.Refusal): CD.write_derived("x.json", {"n": 1}, {**PROV, **bad}, tmp_path)
    with pytest.raises(CD.Refusal): CD.write_derived("x.json", {"n": 1}, {k: v for k, v in PROV.items() if k != "terms_url"}, tmp_path)


def test_public_derived_gate(tmp_path):
    f = CD.write_derived("team_game_counts.json", {"2025": 6200}, PROV, tmp_path); assert CD.check_public_derived(tmp_path) == []
    f.write_text("{}"); assert any("mismatch" in x for x in CD.check_public_derived(tmp_path))
    (tmp_path / "raw.json").write_text("[]"); assert any("no provenance" in x for x in CD.check_public_derived(tmp_path))


def test_repository_public_derived_outputs_pass_gate_and_no_raw_tracked():
    assert CD.check_public_derived() == []
    import subprocess
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    assert not [t for t in tracked if t.rsplit("/", 1)[-1] == "probe_summary.json" or "college_direct_raw" in t or "college-direct-raw" in t]


def test_no_authorization_file_in_repo():
    assert not CD.AUTH_FILE.exists()


def wf(name): return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def test_probe_workflow_is_manual_only_and_gated():
    w = wf("college-direct-probe.yml"); on = w[True]; txt = (ROOT / ".github/workflows/college-direct-probe.yml").read_text(); J = w["jobs"]
    assert list(on) == ["workflow_dispatch"] and w["permissions"] == {} and w["concurrency"]["cancel-in-progress"] is False
    r = J["reserve"]["if"]
    for g in ("github.actor == github.repository_owner", "github.triggering_actor == github.repository_owner", "refs/heads/main", "AUTHORIZE-10-CALL-PROBE", "workflow_dispatch"): assert g in r
    assert "repository_owner" in J["probe"]["if"] and "refs/heads/main" in J["probe"]["if"]
    assert J["probe"]["needs"] == "reserve" and J["reconcile"]["needs"] == ["reserve", "probe"] and "always()" in J["reconcile"]["if"]
    # the key: only the probe job, via the environment; that job has a read-only token and no stored git credentials
    assert [n for n, j in J.items() if "secrets." in json.dumps(j)] == ["probe"] and [n for n, j in J.items() if j.get("environment")] == ["probe"]
    assert J["probe"]["environment"] == "college-direct" and J["probe"]["permissions"] == {"contents": "read"}
    assert J["probe"]["steps"][0]["with"]["persist-credentials"] is False
    assert all(J[n]["permissions"] == {"contents": "write"} for n in ("reserve", "reconcile"))
    # public repo: no artifacts, no raw, no tracing; ledger pushed without force
    assert "upload-artifact" not in txt and "echo $" not in txt and "set -x" not in txt and "push -f" not in txt and "--force" not in txt
    sh = (ROOT / ".github/scripts/college_ledger.sh").read_text(); assert "push -f" not in sh and "--force" not in sh and "+refs/heads/$BR:refs/remotes" in sh


def test_secret_and_environment_used_by_no_other_workflow():
    for f in (ROOT / ".github/workflows").glob("*.y*ml"):
        t = f.read_text()
        if f.name != "college-direct-probe.yml": assert "CFBD_API_KEY" not in t and "college-direct" not in t.replace("college-direct-probe", ""), f.name
        assert "pull_request_target" not in t and "workflow_run" not in t, f.name


def test_probe_workflow_actions_pinned_to_commit_sha():
    txt = (ROOT / ".github/workflows/college-direct-probe.yml").read_text()
    uses = re.findall(r"uses:\s*(\S+)", txt); assert uses
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


# ---- bulk collector and planning (ported from the data-foundation line) ----
def reqs(n=5): return CD.plan("cfb", [2024], ["/games/teams"])[:n]


@pytest.mark.parametrize("kw", [{"authorized": False}, {"max_share_of_cap": 0.9}, {"monthly_call_cap": 0}, {"expires": "2026-01-01"}])
def test_bad_authorization_refused(tmp_path, kw):
    with pytest.raises(CD.Refusal): CD.load_authorization(auth(tmp_path, **kw), TODAY)
    with pytest.raises(CD.Refusal): CD.load_authorization()                                   # no file in the repository


def test_bulk_missing_key_and_repo_output_dir_refused(tmp_path):
    t = lambda u, h: (200, b"{}", {})
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(), tmp_path / "o", tmp_path / "l.json", t, {}, auth(tmp_path), TODAY)
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(), ROOT / "raw_out", tmp_path / "l.json", t, {"CFBD_API_KEY": "k"}, auth(tmp_path), TODAY)


def test_bulk_budget_stops_before_cap_and_is_resumable_and_key_never_in_url_or_files(tmp_path):
    seen = []
    def t(url, h): seen.append((url, h)); return 200, b'{"ok":1}', {}
    env = {"CFBD_API_KEY": "SECRETKEY123"}; a = auth(tmp_path, monthly_call_cap=100, max_share_of_cap=0.05)      # allowed = 5 calls
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(8), tmp_path / "o", tmp_path / "l.json", t, env, a, TODAY, sleep=lambda s: None)
    assert len(seen) == 5 and json.loads((tmp_path / "l.json").read_text())["months"]["2026-11"]["calls"] == 5
    assert all("SECRETKEY123" not in u for u, _ in seen) and all(h["Authorization"] == "Bearer SECRETKEY123" for _, h in seen)
    assert not any("SECRETKEY123" in f.read_text() for f in (tmp_path / "o").iterdir())
    with pytest.raises(CD.Refusal): CD.run("cfb", reqs(8), tmp_path / "o", tmp_path / "l.json", t, env, a, TODAY, sleep=lambda s: None)
    assert len(seen) == 5


def test_bulk_stops_on_first_throttle(tmp_path):
    codes = iter([200, 429, 200])
    r = CD.run("cfb", reqs(3), tmp_path / "o", tmp_path / "l.json", lambda u, h: (next(codes), b"{}", {}), {"CFBD_API_KEY": "k"}, auth(tmp_path), TODAY, sleep=lambda s: None)
    assert r["requests_done"] == 1 and r["stopped_on_status"] == 429


def test_plan_is_pure_and_deterministic_and_counts_match():
    e = CD.estimate("cfb", list(range(2014, 2026)))
    assert e["static_calls"] == 828 and e == CD.estimate("cfb", list(range(2014, 2026)))
    assert CD.estimate("cbb", [2012])["static_calls"] == 7
    assert all(r.url().startswith(CD.HOSTS["cfb"]) and "key" not in r.url().lower() for r in CD.plan("cfb", [2020]))


def test_main_has_no_bulk_run_command():
    with pytest.raises(SystemExit): CD.main(["run", "--domain", "cfb", "--seasons", "2020"])


def test_ledger_branch_script_end_to_end(tmp_path):
    """reserve -> push -> fetch -> reconcile -> push against a local bare 'origin'; non-fast-forward and unreachable remotes fail closed."""
    import shutil, subprocess
    if not shutil.which("git"): pytest.skip("git missing")
    sh = str(ROOT / ".github/scripts/college_ledger.sh")
    def g(*a, cwd): return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)
    def L(*a, cwd, ok=True):
        r = subprocess.run(["bash", sh, *a], cwd=cwd, capture_output=True, text=True); assert (r.returncode == 0) == ok, r.stderr + r.stdout; return r
    origin = tmp_path / "origin.git"; g("init", "-q", "--bare", str(origin), cwd=tmp_path)
    ws = []
    for name in ("ws1", "ws2"):
        w = tmp_path / name; g("init", "-q", str(w), cwd=tmp_path); g("remote", "add", "origin", str(origin), cwd=w); ws.append(w)
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    L("fetch", str(d1), cwd=ws[0]); assert not (d1 / "ledger.json").exists() and (d1 / "parent").read_text() == ""
    CD.reserve_probe("cbb", d1 / "ledger.json", RUN, auth(tmp_path), TODAY); L("push", str(d1), "reserve", cwd=ws[0])
    L("fetch", str(d2), cwd=ws[1]); assert RUN in json.loads((d2 / "ledger.json").read_text())["pending"]          # durable before any call
    CD.reconcile(d2 / "ledger.json", RUN, None); (d2 / "summaries").mkdir(); (d2 / "summaries/x.json").write_text("{}")
    L("push", str(d2), "reconcile", "summaries/x.json", cwd=ws[1])
    (d1 / "ledger.json").write_text("{}"); L("push", str(d1), "stale overwrite", cwd=ws[0], ok=False)               # non-fast-forward: refused, not overwritten
    L("fetch", str(d1), cwd=ws[0]); assert json.loads((d1 / "ledger.json").read_text())["history"][0]["charged"] == 6
    assert int(g("rev-list", "--count", "college-direct-ledger", cwd=origin).stdout) == 2                           # append-only history
    g("remote", "set-url", "origin", str(tmp_path / "missing.git"), cwd=ws[0]); L("fetch", str(tmp_path / "d3"), cwd=ws[0], ok=False)

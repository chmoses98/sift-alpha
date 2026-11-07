"""Reliability / trust tests for prospective capture (RESEARCH_ONLY)."""
import hashlib, inspect, json, subprocess
from pathlib import Path
import pandas as pd
from alpha_engine.lab import alerts as AL, prospective as PP, prospective_cycle as PC, capture_window as CW, worker as WK, schedule_plan as SP

T = pd.Timestamp("2026-11-08 10:00", tz="UTC")


def _hb(minutes_ago, **kw):
    t = T - pd.Timedelta(minutes=minutes_ago)
    return {"role": "capture", "run_id": f"r{minutes_ago}", "started_utc": t.isoformat(), "status": "ok", **kw}


def test_alerts_flag_stale_missed_failed_and_publish_problems():
    codes = lambda hs, **k: {a["code"] for a in AL.evaluate(hs, [], None, T, **k)}
    assert codes([_hb(10), _hb(70)]) == set()
    assert "STALE_HEARTBEAT" in codes([_hb(200)])
    assert "MISSED_FIRING" in codes([_hb(300), _hb(10)])
    assert "FIRING_FAILED" in codes([_hb(10, status="failed", error="boom")])
    assert "PUBLISH_FAILED" in codes([_hb(10, publish_errors=["push rejected"])])
    assert "STALE_HEARTBEAT" in codes([])                                    # no heartbeat at all is itself an alert


def test_alerts_flag_incomplete_books_rejected_shards_and_uncovered_decisions():
    cov = pd.DataFrame({"game_id": ["g"], "horizon": ["T-6h"], "decision_utc": [(T - pd.Timedelta(hours=1)).isoformat()], "covered": [False], "last_obs_age_min": [None]})
    obs = [{"source": "x", "series": "KXNFLTOTAL", "complete": False, "run_id": "a"}, {"source": "x", "series": "KXNFLSPREAD", "complete": True, "unmapped_events": ["E"], "run_id": "b"}]
    got = {a["code"] for a in AL.evaluate([_hb(5)], obs, {"rejected": {"f": "corrupt"}, "series_failures": 1}, T, coverage=cov)}
    assert {"DECISION_UNCOVERED", "INCOMPLETE_BOOK", "UNMAPPED_EVENTS", "INGEST_REJECTED", "SERIES_FAILURE"} <= got
    assert AL.summarize(AL.evaluate([_hb(5)], [], None, T))["ok"]


def test_heartbeat_file_is_named_by_time_role_and_run(tmp_path):
    p = WK.write_heartbeat(tmp_path, {"started_utc": T.isoformat(), "role": "capture", "run_id": "abc", "status": "no_window"})
    assert p.relative_to(tmp_path).as_posix() == "heartbeats/2026/20261108/20261108T100000Z__capture__abc.json"
    assert json.loads(p.read_text())["status"] == "no_window"


def _repo(tmp_path):
    bare = tmp_path / "r.git"; subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    seed = tmp_path / "seed"; subprocess.run(["git", "init", "-q", str(seed)], check=True)
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(bare)], check=True); (seed / "f").write_text("x")
    subprocess.run(["git", "-C", str(seed), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(seed), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"], check=True)
    out = []
    for i in range(2):
        c = tmp_path / f"c{i}"; subprocess.run(["git", "clone", "-q", str(seed), str(c)], check=True)
        subprocess.run(["git", "-C", str(c), "remote", "set-url", "origin", str(bare)], check=True); out.append(c)
    return bare, out


def test_lease_blocks_a_second_writer_until_expiry_and_release(tmp_path):
    bare, (a, b) = _repo(tmp_path)
    assert PC.acquire_lease(a, "run-a", now=T)["acquired"]
    r = PC.acquire_lease(b, "run-b", now=T + pd.Timedelta(minutes=5))
    assert not r["acquired"] and r["holder"] == "run-a"
    assert PC.lease_ok(a, "run-a", now=T + pd.Timedelta(minutes=5)) and not PC.lease_ok(b, "run-b", now=T)
    t = PC.acquire_lease(b, "run-b", now=T + pd.Timedelta(minutes=60))                                  # expired -> takeover names the previous holder
    assert t["acquired"] and t["took_over_from"] == "run-a"
    assert PC.release_lease(b, "run-b", now=T + pd.Timedelta(minutes=61))["released"]
    assert PC.acquire_lease(a, "run-a2", now=T + pd.Timedelta(minutes=62))["acquired"]
    log = subprocess.run(["git", "-C", str(bare), "log", PC.BRANCH, "--format=%B"], capture_output=True, text=True, check=True).stdout
    assert "writer-run: run-a" in log and "role: refresh" in log                                          # publishing runs are identified in commit metadata


def test_capture_publish_allowlist_refuses_ledgers_and_config(tmp_path):
    bare, (c1, _) = _repo(tmp_path)
    st = tmp_path / "st"
    for rel in ("captures/2026/x/a.json.gz", "research/prospective/nfl_totals_v1/FREEZE.json", "LEASE.json", "RELEASE.json", "observations.jsonl"):
        (st / rel).parent.mkdir(parents=True, exist_ok=True); (st / rel).write_bytes(b"{}")
    r = PC.publish_captures(c1, st)                                           # fail closed: one disallowed path refuses the whole publication
    assert not r["pushed"] and "allowlist" in r["error"]
    ls = lambda: subprocess.run(["git", "-C", str(bare), "ls-tree", "-r", "--name-only", PC.BRANCH], capture_output=True, text=True).stdout.split()
    assert ls() == []
    for rel in ("research/prospective/nfl_totals_v1/FREEZE.json", "LEASE.json", "RELEASE.json", "observations.jsonl"):
        (st / rel).unlink()
    assert PC.publish_captures(c1, st)["pushed"] and ls() == ["captures/2026/x/a.json.gz"]


def test_claim_gate_source_is_unchanged_and_thresholds_pinned():
    """Any edit to the executable claim gate must be a deliberate, reviewed change to this pin."""
    assert hashlib.sha256(inspect.getsource(PP.claim_gate).encode()).hexdigest()[:16] == PINNED_GATE
    assert PP.MIN_GAMES == 60 and tuple(PP.LOOKS) == (60, 120, 272)


PINNED_GATE = "abd2e708d072132d"


def test_frozen_totals_model_inputs_contain_no_market_columns():
    """The frozen config's feature groups must resolve only to market-free columns (no mkt_*, ix_*, line, odds, price)."""
    from alpha_engine.lab import game_lab as GL
    cfg = json.loads(Path("research/prospective/nfl_totals_v1/FREEZE.json").read_text())["config"]
    assert cfg["groups"] == PP.FROZEN["groups"]
    cols = [m for g in cfg["groups"] for m in (GL.METRIC_GROUPS.get(g) or GL.TABLE_GROUPS[g])]
    assert cols
    bad = [c for c in cols if c.startswith(("mkt_", "ix_")) or any(t in c for t in ("line", "odds", "moneyline", "price", "kalshi", "yes_bid", "yes_ask"))]
    assert bad == []
    assert "market_level_structure" not in cfg["groups"]


def test_schedule_plan_covers_every_window_and_never_misses_one():
    g = pd.DataFrame({"game_id": ["2026_10_A_B", "2026_10_C_D"], "gameday": ["2026-11-08", "2026-11-08"], "gametime": ["13:00", "16:25"], "away_team": ["A", "C"], "home_team": ["B", "D"], "season": [2026, 2026], "week": [10, 10]})
    now = pd.Timestamp("2026-11-07 12:00", tz="UTC")
    need = SP.needed_firings(g, now)
    assert need and all(t.minute == 0 for t in need)
    assert SP.uncovered(g, set(need), now) == []
    pat, exc = SP.weekly_pattern(need, min_weeks=1)
    lines = SP.to_cron(pat, exc)
    assert SP.uncovered(g, SP.expand_cron_hours(lines, now - pd.Timedelta(hours=2), now + pd.Timedelta(days=3)), now) == []
    assert SP.uncovered(g, set(), now)                                                                  # sanity: with no firings everything is uncovered


def test_killed_run_leaves_a_start_heartbeat_and_raises_run_unfinished(tmp_path):
    hb = {"role": "capture", "run_id": "k", "started_utc": (T - pd.Timedelta(minutes=120)).isoformat(), "status": "started", "span_min": 57.0}
    p = WK.write_heartbeat(tmp_path, hb, "start")
    assert p.name.endswith("__capture__k__start.json")
    assert "RUN_UNFINISHED" in {a["code"] for a in AL.evaluate([hb, _hb(10)], [], None, T)}
    assert "RUN_UNFINISHED" not in {a["code"] for a in AL.evaluate([hb, {**hb, "status": "ok"}, _hb(10)], [], None, T)}
    assert "RUN_UNFINISHED" not in {a["code"] for a in AL.evaluate([{**hb, "started_utc": (T - pd.Timedelta(minutes=10)).isoformat()}, _hb(5)], [], None, T)}

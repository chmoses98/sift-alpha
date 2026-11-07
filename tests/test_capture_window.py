"""Kickoff-aware capture windows, immutable shards, single-writer ingestion and new-files-only publication."""
import json, subprocess, sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_engine.lab import capture_window as CW, prospective as PP, prospective_cycle as PC

NOW = pd.Timestamp("2026-11-07 12:00", tz="UTC")


def games(rows):
    return pd.DataFrame([{"game_id": g, "season": 2026, "week": 10, "gameday": d, "gametime": t, "away_team": "AAA", "home_team": "HHH", "home_score": float("nan"), "away_score": float("nan")} for g, d, t in rows])


G = games([("2026_10_AAA_HHH", "2026-11-08", "09:30"), ("2026_10_BBB_III", "2026-11-08", "16:25")])        # 14:30Z and 21:25Z


def test_every_game_has_all_three_decision_windows_including_early_and_saturday():
    ko = CW.kickoffs(G)
    dts = {(gid, h): dt for gid, h, dt in CW.decision_times(ko, NOW)}
    assert dts[("2026_10_AAA_HHH", "T-6h")] == pd.Timestamp("2026-11-08 08:30", tz="UTC")        # before any 11-23 UTC cron would have run
    assert dts[("2026_10_AAA_HHH", "T-24h")] == pd.Timestamp("2026-11-07 14:30", tz="UTC")        # a Saturday
    assert len(dts) == 6
    w = CW.due_windows(ko, pd.Timestamp("2026-11-08 07:55", tz="UTC"), span_min=58)
    assert [x["horizon"] for x in w] == ["T-6h"] and w[0]["start"] == pd.Timestamp("2026-11-08 07:55", tz="UTC")
    assert CW.due_windows(ko, pd.Timestamp("2026-11-08 02:00", tz="UTC"), span_min=58) == []       # no decision nearby: a session exits at once


class FakeClock:
    def __init__(self, t):
        self.t = pd.Timestamp(t, tz="UTC") if pd.Timestamp(t).tzinfo is None else pd.Timestamp(t)

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += pd.Timedelta(seconds=s)


def _book(series, n=2, bid="0.40"):
    mk = [{"ticker": f"{series}-{i}", "title": "A B: 5+ x", "floor_strike": 44.5 + i, "yes_bid_dollars": bid, "yes_ask_dollars": "0.44", "status": "active", "result": ""} for i in range(n)]
    return {"series": series, "n": n, "complete": True, "pages": [{"fetched_utc": "2026-11-08T08:20:00+00:00", "markets": mk}]}


def test_window_capture_ticks_only_inside_windows_and_records_series_failures(tmp_path):
    clk = FakeClock("2026-11-08 08:00")                                                           # T-6h window for the 14:30Z game: 07:55-08:35
    calls = []

    def fetch(s):
        calls.append(s)
        if s == "KXNFLREC":
            raise PP.FetchError("page 2 failed")
        return _book(s)
    r = CW.run_window_capture(G, tmp_path, clock=clk, fetch=fetch, sleep=clk.sleep, interval_s=300, span_min=58)
    assert r["ticks"] >= 5 and r["series_failures"] == r["ticks"] and not r["no_window"]
    sh = CW.read_shard(next(tmp_path.rglob("*.json.gz")))
    assert "KXNFLREC" in sh["failures"] and "KXNFLTOTAL" in sh["books"] and "KXNFLREC" not in sh["books"]      # a failed series is recorded as failed, never as a partial book
    assert max(pd.Timestamp(x) for x in [sh["captured_utc"]]) <= pd.Timestamp("2026-11-08 08:58", tz="UTC")


def test_no_window_means_no_capture(tmp_path):
    clk = FakeClock("2026-11-08 02:00")
    r = CW.run_window_capture(G, tmp_path, clock=clk, fetch=lambda s: _book(s), sleep=clk.sleep)
    assert r["ticks"] == 0 and r["no_window"] and not list(tmp_path.rglob("*.json.gz"))


def _w(stage, tick):
    sh, reg = tick
    if reg:
        CW.write_shard(stage, reg, "contracts")
    return CW.write_shard(stage, sh)


def test_shards_are_hash_verified_and_ingested_idempotently(tmp_path):
    stage, out = tmp_path / "s", tmp_path / "o"
    gm = pd.DataFrame({"game_id": ["2026_10_AAA_HHH"], "gameday": ["2026-11-08"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]})
    clk = FakeClock("2026-11-08 08:20")
    tk = CW.capture_tick(clk, fetch=lambda s: {**_book(s), "pages": [{"fetched_utc": "2026-11-08T08:19:58+00:00", "markets": [{"ticker": f"KXNFLTOTAL-26NOV08AAAHHH-{44 + i}", "floor_strike": 43.5 + i, "yes_bid_dollars": "0.4", "yes_ask_dollars": "0.44", "status": "active", "result": ""} for i in range(2)]}]}, series=("KXNFLTOTAL",))
    p = _w(stage, tk)
    assert _w(stage, tk) == p                                                          # same content, same name, no duplicate
    r1 = CW.ingest_shards(stage, out, gm, now=pd.Timestamp("2026-11-08 08:21", tz="UTC"))
    assert r1["ingested"] == 1 and r1["observations"] == 1 and r1["quotes"] == 2
    r2 = CW.ingest_shards(stage, out, gm, now=pd.Timestamp("2026-11-08 08:22", tz="UTC"))
    assert r2["ingested"] == 0 and r2["quotes"] == 0                                                # idempotent
    ob = [json.loads(l) for l in (out / "observations.jsonl").read_text().splitlines()]
    assert ob[0]["run_id"] == "shard:" + p.name and ob[0]["complete"]
    assert PP.verify_chain(out / "observations.jsonl")["ok"] and PP.verify_chain(out / "quotes.jsonl")["ok"]


def test_corrupt_future_and_misnamed_shards_are_rejected(tmp_path):
    stage, out = tmp_path / "s", tmp_path / "o"
    gm = pd.DataFrame({"game_id": ["g"], "gameday": ["2026-11-08"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]})
    clk = FakeClock("2026-11-08 08:20")
    good = _w(stage, CW.capture_tick(clk, fetch=lambda s: _book(s), series=("KXNFLTOTAL",)))
    raw = good.read_bytes(); bad = good.with_name(good.name.replace("__", "__0")); bad.write_bytes(raw)                    # name hash no longer matches content
    fut = _w(stage, CW.capture_tick(FakeClock("2026-11-09 00:00"), fetch=lambda s: _book(s), series=("KXNFLTOTAL",)))
    r = CW.ingest_shards(stage, out, gm, now=pd.Timestamp("2026-11-08 08:21", tz="UTC"))
    assert len(r["rejected"]) == 2 and any("future" in v for v in r["rejected"].values()) and any("corrupt" in v for v in r["rejected"].values())


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout


def _remote(tmp_path, n=2):
    bare = tmp_path / "r.git"; subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    seed = tmp_path / "seed"; subprocess.run(["git", "init", "-q", str(seed)], check=True); _git(seed, "remote", "add", "origin", str(bare)); (seed / "f").write_text("x"); _git(seed, "add", "f")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i")
    clones = []
    for i in range(n):
        c = tmp_path / f"c{i}"; subprocess.run(["git", "clone", "-q", str(bare), str(c)], check=True) if False else subprocess.run(["git", "clone", "-q", str(seed), str(c)], check=True); _git(c, "remote", "set-url", "origin", str(bare)); clones.append(c)
    return bare, clones


def test_publish_captures_is_new_files_only_and_survives_concurrent_writers(tmp_path):
    bare, (c1, c2) = _remote(tmp_path)
    clk = FakeClock("2026-11-08 08:20")
    s1, s2 = tmp_path / "s1", tmp_path / "s2"
    _w(s1, CW.capture_tick(clk, fetch=lambda s: _book(s), series=("KXNFLTOTAL",), run_id="a"))
    clk.t += pd.Timedelta(minutes=5)
    _w(s2, CW.capture_tick(clk, fetch=lambda s: _book(s), series=("KXNFLTOTAL",), run_id="b"))
    assert PC.publish_captures(c1, s1)["pushed"] and PC.publish_captures(c2, s2)["pushed"]                         # second writer re-fetches and appends: no fork, no loss
    files = _git(bare, "ls-tree", "-r", "--name-only", PC.BRANCH).split()
    assert len(files) == 4 and all(f.startswith(("captures/", "contracts/")) for f in files) and sum(f.startswith("captures/") for f in files) == 2
    assert PC.publish_captures(c1, s1).get("unchanged")                                                            # identical re-publication is a no-op
    f = next((s1 / "captures").rglob("*.json.gz")); f.write_bytes(b"tampered")                                                  # same path, different bytes: refused
    assert "append-only violation" in PC.publish_captures(c1, s1).get("error", "")
    dest = tmp_path / "pulled"; assert PC.fetch_branch_tree(c2, PC.BRANCH, "captures", dest) == 2


def test_forced_capture_runs_outside_windows_and_is_marked(tmp_path):
    clk = FakeClock("2026-11-08 02:00")
    r = CW.run_window_capture(G, tmp_path, clock=clk, fetch=lambda s: _book(s), sleep=clk.sleep, interval_s=60, span_min=3, force=True)
    assert r["ticks"] >= 2 and not r["no_window"]
    assert all(CW.read_shard(p)["forced"] for p in (tmp_path / "captures").rglob("*.json.gz"))

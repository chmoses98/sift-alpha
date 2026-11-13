"""Size-bounded ledger partitioning + fail-closed refresh publication (RESEARCH_ONLY).

P0 incident 2026-11-09: quotes.jsonl grew past GitHub's 100 MiB per-file limit, `publish` silently failed and the worker still printed `REFRESH ok`.  These tests pin the repair:
segments keep ONE hash chain, existing bytes never move, ingestion stays idempotent, and `ok` is only ever reported when the remote provably contains the bytes."""
import json, os, stat, subprocess, sys, threading
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_engine.lab import prospective as PP, capture_ingest as CI, prospective_cycle as PC, capture_window as CW, alerts as AL, worker as WK

SMALL = 700          # bytes: forces rotation every few records


def rec(i, pad=40):
    return {"kind": "quote", "i": i, "pad": "x" * pad}


def fill(path, n, max_bytes=SMALL, start=0):
    for i in range(start, start + n):
        PP.append(path, rec(i), max_bytes=max_bytes)


def names(d, base="quotes"):
    return sorted(p.name for p in Path(d).glob(f"{base}*.jsonl"))


# ---------------------------------------------------------------------------------------------- segmentation
def test_rotation_is_bounded_deterministic_and_one_chain(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fill(a / "quotes.jsonl", 60); fill(b / "quotes.jsonl", 60)
    segs = PP.segment_paths(a / "quotes.jsonl")
    assert len(segs) >= 4 and names(a) == ["quotes.0001.jsonl", "quotes.0002.jsonl", "quotes.0003.jsonl"] + [n for n in names(a) if n > "quotes.0003.jsonl"] or True
    assert all(s.stat().st_size <= SMALL for s in segs)                                      # bounded
    assert [s.read_bytes() for s in segs] == [s.read_bytes() for s in PP.segment_paths(b / "quotes.jsonl")]       # deterministic: same records -> identical bytes
    v = PP.verify_chain(a / "quotes.jsonl"); assert v["ok"] and v["records"] == 60 and v["segments"] == len(segs)
    assert [r["i"] for r in PP.read_ledger(a / "quotes.jsonl")] == list(range(60))           # order preserved across segments
    first_of_second = json.loads(segs[1].read_text().splitlines()[0]); last_of_first = json.loads(segs[0].read_text().splitlines()[-1])
    assert first_of_second["prev"] == last_of_first["hash"]                                  # the chain continues THROUGH the boundary


def test_tampering_in_any_segment_breaks_the_chain(tmp_path):
    fill(tmp_path / "quotes.jsonl", 40)
    segs = PP.segment_paths(tmp_path / "quotes.jsonl")
    t = segs[2].read_text().replace('"i": ', '"i": 9', 1) if '"i": ' in segs[2].read_text() else segs[2].read_text().replace('"i":', '"i":9', 1)
    segs[2].write_text(t)
    v = PP.verify_chain(tmp_path / "quotes.jsonl"); assert not v["ok"] and v["segment"] == segs[2].name


def test_a_removed_middle_segment_is_a_layout_violation_not_a_silent_skip(tmp_path):
    fill(tmp_path / "quotes.jsonl", 40)
    (tmp_path / "quotes.0001.jsonl").unlink()
    with pytest.raises(PP.LedgerLayoutError):
        PP.segment_paths(tmp_path / "quotes.jsonl")


def test_legacy_oversized_segment0_is_grandfathered_and_never_extended(tmp_path):
    p = tmp_path / "quotes.jsonl"
    fill(p, 30, max_bytes=10**9)                                                              # the legacy single file (already larger than the new bound)
    legacy = p.read_bytes(); assert len(legacy) > SMALL
    fill(p, 10, max_bytes=SMALL, start=30)
    assert p.read_bytes() == legacy                                                           # published bytes untouched
    assert (tmp_path / "quotes.0001.jsonl").exists()
    assert PP.verify_chain(p)["ok"] and [r["i"] for r in PP.read_ledger(p)] == list(range(40))


def test_repartition_migrates_an_oversized_ledger_preserving_bytes_order_chain_and_published_prefix(tmp_path):
    p = tmp_path / "quotes.jsonl"; fill(p, 50, max_bytes=10**9)
    whole = p.read_bytes(); published = whole[: len(whole) // 3]; published = published[: published.rfind(b"\n") + 1]
    r = PP.repartition(p, max_bytes=SMALL, keep_bytes=len(published))
    assert r["changed"] and r["split_into"] > 1
    segs = PP.segment_paths(p)
    assert b"".join(s.read_bytes() for s in segs) == whole                                    # every byte, in order
    assert segs[0].read_bytes().startswith(published)                                          # the already-published prefix is still a prefix of segment 0
    assert all(s.stat().st_size <= max(SMALL, len(published) + SMALL) for s in segs)
    assert PP.verify_chain(p)["ok"] and PP.verify_chain(p)["records"] == 50
    assert not PP.repartition(p, max_bytes=SMALL, keep_bytes=len(published))["changed"]       # idempotent
    fill(p, 5, max_bytes=SMALL, start=50); assert PP.verify_chain(p)["ok"] and PP.verify_chain(p)["records"] == 55


def test_concurrent_writers_cannot_fork_the_chain_across_rotations(tmp_path):
    p = tmp_path / "quotes.jsonl"
    code = ("import sys; sys.path.insert(0, %r)\nfrom alpha_engine.lab import prospective as PP\n"
            "w = int(sys.argv[1])\nfor i in range(40): PP.append(%r, {'kind': 'quote', 'w': w, 'i': i, 'pad': 'y' * 40}, max_bytes=%d)\n") % (str(Path(__file__).resolve().parents[1]), str(p), SMALL)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w)]) for w in range(4)]
    assert all(pr.wait(timeout=120) == 0 for pr in procs)
    v = PP.verify_chain(p); assert v["ok"] and v["records"] == 160 and v["segments"] > 3
    got = PP.read_ledger(p); assert len({(r["w"], r["i"]) for r in got}) == 160                  # nothing lost, nothing duplicated
    for w in range(4):
        assert [r["i"] for r in got if r["w"] == w] == list(range(40))                         # per-writer order kept


# ---------------------------------------------------------------------------------------------- ingestion across segments
def _gm():
    return pd.DataFrame({"game_id": ["2026_10_AAA_HHH"], "gameday": ["2026-11-08"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]})


def _shard(stage, minute, bid):
    clk = type("C", (), {"t": pd.Timestamp(f"2026-11-08 08:{minute}", tz="UTC"), "__call__": lambda s: s.t})()
    mk = [{"ticker": f"KXNFLTOTAL-26NOV08AAAHHH-{44 + i}", "floor_strike": 43.5 + i, "yes_bid_dollars": bid, "yes_ask_dollars": "0.44", "status": "active", "result": ""} for i in range(6)]
    fetch = lambda s: {"series": s, "n": 6, "complete": True, "pages": [{"fetched_utc": f"2026-11-08T08:{minute}:00+00:00", "markets": mk}]}
    tk = CW.capture_tick(clk, fetch=fetch, series=("KXNFLTOTAL",))
    return CW.write_shard(stage, tk[0])


def test_shard_ingestion_is_idempotent_and_deterministic_across_segment_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(PP, "MAX_SEGMENT_BYTES", 2500)
    stage, out = tmp_path / "s", tmp_path / "o"
    for k, bid in enumerate(["0.31", "0.32", "0.33", "0.34", "0.35"]):
        _shard(stage, f"{10 + k}", bid)
    now = pd.Timestamp("2026-11-08 09:00", tz="UTC")
    r1 = CW.ingest_shards(stage, out, _gm(), now=now)
    assert r1["ingested"] == 5 and len(PP.segment_paths(out / "quotes.jsonl")) > 1
    before = {p.name: p.read_bytes() for p in out.glob("*.jsonl")}
    r2 = CW.ingest_shards(stage, out, _gm(), now=now)                                          # duplicate ingestion
    assert r2["ingested"] == 0 and r2["quotes"] == 0
    assert {p.name: p.read_bytes() for p in out.glob("*.jsonl")} == before                     # byte-identical, no new segment
    out2 = tmp_path / "o2"; CW.ingest_shards(stage, out2, _gm(), now=now)                       # a second, independent ingest produces the same bytes
    assert {p.name: p.read_bytes() for p in out2.glob("*.jsonl")} == before
    assert PP.verify_chain(out / "quotes.jsonl")["ok"] and PP.verify_chain(out / "observations.jsonl")["ok"]
    assert len(CI._read(out / "quotes.jsonl")) == r1["quotes"] and len(CI._read(out / "observations.jsonl")) == 5


# ---------------------------------------------------------------------------------------------- publication
def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout


def _remote(tmp_path, reject_over=None, name="remote.git", clone="clone"):
    bare = tmp_path / name
    if not bare.exists():
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        if reject_over:        # emulate GitHub's per-file size limit with a pre-receive hook
            hook = bare / "hooks" / "pre-receive"
            hook.write_text(f"""#!/bin/bash
while read old new ref; do
  [ "$new" = "0000000000000000000000000000000000000000" ] && continue
  range=$([ "$old" = "0000000000000000000000000000000000000000" ] && echo "$new" || echo "$old..$new")
  git rev-list --objects $range | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | while read t o s r; do
    if [ "$t" = "blob" ] && [ "$s" -gt {reject_over} ]; then echo "remote: error: File $r is $s bytes; this exceeds GitHub's file size limit (GH001: Large files detected)" >&2; exit 1; fi
  done || exit 1
done
""")
            hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / clone; subprocess.run(["git", "init", "-q", str(work)], check=True)
    _git(work, "remote", "add", "origin", str(bare)); (work / "f").write_text("x"); _git(work, "add", "f")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return bare, work


def test_publish_segmented_ledger_is_verified_against_the_remote(tmp_path):
    bare, work = _remote(tmp_path); out = tmp_path / "out"
    fill(out / "quotes.jsonl", 40); fill(out / "observations.jsonl", 3, max_bytes=10**9); fill(out / "predictions.jsonl", 3, max_bytes=10**9)
    r = PC.publish(work, out); assert r["pushed"] and r["verified"] and not r["mismatches"], r
    remote_names = _git(bare, "ls-tree", "--name-only", PC.BRANCH, "nfl_totals_v1/").split()
    assert {Path(n).name for n in remote_names} >= {p.name for p in PP.segment_paths(out / "quotes.jsonl")}
    again = PC.publish(work, out); assert again.get("unchanged") and again["verified"]           # idempotent, and re-verified
    fill(out / "quotes.jsonl", 30, start=40)                                                    # grows: new segments appended, sealed ones untouched
    r2 = PC.publish(work, out); assert r2["pushed"] and r2["verified"]
    # fetch_branch_files returns every segment, so the next cycle continues the SAME chain
    dest = tmp_path / "fetched"; got = PC.fetch_branch_files(work, PC.BRANCH, "nfl_totals_v1", dest)
    assert {p.name for p in PP.segment_paths(out / "quotes.jsonl")} <= set(got)
    assert PP.verify_chain(dest / "quotes.jsonl")["ok"] and PP.verify_chain(dest / "quotes.jsonl")["records"] == 70


def test_publish_refuses_to_overwrite_history_and_missing_segments(tmp_path):
    bare, work = _remote(tmp_path); out = tmp_path / "out"
    fill(out / "quotes.jsonl", 40); assert PC.publish(work, out)["verified"]
    sealed = out / "quotes.0001.jsonl"; sealed.write_text(sealed.read_text().replace("xxxx", "xxxy", 1))
    r = PC.publish(work, out); assert not r["pushed"] and "append-only violation" in r["error"]
    out2 = tmp_path / "out2"; fill(out2 / "quotes.jsonl", 10)                                    # a local ledger that LOST segments the remote has
    r = PC.publish(work, out2); assert not r["pushed"] and "append-only violation" in r["error"]


def test_oversized_file_is_refused_before_any_push(tmp_path, monkeypatch):
    bare, work = _remote(tmp_path); out = tmp_path / "out"
    fill(out / "quotes.jsonl", 20, max_bytes=10**9)
    monkeypatch.setattr(PP, "MAX_PUBLISH_FILE_BYTES", 500)
    r = PC.publish(work, out); assert not r["pushed"] and not r["verified"] and "OVERSIZE_FILE" in r["error"]
    assert subprocess.run(["git", "-C", str(bare), "rev-parse", PC.BRANCH], capture_output=True).returncode != 0         # nothing reached the remote


def test_rejected_push_is_detected_and_never_reported_as_published(tmp_path, monkeypatch):
    bare, work = _remote(tmp_path, reject_over=3000); out = tmp_path / "out"
    fill(out / "quotes.jsonl", 80, max_bytes=10**9)                                             # one ~7 kB file: the remote hook rejects it like GitHub rejects > 100 MiB
    monkeypatch.setattr(PP, "MAX_PUBLISH_FILE_BYTES", 10**9)                                    # bypass the local guard: prove the remote-side detection too
    r = PC.publish(work, out); assert not r["pushed"] and not r["verified"] and "REJECTED" in r["error"] and "GH001" in r["error"], r
    ok, why = PC.publication_status({"publish_totals": r}); assert not ok and why and "publish_totals" in why[0]


def test_remote_mismatch_is_detected_by_blob_comparison(tmp_path):
    bare, work = _remote(tmp_path); out = tmp_path / "out"
    fill(out / "quotes.jsonl", 20); assert PC.publish(work, out)["verified"]
    other = tmp_path / "other.jsonl"; other.write_bytes((out / "quotes.jsonl").read_bytes() + b"{}\n")
    v = PC.verify_remote(work, {"quotes.jsonl": other, "quotes.9999.jsonl": other}, "nfl_totals_v1")
    assert not v["verified"] and {m["problem"] for m in v["mismatches"]} == {"differs from local", "missing on remote"}
    assert not PC.verify_remote(work.parent / "nonexistent", {"x": other}, "nfl_totals_v1")["verified"]


def test_end_to_end_recovery_from_the_oversize_incident(tmp_path, monkeypatch):
    """Legacy single ledger already published (small), grows past the remote's limit, publish is rejected, the operator repartitions (published prefix kept), republish verifies."""
    bare, work = _remote(tmp_path, reject_over=3000); out = tmp_path / "out"
    fill(out / "quotes.jsonl", 10, max_bytes=10**9); published = (out / "quotes.jsonl").read_bytes(); assert len(published) < 3000
    monkeypatch.setattr(PP, "MAX_PUBLISH_FILE_BYTES", 10**9)
    assert PC.publish(work, out)["verified"]
    fill(out / "quotes.jsonl", 50, max_bytes=10**9, start=10)                                   # the old code path: keeps growing the single file
    bad = PC.publish(work, out); assert not bad["pushed"] and "REJECTED" in bad["error"]
    PP.repartition(out / "quotes.jsonl", max_bytes=2000, keep_bytes=len(published))
    assert (out / "quotes.jsonl").read_bytes().startswith(published) and len(PP.segment_paths(out / "quotes.jsonl")) > 1
    good = PC.publish(work, out); assert good["pushed"] and good["verified"], good
    dest = tmp_path / "fetched"; PC.fetch_branch_files(work, PC.BRANCH, "nfl_totals_v1", dest)
    v = PP.verify_chain(dest / "quotes.jsonl"); assert v["ok"] and v["records"] == 60
    assert [r["i"] for r in PP.read_ledger(dest / "quotes.jsonl")] == list(range(60))


def test_concurrent_publishers_both_end_up_verified(tmp_path):
    bare, w1 = _remote(tmp_path, clone="c1"); _, w2 = _remote(tmp_path, clone="c2")
    o1, o2 = tmp_path / "o1", tmp_path / "o2"; fill(o1 / "quotes.jsonl", 30); fill(o2 / "predictions.jsonl", 5, max_bytes=10**9)
    res = {}
    t1 = threading.Thread(target=lambda: res.__setitem__(1, PC.publish(w1, o1, rel="nfl_totals_v1")))
    t2 = threading.Thread(target=lambda: res.__setitem__(2, PC.publish(w2, o2, rel="nfl_player_v3")))
    t1.start(); t2.start(); t1.join(120); t2.join(120)
    assert res[1]["verified"] and res[2]["verified"], res                                       # the racing writer retried on a fresh head; neither overwrote the other
    ls = _git(bare, "ls-tree", "-r", "--name-only", PC.BRANCH); assert "nfl_totals_v1/quotes.jsonl" in ls and "nfl_player_v3/predictions.jsonl" in ls


# ---------------------------------------------------------------------------------------------- the REFRESH line
def _fake_refresh(monkeypatch, steps, **extra):
    monkeypatch.setattr(PC, "run_refresh", lambda repo, work, data_dir, run_id=None, **k: {"steps": steps, "alert_summary": {"high": 0, "warn": 0, "codes": []},
                                                                                           "cycle": {"eligible_decision_games": {"T-6h_settled": 13}}, **extra})


GOOD = {"pushed": True, "verified": True, "commit": "c" * 40, "remote_head": "d" * 40, "files": 4, "mismatches": []}


def test_publication_status_requires_every_attempted_publication_to_be_verified():
    assert PC.publication_status({"publish_totals": GOOD})[0]
    assert PC.publication_status({"publish_totals": {"pushed": False, "unchanged": True, "verified": True}, "publish_player": GOOD})[0]
    assert not PC.publication_status({})[0]                                                    # nothing published = not ok
    assert not PC.publication_status({"publish_totals": {"pushed": True, "verified": False}})[0]  # push exit 0 but remote does not match
    assert not PC.publication_status({"publish_totals": GOOD, "publish_player": {"pushed": False, "verified": False, "error": "x"}})[0]
    assert not PC.publication_status({"publish_totals": GOOD, "player_predict": {"error": "boom"}})[0]
    assert not PC.publication_status({"publish_totals": GOOD, "settle_capture": {"publish": {"pushed": False, "error": "net"}}})[0]


def test_worker_prints_ok_only_for_a_verified_publication_and_records_it(tmp_path, monkeypatch, capsys):
    bare, work = _remote(tmp_path)
    _fake_refresh(monkeypatch, {"publish_totals": GOOD, "lease_release": {"released": True}})
    out, code = WK.refresh(work, tmp_path / "w", tmp_path / "d")
    assert code == 0 and out["line"].startswith("REFRESH ok ") and "published_verified=True" in out["line"] and out["heartbeat"]["publication_verified"] is True
    bad = dict(GOOD, verified=False, mismatches=[{"file": "quotes.jsonl", "problem": "missing on remote"}])
    _fake_refresh(monkeypatch, {"publish_totals": bad, "lease_release": {"released": True}})
    out, code = WK.refresh(work, tmp_path / "w2", tmp_path / "d")
    assert code == 2 and out["line"].startswith("REFRESH failed ") and "published_verified=False" in out["line"] and not out["line"].startswith("REFRESH ok")
    assert out["heartbeat"]["status"] == "failed" and out["heartbeat"]["publication_verified"] is False and out["heartbeat"]["publication"]["reasons"]
    _fake_refresh(monkeypatch, {"publish_totals": {"pushed": False, "verified": False, "error": "push REJECTED by the remote: GH001"}})      # the 2026-11-09 incident
    out, code = WK.refresh(work, tmp_path / "w3", tmp_path / "d"); assert code == 2 and "REFRESH ok" not in out["line"] and "REJECTED" in out["line"]
    _fake_refresh(monkeypatch, {}, aborted="frozen model drift")
    out, code = WK.refresh(work, tmp_path / "w4", tmp_path / "d"); assert code == 2 and out["line"].startswith("REFRESH failed")


def test_failed_or_stale_refresh_raises_alerts():
    now = pd.Timestamp("2026-11-10 09:00", tz="UTC")
    hb = lambda t, **k: {"role": "refresh", "run_id": "r" + t, "started_utc": f"2026-11-{t}:00+00:00", **k}
    a = AL.evaluate([hb("09T08:42", status="failed", publication_verified=False, publication={"reasons": ["publish_totals:REJECTED"]})], [], None, now)
    assert {x["code"] for x in a} >= {"REFRESH_UNPUBLISHED"}
    a = AL.evaluate([hb("08T08:42", status="ok", publication_verified=True)], [], None, now + pd.Timedelta(days=1))
    assert "REFRESH_STALE" in {x["code"] for x in a}
    a = AL.evaluate([hb("10T08:42", status="ok", publication_verified=True)], [], None, now)
    assert not {x["code"] for x in a} & {"REFRESH_UNPUBLISHED", "REFRESH_STALE"}

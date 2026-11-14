"""Research feedback loop: one bounded, idempotent pass (RESEARCH_ONLY).

    python -m alpha_engine.foundation.loop                      # offline: rebuild the ledger from committed evidence
    python -m alpha_engine.foundation.loop --market-watch       # + ONE public Kalshi series-list request
    python -m alpha_engine.foundation.loop --challengers        # + re-run the P0 challenger evaluations (needs the sport repos)

Steps, in order: detect new market listings -> re-run challenger evaluations on the newest archived data -> rebuild
the pipeline ledger (missing inputs, stages, ranked queue) -> pick the next task -> write loop_health.json.

Safety properties (tested in tests/test_foundation_ops.py):
  * It never commits, pushes, dispatches a workflow or schedules anything, so it cannot start a successor run.
  * Each step has a hard timeout; the whole pass is bounded by the sum of step timeouts.
  * A lock file refuses a second concurrent pass. Re-running on unchanged inputs rewrites byte-identical artifacts.
  * Health is fail-closed: overall is HEALTHY only if every REQUESTED step succeeded and the ledger reconciles.
    A skipped, failed or timed-out step is reported as such and makes the pass DEGRADED or FAILED, never healthy.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

from .contract import OPS, ROOT, repos_dir, write_json

LOCK = OPS / ".loop.lock"
STEP_TIMEOUT_S = {"market_watch": 120, "nba": 1500, "cbb": 900, "nhl": 1200, "ledger": 300}
CHALLENGERS = {
    "nba": (["-m", "alpha_engine.foundation.nba_availability"], "nba-edge-finder"),
    "nhl": (["-m", "alpha_engine.foundation.nhl_joint"], "NHL-edge-finder"),
    "cbb": (["-m", "alpha_engine.foundation.cbb_joint_periods"], None),      # reads $SIFT_CBB_ARCH_DIR (extracted archive branches)
}


def _run(name: str, args: list) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=STEP_TIMEOUT_S[name])
        ok = p.returncode == 0
        return {"step": name, "status": "OK" if ok else "FAILED", "seconds": round(time.time() - t0, 1), "detail": (p.stdout if ok else p.stderr).strip().splitlines()[-1:] or [""]}
    except subprocess.TimeoutExpired:
        return {"step": name, "status": "TIMED_OUT", "seconds": round(time.time() - t0, 1), "detail": [f"exceeded {STEP_TIMEOUT_S[name]} s"]}


def run_pass(market_watch: bool, challengers: bool, now_utc: str) -> dict:
    steps = []
    steps.append(_run("market_watch", ["-m", "alpha_engine.foundation.market_watch"]) if market_watch
                 else {"step": "market_watch", "status": "NOT_REQUESTED", "seconds": 0, "detail": ["offline pass; committed market_watch.json reused"]})
    for name, (args, repo) in CHALLENGERS.items():
        if not challengers:
            steps.append({"step": name, "status": "NOT_REQUESTED", "seconds": 0, "detail": ["committed evaluation reused"]})
        elif repo and not (repos_dir() / repo).exists():
            steps.append({"step": name, "status": "SKIPPED_SOURCE_UNAVAILABLE", "seconds": 0, "detail": [f"{repos_dir() / repo} not present"]})
        elif name == "cbb" and not os.environ.get("SIFT_CBB_ARCH_DIR"):
            steps.append({"step": name, "status": "SKIPPED_SOURCE_UNAVAILABLE", "seconds": 0, "detail": ["SIFT_CBB_ARCH_DIR not set"]})
        else:
            steps.append(_run(name, args + (["--arch", os.environ["SIFT_CBB_ARCH_DIR"]] if name == "cbb" else [])))
    steps.append(_run("ledger", ["-m", "alpha_engine.foundation.ledger"]))
    return finish(steps, now_utc)


def finish(steps: list, now_utc: str) -> dict:
    requested = [s for s in steps if s["status"] != "NOT_REQUESTED"]
    bad = [s for s in requested if s["status"] != "OK"]
    summ = OPS / "summary.json"
    recon_ok, nxt, stale = False, None, []
    if summ.exists():
        s = json.loads(summ.read_text())
        recon_ok = bool(s["reconciliation"]["ok"])
        q = s["queue_top"].get("P0") or []
        nxt = {"dataset": q[0]["dataset"], "title": q[0]["title"], "action_group": q[0]["action_group"], "first_action": q[0]["next_actions"][0]} if q else None
        mw = s.get("market_watch")
        if mw:
            age = (datetime.datetime.fromisoformat(now_utc.replace("Z", "+00:00")) - datetime.datetime.fromisoformat(mw["observed_utc"].replace("Z", "+00:00"))).days
            if age > 7:
                stale.append(f"market_watch is {age} days old")
        else:
            stale.append("market_watch has never run")
    ledger_step = next(s for s in steps if s["step"] == "ledger")
    if ledger_step["status"] != "OK" or not recon_ok:
        overall = "FAILED"
    elif bad or stale:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"
    return {"schema": "sift-foundation-loop/1", "status": "RESEARCH_ONLY", "ran_utc": now_utc, "overall": overall, "steps": steps,
            "ledger_reconciles": recon_ok, "stale": stale, "not_ok_steps": [s["step"] + ":" + s["status"] for s in bad], "next_task": nxt,
            "note": "HEALTHY means every requested step succeeded, the ledger reconciles to the Market & Input Map and nothing is stale. It says nothing about model quality or profitability."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-watch", action="store_true"); ap.add_argument("--challengers", action="store_true")
    ap.add_argument("--now", default=None, help="UTC timestamp override (tests / reproducible runs)")
    a = ap.parse_args(argv)
    now = a.now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OPS.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("another pass holds the lock; refusing to run concurrently", file=sys.stderr)
        return 3
    try:
        os.close(fd)
        h = run_pass(a.market_watch, a.challengers, now)
        write_json(OPS / "loop_health.json", h)
        print(f"{h['overall']} | " + " ".join(f"{s['step']}={s['status']}" for s in h["steps"]) + (f" | next: {h['next_task']['dataset']}" if h["next_task"] else ""))
        return 0 if h["overall"] != "FAILED" else 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

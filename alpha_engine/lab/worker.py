"""Entry points run by the scheduled worker sessions (RESEARCH_ONLY).  ONE command per firing, ONE output line, and a durable heartbeat for EVERY firing -- including no-window runs and crashes.

    python -m alpha_engine.lab.worker capture --repo . [--span 57 --interval 300] [--force]
    python -m alpha_engine.lab.worker refresh --repo . --work DIR --data-dir DIR

The worker never receives a model task: everything it needs lives in version-controlled code (this module + scripts/prospective/bootstrap.sh) and the release pin on the data branch."""
from __future__ import annotations
import argparse, json, os, platform, subprocess, sys, time, traceback
from pathlib import Path
import pandas as pd


def _versions() -> dict:
    out = {"python": platform.python_version()}
    for m in ("numpy", "pandas", "scipy", "sklearn", "pyarrow"):
        try:
            out[m] = __import__(m).__version__
        except Exception:
            out[m] = None
    return out


def write_heartbeat(stage: Path, hb: dict, phase: str = "") -> Path:
    """phase "" = the final heartbeat of a firing; phase "start" is published BEFORE any work, so a run that is killed (time limit, crash) still leaves evidence."""
    ts = pd.Timestamp(hb["started_utc"]).strftime("%Y%m%dT%H%M%SZ")
    p = Path(stage) / "heartbeats" / ts[:4] / ts[:8] / f"{ts}__{hb['role']}__{hb['run_id']}{'__' + phase if phase else ''}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(hb, sort_keys=True, indent=1, default=str))
    return p


def known_static(repo: Path, days: int = 2) -> dict:
    """{ticker: static_sha} already registered in `contracts/` shards of the last `days` UTC dates on the data branch (read-only; empty on any problem => static rows are simply re-stored)."""
    from . import capture_window as CW
    try:
        subprocess.run(["git", "-C", str(repo), "fetch", "--depth=1", "origin", "prospective-data"], capture_output=True, check=True)
        names = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "FETCH_HEAD", "contracts/"], capture_output=True, text=True, check=True).stdout.split()
        want = {(pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=d)).strftime("%Y%m%d") for d in range(days)}
        out = {}
        for n in sorted(names):
            if n.split("/")[-2] in want:
                raw = subprocess.run(["git", "-C", str(repo), "show", f"FETCH_HEAD:{n}"], capture_output=True, check=True).stdout
                import gzip
                for t, r in json.loads(gzip.decompress(raw))["contracts"].items():
                    out[t] = r["sha"]
        return out
    except Exception:
        return {}


def capture(repo: Path, stage: Path, span: float, interval: float, force: bool, games_csv: str | None = None) -> tuple[dict, int]:
    from . import capture_window as CW, prospective_cycle as PC
    started = pd.Timestamp.now(tz="UTC"); run_id = os.environ.get("CAPTURE_RUN_ID") or f"capture-{started.strftime('%Y%m%dT%H%M%SZ')}"
    hb = {"kind": "heartbeat", "role": "capture", "run_id": run_id, "started_utc": started.isoformat(), "code_sha": PC.code_sha(repo), "release": os.environ.get("RELEASE_SHA"), "versions": _versions(),
          "span_min": span, "interval_s": interval, "forced": force, "status": "failed", "ticks": 0, "series_failures": 0, "publish_errors": []}
    res = None
    try:
        write_heartbeat(stage, {**hb, "status": "started"}, "start")
        PC.publish_captures(repo, stage, message="heartbeat (start)", meta={"writer-run": run_id, "role": "capture-heartbeat", "code": hb["code_sha"][:12], "status": "started"})
    except Exception:
        pass                                                           # the final heartbeat still reports publication state
    try:
        gp = games_csv
        if not gp:
            import urllib.request as U
            gp = str(Path(stage) / "_games.csv"); Path(stage).mkdir(parents=True, exist_ok=True)
            Path(gp).write_bytes(U.urlopen(U.Request("https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv", headers={"User-Agent": "sift-alpha-research"}), timeout=60).read())
        meta = {"writer-run": run_id, "role": "capture", "code": hb["code_sha"][:12]}
        res = CW.run_window_capture(pd.read_csv(gp), Path(stage), span_min=span, interval_s=interval, run_id=run_id, force=force, known_fn=lambda: known_static(repo),
                                    publish=lambda st: PC.publish_captures(repo, st, meta=meta))
        hb.update({k: res[k] for k in ("ticks", "series_failures", "publish_errors", "registry_rows", "missing_fields", "first_tick_utc", "last_tick_utc", "next_window_utc", "tick_seconds") if k in res})
        hb["shards"] = res["shards"]; hb["no_window"] = res["no_window"]
        hb["status"] = "no_window" if res["no_window"] else ("partial" if (res["series_failures"] or res["publish_errors"]) else "ok")
    except Exception as e:
        hb["error"] = f"{type(e).__name__}: {e}"[:300]; hb["traceback"] = traceback.format_exc()[-800:]
    hb["ended_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    write_heartbeat(stage, hb)
    meta = {"writer-run": run_id, "role": "capture-heartbeat", "code": hb["code_sha"][:12], "status": hb["status"]}
    pub = PC.publish_captures(repo, stage, message="heartbeat", meta=meta)
    hb["heartbeat_published"] = bool(pub.get("pushed") or pub.get("unchanged"))
    line = (f"CAPTURE {hb['status']} run={run_id} ticks={hb['ticks']} series_failures={hb['series_failures']} publish_errors={len(hb['publish_errors'])} "
            f"heartbeat={'pushed' if hb['heartbeat_published'] else 'NOT_PUBLISHED'} code={hb['code_sha'][:7]} next_window={hb.get('next_window_utc')}")
    code = 0 if hb["status"] in ("ok", "no_window") and hb["heartbeat_published"] else 1
    return {"line": line, "heartbeat": hb}, code


def refresh(repo: Path, work: Path, data_dir: Path) -> tuple[dict, int]:
    from . import prospective_cycle as PC
    started = pd.Timestamp.now(tz="UTC"); run_id = f"refresh-{started.strftime('%Y%m%dT%H%M%SZ')}"
    rep = PC.run_refresh(repo, work, data_dir, run_id=run_id)
    steps = rep.get("steps") or {}
    # FAIL CLOSED: `ok` only if the run was not aborted/blocked AND every publication it attempted was verified on the remote (blob-for-blob), not merely exit code 0 from `git push`.
    pub_ok, reasons = PC.publication_status(steps) if not (rep.get("aborted") or rep.get("lease_busy")) else (False, [])
    if rep.get("aborted"):
        reasons = ["aborted"]
    elif rep.get("lease_busy"):
        reasons = ["lease_busy"]
    status = "ok" if pub_ok else "failed"
    pt = steps.get("publish_totals") or {}
    pub = {"verified": bool(pub_ok), "reasons": reasons, "remote_head": pt.get("remote_head"), "totals_commit": pt.get("commit"), "files_verified": pt.get("files"),
           "lease_released": bool((steps.get("lease_release") or {}).get("released"))}
    hb = {"kind": "heartbeat", "role": "refresh", "run_id": run_id, "started_utc": started.isoformat(), "ended_utc": pd.Timestamp.now(tz="UTC").isoformat(), "code_sha": PC.code_sha(repo),
          "versions": _versions(), "status": status, "publication_verified": bool(pub_ok), "publication": pub, "alerts": rep.get("alert_summary")}
    stage = Path(work) / "hb_stage"; write_heartbeat(stage, hb)
    hp = PC.publish_captures(repo, stage, message="heartbeat", meta={"writer-run": run_id, "role": "refresh-heartbeat", "code": hb["code_sha"][:12]})
    s = rep.get("alert_summary") or {}
    line = (f"REFRESH {status} run={run_id} aborted={bool(rep.get('aborted'))} lease_busy={bool(rep.get('lease_busy'))} alerts_high={s.get('high')} warn={s.get('warn')} codes={s.get('codes')} "
            f"eligible_T-6h_settled={((rep.get('cycle') or {}).get('eligible_decision_games') or {}).get('T-6h_settled')} published_verified={pub_ok} "
            f"remote_head={(pt.get('remote_head') or 'none')[:10]} heartbeat={'pushed' if hp.get('pushed') else 'NOT_PUBLISHED'}" + (f" reasons={reasons}" if reasons else ""))
    return {"line": line, "report": rep, "heartbeat": hb}, (0 if status == "ok" else 2)


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture"); c.add_argument("--repo", required=True); c.add_argument("--stage", default="/tmp/stage"); c.add_argument("--span", type=float, default=57.0)
    c.add_argument("--interval", type=float, default=300.0); c.add_argument("--force", action="store_true"); c.add_argument("--games")
    r = sub.add_parser("refresh"); r.add_argument("--repo", required=True); r.add_argument("--work", default="/tmp/work"); r.add_argument("--data-dir", default="/tmp/nflverse")
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        out, code = capture(Path(a.repo), Path(a.stage), a.span, a.interval, a.force, a.games)
    else:
        out, code = refresh(Path(a.repo), Path(a.work), Path(a.data_dir))
    print(out["line"], flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())

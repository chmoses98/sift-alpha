"""Publish a finished sweep state to the `sweep-data` data branch layout, with provenance.

Layout written under OUT_DIR (a checkout of the sweep-data branch):
  sweeps/<queue-stem>/state_<UTC>_run<RUNID>.json   raw sweeper state, byte-for-byte
  sweeps/<queue-stem>/latest.json                   pointer + manifest of the newest publish
  index.jsonl                                       append-only log of every publish
Usage: python -m kalshi_sweep.publish STATE.json QUEUE.json OUT_DIR   (run metadata from GITHUB_* env vars)."""
import hashlib, json, os, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("open", "unopened", "closed", "settled")


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def summarize(state, queue):
    series = state.get("series", {})
    done = [s for s in queue if s in series and all(series[s].get(k, {}).get("complete") for k in STATUSES)]
    return {"series_queued": len(queue), "series_complete": len(done), "complete": len(done) == len(queue),
            "requests_total": state.get("requests_total"), "errors": len(state.get("errors", [])), "rate_limited": state.get("rate_limited", 0),
            "markets_by_status": {k: sum(series[s].get(k, {}).get("markets", 0) for s in series) for k in STATUSES}}


def publish(state_path, queue_path, out_dir, env=None, now=None):
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    state = json.load(open(state_path)); queue = json.load(open(queue_path))["series"]
    stem = Path(queue_path).stem
    d = Path(out_dir) / "sweeps" / stem; d.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ"); run = env.get("GITHUB_RUN_ID", "local")
    name = f"state_{stamp}_run{run}.json"
    shutil.copyfile(state_path, d / name)
    man = {"schema_version": "sweep-publish-1", "published_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "file": name, "state_sha256": sha256(d / name),
           "queue_file": str(queue_path), "queue_sha256": sha256(queue_path), "workflow_run_id": run, "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
           "workflow_sha": env.get("GITHUB_SHA"), "workflow_ref": env.get("GITHUB_REF"), "repository": env.get("GITHUB_REPOSITORY"), **summarize(state, queue)}
    (d / "latest.json").write_text(json.dumps(man, indent=1))
    with open(Path(out_dir) / "index.jsonl", "a") as f:
        f.write(json.dumps({k: man[k] for k in ("published_utc", "file", "state_sha256", "workflow_run_id", "series_complete", "series_queued", "complete", "requests_total")} | {"queue": stem}) + "\n")
    return man


if __name__ == "__main__":
    m = publish(*sys.argv[1:4])
    print(json.dumps({k: m[k] for k in ("file", "series_complete", "series_queued", "complete", "requests_total")}))

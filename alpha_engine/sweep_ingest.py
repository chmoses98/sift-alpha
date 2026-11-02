"""Ingest Kalshi sweep results from the `sweep-data` branch into research/audit/sweep_results/*.json.

Preferred source: the newest COMPLETE raw state listed in index.jsonl (sha256-verified); partial/bounded publishes never displace it.
Fallback: seed/<queue>.compact.json (rows parsed from a job log). Every output carries its provenance.
Usage: python -m alpha_engine.sweep_ingest [--repo PATH] [--branch sweep-data]   (needs git read access to origin)"""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path

from kalshi_sweep.dump_state import compact_rows

R = Path(__file__).resolve().parents[1] / "research" / "audit" / "sweep_results"
QUEUES = {"mlb": "mlb_queue", "soccer": "soccer_ambiguous_queue"}


def _show(repo, ref, path):
    r = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def load(repo, ref, stem):
    """-> (meta, rows, provenance) for one queue from a git ref."""
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True).stdout.strip()
    # newest COMPLETE raw publish for this queue (index.jsonl is append-only); a later partial/bounded run never displaces it
    idx = _show(repo, ref, "index.jsonl")
    pick = None
    for line in (idx or b"").decode().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("queue") == stem and e.get("complete"):
            pick = e
    if pick:
        raw = _show(repo, ref, f"sweeps/{stem}/{pick['file']}")
        if raw is None or hashlib.sha256(raw).hexdigest() != pick["state_sha256"]:
            raise ValueError(f"{stem}: raw state missing or sha256 mismatch against its index entry")
        man = json.loads(_show(repo, ref, f"sweeps/{stem}/latest.json") or b"{}")
        st = json.loads(raw)
        return ({k: v for k, v in st.items() if k != "series"}, list(compact_rows(st)),
                {"transport": "sweep-data branch (raw state)", "data_branch_commit": commit, "file": f"sweeps/{stem}/{pick['file']}", "state_sha256": pick["state_sha256"], "workflow_run_id": pick["workflow_run_id"],
                 "published_utc": pick["published_utc"], "series_complete": pick["series_complete"], "series_queued": pick["series_queued"], "newest_publish_complete": man.get("complete")})
    seed = _show(repo, ref, f"seed/{stem}.compact.json")
    if seed is None:
        raise FileNotFoundError(f"{stem}: neither sweeps/{stem}/latest.json nor seed/{stem}.compact.json on {ref}")
    d = json.loads(seed)
    return d["meta"], d["series"], {"transport": "sweep-data branch (seed: compact rows parsed from a job log)", "data_branch_commit": commit, "file": f"seed/{stem}.compact.json",
                                    "file_sha256": hashlib.sha256(seed).hexdigest(), **d["provenance"]}


def ingest(repo, ref="FETCH_HEAD", out=R):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for name, stem in QUEUES.items():
        meta, rows, prov = load(repo, ref, stem)
        (out / f"{name}.json").write_text(json.dumps({"schema_version": "audit-1.0", "queue": name, "meta": meta, "provenance": prov, "series": rows}, indent=1))
        print(name, len(rows), "series from", prov["file"], "@", prov["data_branch_commit"][:9])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1])); ap.add_argument("--branch", default="sweep-data")
    a = ap.parse_args()
    subprocess.run(["git", "-C", a.repo, "fetch", "-q", "--depth=1", "origin", a.branch], check=True)
    ingest(a.repo)

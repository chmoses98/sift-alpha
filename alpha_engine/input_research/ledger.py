"""Append-only experiment ledger (schema identical to PR #59's alpha_engine/lab/ledger.py so evidence from both laboratories can be pooled; copied, not re-implemented).
Append-only experiment ledger.  Every experiment (including failures) is one JSON line keyed by a hash of its full configuration, so a re-run is a cache hit and
the file is a complete, reproducible record of everything that was tried (the denominator for multiple-testing control)."""
from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path


def exp_id(config: dict) -> str:
    return hashlib.sha1(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


def data_fingerprint(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode())
    return h.hexdigest()[:12]


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.rows: dict[str, dict] = {}
        gz = Path(str(self.path) + ".gz")
        if not self.path.exists() and gz.exists():          # fresh checkouts carry only the gzipped ledgers: read them (reading only; new records still go to self.path)
            import gzip
            for l in gzip.decompress(gz.read_bytes()).decode().splitlines():
                if l.strip():
                    r = json.loads(l)
                    self.rows[r["id"]] = r
        if self.path.exists():
            for l in self.path.read_text().splitlines():
                if l.strip():
                    r = json.loads(l)
                    self.rows[r["id"]] = r

    def has(self, config: dict) -> bool:
        return exp_id(config) in self.rows

    def get(self, config: dict):
        return self.rows.get(exp_id(config))

    def record(self, config: dict, metrics: dict, *, status="ok", note="", sample=None, fingerprint="") -> dict:
        """Idempotent: an experiment with the same configuration is stored once (the first result stands; it is deterministic)."""
        i = exp_id(config)
        if i in self.rows:
            return self.rows[i]
        r = dict(id=i, config=config, metrics=metrics, status=status, note=note, sample=sample or {}, data=fingerprint, ts=int(time.time()))
        self.rows[i] = r
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(r, separators=(",", ":"), default=float) + "\n")
        return r

    def select(self, **kv):
        return [r for r in self.rows.values() if all(r["config"].get(k) == v for k, v in kv.items())]

    def __len__(self):
        return len(self.rows)


LAB59_REF = "origin/feat/sift-lab"
LAB59_FILES = "research/audit/lab/ledger_"


def count_lab59(ref: str = LAB59_REF) -> dict:
    """Read-only count of PR #59's logged experiments straight from its git ref (nothing is copied into this branch)."""
    import gzip
    import subprocess
    try:
        names = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref], capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        return {"available": False}
    per = {}
    for n in names:
        if n.startswith(LAB59_FILES) and n.endswith(".jsonl.gz"):
            blob = subprocess.run(["git", "show", f"{ref}:{n}"], capture_output=True, check=True).stdout
            per[n.rsplit("ledger_", 1)[1][:-9]] = sum(1 for l in gzip.decompress(blob).decode().splitlines() if l.strip())
    return {"available": True, "ref": ref, "per_ledger": per, "total": sum(per.values())}

"""Append-only experiment ledger.  Every experiment (including failures) is one JSON line keyed by a hash of its full configuration, so a re-run is a cache hit and
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

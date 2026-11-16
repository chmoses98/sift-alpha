"""Reproducible recovery manifest for the raw inputs behind the training datasets (RESEARCH_ONLY).

No raw row is stored here. The manifest records where each input came from, the sha256 of the exact bytes a dataset was
built from, the rights tier, and a reproducibility class:

  GIT_PINNED        bytes live in an owner git repository at a pinned commit (durable; recover with git)
  UPSTREAM_MUTABLE  public upstream URL whose bytes can be republished (re-fetch, then compare hashes; drift = not recoverable
                    byte-exact, the dataset must be rebuilt and re-hashed, never silently replaced)
  LOST_EPHEMERAL    existed only in a previous session's temporary storage, or a point-in-time value that cannot be re-fetched

    python -m alpha_engine.certify.recovery pin-dir --dir D --pattern '*/*.parquet' --url-base URL   # hashes of local files
    python -m alpha_engine.certify.recovery verify --manifest research/certification/recovery_manifest.json --source cbb_sportsdataverse --dir D
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pin_dir(d: Path, pattern: str) -> dict:
    return {str(p.relative_to(d)): {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(d.glob(pattern)) if p.is_file()}


def verify(manifest: dict, source: str, d: Path, fetch: bool = False) -> dict:
    """Compare local (or freshly fetched, with --fetch) bytes against the pinned hashes of one source."""
    s = manifest["sources"][source]; res = {"same": [], "changed": [], "missing": []}
    for rel, meta in s["files"].items():
        p = d / rel
        if fetch and s.get("url_template"):
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                tag = s.get("tags", {}).get(Path(rel).parts[0], "")
                urllib.request.urlretrieve(s["url_template"].format(path=rel, name=Path(rel).name, tag=tag), p)
            except Exception:                                           # noqa: BLE001 - record and continue
                res["missing"].append(rel); continue
        if not p.exists():
            res["missing"].append(rel)
        elif sha256(p) == meta["sha256"]:
            res["same"].append(rel)
        else:
            res["changed"].append(rel)
    return {k: (len(v), v[:50]) for k, v in res.items()} | {"recoverable_byte_exact": not res["changed"] and not res["missing"]}


def main(x=None) -> int:
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("pin-dir"); a.add_argument("--dir", required=True); a.add_argument("--pattern", required=True)
    b = sp.add_parser("verify"); b.add_argument("--manifest", required=True); b.add_argument("--source", required=True); b.add_argument("--dir", required=True)
    b.add_argument("--fetch", action="store_true", help="re-download from the pinned URL template into --dir first")
    o = ap.parse_args(x)
    if o.cmd == "pin-dir":
        print(json.dumps(pin_dir(Path(o.dir), o.pattern), indent=1))
    else:
        print(json.dumps(verify(json.loads(Path(o.manifest).read_text()), o.source, Path(o.dir), o.fetch), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

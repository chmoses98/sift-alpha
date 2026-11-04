"""Build the NFL Kalshi market-family inventory from nfl-edge-finder's series registry.

Usage: python -m alpha_engine.nfl_inventory REGISTRY_JSON COMMIT OUT_JSON
The registry counts (`markets_seen`) are a 2026-09-04 discovery snapshot, NOT current availability; a family with
0 seen is "not observed by that snapshot", never "does not exist".
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

from .audit_schema import SCHEMA_VERSION, validate_inventory

REPO = "chmoses98/nfl-edge-finder"
PATH = "config/kalshi_nfl_series.json"
SNAPSHOT_NOTE = "markets_seen is the registry's 2026-09-04 discovery count; 0 means unobserved by it, not nonexistent"


def build(raw: bytes, commit: str, now: datetime | None = None):
    reg = json.loads(raw)["series"]
    fams = {}
    for ticker, s in sorted(reg.items()):
        f = fams.setdefault(s["family"], {"family": s["family"], "series": [], "snapshot_markets_seen": 0})
        f["series"].append({"ticker": ticker, "title": s["title"], "scope": s.get("product_scope"),
                            "tier": s.get("tier"), "snapshot_markets_seen": int(s.get("markets_seen", 0))})
        f["snapshot_markets_seen"] += int(s.get("markets_seen", 0))
    out = {"schema_version": SCHEMA_VERSION, "sport": "NFL",
           "last_verified_utc": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": {"repo": REPO, "commit": commit, "path": PATH, "sha256": hashlib.sha256(raw).hexdigest()},
           "note": SNAPSHOT_NOTE, "series_total": len(reg),
           "families": sorted(fams.values(), key=lambda f: (-f["snapshot_markets_seen"], f["family"]))}
    errs = validate_inventory(out)
    if errs:
        raise ValueError(errs)
    return out


def main(argv=None):
    reg, commit, out = (argv or sys.argv[1:])[:3]
    inv = build(open(reg, "rb").read(), commit)
    json.dump(inv, open(out, "w"), indent=1)
    print(f"{len(inv['families'])} families / {inv['series_total']} series -> {out}")


if __name__ == "__main__":
    main()

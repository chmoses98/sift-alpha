#!/usr/bin/env python3
"""Owner/reviewer-only: publish RELEASE.json (the approved worker code pin) to the data branch.  Capture workers cannot write this file (publish allowlist).
usage: set_release.py <sha> [--note TEXT]   -- <sha> must be an ancestor of origin/feat/sift-lab or origin/main."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
from alpha_engine.lab import prospective_cycle as PC

sha = subprocess.run(["git", "rev-parse", sys.argv[1]], capture_output=True, text=True, check=True).stdout.strip()
ok = any(subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref]).returncode == 0 for ref in ("origin/feat/sift-lab", "origin/main"))
if not ok:
    sys.exit(f"refused: {sha} is not on a reviewed branch")
note = sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else ""
doc = {"code_commit": sha, "set_utc": pd.Timestamp.now(tz="UTC").isoformat(), "note": note}
r = PC._push_one(Path("."), {"RELEASE.json": json.dumps(doc, indent=1).encode()}, f"release: pin worker code {sha[:8]}", PC.BRANCH, "origin", {"role": "release", "code": sha[:12]})
print(r)

#!/usr/bin/env python3
"""usage: python scripts/measure_nba_starter_evidence.py AVAILABILITY_DIR PROJECTION_DATA_COMMIT STARTER_ONOFF_JSON [LIVE_SUMMARY_JSON]
Writes research/audit/verification/NBA_starters_evidence.json from (a) the archived availability rows of nba-edge-finder@projection-data
(how many starter observations exist and when), (b) the deterministic ON/OFF experiment output, (c) optionally the live pre-tip capture summary."""
import collections
import glob
import gzip
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
avail, commit, onoff = sys.argv[1:4]
live = json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv) > 4 else None
src, kinds, first, last, files = collections.Counter(), collections.Counter(), None, None, 0
n = 0
for f in sorted(glob.glob(f"{avail}/*/*.jsonl.gz")):
    files += 1
    for line in gzip.open(f, "rt"):
        r = json.loads(line)
        n += 1
        src[r.get("source")] += 1
        kinds[r.get("kind")] += 1
        c = r.get("captured_utc")
        first = c if first is None or c < first else first
        last = c if last is None or c > last else last
out = {"schema_version": "nba-starters-evidence-1.0",
       "archive": {"repo": "chmoses98/nba-edge-finder", "branch": "projection-data", "commit": commit, "path": "availability/nba", "files": files, "rows": n, "captured_range": [first, last],
                   "rows_by_kind": dict(kinds), "rows_by_source": dict(src), "starter_rows": kinds.get("starter", 0),
                   "finding": "ZERO starter observations in the archived availability feed: the summary-based starter source never produced a row" if not kinds.get("starter") else "starter rows exist"},
       "onoff_experiment": json.loads(Path(onoff).read_text()),
       "live_pretip_capture": live,
       "oracle_upper_bound_repo_reported": {"minutes_mae_beyond_E_inj": -0.1686, "ci95": [-0.1829, -0.1536], "n_obs": 52796,
                                            "note": "uses the ACTUAL starter flag (not pregame-knowable); an upper bound on what a confirmed-lineup feed could add, repo-reported not reproduced"},
       "separation": {"feature_availability": "starter observations: see archive.starter_rows and live_pretip_capture", "verified_consumption": "starter rows reach P(play) only (onoff_experiment)",
                      "projection_validity": "not established for starter-conditioned projections: no pregame starter history exists", "predictive_improvement": "no starter-ON history exists; oracle bound only",
                      "market_advantage": "none established or tested"}}
(root / "research/audit/verification/NBA_starters_evidence.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print(out["archive"]["rows"], out["archive"]["starter_rows"], out["archive"]["captured_range"])

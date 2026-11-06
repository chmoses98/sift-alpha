#!/usr/bin/env python3
"""usage: python scripts/measure_nba_starter_evidence.py AVAILABILITY_DIR PROJECTION_DATA_COMMIT STARTER_ONOFF_JSON NBA_EDGE_FINDER_COMMIT_OF_ONOFF [LIVE_SUMMARY_JSON]
Writes research/audit/verification/NBA_starters_evidence.json from (a) the archived availability rows of nba-edge-finder@projection-data
(how many starter observations exist and when), (b) the deterministic ON/OFF experiment output, (c) optionally the live pre-tip capture summary."""
import collections
import glob
import gzip
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[1]
avail, commit, onoff, onoff_commit = sys.argv[1:5]
live = json.loads(Path(sys.argv[5]).read_text()) if len(sys.argv) > 5 else None
src, kinds, first, last, files = collections.Counter(), collections.Counter(), None, None, 0
n = 0
near_tip = 0
for f in sorted(glob.glob(f"{avail}/*/*.jsonl.gz")):
    files += 1
    for line in gzip.open(f, "rt"):
        r = json.loads(line)
        n += 1
        src[r.get("source")] += 1
        kinds[r.get("kind")] += 1
        c = r.get("captured_utc")
        if not c:
            continue
        first = c if first is None or c < first else first
        last = c if last is None or c > last else last
        try:
            gap = datetime.fromisoformat(r["event_start_utc"].replace("Z", "+00:00")) - datetime.fromisoformat(c.replace("Z", "+00:00"))
            near_tip += timedelta(0) <= gap <= timedelta(minutes=150)
        except (KeyError, ValueError, AttributeError):
            pass
out = {"schema_version": "nba-starters-evidence-1.0",
       "archive": {"repo": "chmoses98/nba-edge-finder", "branch": "projection-data", "commit": commit, "path": "availability/nba", "files": files, "rows": n, "captured_range": [first, last],
                   "rows_by_kind": dict(kinds), "rows_by_source": dict(src), "starter_rows": kinds.get("starter", 0), "rows_captured_within_150min_before_tip": near_tip,
                   "finding": (f"no starter observations exist in the archived availability feed ({near_tip} rows were captured within 150 minutes before tip, so the pre-tip window was reached); consistent with the SIFT Alpha probe finding that ESPN summary payloads carry no pregame starter flags, but row counts alone cannot prove why" if not kinds.get("starter") else "starter rows exist")},
       "onoff_experiment": dict(json.loads(Path(onoff).read_text()), generated_from={"repo": "chmoses98/nba-edge-finder", "commit": onoff_commit, "module": "research/projection_foundation/nba/live/starter_onoff.py"},
                                caveats=["the ON arm injects a hypothetical CONFIRMED starter row (the PR #87 core-roster design); the archived summary-based source emitted PROJECTED rows and no CONFIRMED row has been observed in any archive",
                                         "the experiment stops at participation -> P(play) -> minutes-model choice; project.py was NOT run, so reconcile scaling, expected_mean, actionable and gate status (all downstream of P(play)/participation) were not exercised"]),
       "live_pretip_capture": live,
       "oracle_upper_bound_repo_reported": {"minutes_mae_beyond_E_inj": -0.1686, "ci95": [-0.1829, -0.1536], "n_obs": 52796,
                                            "note": "uses the ACTUAL starter flag (not pregame-knowable); an upper bound on what a confirmed-lineup feed could add, repo-reported not reproduced"},
       "separation": {"feature_availability": "starter observations: see archive.starter_rows and live_pretip_capture", "verified_consumption": "in the participation code a CONFIRMED starter row sets P(play)=0.995 and (fixed rule) does not switch the minutes model; downstream effects of P(play) on reconcile scaling, expected_mean, actionable and gate status are NOT measured here (project.py not run)",
                      "projection_validity": "not established for starter-conditioned projections: no pregame starter history exists", "predictive_improvement": "no starter-ON history exists; oracle bound only",
                      "market_advantage": "none established or tested"}}
(root / "research/audit/verification/NBA_starters_evidence.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print(out["archive"]["rows"], out["archive"]["starter_rows"], out["archive"]["captured_range"])

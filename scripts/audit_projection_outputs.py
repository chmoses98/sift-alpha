"""Build research/audit/verification/projection_outputs.json from pinned checkouts of the sport repos' published-projection branches.
usage: python scripts/audit_projection_outputs.py NBA_LATEST_JSON NBA_COMMIT CBB_CHECKOUT NFL_CHECKOUT   (CBB/NFL checkouts have FETCH_HEAD = projections branch)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_engine import projection_output_audit as po  # noqa: E402

nba_json, nba_commit, cbb, nfl = sys.argv[1:5]
out = {"schema_version": "projection-outputs-1.0",
       "NBA": dict(po.audit(Path(nba_json).read_bytes(), {"repo": "chmoses98/nba-edge-finder", "branch": "projection-data", "commit": nba_commit, "path": "projections/nba/latest.json"}), sport="NBA"),
       "CBB": po.cbb_audit(cbb), "NFL": po.nfl_audit(nfl)}
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(x) for x in o]
    return o


out = clean(out)
p = Path(__file__).resolve().parents[1] / "research/audit/verification/projection_outputs.json"
p.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print({k: (v.get("n_players") or v.get("n_games") or v.get("n_forecasts")) for k, v in out.items() if isinstance(v, dict)})

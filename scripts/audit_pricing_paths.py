"""usage: python scripts/audit_pricing_paths.py CHECKOUT_ROOT   (contains nfl-edge-finder, nba-edge-finder, cbb-edge-finder checkouts)"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from alpha_engine import pricing_path_audit as pa  # noqa: E402

A = root / "research/audit"
cs = json.loads((A / "collection_status.json").read_text())
ms = json.loads((A / "market_specs.json").read_text())["families"]
R = {"NFL": "nfl-edge-finder", "NBA": "nba-edge-finder", "CBB": "cbb-edge-finder"}
res = {}
for fk in pa.PATHS:
    s = fk.split("/")[0]
    rx = {i: x["code"]["regex"] for i, x in cs["sports"][s]["inputs"].items() if x.get("code", {}).get("regex")}
    res[fk] = pa.audit_family(fk, Path(sys.argv[1]) / R[s], ms[fk]["drivers"], rx)
(A / "verification/pricing_paths.json").write_text(json.dumps({"schema_version": "pricing-path-1.0", "families": res}, indent=0, sort_keys=True) + "\n")
print({k: (v["n_files"], sum(1 for i in v["inputs"].values() if i["state"] == "REFERENCED"), len(v["inputs"])) for k, v in res.items()})

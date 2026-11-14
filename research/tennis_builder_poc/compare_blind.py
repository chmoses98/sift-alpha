"""Compare an independent blind re-implementation's output with tennis_ext6 on the same input (RESEARCH_ONLY).

    python research/tennis_builder_poc/compare_blind.py <input.csv> <blind_out.csv> <out.json>
Per column: rows compared on (game_id, team), NaN-pattern mismatches, exact matches at rtol=atol=1e-9, max abs diff. A column MATCHes only if both are clean."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from alpha_engine.features import tennis_ext6 as X  # noqa: E402


def main(inp, blind, out):
    ref = X.compute(X.prepare(pd.read_csv(inp)))["team"]; b = pd.read_csv(blind)
    j = ref.merge(b, on=["game_id", "team"], how="outer", suffixes=("", "__b"), indicator=True)
    res = {"input": str(inp), "n_ref": len(ref), "n_blind": len(b), "keys_identical": bool((j._merge == "both").all()), "inputs": {}}
    for s in X.specs():
        cols = {}
        for c in s.columns:
            if c + "__b" not in j: cols[c] = {"verdict": "MISSING_IN_BLIND"}; continue
            a, z = j[c].to_numpy(float), j[c + "__b"].to_numpy(float); na, nz = np.isnan(a), np.isnan(z); both = ~na & ~nz
            close = np.isclose(a[both], z[both], rtol=1e-9, atol=1e-9)
            cols[c] = {"n_both": int(both.sum()), "nan_pattern_mismatch": int((na != nz).sum()), "match": int(close.sum()),
                       "max_abs_diff": float(np.max(np.abs(a[both] - z[both]))) if both.any() else None,
                       "verdict": "MATCH" if (na == nz).all() and close.all() else "MISMATCH"}
        res["inputs"][s.catalog_id] = {"verdict": "MATCH" if all(v["verdict"] == "MATCH" for v in cols.values()) else "MISMATCH", "columns": cols}
    Path(out).write_text(json.dumps(res, indent=1)); print({k: v["verdict"] for k, v in res["inputs"].items()})


if __name__ == "__main__":
    main(*sys.argv[1:4])

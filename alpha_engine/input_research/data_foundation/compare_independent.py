"""Exact column-by-column comparison of a builder against a BLIND re-implementation's output CSV (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.compare_independent MODULE OUT.json BLIND.csv NOTES.json BRIEF.md -- <args for module.load_raw>

The comparison is computed here from the two value tables (no verdict is taken from the verifier's say-so): a column is MATCH only if the NaN pattern is identical and every non-NaN value agrees to rtol=atol=1e-9 over ALL (game_id, team) rows, and the blind file covers exactly the builder's keys. Output keys match assemble_independent / verified_coverage.load_independent.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main(a=None) -> int:
    a = a or sys.argv[1:]; i = a.index("--"); mod, out, blind, notes, brief = a[:i]; args = a[i + 1:]
    m = importlib.import_module("alpha_engine." + mod); base = m.compute(m.load_raw(*args))["team"]; b = pd.read_csv(blind.split(",")[0])
    for extra in blind.split(",")[1:]:
        b = b.merge(pd.read_csv(extra), on=["game_id", "team"], how="outer")
    j = base.merge(b, on=["game_id", "team"], how="outer", suffixes=("", "_b"), indicator=True)
    keys_ok = bool((j._merge == "both").all()) and not b.duplicated(["game_id", "team"]).any()
    res = {}
    for s in m.specs():
        cols = {}
        for c in s.columns:
            if c + "_b" not in j:
                cols[c] = {"verdict": "MISSING"}; continue
            x, y = j[c].astype(float), j[c + "_b"].astype(float); both = x.notna() & y.notna()
            nanmis = int((x.isna() != y.isna()).sum()); bad = int((~np.isclose(x[both], y[both], rtol=1e-9, atol=1e-9)).sum())
            ok = keys_ok and nanmis == 0 and bad == 0 and int(both.sum()) > 0
            cols[c] = {"n": int(both.sum()), "match": int(both.sum()) - bad, "nan_pattern_mismatch": nanmis, "verdict": "MATCH" if ok else "MISMATCH", "note": "exact (rtol=atol=1e-9) over all keys"}
        res[s.catalog_id] = {"columns": cols}
    amb = json.loads(Path(notes).read_text()).get("ambiguities", [])
    Path(out).write_text(json.dumps({"family": mod, "verifier": "blind Claude agent re-implementation from the brief only; comparison computed by compare_independent.py (agent verification, not human)", "brief_sha256": hashlib.sha256(Path(brief).read_bytes()).hexdigest(),
                                     "blind_csv_sha256": hashlib.sha256(b"".join(Path(x).read_bytes() for x in blind.split(","))).hexdigest(), "keys_identical": keys_ok, "n_rows": int(len(base)), "inputs": res, "ambiguities": amb}, indent=1) + "\n")
    print({k: sorted({c["verdict"] for c in v["columns"].values()}) for k, v in res.items()}); return 0


if __name__ == "__main__":
    raise SystemExit(main())

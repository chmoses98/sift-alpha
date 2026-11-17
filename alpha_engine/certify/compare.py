"""Compare an independent re-implementation against the dataset it certifies (RESEARCH_ONLY).

    python -m alpha_engine.certify.compare --a ORIGINAL.parquet --b INDEPENDENT.parquet --out OUT.json

Keys: game_id (or --key). Every column present in both is compared: numeric columns with |a-b| <= 1e-6*max(1,|a|) and an
identical missing pattern; other columns by exact equality after string normalisation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RTOL = 1e-6


def compare(a: pd.DataFrame, b: pd.DataFrame, key: str = "game_id") -> dict:
    a = a.drop_duplicates(key).set_index(key); b = b.drop_duplicates(key).set_index(key)
    common = a.index.intersection(b.index)
    cols = [c for c in a.columns if c in b.columns]
    res, worst = {}, []
    for c in cols:
        x, y = a.loc[common, c], b.loc[common, c]
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
            X, Y = x.to_numpy(float), y.to_numpy(float)
            nan_mis = np.isnan(X) != np.isnan(Y)
            d = np.abs(np.nan_to_num(X) - np.nan_to_num(Y))
            bad = nan_mis | (d > RTOL * np.maximum(1, np.abs(np.nan_to_num(X))))
            res[c] = {"mismatch": int(bad.sum()), "nan_pattern_mismatch": int(nan_mis.sum()), "max_abs_diff": float(d.max()) if len(d) else 0.0}
        else:
            nx = x.astype(str).str.replace(r"\+00:00$", "", regex=True).str.replace(" 00:00:00", "", regex=False)
            ny = y.astype(str).str.replace(r"\+00:00$", "", regex=True).str.replace(" 00:00:00", "", regex=False)
            bad = (nx != ny).to_numpy()
            res[c] = {"mismatch": int(bad.sum())}
        if bad.any():
            worst += [{"column": c, "game_id": str(g)} for g in common[bad][:5]]
    return {"rows_a": int(len(a)), "rows_b": int(len(b)), "rows_common": int(len(common)), "only_a": int(len(a.index.difference(b.index))),
            "only_b": int(len(b.index.difference(a.index))), "columns_compared": len(cols), "columns_only_a": [c for c in a.columns if c not in b.columns],
            "columns_only_b": [c for c in b.columns if c not in a.columns], "cells_mismatched": int(sum(v["mismatch"] for v in res.values())),
            "columns_with_mismatch": {k: v for k, v in res.items() if v["mismatch"]}, "examples": worst[:40],
            "identical_within_tolerance": bool(len(common) == len(a) == len(b) and not any(v["mismatch"] for v in res.values()))}


def main(x=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--a", required=True); ap.add_argument("--b", required=True); ap.add_argument("--out")
    ap.add_argument("--key", default="game_id", help="row key column (default game_id; player datasets use key)")
    p = ap.parse_args(x)
    r = compare(pd.read_parquet(p.a), pd.read_parquet(p.b), p.key)
    if p.out:
        Path(p.out).write_text(json.dumps(r, indent=1) + "\n")
    print(json.dumps(r, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

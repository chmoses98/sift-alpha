"""Head-to-head: a discovery study's full model vs the sport repository's archived PRODUCTION projections (RESEARCH_ONLY).

    python -m alpha_engine.discovery.production_h2h --sport CBB --pred PRED.parquet --dataset DATASET.parquet \
        --production PROD.parquet --out research/discovery/production_h2h_cbb.json

PRED is the study's `--pred-out` file (walk-forward predictions; season S is fitted on seasons before S only). PROD is a table of the
last projection archived BEFORE each game's start (columns: game_id, margin, total, p_home, generated_utc, start_utc) extracted from
the sport repository's append-only projection archive. Outcomes come from the certified dataset. Identical games only; paired
differences with date-clustered bootstrap CIs. No market data is read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _ci(v: np.ndarray, c: np.ndarray, n_boot: int = 2000, seed: int = 7) -> list[float]:
    g = pd.DataFrame({"v": v, "c": c}).groupby("c")["v"].agg(["sum", "count"])
    s, n = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(n_boot, len(s)))
    est = s[idx].sum(1) / n[idx].sum(1)
    return [round(float(np.quantile(est, .025)), 4), round(float(np.quantile(est, .975)), 4)]


def _ncdf(z):
    from scipy.stats import norm

    return norm.cdf(z)


def compare(pred: pd.DataFrame, data: pd.DataFrame, prod: pd.DataFrame, margin_col: str = "y_home_margin", total_col: str = "y_total") -> dict:
    d = data[["game_id", "date", margin_col, total_col]].merge(pred, on="game_id").merge(prod, on="game_id", suffixes=("", "_prod"))
    d = d.dropna(subset=[margin_col, total_col, "margin_mu", "margin"])
    c = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d").to_numpy()      # date clusters (a few weeks of games)
    out = {"n_games": int(len(d)), "dates": [str(d["date"].min()), str(d["date"].max())]}
    for nm, a, b, y in (("margin", "margin", "margin_mu", margin_col), ("total", "total", "total_mu", total_col)):
        if b not in d:
            continue
        ea, eb = d[a] - d[y], d[b] - d[y]
        out[nm] = {"production": {"mae": round(float(ea.abs().mean()), 3), "rmse": round(float(np.sqrt((ea ** 2).mean())), 3), "bias": round(float(ea.mean()), 3)},
                   "challenger": {"mae": round(float(eb.abs().mean()), 3), "rmse": round(float(np.sqrt((eb ** 2).mean())), 3), "bias": round(float(eb.mean()), 3)},
                   "delta_mae_challenger_minus_production": [round(float((eb.abs() - ea.abs()).mean()), 3), _ci((eb.abs() - ea.abs()).to_numpy(), c)],
                   "delta_mse_challenger_minus_production": [round(float((eb ** 2 - ea ** 2).mean()), 2), _ci((eb ** 2 - ea ** 2).to_numpy(), c)]}
    y = (d[margin_col] > 0).astype(float).to_numpy()
    pa = np.clip(d["p_home"].to_numpy(float), 1e-4, 1 - 1e-4)
    pb = np.clip(_ncdf(d["margin_mu"] / d["margin_sigma"]), 1e-4, 1 - 1e-4) if "margin_sigma" in d else None
    out["winner"] = {"production_brier": round(float(((pa - y) ** 2).mean()), 4)}
    if pb is not None:
        db = (pb - y) ** 2 - (pa - y) ** 2
        out["winner"].update({"challenger_brier": round(float(((pb - y) ** 2).mean()), 4), "delta": [round(float(db.mean()), 4), _ci(db, c)]})
    # blend (exploratory, not preregistered)
    em = (d["margin"] + d["margin_mu"]) / 2 - d[margin_col]
    out["blend_exploratory_margin_mae"] = round(float(em.abs().mean()), 3)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--production", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    r = compare(pd.read_parquet(a.pred), pd.read_parquet(a.dataset), pd.read_parquet(a.production))
    r = {"schema": "production-h2h-1.0", "status": "RESEARCH_ONLY", "sport": a.sport, "note": a.note, **r}
    Path(a.out).write_text(json.dumps(r, indent=1) + "\n")
    print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

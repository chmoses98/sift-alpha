"""Dependence between game-line outcomes: how far joint probabilities are from the product of the legs (RESEARCH_ONLY).

    python -m alpha_engine.discovery.joint --sport NFL --dataset DS.parquet --market PATH --first-season 2010 --out research/discovery/joint_dependence_NFL.json

Events are defined against the contemporaneous sportsbook closing line held in the market side-table (never a feature):
  COVER = favourite beats the spread, OVER = total above the closing total, FAVWIN = favourite wins outright. Pushes are excluded.
For each pair: marginal rates, joint rate, product of marginals, joint / product, phi correlation, with a season-week cluster bootstrap.
`by_spread` repeats FAVWIN x OVER and COVER x OVER by size of the closing spread. A ratio of 1.00 means multiplying leg probabilities is right
for that pair; this measures realised dependence only and says nothing about prices.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..input_research import stats as S
from .adapters import ADAPTERS, MARKET_NOTE


def pair(a: np.ndarray, b: np.ndarray, keys: np.ndarray) -> dict:
    ok = ~np.isnan(a) & ~np.isnan(b); a, b, keys = a[ok], b[ok], keys[ok]
    if len(a) < 100:
        return {"n": int(len(a))}
    pa, pb, pj = a.mean(), b.mean(), (a * b).mean()
    boot = S.ClusterBoot(keys); A, B, J = boot.means(a), boot.means(b), boot.means(a * b)
    ratio = J / (A * B); phi = (J - A * B) / np.sqrt(A * (1 - A) * B * (1 - B))
    q = lambda x: [round(float(np.quantile(x, 0.025)), 4), round(float(np.quantile(x, 0.975)), 4)]
    return {"n": int(len(a)), "p_a": round(float(pa), 4), "p_b": round(float(pb), 4), "p_joint": round(float(pj), 4), "p_product": round(float(pa * pb), 4),
            "joint_over_product": round(float(pj / (pa * pb)), 4), "joint_over_product_ci95": q(ratio),
            "phi": round(float((pj - pa * pb) / np.sqrt(pa * (1 - pa) * pb * (1 - pb))), 4), "phi_ci95": q(phi)}


def run(d: pd.DataFrame, m: pd.DataFrame, margin: str, total: str, first_season: int, buckets) -> dict:
    d = d[(d.season >= first_season) & d[margin].notna()].reset_index(drop=True)
    m = m.set_axis(m.index.astype(str)).reindex(d.game_id.astype(str)).reset_index(drop=True)
    L, T, y, t = m.spread_line.to_numpy(float), m.total_line.to_numpy(float), d[margin].to_numpy(float), d[total].to_numpy(float)
    fav = np.sign(L)                                    # +1 home favourite, -1 away favourite, 0 pick'em (excluded)
    nanif = lambda v, bad: np.where(bad, np.nan, v)
    cover = nanif((fav * (y - L) > 0).astype(float), (fav == 0) | np.isnan(L) | (y == L))
    favwin = nanif((fav * y > 0).astype(float), (fav == 0) | np.isnan(L) | (y == 0))
    over = nanif((t > T).astype(float), np.isnan(T) | (t == T))
    order = "gameday" if "gameday" in d else "date"
    keys = (d.season.astype(str) + "-" + pd.to_datetime(d[order]).dt.strftime("%G-%V")).to_numpy()
    out = {"games": int(len(d)), "seasons": [int(d.season.min()), int(d.season.max())],
           "pairs": {"FAVWIN x OVER": pair(favwin, over, keys), "COVER x OVER": pair(cover, over, keys), "FAVWIN x COVER": pair(favwin, cover, keys)}, "by_spread": []}
    for lo, hi in buckets:
        k = (np.abs(L) >= lo) & (np.abs(L) < hi)
        out["by_spread"].append({"abs_spread": [lo, hi], "FAVWIN x OVER": pair(favwin[k], over[k], keys[k]), "COVER x OVER": pair(cover[k], over[k], keys[k])})
    half = d.season <= d.season.median()
    out["stability"] = {"first_half_seasons": pair(favwin[half.to_numpy()], over[half.to_numpy()], keys[half.to_numpy()]), "second_half_seasons": pair(favwin[~half.to_numpy()], over[~half.to_numpy()], keys[~half.to_numpy()])}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--sport", required=True); ap.add_argument("--dataset", required=True); ap.add_argument("--market", required=True)
    ap.add_argument("--first-season", type=int, default=0); ap.add_argument("--last-season", type=int, default=9999); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    d = pd.read_parquet(a.dataset); d = d[d.season <= a.last_season]
    r = run(d, ADAPTERS[a.sport]["market"](a.market), "y_home_margin", "y_total", a.first_season, [[0.5, 3.5], [3.5, 7.5], [7.5, 14.5], [14.5, 99]])
    r = {"schema": "joint-dependence-1.0", "status": "RESEARCH_ONLY", "sport": a.sport, "market_note": MARKET_NOTE.get(a.sport), **r,
         "reading": "joint_over_product = 1 means the two legs behaved independently; FAVWIN x COVER is the mechanical dependence between two views of the same margin."}
    Path(a.out).write_text(json.dumps(r, indent=1) + "\n"); print(json.dumps({k: (v.get("joint_over_product"), v.get("joint_over_product_ci95"), v.get("phi")) for k, v in r["pairs"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

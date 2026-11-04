#!/usr/bin/env python3
"""Market-only scan of every NFL family with horizon quotes (RESEARCH_ONLY; no model, no selection signal): which families/horizons come closest to a positive
net-of-fee return when buying at the ask and holding to settlement, judged chronologically (weeks 1-6 discovery / 7-12 validation / 13+ holdout) with games as clusters.
This is a benchmark for outcome models (the market-implied probability), NOT a trading rule.  usage: outcome_family_scan.py --horizons DIR --out reports/exec_track/outcome_family_scan.json"""
import argparse, collections, glob, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_exec import fees as FE      # noqa: E402
from sift_research import stats as S  # noqa: E402

HOR = ("T-168h", "T-24h", "T-90m")
SPLIT = lambda w: "discovery" if w <= 6 else "validation" if w <= 12 else "holdout"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", required=True); ap.add_argument("--out", required=True); ap.add_argument("--min-n", type=int, default=150)
    a = ap.parse_args(argv)
    cells = collections.defaultdict(list)
    n_rows = n_used = 0
    for p in sorted(glob.glob(os.path.join(a.horizons, "[0-9]*.jsonl"))):
        for l in open(p):
            r = json.loads(l); n_rows += 1
            if r.get("result") not in ("yes", "no") or r.get("anchor_kind") != "kickoff" or not r.get("week") or not r.get("game_id"):
                continue
            try:
                w = int(r["week"]); season = int(r["season"])
            except (TypeError, ValueError):
                continue
            if season != 2025:
                continue
            y = 1 if r["result"] == "yes" else 0
            for h in HOR:
                s = (r.get("snaps") or {}).get(h)
                if not s or s.get("book_empty") or s.get("bid") is None or s.get("ask") is None or not (0 < s["bid"] < s["ask"] < 1) or s["ask"] - s["bid"] > 0.10 or s.get("age_min", 0) > 120:
                    continue
                n_used += 1
                for side, price, win in (("YES", round(s["ask"] * 100), y), ("NO", round((1 - s["bid"]) * 100), 1 - y)):
                    net = 100 * win - price - 100 * FE.order_fee(price, 10, FE.TAKER_COEF) / 10
                    cells[(r["series"], h, side)].append((r["game_id"], w, net))
    rows = []
    for (s, h, side), L in cells.items():
        by = {sp: [x for x in L if SPLIT(x[1]) == sp] for sp in ("discovery", "validation", "holdout")}
        if len(L) < a.min_n or any(len(v) < 30 for v in by.values()):
            continue
        res = {}
        for sp, v in by.items():
            r = S.cluster_bootstrap([x[2] for x in v], [x[0] for x in v], 500, 3)
            res[sp] = dict(mean=round(r["mean"], 3), lo=round(r["lo"], 3), hi=round(r["hi"], 3), n=r["n"], games=r["n_clusters"], p=r["p"])
        rows.append(dict(series=s, horizon=h, side=side, n=len(L), **res))
    # multiple testing over every cell tried: holdout one-sided p (mean>0), Holm and BH
    p1 = [(r["holdout"]["p"] / 2 if r["holdout"]["mean"] > 0 else 1 - r["holdout"]["p"] / 2) for r in rows]
    holm, bh = S.holm(p1), S.benjamini_hochberg(p1)
    for r, h_, b_ in zip(rows, holm, bh):
        r["holdout_p_one_sided_holm"], r["holdout_bh_q"] = round(float(h_), 4), round(float(b_), 4)
    rows.sort(key=lambda r: -(min(r["validation"]["mean"], r["holdout"]["mean"])))
    out = dict(version="sift-exec-family-scan/1", status="RESEARCH_ONLY", horizon_rows_read=n_rows, quote_observations_used=n_used, cells_tried=len(rows),
               design="buy at the ask (taker fee 0.07, 10-lot) and hold; weeks 1-6 / 7-12 / 13+; cluster = game; ranking = min(validation mean, holdout mean); multiple-testing over every cell",
               cells_with_positive_validation_and_holdout_mean=sum(r["validation"]["mean"] > 0 and r["holdout"]["mean"] > 0 for r in rows),
               cells_passing_holdout_holm_0p10=sum(r["holdout_p_one_sided_holm"] < 0.10 and r["holdout"]["mean"] > 0 for r in rows), top=rows[:12],
               by_family_unconditional=None)
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("horizon_rows_read", "quote_observations_used", "cells_tried", "cells_with_positive_validation_and_holdout_mean", "cells_passing_holdout_holm_0p10")}))
    for r in rows[:8]:
        print(r["series"], r["horizon"], r["side"], "n", r["n"], "val", r["validation"]["mean"], "hold", r["holdout"]["mean"], (r["holdout"]["lo"], r["holdout"]["hi"]), "holm", r["holdout_p_one_sided_holm"])


if __name__ == "__main__":
    main()

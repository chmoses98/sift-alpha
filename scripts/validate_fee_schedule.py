#!/usr/bin/env python3
"""Empirical Kalshi fee-schedule validation from exchange-REPORTED entry fees (aggregates only).

    validate_fee_schedule.py --wagers FILE_OR_DIR [FILE_OR_DIR ...] --out out.json

For each opening BUY with exchange-reported (non-estimated) fees: implied_rate = fee / (contracts * p * (1-p)).
The taker schedule is rate 0.07 rounded UP to the cent per order; the assumed maker schedule is 0.0175 (UNVERIFIED).
A wager can aggregate several fills, so per-wager rounding is a tolerance, not an exact test: a wager is classed
TAKER if |fee - taker_model| <= tol, MAKER_QUARTER if |fee - maker_model| <= tol, ZERO if fee == 0, else OTHER.
Output is by series prefix (e.g. KXNBASPREAD): counts and class shares only. No tickers, prices, amounts or ids.
"""
import argparse, glob, json, math, os, sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sift_clv import canonical as C  # noqa: E402

KEYS = {"ticker": ("market_ticker", "ticker"), "count": ("contracts",), "price": ("execution_price", "actual_price"), "fee": ("fees_paid", "fees")}


def pick(w, names):
    for n in names:
        if w.get(n) is not None:
            return w[n]
    return None


def rows(paths):
    for p in paths:
        files = [p] if os.path.isfile(p) else sorted(glob.glob(os.path.join(p, "**", "*"), recursive=True))
        for f in files:
            if not os.path.isfile(f) or not f.endswith((".jsonl", ".json")):
                continue
            try:
                txt = open(f).read()
                data = [json.loads(l) for l in txt.splitlines() if l.strip()] if f.endswith(".jsonl") else json.loads(txt)
            except Exception:
                continue
            if isinstance(data, dict):
                data = next((v for v in data.values() if isinstance(v, list)), [data])
            for w in data:
                if isinstance(w, dict):
                    yield w


def classify(fee, count, price, tol):
    t = float(C.estimate_fee(Decimal(str(price)), Decimal(str(count)), role="taker"))
    m = float(C.estimate_fee(Decimal(str(price)), Decimal(str(count)), role="maker"))
    if fee == 0:
        return "ZERO_FEE"
    if abs(fee - t) <= tol * max(1.0, t):
        return "TAKER_0.07"
    if abs(fee - m) <= tol * max(1.0, m):
        return "MAKER_0.0175"
    return "OTHER"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wagers", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tol", type=float, default=0.03, help="relative tolerance (aggregated fills and cent rounding)")
    a = ap.parse_args()
    by = defaultdict(lambda: defaultdict(int))
    rates = defaultdict(list)
    excluded = defaultdict(int)
    for w in rows(a.wagers):
        if w.get("fees_are_estimated") is True:
            excluded["estimated_fee"] += 1
            continue
        t, c, p, f = (pick(w, KEYS[k]) for k in ("ticker", "count", "price", "fee"))
        if None in (t, c, p, f) or not (0 < float(p) < 1) or float(c) <= 0:
            excluded["missing_or_invalid"] += 1
            continue
        series = str(t).split("-")[0]
        cls = classify(float(f), float(c), float(p), a.tol)
        by[series][cls] += 1
        by[series]["n"] += 1
        rates[series].append(float(f) / (float(c) * float(p) * (1 - float(p))))
    out = {"schema": "sift-fee-validation/1", "privacy": "aggregates only; no tickers, prices, amounts or ids",
           "taker_model": "ceil_cent(0.07*C*P*(1-P))", "maker_model_assumed_unverified": "ceil_cent(0.0175*C*P*(1-P))",
           "tolerance_relative": a.tol, "excluded": dict(excluded), "by_series": {}}
    for s, d in sorted(by.items()):
        r = sorted(rates[s])
        out["by_series"][s] = {**dict(d), "implied_rate_median": round(r[len(r) // 2], 5),
                               "implied_rate_min": round(r[0], 5), "implied_rate_max": round(r[-1], 5)}
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    for s, d in out["by_series"].items():
        print(s, {k: v for k, v in d.items()})


if __name__ == "__main__":
    main()

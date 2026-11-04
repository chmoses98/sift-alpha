#!/usr/bin/env python3
"""NFL shadow-v2 (HYPOTHETICAL model selections, not bets): early-entry TAKER vs a closing buyer, by horizon / family / price.

    recalc_nfl_shadow_exec.py --clv-root R1 R2 --out out.json

For a record bought at the horizon ASK on the model-preferred side (what an immediate taker would have paid):
    selection          close_mid  - horizon_mid                    fair-value movement (no spread, no fee)
    early_advantage    close_ask  - horizon_ask         (B)        >0: the early taker paid LESS than a closing buyer
    quoted_exec        close_mid  - horizon_ask         (D)        the midpoint mark-to-market of that early purchase
    half-spread terms  entry_half = horizon_ask - horizon_mid ; close_half = close_ask - close_mid
Identity:  early_advantage = selection + (close_half - entry_half).  A widening closing spread therefore inflates the
"advantage" with no change in fair value; both parts are reported so it cannot be mistaken for skill.
Fees: both buyers are takers, so the fee difference is fee(horizon_ask) - fee(close_ask) (modelled, tiny); the entry fee
itself is reported on its own and is not part of the price comparison.
Gates (as in recalc_nfl_shadow_clv): CLV_OK, close age <= 3600 s, one record per (game, ticker, horizon, arm), cluster = game.
Horizons present in the corpus: CYCLE, T-24h, T-6h, T-90m, T-30m (no T-48h / T-12h / T-1h exist; not invented).
"""
import argparse, glob, gzip, json, os, random, statistics, sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sift_clv import canonical as C  # noqa: E402

M = ("selection", "early_advantage", "quoted_exec", "entry_half_spread", "close_half_spread", "fee_delta", "entry_fee")
EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)


def fam(t):
    return t.split("-")[0] if t else "?"


def bucket(p):
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= p < hi:
            return f"{lo:.1f}-{min(hi, 1.0):.1f}"
    return "unknown"


def fee(p):
    return float(C.estimate_fee(Decimal(str(round(p, 4))), 100, role="taker") / 100)


class G:
    __slots__ = ("v", "g")

    def __init__(self):
        self.v = {m: [] for m in M}
        self.g = {m: defaultdict(lambda: [0.0, 0]) for m in M}

    def add(self, game, vals):
        for m, x in zip(M, vals):
            self.v[m].append(x)
            a = self.g[m][game]
            a[0] += x
            a[1] += 1


def boot(gs, reps=1200, seed=5):
    keys = list(gs)
    if len(keys) < 2:
        return None
    rng, ms, arr = random.Random(seed), [], [gs[k] for k in keys]
    for _ in range(reps):
        s = n = 0
        for _ in keys:
            a = arr[rng.randrange(len(arr))]
            s += a[0]; n += a[1]
        ms.append(s / n)
    ms.sort()
    return [round(100 * ms[int(.025 * reps)], 4), round(100 * ms[int(.975 * reps)], 4)]


def cell(g, ci=True):
    out = {"n": len(g.v["selection"]), "games": len(g.g["selection"])}
    for m in M:
        xs = g.v[m]
        if not xs:
            continue
        st = {"mean_cents": round(100 * sum(xs) / len(xs), 4), "median_cents": round(100 * statistics.median(xs), 4),
              "positive_pct": round(100 * sum(x > 0 for x in xs) / len(xs), 2),
              "zero_pct": round(100 * sum(x == 0 for x in xs) / len(xs), 2)}
        if ci and m in ("selection", "early_advantage", "quoted_exec") and len(xs) >= 30:
            st["game_cluster_ci95_cents"] = boot(g.g[m])
        out[m] = st
    if g.v["selection"]:
        k = len(g.v["selection"])
        out["identity_check_cents"] = round(100 * (sum(g.v["early_advantage"]) - sum(g.v["selection"])
                                                    - sum(g.v["close_half_spread"]) + sum(g.v["entry_half_spread"])) / k, 6)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clv-root", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-age", type=float, default=3600.0)
    ap.add_argument("--min-n", type=int, default=100)
    ap.add_argument("--min-games", type=int, default=10)
    a = ap.parse_args()
    seen, counts = set(), defaultdict(int)
    dims = {k: defaultdict(G) for k in ("horizon", "family", "price_bucket", "week", "split")}
    overall = G()
    for path in sorted(p for r in a.clv_root for p in glob.glob(os.path.join(r, "*", "*.clv_v2.jsonl.gz"))):
        game = os.path.basename(os.path.dirname(path))
        week = game.split("_")[1] if "_" in game else "?"
        with gzip.open(path, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                counts["records"] += 1
                if r.get("clv_status") != "CLV_OK":
                    continue
                side = r.get("model_side")
                if side not in ("YES", "NO"):
                    continue
                ask, cask = r.get("entry_executable_price"), r.get("close_executable_price_same_side")
                sel, qex = r.get("clv_mid_toward_model"), r.get("clv_exec_toward_model")
                hmid = r.get("horizon_yes_mid") if side == "YES" else r.get("horizon_no_mid")
                if None in (ask, cask, sel, qex, hmid):
                    counts["dropped_missing_field"] += 1
                    continue
                age = r.get("close_age_seconds")
                if age is None or age > a.max_age:
                    counts["dropped_stale_or_unaged_close"] += 1
                    continue
                key = (game, r.get("ticker"), r.get("horizon_label"), r.get("model_arm"))
                if key in seen:
                    counts["dropped_duplicate_key"] += 1
                    continue
                seen.add(key)
                cmid = ask + qex
                if not (0 < ask < 1 and 0 < cask < 1):
                    counts["dropped_sentinel_price"] += 1
                    continue
                counts["kept"] += 1
                vals = (sel, cask - ask, qex, ask - hmid, cask - cmid, fee(ask) - fee(cask), fee(ask))
                overall.add(game, vals)
                dims["horizon"][str(r.get("horizon_label"))].add(game, vals)
                dims["family"][fam(r.get("ticker"))].add(game, vals)
                dims["price_bucket"][bucket(ask)].add(game, vals)
                dims["week"][week].add(game, vals)
                dims["split"]["weeks_01-04" if week.isdigit() and int(week) <= 4 else "weeks_05-08"].add(game, vals)
    res = {"definition": __doc__.strip().splitlines()[0], "counts": dict(counts), "overall": cell(overall), "by": {}}
    for d, groups in dims.items():
        res["by"][d] = {k: cell(g) for k, g in sorted(groups.items())}
    ranked = [(k, v) for k, v in res["by"]["family"].items() if v["n"] >= a.min_n and v["games"] >= a.min_games]
    res["rank_basis"] = f"family cells with n>={a.min_n} records and >={a.min_games} games"
    res["ranked_families_by_early_advantage"] = [
        {"family": k, "n": v["n"], "games": v["games"], "early_advantage_cents": v["early_advantage"]["mean_cents"],
         "ci95_cents": v["early_advantage"].get("game_cluster_ci95_cents"), "selection_cents": v["selection"]["mean_cents"],
         "spread_change_cents": round(v["close_half_spread"]["mean_cents"] - v["entry_half_spread"]["mean_cents"], 4)}
        for k, v in sorted(ranked, key=lambda kv: -kv[1]["early_advantage"]["mean_cents"])]
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True)
    o = res["overall"]
    print(res["counts"])
    for m in ("selection", "early_advantage", "quoted_exec", "entry_half_spread", "close_half_spread", "fee_delta"):
        print(" ", m, o[m]["mean_cents"], o[m].get("game_cluster_ci95_cents"))
    print("  identity residual (cents):", o["identity_check_cents"])


if __name__ == "__main__":
    main()

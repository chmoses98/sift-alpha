#!/usr/bin/env python3
"""NFL shadow-v2 (HYPOTHETICAL model selections, not real bets): re-aggregate the published clv-2.0.0 records.

Separates the three quantities the producing evaluator stores, and applies the canonical eligibility gates:
  selection     clv_mid_toward_model   horizon mid -> close mid on the model side; fee- and spread-exclusive
  quoted_exec   clv_exec_toward_model  close mid - horizon ASK; pre-fee; includes the half-spread
  fee_adjusted  clv_net_of_fee         quoted_exec - MODELLED entry fee, once (a schedule estimate, never a fill)
  spread_drag   selection - quoted_exec  (derived; = the entry half-spread actually paid)
  fee_drag      quoted_exec - fee_adjusted

Gates (after): clv_status == CLV_OK, close_age_seconds <= max_age, one record per (game, ticker, horizon, arm),
cluster = game.  "Before" = every CLV_OK record pooled as published (no age gate, no de-duplication).
Breakdowns: family, entry horizon, entry-price bucket, week (chronological), each with a game-clustered bootstrap CI.
"""
import argparse, glob, gzip, json, os, random, statistics
from collections import defaultdict

FIELDS = ("selection", "quoted_exec", "fee_adjusted")
PRICE_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)


def fam(t):
    return t.split("-")[0] if t else "?"


def price_bucket(p):
    if p is None:
        return "unknown"
    for lo, hi in zip(PRICE_EDGES, PRICE_EDGES[1:]):
        if lo <= p < hi:
            return f"{lo:.1f}-{min(hi, 1.0):.1f}"
    return "unknown"


class Group:
    """Values for one cell: per-game (sum, n) for the clustered bootstrap, raw values for median / positive rate."""
    __slots__ = ("vals", "game")

    def __init__(self):
        self.vals = {f: [] for f in FIELDS}
        self.game = {f: defaultdict(lambda: [0.0, 0]) for f in FIELDS}

    def add(self, game, sel, qex, net):
        for f, v in zip(FIELDS, (sel, qex, net)):
            if v is None:
                continue
            self.vals[f].append(v)
            g = self.game[f][game]
            g[0] += v
            g[1] += 1


def boot(game_sums, reps=1500, seed=11):
    keys = list(game_sums)
    if len(keys) < 2:
        return None
    rng, ms = random.Random(seed), []
    sums = [game_sums[k] for k in keys]
    for _ in range(reps):
        s = n = 0
        for _ in keys:
            a = sums[rng.randrange(len(sums))]
            s += a[0]
            n += a[1]
        ms.append(s / n)
    ms.sort()
    return [ms[int(.025 * reps)], ms[int(.975 * reps)]]


def stats(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "median": statistics.median(xs),
            "positive_pct": 100 * sum(x > 0 for x in xs) / len(xs), "zero_pct": 100 * sum(x == 0 for x in xs) / len(xs),
            "negative_pct": 100 * sum(x < 0 for x in xs) / len(xs)}


def cell(g, with_ci=True):
    out = {"games": len(g.game["selection"])}
    for f in FIELDS:
        s = stats(g.vals[f])
        if with_ci and s.get("n", 0) >= 30:
            s["game_cluster_ci95"] = boot(g.game[f])
        out[f] = s
    if g.vals["selection"] and g.vals["quoted_exec"]:
        out["spread_drag_mean"] = out["selection"]["mean"] - out["quoted_exec"]["mean"]
    if g.vals["quoted_exec"] and g.vals["fee_adjusted"]:
        out["fee_drag_mean"] = out["quoted_exec"]["mean"] - out["fee_adjusted"]["mean"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clv-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-age", type=float, default=3600.0)
    ap.add_argument("--min-n", type=int, default=100, help="minimum records for a cell to be ranked")
    ap.add_argument("--min-games", type=int, default=10, help="minimum games for a cell to be ranked")
    a = ap.parse_args()
    before = {f: [] for f in FIELDS}
    seen, counts = set(), defaultdict(int)
    overall = Group()
    dims = {"family": defaultdict(Group), "horizon": defaultdict(Group), "price_bucket": defaultdict(Group),
            "week": defaultdict(Group)}
    for path in sorted(glob.glob(os.path.join(a.clv_root, "*", "*.clv_v2.jsonl.gz"))):
        game = os.path.basename(os.path.dirname(path))
        week = game.split("_")[1] if "_" in game else "?"
        with gzip.open(path, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                counts["records"] += 1
                counts["status_" + str(r.get("clv_status"))] += 1
                if r.get("clv_status") != "CLV_OK":
                    continue
                sel, qex, net = r.get("clv_mid_toward_model"), r.get("clv_exec_toward_model"), r.get("clv_net_of_fee")
                if sel is None or qex is None:
                    continue
                for f, v in zip(FIELDS, (sel, qex, net)):
                    if v is not None:
                        before[f].append(v)
                age = r.get("close_age_seconds")
                if age is None or age > a.max_age:
                    counts["dropped_stale_or_unaged_close"] += 1
                    continue
                key = (game, r.get("ticker"), r.get("horizon_label"), r.get("model_arm"))
                if key in seen:
                    counts["dropped_duplicate_key"] += 1
                    continue
                seen.add(key)
                counts["kept"] += 1
                overall.add(game, sel, qex, net)
                dims["family"][fam(r.get("ticker"))].add(game, sel, qex, net)
                dims["horizon"][str(r.get("horizon_label"))].add(game, sel, qex, net)
                dims["price_bucket"][price_bucket(r.get("entry_executable_price"))].add(game, sel, qex, net)
                dims["week"][week].add(game, sel, qex, net)
    out = {"definition": __doc__.strip().splitlines()[0], "counts": dict(counts), "max_close_age_seconds": a.max_age,
           "unit": "probability points (dollars per contract); positive = market moved toward / beat the benchmark",
           "before_pooled_as_published": {f: stats(v) for f, v in before.items()},
           "after_gated_deduped": cell(overall), "by": {}}
    for d, groups in dims.items():
        out["by"][d] = {k: cell(g, with_ci=True) for k, g in sorted(groups.items())}
    # rankings: only cells with enough records AND games, ranked by fee-adjusted mean and by selection mean
    fam_cells = [(k, v) for k, v in out["by"]["family"].items()
                 if v["selection"]["n"] >= a.min_n and v["games"] >= a.min_games]
    out["rank_basis"] = f"family cells with n>={a.min_n} records and >={a.min_games} games"
    out["ranked_families_by_selection"] = [
        {"family": k, "n": v["selection"]["n"], "games": v["games"], "selection_mean": v["selection"]["mean"],
         "selection_ci95": v["selection"].get("game_cluster_ci95"), "quoted_exec_mean": v["quoted_exec"]["mean"],
         "fee_adjusted_mean": v["fee_adjusted"].get("mean")} for k, v in sorted(fam_cells, key=lambda kv: -kv[1]["selection"]["mean"])]
    out["ranked_families_by_fee_adjusted"] = [
        {"family": k, "n": v["fee_adjusted"]["n"], "games": v["games"], "fee_adjusted_mean": v["fee_adjusted"]["mean"],
         "ci95": v["fee_adjusted"].get("game_cluster_ci95")}
        for k, v in sorted(fam_cells, key=lambda kv: -kv[1]["fee_adjusted"].get("mean", -9))]
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps({k: out[k] for k in ("counts", "after_gated_deduped")}, indent=1, sort_keys=True)[:2500])


if __name__ == "__main__":
    main()

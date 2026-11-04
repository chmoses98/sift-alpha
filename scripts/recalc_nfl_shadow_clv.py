#!/usr/bin/env python3
"""NFL shadow-v2 (HYPOTHETICAL model selections, not real bets): re-aggregate the published clv-2.0.0 records.

Separates the three quantities the producing evaluator already stores, and applies the canonical eligibility gates:
  selection        clv_mid_toward_model   (horizon mid -> close mid, model side, fee- and spread-exclusive)
  quoted_exec      clv_exec_toward_model  (close mid - horizon ASK; pre-fee; includes the half-spread)
  fee_adjusted     clv_net_of_fee         (quoted_exec - MODELLED entry fee, once)  -- a schedule estimate, not a fill
Gates (after): clv_status == CLV_OK, close_age_seconds <= max_age, one observation per (game, ticker, horizon, arm),
cluster = game.  "Before" = every CLV_OK record pooled as published (no age gate, no de-duplication).
"""
import argparse, glob, gzip, json, os, random, statistics
from collections import defaultdict


def fam(t):
    return t.split("-")[0] if t else "?"


def stats(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "median": statistics.median(xs),
            "positive_pct": 100 * sum(x > 0 for x in xs) / len(xs), "zero_pct": 100 * sum(x == 0 for x in xs) / len(xs)}


def boot(by_game, reps=2000, seed=11):
    keys = list(by_game)
    if len(keys) < 2:
        return None
    rng, ms = random.Random(seed), []
    for _ in range(reps):
        v = [x for k in (rng.choice(keys) for _ in keys) for x in by_game[k]]
        ms.append(sum(v) / len(v))
    ms.sort()
    return [ms[int(.025 * reps)], ms[int(.975 * reps)]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clv-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-age", type=float, default=3600.0)
    a = ap.parse_args()
    before = defaultdict(list)           # field -> values (pooled, as published)
    seen, after = set(), defaultdict(lambda: defaultdict(list))   # after[field][game] -> values
    fam_after = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    counts = defaultdict(int)
    for path in sorted(glob.glob(os.path.join(a.clv_root, "*", "*.clv_v2.jsonl.gz"))):
        game = os.path.basename(os.path.dirname(path))
        with gzip.open(path, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                counts["records"] += 1
                counts["status_" + str(r.get("clv_status"))] += 1
                if r.get("clv_status") != "CLV_OK":
                    continue
                m, x, n = r.get("clv_mid_toward_model"), r.get("clv_exec_toward_model"), r.get("clv_net_of_fee")
                if m is None or x is None:
                    continue
                before["selection"].append(m); before["quoted_exec"].append(x)
                if n is not None:
                    before["fee_adjusted"].append(n)
                age = r.get("close_age_seconds")
                if age is None or age > a.max_age:
                    counts["dropped_stale_or_unaged_close"] += 1
                    continue
                key = (game, r.get("ticker"), r.get("horizon_label"), r.get("model_arm"))
                if key in seen:
                    counts["dropped_duplicate_key"] += 1
                    continue
                seen.add(key)
                f = fam(r.get("ticker"))
                for name, v in (("selection", m), ("quoted_exec", x), ("fee_adjusted", n)):
                    if v is not None:
                        after[name][game].append(v)
                        fam_after[f][name][game].append(v)
    out = {"counts": dict(counts), "max_close_age_seconds": a.max_age, "before_pooled_as_published":
           {k: stats(v) for k, v in before.items()}, "after_gated_deduped": {}, "by_family_after": {}}
    for name, g in after.items():
        flat = [x for v in g.values() for x in v]
        out["after_gated_deduped"][name] = {**stats(flat), "games": len(g), "game_cluster_ci95": boot(g)}
    for f, d in sorted(fam_after.items(), key=lambda kv: -sum(len(v) for v in kv[1]["selection"].values())):
        sel = [x for v in d["selection"].values() for x in v]
        if len(sel) < 30:
            continue
        ex = [x for v in d["quoted_exec"].values() for x in v]
        fa = [x for v in d["fee_adjusted"].values() for x in v]
        out["by_family_after"][f] = {"n": len(sel), "games": len(d["selection"]),
                                     "selection_mean": sum(sel) / len(sel), "selection_ci95": boot(d["selection"]),
                                     "quoted_exec_mean": sum(ex) / len(ex),
                                     "fee_adjusted_mean": (sum(fa) / len(fa)) if fa else None}
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps(out, indent=1, sort_keys=True)[:5000])


if __name__ == "__main__":
    main()

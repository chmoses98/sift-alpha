"""Reusable, stdlib-only research evaluation primitives. Nothing here certifies a feature as predictive.

* asof_join       - point-in-time feature reconstruction: for each decision, the latest observation with
                    observed_at <= decision_at (never later), with staleness cap; misses are reported, not imputed.
* brier/log_loss/calibration_bins - scoring of probabilistic predictions against realised outcomes.
* compare_to_market - paired model-vs-market-implied score difference with a GROUP bootstrap (resample whole
                    events/days, not rows) so overlapping/correlated rows (ladders, same-game markets) cannot fake precision.
* feature_screen  - exploratory rank-association screen. Its verdict is always EXPLORATORY; promotion to
                    VALIDATED requires out-of-sample, time-ordered evaluation done elsewhere.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta


def _t(v):
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("naive timestamp")
    return d


def asof_join(decisions, observations, *, key="entity", max_age_minutes=None, value_field="value"):
    """decisions: [{id, entity, decision_at}] ; observations: [{entity, observed_at, value}].
    Returns (joined, report). A joined row carries the observation's own timestamp and age so leakage is auditable."""
    by = defaultdict(list)
    for o in observations:
        by[o[key]].append((_t(o["observed_at"]), o))
    for v in by.values():
        v.sort(key=lambda x: x[0])
    out, miss_none, miss_stale = [], 0, 0
    for d in decisions:
        at = _t(d["decision_at"])
        cands = [x for x in by.get(d[key], []) if x[0] <= at]
        if not cands:
            miss_none += 1
            out.append({**d, "feature": None, "feature_observed_at": None, "feature_age_min": None, "status": "MISSING"})
            continue
        ts, o = cands[-1]
        age = (at - ts).total_seconds() / 60
        if max_age_minutes is not None and age > max_age_minutes:
            miss_stale += 1
            out.append({**d, "feature": None, "feature_observed_at": o["observed_at"], "feature_age_min": round(age, 1), "status": "STALE"})
            continue
        out.append({**d, "feature": o.get(value_field), "feature_observed_at": o["observed_at"], "feature_age_min": round(age, 1), "status": "OK"})
    n = len(decisions)
    return out, {"decisions": n, "ok": n - miss_none - miss_stale, "missing": miss_none, "stale": miss_stale,
                 "coverage": round((n - miss_none - miss_stale) / n, 4) if n else None}


def brier(p, y):
    return sum((a - b) ** 2 for a, b in zip(p, y)) / len(p)


def log_loss(p, y, eps=1e-9):
    return -sum(b * math.log(min(max(a, eps), 1 - eps)) + (1 - b) * math.log(min(max(1 - a, eps), 1 - eps)) for a, b in zip(p, y)) / len(p)


def calibration_bins(p, y, bins=10):
    rows = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [k for k, a in enumerate(p) if lo <= a < hi or (i == bins - 1 and a == 1.0)]
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(idx), "mean_p": round(sum(p[k] for k in idx) / len(idx), 4) if idx else None,
                     "observed": round(sum(y[k] for k in idx) / len(idx), 4) if idx else None})
    return rows


def compare_to_market(model_p, market_p, y, groups, *, boot=2000, seed=7, score=brier):
    """delta = score(market) - score(model); positive favours the model. CI by resampling whole groups."""
    if not (len(model_p) == len(market_p) == len(y) == len(groups)):
        raise ValueError("length mismatch")
    gi = defaultdict(list)
    for i, g in enumerate(groups):
        gi[g].append(i)
    keys = list(gi)

    def delta(idx):
        return score([market_p[i] for i in idx], [y[i] for i in idx]) - score([model_p[i] for i in idx], [y[i] for i in idx])

    point = delta(range(len(y)))
    rng = random.Random(seed)
    ds = sorted(delta([i for g in (rng.choice(keys) for _ in keys) for i in gi[g]]) for _ in range(boot))
    lo, hi = ds[int(0.025 * boot)], ds[int(0.975 * boot) - 1]
    return {"n_rows": len(y), "n_groups": len(keys), "delta_score": round(point, 6), "ci95": [round(lo, 6), round(hi, 6)],
            "model_score": round(score(model_p, y), 6), "market_score": round(score(market_p, y), 6),
            "verdict": "EXPLORATORY_MODEL_BETTER" if lo > 0 else ("EXPLORATORY_MARKET_BETTER" if hi < 0 else "INCONCLUSIVE"),
            "note": "in-sample unless model_p was frozen before outcomes; this is not a validation certificate"}


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def feature_screen(x, y, groups, *, boot=1000, seed=11, min_groups=30):
    """Exploratory association with group-bootstrap CI. Never returns a 'predictive' verdict."""
    keys = sorted(set(groups))
    if len(keys) < min_groups:
        return {"verdict": "INSUFFICIENT_GROUPS", "n_groups": len(keys), "min_groups": min_groups}
    gi = defaultdict(list)
    for i, g in enumerate(groups):
        gi[g].append(i)
    rng = random.Random(seed)
    vals = []
    for _ in range(boot):
        idx = [i for g in (rng.choice(keys) for _ in keys) for i in gi[g]]
        vals.append(spearman([x[i] for i in idx], [y[i] for i in idx]))
    vals.sort()
    lo, hi = vals[int(0.025 * boot)], vals[int(0.975 * boot) - 1]
    return {"verdict": "EXPLORATORY_ASSOCIATION" if (lo > 0 or hi < 0) else "NO_RELIABLE_ASSOCIATION", "spearman": round(spearman(x, y), 4),
            "ci95": [round(lo, 4), round(hi, 4)], "n_rows": len(x), "n_groups": len(keys),
            "note": "association only; no temporal holdout, no causal claim"}

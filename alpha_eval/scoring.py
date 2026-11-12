"""Scoring components, one per scoring type. Every function preserves error DIRECTION (signed) next to magnitude.
Reuses ``sift_research.stats`` (brier, logloss, cluster bootstrap, Holm/BH) and ``alpha_engine.research_eval`` bins."""
from __future__ import annotations

import math
from typing import Dict, Sequence

from sift_research.stats import brier, logloss  # noqa: F401  (re-exported: single source of truth)

EPS = 1e-6
PMF_TOL = 1e-6


def check_prob(p) -> float:
    p = float(p)
    if not (0.0 <= p <= 1.0) or math.isnan(p):
        raise ValueError(f"probability out of range: {p}")
    return p


# ---------------------------------------------------------------- binary
def binary_row(p: float, y: int) -> dict:
    p = check_prob(p)
    pc = min(max(p, EPS), 1 - EPS)
    return dict(brier=(p - y) ** 2, log=-(y * math.log(pc) + (1 - y) * math.log(1 - pc)), signed_error=p - y)


# ---------------------------------------------------------------- continuous
def continuous_row(mean: float, y: float, quantiles: Dict[float, float] | None = None) -> dict:
    out = dict(abs_error=abs(mean - y), sq_error=(mean - y) ** 2, signed_error=mean - y)   # + = over-forecast
    if quantiles:
        qs = sorted((float(q), float(v)) for q, v in quantiles.items())
        out["pinball_crps_approx"] = 2 * sum(max(q * (y - v), (q - 1) * (y - v)) for q, v in qs) / len(qs)
    return out


# ---------------------------------------------------------------- ordinal pmf (count/ladder)
def _norm_pmf(pmf: Dict) -> Dict[float, float]:
    d = {float(k): float(v) for k, v in pmf.items()}
    if any(v < 0 for v in d.values()) or abs(sum(d.values()) - 1.0) > 1e-4:
        raise ValueError("pmf must be non-negative and sum to 1")
    return dict(sorted(d.items()))


def ordinal_row(pmf: Dict, y: float) -> dict:
    """Discrete CRPS = sum_k (F(k) - 1{y<=k})^2 over unit-spaced support (exact for integer counts); RPS on the same
    support; log score of the realised value (floored); signed error of the pmf mean."""
    d = _norm_pmf(pmf)
    ks = list(d)
    cum, crps = 0.0, 0.0
    for k in range(int(min(ks[0], y)), int(max(ks[-1], y)) + 1):
        cum += d.get(float(k), 0.0)
        crps += (min(cum, 1.0) - (1.0 if y <= k else 0.0)) ** 2
    mean = sum(k * p for k, p in d.items())
    return dict(crps=crps, log=-math.log(max(d.get(float(y), 0.0), EPS)), abs_error=abs(mean - y), signed_error=mean - y,
                rps=crps / max(len(ks) - 1, 1))


# ---------------------------------------------------------------- categorical
def categorical_row(probs: Dict[str, float], y: str) -> dict:
    d = {str(k): float(v) for k, v in probs.items()}
    if y not in d:
        raise ValueError("realised category absent from forecast support (probability 0 would be hidden by a floor)")
    if abs(sum(d.values())) < 1e-9 or abs(sum(d.values()) - 1) > 1e-4 or any(v < 0 for v in d.values()):
        raise ValueError("categorical probabilities must sum to 1")
    return dict(brier_multiclass=sum((v - (1.0 if k == y else 0.0)) ** 2 for k, v in d.items()),
                log=-math.log(max(d[y], EPS)), p_realised=d[y])


# ---------------------------------------------------------------- calibration (binary)
def calibration_buckets(p: Sequence[float], y: Sequence[int], bins: int = 10) -> list:
    """Per probability bucket: n, mean forecast, observed frequency, signed gap (forecast - observed; + = over-predicts YES).
    Empty buckets are listed with n=0, never omitted."""
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [k for k, a in enumerate(p) if lo <= a < hi or (i == bins - 1 and a == 1.0)]
        mp = sum(p[k] for k in idx) / len(idx) if idx else None
        of = sum(y[k] for k in idx) / len(idx) if idx else None
        out.append(dict(bucket=f"{lo:.1f}-{hi:.1f}", n=len(idx), mean_p=mp, observed=of,
                        signed_gap=None if mp is None else mp - of))
    return out


def reliability_summary(p: Sequence[float], y: Sequence[int], bins: int = 10) -> dict:
    """Signed bias = mean(p) - mean(y). Calibration slope via logistic regression of y on logit(p) (1 = calibrated,
    <1 overconfident, >1 underconfident); ECE is |gap| weighted (direction lost, so signed bias is reported beside it)."""
    n = len(p)
    if n == 0:
        return dict(n=0)
    bk = calibration_buckets(p, y, bins)
    ece = sum(b["n"] / n * abs(b["signed_gap"]) for b in bk if b["n"])
    return dict(n=n, signed_bias=sum(p) / n - sum(y) / n, ece=ece, calibration_slope=_slope(p, y),
                confidence_reading=_reading(_slope(p, y)))


def _slope(p, y, iters=100):
    """Logistic-recalibration slope (y ~ a + b*logit(p)) by damped Newton (step halving on the log-likelihood)."""
    if len(set(y)) < 2 or len(p) < 20:
        return None
    x = [math.log(min(max(a, EPS), 1 - EPS) / (1 - min(max(a, EPS), 1 - EPS))) for a in p]
    if max(x) - min(x) < 1e-9:
        return None

    def ll(a, b):
        t = 0.0
        for xi, yi in zip(x, y):
            z = max(min(a + b * xi, 30), -30)
            t += yi * z - math.log1p(math.exp(z))
        return t

    a, b, cur = 0.0, 1.0, None
    cur = ll(a, b)
    for _ in range(iters):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for xi, yi in zip(x, y):
            z = max(min(a + b * xi, 30), -30)
            q = 1 / (1 + math.exp(-z))
            w = q * (1 - q) + 1e-12
            g0 += yi - q; g1 += (yi - q) * xi
            h00 += w; h01 += w * xi; h11 += w * xi * xi
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-14:
            return None
        da, db = (h11 * g0 - h01 * g1) / det, (-h01 * g0 + h00 * g1) / det
        step = 1.0
        while step > 1e-6:
            new = ll(a + step * da, b + step * db)
            if new >= cur:
                break
            step /= 2
        else:
            break
        a, b, cur = a + step * da, b + step * db, new
        if abs(step * da) + abs(step * db) < 1e-9:
            break
    return b


def _reading(slope):
    if slope is None:
        return "INSUFFICIENT_DATA"
    return "OVERCONFIDENT" if slope < 0.9 else ("UNDERCONFIDENT" if slope > 1.1 else "ROUGHLY_CALIBRATED")

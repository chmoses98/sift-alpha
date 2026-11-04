"""Inference helpers. Observations inside one physical game are not independent, so everything resamples GAMES (clusters)."""
from __future__ import annotations
import math
import numpy as np


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def _group(values, clusters):
    v = np.asarray(values, dtype=float)
    _, inv = np.unique(np.asarray(clusters), return_inverse=True)
    k = inv.max() + 1
    s = np.bincount(inv, weights=v, minlength=k)
    n = np.bincount(inv, minlength=k).astype(float)
    return s, n


def cluster_bootstrap(values, clusters, n_boot=2000, seed=7, alpha=0.05):
    """Mean of ``values`` with a percentile CI and a two-sided p-value (H0: mean = 0) from resampling clusters.
    Returns dict(mean, lo, hi, p, n, n_clusters). Ratio-of-sums estimator: unequal cluster sizes are handled."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return dict(mean=float("nan"), lo=float("nan"), hi=float("nan"), p=float("nan"), n=0, n_clusters=0)
    s, n = _group(v, clusters)
    k = len(s)
    mean = s.sum() / n.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    bm = s[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.quantile(bm, [alpha / 2, 1 - alpha / 2])
    # p-value by centring the bootstrap distribution at 0 (shift method)
    cen = bm - mean
    p = (1 + np.sum(np.abs(cen) >= abs(mean))) / (n_boot + 1)
    return dict(mean=float(mean), lo=float(lo), hi=float(hi), p=float(p), n=int(v.size), n_clusters=int(k))


def holm(pvals):
    """Holm-Bonferroni adjusted p-values (family-wise error control)."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * p[i])
        adj[i] = min(1.0, run)
    return adj


def benjamini_hochberg(pvals):
    """BH adjusted p-values (q-values; false discovery rate control, valid under positive dependence)."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)[::-1]
    adj = np.empty(m)
    run = 1.0
    for rank, i in enumerate(order):
        run = min(run, p[i] * m / (m - rank))
        adj[i] = run
    return adj


def brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def logloss(p, y, eps=1e-6):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_bins(p, y, edges):
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi) if hi < edges[-1] else (p >= lo) & (p <= hi)
        if m.sum():
            out.append(dict(lo=lo, hi=hi, n=int(m.sum()), mean_p=float(p[m].mean()), freq=float(y[m].mean())))
    return out

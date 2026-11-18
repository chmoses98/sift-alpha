"""Scoring + game-clustered paired bootstrap (Phase 14 MLB)."""
from __future__ import annotations

import numpy as np


def brier(p, y):
    return (np.asarray(p) - np.asarray(y)) ** 2


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return -(np.asarray(y) * np.log(p) + (1 - np.asarray(y)) * np.log(1 - p))


def crps_pmf(pmf, y):
    """Discrete CRPS (ranked probability score over integer thresholds). pmf (n,K) with last bin = K-1+ ; y ints."""
    cdf = np.cumsum(pmf, 1)
    k = np.arange(pmf.shape[1])
    ind = (np.asarray(y)[:, None] <= k[None, :]).astype(float)
    return ((cdf - ind) ** 2).sum(1)


def calib_slope(p, y, iters: int = 50):
    """Slope b of logistic regression y ~ a + b*logit(p) (Newton)."""
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    x = np.log(p / (1 - p))
    X = np.c_[np.ones_like(x), x]
    w = np.array([0.0, 1.0])
    y = np.asarray(y, float)
    for _ in range(iters):
        q = 1 / (1 + np.exp(-X @ w))
        H = X.T @ (X * (q * (1 - q))[:, None]) + 1e-9 * np.eye(2)
        w = w + np.linalg.solve(H, X.T @ (y - q))
    return float(w[1])


def paired_ci(loss_a, loss_b, clusters, B: int = 1000, seed: int = 0):
    """Mean(loss_b - loss_a) with game-clustered bootstrap 95% CI (negative => b better)."""
    d = np.asarray(loss_b, float) - np.asarray(loss_a, float)
    cl = np.asarray(clusters)
    u, inv = np.unique(cl, return_inverse=True)
    s = np.bincount(inv, d, len(u))
    n = np.bincount(inv, None, len(u))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), (B, len(u)))
    bs = s[idx].sum(1) / n[idx].sum(1)
    return {"diff": float(d.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
            "n": int(len(d)), "games": int(len(u))}


def nb_pmf(mu, r, K):
    """Negative-binomial pmf (mean mu, size r) on 0..K-1, tail folded into last bin. mu array (n,)."""
    from scipy.stats import nbinom
    mu = np.asarray(mu, float)[:, None]
    p = r / (r + mu)
    k = np.arange(K)[None, :]
    pmf = nbinom.pmf(k, r, p)
    pmf[:, -1] += 1 - pmf.sum(1)
    return pmf


def pois_pmf(mu, K):
    from scipy.stats import poisson
    mu = np.asarray(mu, float)[:, None]
    pmf = poisson.pmf(np.arange(K)[None, :], np.maximum(mu, 1e-6))
    pmf[:, -1] += 1 - pmf.sum(1)
    return pmf


def pmf_median(pmf):
    return (np.cumsum(pmf, 1) < 0.5).sum(1)

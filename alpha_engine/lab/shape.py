"""Predictive-distribution shape for player stats (market-free).  The incumbent is a negative binomial with ONE pooled size (variance = mu + mu^2/size), applied to yards as if they
were counts.  `local_empirical` instead takes, for each prediction, the realised ratios y/mu of the K earlier OUT-OF-SAMPLE predictions with the nearest mu (a heteroscedasticity-aware,
shape-free predictive distribution) and reads P(Y >= k) as the share of mu*ratio >= k.  Only information from seasons strictly before the predicted season is used."""
from __future__ import annotations
import numpy as np

K_DEFAULT = 300


def local_ratios(mu_pool, y_pool, mu_new, k=K_DEFAULT):
    """Returns (R, ) sorted ratio arrays per new point: matrix [n_new, k] of y/mu for the k nearest mu in the pool."""
    o = np.argsort(mu_pool)
    m, r = mu_pool[o], (y_pool / np.maximum(mu_pool, 1e-6))[o]
    pos = np.searchsorted(m, mu_new)
    lo = np.clip(pos - k // 2, 0, max(0, len(m) - k))
    idx = lo[:, None] + np.arange(min(k, len(m)))[None, :]
    return r[idx]


def prob_ge(mu_new, ratios, k):
    """P(Y >= k) for integer-valued stat: share of mu*ratio >= k - 0.5 (continuity boundary), with a +0.5/(n+1) additive smoothing so probabilities are never exactly 0/1."""
    n = ratios.shape[1]
    hit = (mu_new[:, None] * ratios >= k - 0.5).sum(1)
    return (hit + 0.5) / (n + 1.0)

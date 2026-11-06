"""Exceedance-probability calibration (market-free).  A fitted predictive distribution can have the right mean and still mis-state tail probabilities (a negative binomial that is too
thin above the median and too fat below it).  We build (raw P(Y >= k), realised 1[Y >= k]) pairs over a threshold grid from OUT-OF-SAMPLE predictions of earlier seasons only and fit
logit(p_cal) = a + b*logit(p_raw).  No price enters.  Walk-forward: season S is calibrated with pairs from seasons < S."""
from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression
from . import dists

EPS = 1e-4
GRIDS = {"rec_yds": [10, 20, 30, 40, 50, 60, 70, 80, 100, 125], "receptions": [1, 2, 3, 4, 5, 6, 7, 8, 10], "rush_yds": [10, 20, 30, 40, 50, 60, 70, 80, 100, 125],
         "pass_yds": [150, 175, 200, 225, 250, 275, 300, 325, 350], "td_any": [1, 2]}
Z_GRID = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)           # game models: thresholds placed at the model mean +/- z sigma


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def pairs_counts(kind, mu, disp, y, grid):
    """Stack pairs for every row x threshold k: p_raw = P(Y >= k), o = 1[y >= k]; returns arrays and the row index of each pair."""
    mu, y = np.asarray(mu, float), np.asarray(y, float)
    P, O, R = [], [], []
    for k in grid:
        p = dists.prob_gt(kind, mu, disp, k - 0.5)
        P.append(np.asarray(p, float)); O.append((y >= k).astype(float)); R.append(np.arange(len(y)))
    return np.concatenate(P), np.concatenate(O), np.concatenate(R)


def pairs_z(kind, mu, sigma, y):
    mu, sigma, y = np.asarray(mu, float), np.asarray(sigma, float), np.asarray(y, float)
    P, O, R = [], [], []
    for z in Z_GRID:
        k = mu + z * sigma
        p = dists.prob_gt(kind, mu, sigma, k)
        P.append(np.asarray(p, float)); O.append((y > k).astype(float)); R.append(np.arange(len(y)))
    return np.concatenate(P), np.concatenate(O), np.concatenate(R)


def fit(p, o):
    """Platt scaling on the logit.  Returns (a, b)."""
    m = LogisticRegression(C=1e6, solver="lbfgs", max_iter=500).fit(logit(p).reshape(-1, 1), o)
    return float(m.intercept_[0]), float(m.coef_[0, 0])


def apply(ab, p):
    a, b = ab
    z = a + b * logit(p)
    return 1.0 / (1.0 + np.exp(-z))


def logloss(p, o):
    p = np.clip(p, EPS, 1 - EPS)
    return -(o * np.log(p) + (1 - o) * np.log(1 - p))

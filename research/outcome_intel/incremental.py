"""Incremental-information test: does a challenger probability add predictive information beyond a contemporaneous market-only baseline?

Pure numpy. RESEARCH_ONLY. Rows are dicts with: game (cluster id), t (sortable decision time), mid (market probability at decision time),
q (challenger probability at decision time), y (0/1 outcome, never a feature). No row may use information after ``t``.

Protocol (fixed before looking at any holdout):
  * games are ordered by first decision time; train = earliest ``train_frac`` of games, holdout = the rest, never used for fitting;
  * baselines: B_raw (market as quoted) and B_cal (a + b*logit(mid) fitted on train);
  * challenger C: B_cal + c*(logit(q) - logit(mid)) fitted on train with a fixed small ridge (no tuning on holdout);
  * statistic = mean per-row (logloss_baseline - logloss_challenger) on holdout; positive = challenger better; CI = game-cluster bootstrap.
"""
from __future__ import annotations
import math
import numpy as np

EPS = 0.02


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logistic(X, y, ridge=1.0, iters=50):
    """Newton-Raphson logistic regression; intercept (col 0) unpenalised."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    w = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], ridge)
    pen[0] = 0.0
    for _ in range(iters):
        p = sigmoid(X @ w)
        g = X.T @ (p - y) + pen * w
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen) + 1e-9 * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return w


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def split_games(rows, train_frac=2 / 3):
    first = {}
    for r in rows:
        first[r["game"]] = min(first.get(r["game"], r["t"]), r["t"])
    order = [g for g, _ in sorted(first.items(), key=lambda kv: (kv[1], kv[0]))]
    k = int(round(len(order) * train_frac))
    return set(order[:k]), set(order[k:])


def cluster_ci(vals, clusters, n_boot=2000, seed=17):
    v = np.asarray(vals, float)
    _, inv = np.unique(np.asarray(clusters), return_inverse=True)
    k = inv.max() + 1
    s, n = np.bincount(inv, weights=v, minlength=k), np.bincount(inv, minlength=k).astype(float)
    mean = s.sum() / n.sum()
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    b = s[idx].sum(1) / n[idx].sum(1)
    cen = b - mean
    p = (1 + np.sum(np.abs(cen) >= abs(mean))) / (n_boot + 1)
    return dict(mean=float(mean), lo=float(np.quantile(b, .025)), hi=float(np.quantile(b, .975)), p=float(p), n=int(v.size), n_games=int(k))


def holm(p):
    p = np.asarray(p, float)
    o = np.argsort(p)
    out = np.empty(len(p))
    run = 0.0
    for rank, i in enumerate(o):
        run = max(run, (len(p) - rank) * p[i])
        out[i] = min(1.0, run)
    return out


def _X(rows, with_q):
    lm = logit([r["mid"] for r in rows])
    cols = [np.ones(len(rows)), lm]
    if with_q:
        cols.append(logit([r["q"] for r in rows]) - lm)
    return np.column_stack(cols)


def incremental_test(rows, train_frac=2 / 3, ridge=1.0, seed=17, min_games=12):
    """Fit on train games only; evaluate on later holdout games. Returns dict (UNKNOWN fields as None when under-powered)."""
    tr_g, te_g = split_games(rows, train_frac)
    tr = [r for r in rows if r["game"] in tr_g]
    te = [r for r in rows if r["game"] in te_g]
    if len(tr_g) < min_games or len(te_g) < min_games or len(tr) < 50:
        return dict(status="UNDERPOWERED", train_games=len(tr_g), holdout_games=len(te_g), n_train=len(tr), n_holdout=len(te))
    ytr, yte = np.array([r["y"] for r in tr], float), np.array([r["y"] for r in te], float)
    wB = fit_logistic(_X(tr, False), ytr, ridge)
    wC = fit_logistic(_X(tr, True), ytr, ridge)
    pRaw = np.clip(np.array([r["mid"] for r in te], float), 1e-6, 1 - 1e-6)
    pB, pC = sigmoid(_X(te, False) @ wB), sigmoid(_X(te, True) @ wC)
    g = [r["game"] for r in te]
    out = dict(status="OK", train_games=len(tr_g), holdout_games=len(te_g), n_train=len(tr), n_holdout=len(te),
               coef_baseline=[float(x) for x in wB], coef_challenger=[float(x) for x in wC],
               logloss=dict(raw_market=float(ll(pRaw, yte).mean()), calibrated_market=float(ll(pB, yte).mean()), challenger=float(ll(pC, yte).mean())),
               brier=dict(raw_market=float(((pRaw - yte) ** 2).mean()), calibrated_market=float(((pB - yte) ** 2).mean()), challenger=float(((pC - yte) ** 2).mean())))
    # positive = challenger better
    out["gain_vs_calibrated_market_logloss"] = cluster_ci(ll(pB, yte) - ll(pC, yte), g, seed=seed)
    out["gain_vs_raw_market_logloss"] = cluster_ci(ll(pRaw, yte) - ll(pC, yte), g, seed=seed)
    out["calibration_gain_of_market_alone_logloss"] = cluster_ci(ll(pRaw, yte) - ll(pB, yte), g, seed=seed)
    return out


def negative_control(rows, seed=0, **kw):
    """Replace the challenger with a game-shuffled copy of itself (keeps its marginal distribution, destroys any link to y). Expect ~0 gain."""
    rng = np.random.default_rng(seed)
    qs = np.array([r["q"] for r in rows], float)
    idx = rng.permutation(len(rows))
    fake = [dict(r, q=float(qs[i])) for r, i in zip(rows, idx)]
    return incremental_test(fake, **kw)

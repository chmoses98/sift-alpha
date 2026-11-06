"""Statistical core for input research. Pure numpy (+ optional scikit-learn for gradient boosting). No network, no randomness without a seed.

Design rules (they are what keep a "finding" honest):
  * Walk-forward by season: every prediction for season S uses a model fit on seasons < S only (lambda chosen on the last TRAIN season).
  * The yardstick is always a MARKET benchmark when a contemporaneous line exists (B0 = the line itself, B1 = line + past mean residual) and a
    no-information baseline otherwise. A gain only counts against the strictest baseline available.
  * Uncertainty is cluster-bootstrapped over calendar weeks (games in a week share weather, officiating drift, injuries news, market regime).
  * Every family of tests gets multiple-comparison control (Holm for the confirmatory gate, Benjamini-Hochberg q-values for discovery lists).
  * Verdict ladder (never skips a rung): DEMONSTRATED needs Holm-adjusted p < 0.05, both chronological halves > 0, every leave-one-season-out > 0 and a season-block bootstrap 95% CI > 0.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np

SEED = 20261105
BOOT = 3000
LAMBDAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)


# ----------------------------------------------------------------------------- resampling
class ClusterBoot:
    """Cluster bootstrap of a mean of per-observation differences. Clusters = e.g. season-week keys."""

    def __init__(self, keys: Sequence, n_boot: int = BOOT, seed: int = SEED):
        keys = np.asarray(keys)
        self.uniq, self.inv = np.unique(keys, return_inverse=True)
        self.m = len(self.uniq)
        rng = np.random.default_rng(seed)
        self.idx = rng.integers(0, self.m, size=(n_boot, self.m))
        self.n_boot = n_boot

    def means(self, d: np.ndarray) -> np.ndarray:
        d = np.asarray(d, float)
        s = np.bincount(self.inv, weights=d, minlength=self.m)
        c = np.bincount(self.inv, minlength=self.m).astype(float)
        return s[self.idx].sum(1) / c[self.idx].sum(1)

    def summarize(self, d: np.ndarray, alphas: Sequence[float] = (0.05,)) -> dict:
        b = self.means(d)
        out = {"mean": float(np.mean(d)), "n": int(len(d)), "n_clusters": int(self.m)}
        for a in alphas:
            out[f"ci_{a:g}"] = [float(np.quantile(b, a / 2)), float(np.quantile(b, 1 - a / 2))]
        p = 2 * min(float((b <= 0).mean()), float((b >= 0).mean()))
        out["p"] = float(min(1.0, max(p, 1.0 / self.n_boot)))
        return out


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (monotone)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, run = {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        adj[k] = run
    return adj


def benjamini_hochberg(pvals: dict[str, float]) -> dict[str, float]:
    """BH q-values (FDR control under independence/PRDS)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    q, prev = {}, 1.0
    for i in range(m - 1, -1, -1):
        k, p = items[i]
        prev = min(prev, p * m / (i + 1))
        q[k] = prev
    return q


# ----------------------------------------------------------------------------- models
def _prep(X: np.ndarray):
    mu = np.nanmean(X, 0)
    mu = np.where(np.isnan(mu), 0.0, mu)
    sd = np.nanstd(X, 0)
    sd = np.where((sd == 0) | np.isnan(sd), 1.0, sd)
    return mu, sd


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float) -> tuple[Callable, np.ndarray, float]:
    """Standardised ridge; NaN features are mean-imputed (=0 after scaling). Returns (predict, standardised beta, intercept)."""
    mu, sd = _prep(X)
    Z = np.nan_to_num((X - mu) / sd)
    ym = float(np.mean(y))
    beta = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return (lambda Xn: ym + np.nan_to_num((Xn - mu) / sd) @ beta), beta, ym


def fit_ridge_lambda(X, y, seasons, s):
    """Choose lambda on the last train season only (never on the test season)."""
    tr, last = seasons < s, seasons == s - 1
    fit_tr = tr & ~last
    best, bl = None, LAMBDAS[0]
    for lam in LAMBDAS:
        f, _, _ = ridge_fit(X[fit_tr], y[fit_tr], lam)
        e = float(np.mean((f(X[last]) - y[last]) ** 2))
        if best is None or e < best:
            best, bl = e, lam
    return bl


def walk_forward_ridge(X, y, seasons, test_seasons, min_train: int = 300):
    out = np.full(len(y), np.nan)
    lams = {}
    for s in test_seasons:
        tr, te = seasons < s, seasons == s
        if tr.sum() < min_train or te.sum() == 0:
            continue
        lam = fit_ridge_lambda(X, y, seasons, s)
        lams[int(s)] = lam
        f, _, _ = ridge_fit(X[tr], y[tr], lam)
        out[te] = f(X[te])
    return out, lams


def make_gbm(seed: int = SEED):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.03, max_iter=250, min_samples_leaf=60, l2_regularization=10.0, random_state=seed)


def walk_forward_gbm(X, y, seasons, test_seasons, min_train: int = 300, keep_models: bool = False):
    out = np.full(len(y), np.nan)
    models = {}
    for s in test_seasons:
        tr, te = seasons < s, seasons == s
        if tr.sum() < min_train or te.sum() == 0:
            continue
        m = make_gbm().fit(X[tr], y[tr])
        out[te] = m.predict(X[te])
        if keep_models:
            models[int(s)] = m
    return (out, models) if keep_models else out


def baseline_mean(y, seasons, test_seasons):
    """B1: expanding past mean of y (for residual targets: market + past mean residual; for raw targets: past league mean)."""
    out = np.full(len(y), np.nan)
    for s in test_seasons:
        tr = seasons < s
        if tr.any():
            out[seasons == s] = y[tr].mean()
    return out


# ----------------------------------------------------------------------------- scoring
def gain_summary(boot: ClusterBoot, test: np.ndarray, base_err: np.ndarray, model_err: np.ndarray, seasons: np.ndarray, test_seasons,
                 alphas=(0.05,)) -> dict:
    """Error reduction (base - model); positive = the model is better. Includes both-halves and leave-one-season-out checks."""
    d = (base_err - model_err)[test]
    ts = seasons[test]
    n = len(d)
    h = n // 2
    loso = {int(s): float(d[ts != s].mean()) for s in test_seasons if (ts == s).any()}
    per_season = {int(s): float(d[ts == s].mean()) for s in test_seasons if (ts == s).any()}
    res = boot.summarize(d, alphas)
    sb = getattr(boot, "season_boot", None)
    if sb is not None:      # extra-conservative check: resample whole SEASONS (few clusters, but it respects serial dependence of rolling ratings)
        res["ci_season_block"] = sb.summarize(d, (0.05,))["ci_0.05"]
    res.update({"halves": [float(d[:h].mean()), float(d[h:].mean())], "leave_one_season_out": loso, "per_season": per_season,
                "seasons_positive": int(sum(v > 0 for v in per_season.values())), "seasons_total": len(per_season)})
    return res


def verdict(gain: dict, holm_p: float | None = None, alpha: float = 0.05) -> str:
    ci_lo = gain["ci_0.05"][0]
    ci_hi = gain["ci_0.05"][1]
    sblock_ok = gain.get("ci_season_block") is None or gain["ci_season_block"][0] > 0
    if holm_p is not None and holm_p < alpha and min(gain["halves"]) > 0 and min(gain["leave_one_season_out"].values()) > 0 and sblock_ok:
        return "DEMONSTRATED_INCREMENTAL"
    if ci_lo > 0:
        return "SUGGESTIVE_UNCONFIRMED"      # nominal 95% only; survives no multiple-comparison control
    if ci_hi < 0:
        return "WORSE_THAN_BASELINE"
    return "NOT_DEMONSTRATED"


# probability scoring ---------------------------------------------------------
EPS = 1e-6


def logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier(p, y):
    return (p - y) ** 2


def norm_cdf(z):
    z = np.asarray(z, float)
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def devig_two_way(odds_a, odds_b):
    """American odds on both sides -> vig-free P(a). Returns NaN where either side is missing."""
    def imp(o):
        o = np.asarray(o, float)
        return np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))
    a, b = imp(odds_a), imp(odds_b)
    return a / (a + b)


def calibration_table(p, y, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1, 2
    out = []
    for i in range(bins):
        m = (p > edges[i]) & (p <= edges[i + 1]) if i else (p >= edges[i]) & (p <= edges[i + 1])
        if m.sum():
            out.append({"p_mean": float(p[m].mean()), "freq": float(y[m].mean()), "n": int(m.sum())})
    return out


def calibration_slope(p, y):
    """Logistic recalibration slope/intercept of outcomes on logit(p) (1.0 / 0.0 = perfectly calibrated). Newton iterations, no sklearn."""
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    x = np.log(p / (1 - p))
    X = np.column_stack([np.ones_like(x), x])
    b = np.array([0.0, 1.0])
    for _ in range(50):
        eta = X @ b
        mu = 1 / (1 + np.exp(-eta))
        W = mu * (1 - mu)
        g = X.T @ (y - mu)
        H = X.T @ (X * W[:, None]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g)
        b = b + step
        if np.abs(step).max() < 1e-8:
            break
    return {"intercept": float(b[0]), "slope": float(b[1])}

"""Systematic, overfit-resistant search over inputs, transforms, interactions and model structures (RESEARCH_ONLY, market-free).

A single table (one row per decision unit, chronologically ordered by ``season``) with a target, a strong no-information baseline and named input groups goes in.
For every OUTER test season S:
  1. Draw ``n_configs`` configurations at random (seeded): a subset of input groups, optional squared terms, 0/6/20 data-picked pairwise interactions, and a model
     structure (ridge with a penalty, or shallow gradient boosting).
  2. Score each on INNER folds: train on seasons before V, validate on V, for the last ``inner_k`` seasons before S. Nothing from S or later is ever touched.
  3. Pick by the one-standard-error rule: the simplest configuration within one SE of the best inner score (guards against choosing noise).
  4. Refit the chosen configuration on all seasons before S and predict S.
Because selection happens inside every fold, the pooled outer error is an honest estimate of "the search procedure", not of a hand-picked winner. A PERMUTATION NULL
(residual shuffled within season) is run through the identical procedure: its apparent gain is the search's own overfitting and must be ~0 for the real gain to mean anything.
Market-derived columns are rejected (marketfree.assert_market_free).
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from . import marketfree as MF
from . import stats as S

COMPLEXITY_GBM = 40
GBM_MAX_ROWS = 40000   # cap on training rows for boosted models (most recent rows) to keep the sweep tractable


def _ridge(X, y, alpha):
    med = np.nanmedian(X, axis=0)
    Xf = np.where(np.isnan(X), med, X)
    mu, sd = Xf.mean(0), Xf.std(0) + 1e-9
    Z = (Xf - mu) / sd
    ym = y.mean()
    w = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return lambda Q: ym + ((np.where(np.isnan(Q), med, Q) - mu) / sd) @ w


def _gbm(X, y, depth, n_iter):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(max_depth=depth, max_iter=n_iter, learning_rate=0.04, min_samples_leaf=40, l2_regularization=5.0, random_state=0).fit(X, y)
    return m.predict


class Space:
    def __init__(self, groups: dict[str, list[str]], seed: int = 1):
        self.groups = groups
        self.rng = np.random.default_rng(seed)

    def draw(self, n: int) -> list[dict]:
        names = list(self.groups)
        cfgs, seen = [], set()
        # always include the full set and each leave-one-group-out set: a structured core so group importance is readable
        core = [tuple(names)] + [tuple(g for g in names if g != x) for x in names]
        subsets = list(core)
        while len(subsets) < n:
            k = int(self.rng.integers(2, len(names) + 1))
            subsets.append(tuple(sorted(self.rng.choice(names, k, replace=False), key=names.index)))
        for j, sub in enumerate(subsets[:n]):
            model = self.rng.choice(["ridge", "ridge", "ridge", "gbm"])
            cfg = {"groups": sub, "sq": bool(self.rng.random() < 0.35), "ix": int(self.rng.choice([0, 0, 6, 20])),
                   "model": str(model), "alpha": float(self.rng.choice([3, 30, 300, 3000])), "depth": int(self.rng.choice([2, 3])), "n_iter": int(self.rng.choice([60, 120]))}
            if j < len(core):      # the structured core is evaluated under ONE fixed structure so group importance is a clean leave-one-group-out contrast
                cfg.update({"sq": False, "ix": 0, "model": "ridge", "alpha": 300.0}); model = "ridge"
            key = (cfg["groups"], cfg["sq"], cfg["ix"], cfg["model"], cfg["alpha"] if model == "ridge" else (cfg["depth"], cfg["n_iter"]))
            if key in seen:
                continue
            seen.add(key); cfgs.append(cfg)
        return cfgs


def _columns(space: Space, cfg: dict) -> list[str]:
    return [c for g in cfg["groups"] for c in space.groups[g]]


def _design(cfg, cols, X_tr, r_tr, X_te_list):
    """Build transformed matrices. Interaction pairs are chosen on the TRAINING rows only (correlation of the product with the residual target)."""
    mats_tr, mats_te = [X_tr], [[x] for x in X_te_list]
    if cfg["sq"]:
        med = np.nanmedian(X_tr, axis=0); sd = np.nanstd(X_tr, axis=0) + 1e-9
        f = lambda X: ((np.where(np.isnan(X), med, X) - med) / sd) ** 2
        mats_tr.append(f(X_tr))
        for i, x in enumerate(X_te_list): mats_te[i].append(f(x))
    if cfg["ix"] and X_tr.shape[1] >= 3:
        med = np.nanmedian(X_tr, axis=0); sd = np.nanstd(X_tr, axis=0) + 1e-9
        Z = (np.where(np.isnan(X_tr), med, X_tr) - med) / sd
        main = np.abs([np.corrcoef(Z[:, j], r_tr)[0, 1] if Z[:, j].std() > 0 else 0 for j in range(Z.shape[1])])
        top = np.argsort(-np.nan_to_num(main))[:min(10, Z.shape[1])]
        pairs = list(itertools.combinations(top, 2))
        sc = [abs(np.corrcoef(Z[:, a] * Z[:, b], r_tr)[0, 1]) if (Z[:, a] * Z[:, b]).std() > 0 else 0 for a, b in pairs]
        keep = [pairs[i] for i in np.argsort(-np.nan_to_num(sc))[:cfg["ix"]]]
        g = lambda X: np.column_stack([((np.where(np.isnan(X), med, X) - med) / sd)[:, a] * ((np.where(np.isnan(X), med, X) - med) / sd)[:, b] for a, b in keep])
        mats_tr.append(g(X_tr))
        for i, x in enumerate(X_te_list): mats_te[i].append(g(x))
    return np.column_stack(mats_tr), [np.column_stack(m) for m in mats_te]


def fit_predict(cfg, space, X_all, r, tr_idx, te_idx_list):
    cols = _columns(space, cfg)
    Xt = X_all[cols].to_numpy(float)
    Xtr, tes = _design(cfg, cols, Xt[tr_idx], r[tr_idx], [Xt[i] for i in te_idx_list])
    if cfg["model"] == "ridge":
        f = _ridge(Xtr, r[tr_idx], cfg["alpha"])
    else:
        k = max(0, len(Xtr) - GBM_MAX_ROWS)
        f = _gbm(np.nan_to_num(Xtr[k:], nan=0.0), r[tr_idx][k:], cfg["depth"], cfg["n_iter"])
    return [f(t) if cfg["model"] == "ridge" else f(np.nan_to_num(t, nan=0.0)) for t in tes]


def complexity(cfg, space):
    n = len(_columns(space, cfg))
    return n * (2 if cfg["sq"] else 1) + cfg["ix"] + (COMPLEXITY_GBM if cfg["model"] == "gbm" else 0)


def nested_search(d: pd.DataFrame, r: np.ndarray, groups: dict[str, list[str]], test_seasons, n_configs=120, inner_k=3, seed=1, min_train=3, ledger=None, ctx=None) -> dict:
    """d: feature table with ``season``; r: residual target (y - baseline). Returns outer predictions of the search procedure and what it selected.
    ``ledger`` (ledger.Ledger) + ``ctx`` (dict identifying market/null/rep/data fingerprint) log EVERY configuration x outer season with its inner-fold scores and whether it was picked."""
    MF.assert_market_free([c for g in groups.values() for c in g])
    space = Space(groups, seed)
    seasons = d["season"].to_numpy()
    pred = np.full(len(d), np.nan)
    chosen = []
    cfgs = space.draw(n_configs)
    for s in test_seasons:
        train_seasons = sorted(set(seasons[seasons < s]))
        if len(train_seasons) < min_train + inner_k:
            continue
        vals = train_seasons[-inner_k:]
        scores = np.zeros((len(cfgs), len(vals)))
        for fi, v in enumerate(vals):
            tr = np.where(seasons < v)[0]; va = np.where(seasons == v)[0]
            for ci, cfg in enumerate(cfgs):
                p = fit_predict(cfg, space, d, r, tr, [va])[0]
                scores[ci, fi] = np.mean((r[va] - p) ** 2)
        base_mse = np.array([np.mean(r[seasons == v] ** 2) for v in vals])
        rel = scores / base_mse                       # per-season MSE relative to the baseline (1.0 = no better than the baseline)
        m, se = rel.mean(1), rel.std(1, ddof=1) / math.sqrt(len(vals))
        best = int(np.argmin(m))
        ok = [i for i in range(len(cfgs)) if m[i] <= m[best] + se[best]]
        pick = min(ok, key=lambda i: (complexity(cfgs[i], space), m[i]))
        te = np.where(seasons == s)[0]; trn = np.where(seasons < s)[0]
        pred[te] = fit_predict(cfgs[pick], space, d, r, trn, [te])[0]
        n_core = 1 + len(groups)
        core = {"full": round(float(m[0]), 4), **{f"drop:{g}": round(float(m[1 + i]), 4) for i, g in enumerate(groups)}}
        if ledger is not None:
            for ci, cfg in enumerate(cfgs):
                ledger.record({**(ctx or {}), "outer_season": int(s), "cfg": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()}},
                              {"inner_rel_mse": round(float(m[ci]), 5), "inner_folds": [round(float(x), 5) for x in rel[ci]], "picked": bool(ci == pick), "within_1se": bool(ci in ok), "complexity": complexity(cfg, space)},
                              sample={"inner_seasons": [int(v) for v in vals]})
        chosen.append({"core_inner_rel_mse": core, "season": int(s), "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfgs[pick].items()}, "inner_rel_mse": round(float(m[pick]), 4),
                       "best_inner_rel_mse": round(float(m[best]), 4), "n_within_1se": len(ok)})
    return {"pred": pred, "chosen": chosen, "n_configs": len(cfgs)}


def summarize_gain(d, r, pred, cluster_keys, n_boot=2000) -> dict:
    ok = ~np.isnan(pred)
    if not ok.any():
        return {"mean": None, "n": 0, "pct_gain": float("nan"), "seasons": [], "pct_gain_by_season": {}, "seasons_positive": 0, "error": "no outer fold had enough earlier history"}
    e0 = r[ok] ** 2
    e1 = (r[ok] - pred[ok]) ** 2
    diff = e0 - e1
    cb = S.ClusterBoot(np.asarray(cluster_keys)[ok], n_boot=n_boot)
    out = cb.summarize(diff)
    out.update({"mse_baseline": float(e0.mean()), "mse_search": float(e1.mean()), "pct_gain": float(100 * diff.mean() / e0.mean()),
                "seasons": sorted(int(x) for x in np.unique(d["season"].to_numpy()[ok]))})
    by = {}
    for sn in out["seasons"]:
        m = d["season"].to_numpy()[ok] == sn
        by[str(sn)] = round(float(100 * (e0[m].mean() - e1[m].mean()) / e0[m].mean()), 2)
    out["pct_gain_by_season"] = by
    out["seasons_positive"] = int(sum(v > 0 for v in by.values()))
    return out


def permutation_null(d, r, groups, test_seasons, cluster_keys, reps=2, **kw) -> list[dict]:
    """Same procedure on a target whose signal is destroyed (residual shuffled within season). Its apparent gain is pure search overfitting."""
    out = []
    for k in range(reps):
        rng = np.random.default_rng(100 + k)
        rs = r.copy()
        for sn in np.unique(d["season"]):
            idx = np.where(d["season"].to_numpy() == sn)[0]
            rs[idx] = rng.permutation(r[idx])
        kw2 = dict(kw)
        if kw2.get("ctx") is not None:
            kw2["ctx"] = {**kw2["ctx"], "null": True, "rep": k}
        res = nested_search(d, rs, groups, test_seasons, seed=1 + k, **kw2)
        g = summarize_gain(d, rs, res["pred"], cluster_keys)
        out.append({"rep": k, "pct_gain": g["pct_gain"], "ci_0.05": g["ci_0.05"]})
    return out

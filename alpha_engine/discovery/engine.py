"""Historical pattern-discovery engine: preregistered, leakage-safe, walk-forward evaluation of certified pregame inputs (RESEARCH_ONLY).

One engine for every sport and game-level market family; a study is a JSON preregistration, not a script:

    python -m alpha_engine.discovery.run --prereg research/discovery/<study>/prereg.json --dataset DS.parquet [--market M.csv] [--official DIR] [--holdout]

Protocol (enforced in code, not by convention):
  * DATA      the dataset must hash (canonical sha256) to `dataset_sha256` in the preregistration AND that hash must be a registered,
              non-superseded entry of research/certification/dataset_versions.json. Otherwise the run stops.
  * FEATURES  only `home_*` / `away_*` pregame columns named in the preregistration; `marketfree.assert_market_free` rejects any
              sportsbook / Kalshi / postgame column. Market lines are loaded into a SEPARATE frame used for scoring only.
  * TIME      walk-forward by season: season S is predicted by a ridge fitted on seasons < S (lambda chosen on the last train season,
              sigma from earlier out-of-sample residuals). Nothing from S or later is visible to the fit.
  * SPLITS    `dev` seasons may be looked at freely; `test` seasons are the confirmatory evidence; `holdout` seasons are never scored
              unless --holdout is passed, and the holdout file records the preregistration hash it was run under. A changed
              preregistration cannot reuse or overwrite an existing holdout file.
  * TESTS     every hypothesis (feature group x target) is listed before scoring; p-values are cluster-bootstrapped (season-week)
              and Holm-adjusted across the whole preregistered family; verdicts use `input_research.stats.verdict`.
A result is evidence about forecast accuracy only. No price, liquidity or fee evidence enters here, so nothing in the output is a
claim about betting value.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..input_research import stats as S
from ..input_research.marketfree import assert_market_free

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "research/certification/dataset_versions.json"
ENGINE_VERSION = "discovery-1.0"


def canonical_hash(df: pd.DataFrame) -> str:
    from ..foundation.training_sets import canonical_hash as h
    return h(df)


def prereg_hash(p: dict) -> str:
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_dataset(path: Path, prereg: dict, versions_path: Path = VERSIONS) -> pd.DataFrame:
    """Fail-closed: the bytes must be the preregistered, registered, non-superseded dataset version."""
    d = pd.read_parquet(path)
    h = canonical_hash(d)
    if h != prereg["dataset_sha256"]:
        raise ValueError(f"dataset hash {h[:12]} is not the preregistered {prereg['dataset_sha256'][:12]}")
    live = {(e["sport"], e["canonical_sha256"]) for e in json.loads(Path(versions_path).read_text())["versions"] if not e.get("superseded_by")}
    if (prereg["sport"], h) not in live:
        raise ValueError(f"dataset {h[:12]} is not a registered, non-superseded {prereg['sport']} version")
    return d


def group_columns(prereg: dict, names: list[str], cols: set[str]) -> list[str]:
    out = []
    for g in names:
        for c in prereg["groups"][g]:
            for side in ("home_", "away_"):
                if side + c in cols and side + c not in out:
                    out.append(side + c)
    assert_market_free(out)
    return out


def walk_forward(d: pd.DataFrame, feats: list[str], target: str, seasons: list[int], min_train: int) -> tuple[np.ndarray, np.ndarray]:
    """Out-of-sample mean and sigma for every row of `seasons` (NaN elsewhere). Sigma for season S = RMSE of OOS residuals of seasons < S."""
    y = d[target].to_numpy(float); se = d["season"].to_numpy(int); ok = ~np.isnan(y)
    mu = np.full(len(d), np.nan); sig = np.full(len(d), np.nan)
    if feats:
        X = d[feats].to_numpy(float)
        for s in seasons:
            tr = (se < s) & ok; te = se == s
            if tr.sum() < min_train or not te.any():
                continue
            lam = S.fit_ridge_lambda(X[ok], y[ok], se[ok], s)
            f, _, _ = S.ridge_fit(X[tr], y[tr], lam)
            mu[te] = f(X[te])
    else:
        for s in seasons:
            tr = (se < s) & ok
            if tr.sum() >= min_train:
                mu[se == s] = y[tr].mean()
    for s in seasons:
        past = (se < s) & ok & ~np.isnan(mu)
        if past.sum() >= 100:
            sig[se == s] = float(np.sqrt(np.mean((y[past] - mu[past]) ** 2)))
        else:                                   # first predicted seasons: no earlier OOS residuals yet, use the unconditional spread of the train rows
            tr = (se < s) & ok
            if tr.any():
                sig[se == s] = float(np.std(y[tr]))
    return mu, sig


def _boot(d: pd.DataFrame, mask: np.ndarray) -> S.ClusterBoot:
    return S.ClusterBoot((d["season"].astype(str) + "-" + d["cluster"].astype(str)).to_numpy()[mask])


def _ci(boot: S.ClusterBoot, v: np.ndarray) -> dict:
    r = boot.summarize(v)
    return {"mean": round(r["mean"], 5), "ci95": [round(x, 5) for x in r["ci_0.05"]], "p": round(r["p"], 5), "n": r["n"], "clusters": r["n_clusters"]}


def point_metrics(y, mu) -> dict:
    e = mu - y
    return {"n": int(len(y)), "mae": round(float(np.mean(np.abs(e))), 4), "rmse": round(float(np.sqrt(np.mean(e ** 2))), 4), "signed_error_pred_minus_actual": round(float(np.mean(e)), 4)}


def prob_metrics(p, y) -> dict:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    return {"n": int(len(y)), "brier": round(float(np.mean((p - y) ** 2)), 5), "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 5),
            "base_rate": round(float(y.mean()), 4), "mean_p": round(float(p.mean()), 4), "accuracy": round(float(((p > 0.5) == (y > 0.5)).mean()), 4),
            "calibration_slope": round(float(S.calibration_slope(p, y)), 4) if len(y) > 50 else None,
            "calibration": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in S.calibration_table(p, y, 5)]}


def _ncdf(z):
    from scipy.stats import norm
    return norm.cdf(z)


def evaluate_split(d: pd.DataFrame, P: dict, mkt: pd.DataFrame | None, seasons: list[int], prereg: dict) -> dict:
    """All metrics for one split. P[model][target] = (mu, sigma) arrays aligned with d."""
    se = d["season"].to_numpy(int); out = {"seasons": seasons, "targets": {}}
    m = mkt.reindex(d["game_id"]).reset_index(drop=True) if mkt is not None else None
    for tname, t in prereg["targets"].items():
        y = d[t["column"]].to_numpy(float)
        base = np.isin(se, seasons) & ~np.isnan(y)
        for mod in P:
            base &= ~np.isnan(P[mod][tname][0])
        if not base.any():
            continue
        boot = _boot(d, base); res = {"n": int(base.sum()), "models": {}, "by_season": {}}
        for mod in P:
            mu, sig = P[mod][tname]
            r = point_metrics(y[base], mu[base])
            if t.get("binary_from_sign"):                       # e.g. margin -> home win
                yy = (y[base] > 0).astype(float); keep = y[base] != 0
                r["win_prob"] = prob_metrics(_ncdf(mu[base] / sig[base])[keep], yy[keep])
            res["models"][mod] = r
        full = prereg["full_model"]; ref = prereg["reference_model"]
        e_full = (P[full][tname][0] - y) ** 2
        for mod in P:
            if mod != full:
                res["models"][mod]["sq_err_minus_full"] = _ci(boot, ((P[mod][tname][0] - y) ** 2 - e_full)[base])
        for s in seasons:
            k = base & (se == s)
            if k.any():
                res["by_season"][str(s)] = {mod: point_metrics(y[k], P[mod][tname][0][k]) for mod in (ref, full)}
        line_col = t.get("market_line")
        if m is not None and line_col and line_col in m:
            L = m[line_col].to_numpy(float); k = base & ~np.isnan(L)
            if k.any():
                bk = _boot(d, k); mu, sig = P[full][tname]
                mk = {"n": int(k.sum()), "market_line": point_metrics(y[k], L[k]), "model": point_metrics(y[k], mu[k]),
                      "sq_err_model_minus_market": _ci(bk, ((mu - y) ** 2 - (L - y) ** 2)[k]),
                      "abs_err_model_minus_market": _ci(bk, (np.abs(mu - y) - np.abs(L - y))[k])}
                # side selection against the line: the model takes the side its mean is on; a push is no decision
                side = np.sign(mu - L); win = np.sign(y - L); dec = k & (side != 0) & (win != 0)
                hit = (side == win).astype(float)
                mk["side_vs_line"] = {"decisions": int(dec.sum()), "pushes_or_no_edge": int(k.sum() - dec.sum()), "hit_rate": _ci(_boot(d, dec), hit[dec] - 0.5),
                                      "note": "hit_rate.mean is (hit rate - 0.5); break-even at -110 pricing needs +0.0238. No price is used: this is direction only."}
                p_side = 1 - _ncdf((L - mu) / sig)          # P(outcome > line)
                yb = (y > L).astype(float); nb = k & (y != L)
                mk["prob_over_line"] = prob_metrics(p_side[nb], yb[nb])
                mk["prob_over_line"]["coin_flip_brier"] = 0.25
                edge = np.abs(mu - L)
                buckets = []
                for lo, hi in prereg.get("edge_buckets", {}).get(tname, []):
                    b = dec & (edge >= lo) & (edge < hi)
                    if b.sum() >= 30:
                        buckets.append({"abs_model_minus_line": [lo, hi], "n": int(b.sum()), "hit_rate": round(float(hit[b].mean()), 4)})
                mk["hit_rate_by_disagreement"] = buckets
                mk["by_season"] = {str(s): {"n": int((k & (se == s)).sum()), "model_mae": round(float(np.abs(mu - y)[k & (se == s)].mean()), 4),
                                            "market_mae": round(float(np.abs(L - y)[k & (se == s)].mean()), 4),
                                            "side_hit_rate": round(float(hit[dec & (se == s)].mean()), 4) if (dec & (se == s)).any() else None}
                                   for s in seasons if (k & (se == s)).any()}
                res["vs_market"] = mk
        pcol = t.get("market_prob")
        if m is not None and pcol and pcol in m and t.get("binary_from_sign"):
            q = m[pcol].to_numpy(float); k = base & ~np.isnan(q) & (y != 0)
            if k.any():
                mu, sig = P[full][tname]; pm = _ncdf(mu / sig); yy = (y > 0).astype(float)
                rows = {"n": int(k.sum()), "model": prob_metrics(pm[k], yy[k]), "market_devig": prob_metrics(q[k], yy[k]),
                        "brier_model_minus_market": _ci(_boot(d, k), ((pm - yy) ** 2 - (q - yy) ** 2)[k]), "by_market_price": []}
                for lo, hi in prereg.get("price_buckets", []):
                    b = k & (q >= lo) & (q < hi)
                    if b.sum() >= 30:
                        rows["by_market_price"].append({"market_p": [lo, hi], "n": int(b.sum()), "outcome_rate": round(float(yy[b].mean()), 4), "market_mean_p": round(float(q[b].mean()), 4),
                                                        "model_mean_p": round(float(pm[b].mean()), 4), "model_brier": round(float(((pm - yy) ** 2)[b].mean()), 5),
                                                        "market_brier": round(float(((q - yy) ** 2)[b].mean()), 5)})
                res["win_prob_vs_market"] = rows
        out["targets"][tname] = res
    return out


def hypotheses(d: pd.DataFrame, prereg: dict, seasons: list[int], cols: set[str]) -> list[dict]:
    """Each preregistered (group, target): does adding the group to the reference model cut squared error on `seasons`? Holm across all."""
    se = d["season"].to_numpy(int); rows = []; wf = sorted(set(prereg["walk_forward_seasons"]))
    ref_groups = prereg["models"][prereg["reference_model"]]
    cache = {}
    for h in prereg["hypotheses"]:
        t = prereg["targets"][h["target"]]; y = d[t["column"]].to_numpy(float)
        if h["target"] not in cache:
            cache[h["target"]] = walk_forward(d, group_columns(prereg, ref_groups, cols), t["column"], wf, prereg["min_train"])[0]
        mu0 = cache[h["target"]]
        mu1 = walk_forward(d, group_columns(prereg, ref_groups + [h["group"]], cols), t["column"], wf, prereg["min_train"])[0]
        k = np.isin(se, seasons) & ~np.isnan(y) & ~np.isnan(mu0) & ~np.isnan(mu1)
        if k.sum() < 50:
            rows.append({**h, "n": int(k.sum()), "verdict": "INSUFFICIENT_SAMPLE"}); continue
        boot = _boot(d, k); boot.season_boot = S.ClusterBoot(se[k])
        g = S.gain_summary(boot, k, (mu0 - y) ** 2, (mu1 - y) ** 2, se, seasons)
        rows.append({**h, "n": int(k.sum()), "gain_sq_err": round(g["mean"], 5), "ci95": [round(x, 5) for x in g["ci_0.05"]], "ci95_season_block": [round(x, 5) for x in g["ci_season_block"]],
                     "p": g["p"], "halves": [round(x, 5) for x in g["halves"]], "seasons_positive": f"{g['seasons_positive']}/{g['seasons_total']}", "_g": g,
                     "rmse_reference": round(float(np.sqrt(np.mean(((mu0 - y) ** 2)[k]))), 4), "rmse_with_group": round(float(np.sqrt(np.mean(((mu1 - y) ** 2)[k]))), 4)})
    hp = S.holm({f"{r['group']}|{r['target']}": r["p"] for r in rows if "p" in r})
    for r in rows:
        if "p" in r:
            r["p_holm"] = round(hp[f"{r['group']}|{r['target']}"], 5); r["p"] = round(r["p"], 5)
            r["verdict"] = S.verdict(r.pop("_g"), r["p_holm"])
    return rows


def run(prereg: dict, d: pd.DataFrame, mkt: pd.DataFrame | None, holdout: bool = False) -> dict:
    cols = set(d.columns)
    d = d[d["season"] >= prereg.get("first_season", 0)]
    d = d.sort_values(["season", prereg["order_column"], "game_id"], kind="mergesort").reset_index(drop=True)
    d["cluster"] = d[prereg["cluster_column"]]
    sp = prereg["splits"]; wf = sorted(set(prereg["walk_forward_seasons"]))
    if set(sp["holdout"]) & (set(sp["dev"]) | set(sp["test"])):
        raise ValueError("holdout seasons overlap dev/test")
    if not holdout:                                   # the holdout outcome is physically removed before any model code runs
        hm = d["season"].isin(sp["holdout"])
        for t in prereg["targets"].values():
            d.loc[hm, t["column"]] = np.nan
    P = {}
    for mod, groups in prereg["models"].items():
        feats = group_columns(prereg, groups, cols)
        P[mod] = {tn: walk_forward(d, feats, t["column"], wf, prereg["min_train"]) for tn, t in prereg["targets"].items()}
    out = {"engine": ENGINE_VERSION, "study": prereg["study"], "prereg_sha256": prereg_hash(prereg), "dataset_sha256": prereg["dataset_sha256"], "rows": len(d),
           "models": {m: {"groups": g, "n_features": len(group_columns(prereg, g, cols))} for m, g in prereg["models"].items()}}
    if holdout:
        out["holdout"] = evaluate_split(d, P, mkt, sp["holdout"], prereg)
    else:
        out["dev"] = evaluate_split(d, P, mkt, sp["dev"], prereg)
        out["test"] = evaluate_split(d, P, mkt, sp["test"], prereg)
        out["hypotheses_dev"] = hypotheses(d, prereg, sp["dev"], cols)
        out["hypotheses_test"] = hypotheses(d, prereg, sp["test"], cols)
    out["_predictions"] = pd.DataFrame({"game_id": d["game_id"], "season": d["season"],
                                        **{f"{tn}_mu": P[prereg["full_model"]][tn][0] for tn in prereg["targets"]},
                                        **{f"{tn}_sigma": P[prereg["full_model"]][tn][1] for tn in prereg["targets"]}})
    return out

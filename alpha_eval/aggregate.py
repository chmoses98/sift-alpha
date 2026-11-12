"""Cell-level aggregation of graded rows. Inference is clustered by event (``group_id``) and, for model-vs-market and
economics, correlated rows (alternate lines / ladder rungs / repeated captures of one event+family) are first COLLAPSED to
one unit so they cannot masquerade as independent observations. Multiple-comparison control (Holm + BH) is applied to the
primary comparison grid only; every other slice is labelled descriptive/unadjusted."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Callable, Iterable

import numpy as np

from sift_research.stats import _group, benjamini_hochberg, cluster_bootstrap, holm

from . import scoring as S
from .schema import BINARY, CATEGORICAL, CONTINUOUS, GRADED, MARKET_INFORMED, ORDINAL_PMF, PROSPECTIVE, SPORTS_ONLY

MIN_CLUSTERS = 30           # below this no directional verdict is issued
MIN_FILLS = 200
N_BOOT = 2000
SEED = 20261112


def _r(x, nd=6):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def status_counts(rows: Iterable[dict], dim: str) -> dict:
    """Accounting for one evaluation dimension: status -> reason -> n. Included in every cell so exclusions stay visible."""
    c = defaultdict(Counter)
    for r in rows:
        e = r[dim]
        c[e["status"]][e["reason"]] += 1
    return {s: dict(v) for s, v in sorted(c.items())}


def _ci(values, clusters, seed=SEED):
    if len(values) == 0:
        return dict(mean=None, lo=None, hi=None, p=None, n=0, n_clusters=0)
    d = cluster_bootstrap(values, clusters, n_boot=N_BOOT, seed=seed)
    return {k: (_r(v) if isinstance(v, float) else v) for k, v in d.items()}


def ratio_ci(num, den, clusters, seed=SEED):
    """Ratio of sums (ROI = sum pnl / sum cost) with event-cluster bootstrap; p-value for H0: ratio = 0 by centring."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    if num.size == 0 or den.sum() <= 0:
        return dict(ratio=None, lo=None, hi=None, p=None, n=int(num.size), n_clusters=0)
    sn, _ = _group(num, clusters)
    sd, _ = _group(den, clusters)
    k = len(sn)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(N_BOOT, k))
    bd = sd[idx].sum(1)
    bm = np.where(bd > 0, sn[idx].sum(1) / np.where(bd > 0, bd, 1), np.nan)
    bm = bm[~np.isnan(bm)]
    ratio = sn.sum() / sd.sum()
    lo, hi = np.quantile(bm, [0.025, 0.975])
    p = (1 + np.sum(np.abs(bm - ratio) >= abs(ratio))) / (len(bm) + 1)
    return dict(ratio=_r(ratio), lo=_r(lo), hi=_r(hi), p=_r(p), n=int(num.size), n_clusters=int(k))


# ------------------------------------------------------------------ accuracy
def accuracy_cell(rows: list) -> dict:
    g = [r for r in rows if r["accuracy"]["status"] == GRADED]
    out = dict(status_counts=status_counts(rows, "accuracy"), n_forecasts=len(rows), n_graded=len(g),
               n_events=len({r["group_id"] for r in g}), by_scoring_type={})
    for st in (BINARY, CONTINUOUS, ORDINAL_PMF, CATEGORICAL):
        sub = [r for r in g if r["scoring_type"] == st]
        if not sub:
            continue
        a, cl = [r["accuracy"] for r in sub], [r["group_id"] for r in sub]
        d = dict(n=len(sub))
        if st == BINARY:
            p, y = [x["p"] for x in a], [x["y"] for x in a]
            d.update(brier=_ci([x["brier"] for x in a], cl), log_loss=_ci([x["log"] for x in a], cl),
                     reliability=S.reliability_summary(p, y), calibration=S.calibration_buckets(p, y))
        elif st == CONTINUOUS:
            d.update(mae=_ci([x["abs_error"] for x in a], cl), rmse=_r(math.sqrt(np.mean([x["sq_error"] for x in a]))),
                     signed_bias=_ci([x["signed_error"] for x in a], cl),
                     bias_note="signed = forecast - actual; positive = over-forecast")
        elif st == ORDINAL_PMF:
            d.update(crps=_ci([x["crps"] for x in a], cl), log_score=_ci([x["log"] for x in a], cl),
                     signed_bias=_ci([x["signed_error"] for x in a], cl), mae_of_mean=_ci([x["abs_error"] for x in a], cl))
        else:
            d.update(brier_multiclass=_ci([x["brier_multiclass"] for x in a], cl), log_score=_ci([x["log"] for x in a], cl),
                     note="multiclass Brier; never a binary Brier")
        out["by_scoring_type"][st] = d
    return out


# ------------------------------------------------------------------ model vs market
def market_cell(rows: list) -> dict:
    ok = [r for r in rows if r["market"]["status"] == GRADED]
    out = dict(status_counts=status_counts(rows, "market"), n_paired_rows=len(ok))
    if not ok:
        out["verdict"] = "NO_PAIRED_DATA"
        return out
    # collapse correlated rows: one unit per (event, model_version, family) so ladders/alternates are not independent
    units = defaultdict(list)
    for r in ok:
        units[(r["group_id"], r["model_version"], r["family"])].append(r)
    dB, dL, dis, cl = [], [], [], []
    for (gid, _, _), rs in units.items():
        m = [x["market"] for x in rs]
        dB.append(np.mean([x["brier_market"] - x["brier_model"] for x in m]))      # + favours MODEL
        dL.append(np.mean([x["log_market"] - x["log_model"] for x in m]))
        dis.append(np.mean([x["signed_disagreement"] for x in m]))
        cl.append(gid)
    b, l = _ci(dB, cl), _ci(dL, cl)
    ind = {r["market"]["independent"] for r in ok}
    out.update(n_collapsed_units=len(units), n_events=len(set(cl)),
               rows_per_unit_mean=_r(len(ok) / len(units), 2),
               model_brier=_r(np.mean([r["market"]["brier_model"] for r in ok])),
               market_brier=_r(np.mean([r["market"]["brier_market"] for r in ok])),
               brier_delta_market_minus_model=b, logloss_delta_market_minus_model=l,
               mean_signed_disagreement_model_minus_market=_r(np.mean(dis)),
               mean_abs_disagreement=_r(np.mean([abs(r["market"]["signed_disagreement"]) for r in ok])),
               independent_sports_only=ind == {True},
               disagreement_note=("disagreement with the market is NOT evidence of predictive advantage; only the paired "
                                  "score delta on identical outcomes counts"),
               market_basis="mid of last two-sided quote at or before forecast freeze (includes vig; not de-vigged)")
    out["_p"] = b["p"]
    ev = {r["evidence_class"] for r in ok}
    out["_evidence"] = ev
    return out


def verdict_for(cell: dict, *, p_holm=None) -> str:
    """Conservative: CONFIRMED needs prospective + sports-only + family-wise-adjusted significance + enough events."""
    b = cell.get("brier_delta_market_minus_model")
    if not b or b["n_clusters"] < MIN_CLUSTERS:
        return "INSUFFICIENT_SAMPLE"
    if b["hi"] is not None and b["hi"] < 0:
        return "MARKET_BETTER"
    if b["lo"] is not None and b["lo"] > 0:
        ok = (cell["_evidence"] == {PROSPECTIVE} and cell.get("independent_sports_only") and p_holm is not None and p_holm < 0.05)
        return "MODEL_BETTER_CONFIRMED" if ok else "MODEL_BETTER_EXPLORATORY_NOT_CONFIRMED"
    return "NOT_DISTINGUISHABLE"


# ------------------------------------------------------------------ economics
def econ_cell(rows: list) -> dict:
    out = dict(status_counts=status_counts(rows, "economics"))
    g = [r for r in rows if r["economics"]["status"] == GRADED]
    out["n_priced_eligible"] = len(g)
    out["n_events"] = len({r["group_id"] for r in g})
    pop = _roi(g, lambda e: True)
    sel = _roi(g, lambda e: e["traded_under_threshold"])
    out["hypothetical_all_rows_model_side"] = dict(pop, label="QUOTED_HYPOTHETICAL, FULL eligible priced population, taker, size 1, top-of-book ask, no depth/slippage")
    out["hypothetical_positive_edge_subset"] = dict(sel, label="QUOTED_HYPOTHETICAL, subset with model edge after fee > threshold; selection-biased, shown beside the full population")
    out["edge_bands"] = _bands(g)
    vf = [r for r in rows if r["economics"].get("verified_fill", {}).get("status") == GRADED]
    v = [r["economics"]["verified_fill"] for r in vf]
    cl = [r["group_id"] for r in vf]
    out["verified_fills"] = dict(n=len(v), n_events=len(set(cl)),
                                 roi=ratio_ci([x["pnl"] for x in v], [x["cost"] for x in v], cl) if v else None,
                                 label="VERIFIED_FILL: exchange fills with exchange-reported fees")
    pos_verified = bool(v) and out["verified_fills"]["roi"]["lo"] is not None and out["verified_fills"]["roi"]["lo"] > 0
    out["profitability_claim"] = (
        "VERIFIED_FILL_EVIDENCE_POSITIVE_REQUIRES_PROSPECTIVE_REVIEW" if (len(v) >= MIN_FILLS and pos_verified)
        else "NO_PROFITABILITY_CLAIM: " + ("no verified fills" if not v else f"verified fills n={len(v)} < {MIN_FILLS} or CI includes 0")
        + "; hypothetical quoted returns are not evidence of realisable profit")
    return out


def _roi(g, pred) -> dict:
    s = [r for r in g if pred(r["economics"])]
    if not s:
        return dict(n=0, roi=None)
    e = [r["economics"] for r in s]
    return dict(n=len(s), hit_rate=_r(np.mean([x["win"] for x in e])), mean_fee=_r(np.mean([x["fee"] for x in e])),
                roi=ratio_ci([x["pnl"] for x in e], [x["cost"] for x in e], [r["group_id"] for r in s]))


def _bands(g, edges=(-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)) -> list:
    out = []
    bounds = [-math.inf, *edges, math.inf]
    for lo, hi in zip(bounds, bounds[1:]):
        s = [r for r in g if lo <= r["economics"]["edge_after_fee"] < hi]
        e = [r["economics"] for r in s]
        out.append(dict(edge_after_fee=f"[{lo}, {hi})", n=len(s),
                        mean_predicted_edge=_r(np.mean([x["edge_after_fee"] for x in e])) if e else None,
                        realised_pnl_per_contract=_r(np.mean([x["pnl"] for x in e])) if e else None))
    return out


# ------------------------------------------------------------------ CLV
def clv_cell(rows: list) -> dict:
    out = dict(status_counts=status_counts(rows, "clv"))
    g = [r for r in rows if r["clv"]["status"] == GRADED]
    cl = [r["group_id"] for r in g]
    out["n"] = len(g)
    out["selection_clv"] = _ci([r["clv"]["selection_clv"] for r in g if r["clv"]["selection_clv"] is not None],
                               [r["group_id"] for r in g if r["clv"]["selection_clv"] is not None])
    q = [r for r in g if r["clv"]["quoted_execution_clv"] is not None]
    out["quoted_execution_clv"] = _ci([r["clv"]["quoted_execution_clv"] for r in q], [r["group_id"] for r in q])
    a = [r for r in g if r["clv"]["actual_fill_clv"] is not None]
    out["actual_fill_clv"] = dict(_ci([r["clv"]["actual_fill_clv"] for r in a], [r["group_id"] for r in a]),
                                  label="ACTUAL FILLS ONLY, reported separately from quoted CLV")
    out["note"] = ("signed, from the model-favoured side: + means the market later moved toward the model. "
                   "CLV is a process diagnostic, not realised profit; quoted CLV is hypothetical")
    return out


def cell(rows: list) -> dict:
    return dict(accuracy=accuracy_cell(rows), model_vs_market=_clean(market_cell(rows)), economics=econ_cell(rows),
                clv=clv_cell(rows))


def _clean(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def primary_grid(rows: list) -> list:
    """sport x family x model_version x evidence_class model-vs-market cells with Holm + BH over ALL cells that have data."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["evidence_class"], r["sport"], r["family"], r["model_version"])].append(r)
    cells = []
    for k, rs in sorted(groups.items()):
        m = market_cell(rs)
        if m.get("n_paired_rows"):
            cells.append((k, m))
    ps = [m["_p"] if m["_p"] is not None else 1.0 for _, m in cells]
    ph = holm(ps) if ps else []
    qb = benjamini_hochberg(ps) if ps else []
    out = []
    for (k, m), h, q in zip(cells, ph, qb):
        out.append(dict(evidence_class=k[0], sport=k[1], family=k[2], model_version=k[3], n_comparisons_in_family=len(cells),
                        p_raw=m["_p"], p_holm=_r(h), q_bh=_r(q), verdict=verdict_for(m, p_holm=float(h)), **_clean(m)))
    return out

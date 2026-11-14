"""Operation Data Foundation: shared contract for collection manifests, feature manifests and challenger evaluations.

RESEARCH_ONLY. Every P0 vertical slice (NBA, CBB, NHL) writes ONE evaluation document with this shape under
``research/data_foundation_ops/<SPORT>/<challenger_id>/evaluation.json``. The pipeline ledger
(``alpha_engine.foundation.ledger``) reads only these documents plus the Market & Input Map, so a dashboard status can
never be claimed without a committed, schema-valid evidence file behind it.

Raw source rows are NEVER written into this repository: slices read the owner's sport repositories from
``$SIFT_REPOS_DIR`` (default ``/home/user/repos``) and commit only aggregates, digests and row counts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "research" / "data_foundation_ops"
EVAL_SCHEMA = "sift-foundation-eval/1"

# Explicit lifecycle stages (owner brief section 14). Order matters; a stage is never implied by a later one.
STAGES = ["IDENTIFIED", "SOURCE_LOCATED", "COLLECTED", "VERIFIED", "FEATURE_BUILT", "CHALLENGER_INTEGRATED", "EVALUATED",
          "VALIDATED_IMPROVEMENT", "PRODUCTION_APPROVED", "PRODUCTION_ACTIVE"]
# Outcome of the stage a record is currently AT (never a percentage).
OUTCOMES = ["OK", "MISSING", "FAILED", "BLOCKED", "REJECTED", "PARTIAL", "UNKNOWN"]
# Verdicts allowed for a challenger result row and for the overall evaluation.
VERDICTS = ["VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED", "INCONCLUSIVE", "NOT_IMPROVED", "REJECTED"]


def repos_dir() -> Path:
    return Path(os.environ.get("SIFT_REPOS_DIR", "/home/user/repos"))


def sha256_file(path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def write_json(path, doc) -> None:
    """Deterministic JSON (sorted keys, 6-dp floats, NaN -> null) so a re-run on the same inputs is byte-identical."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")       # atomic replace: a killed step can never leave a truncated evidence file
    tmp.write_text(json.dumps(_clean(doc), indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


# ------------------------------------------------------------------ scoring helpers (vectorised)
def brier_rows(p, y):
    p = np.asarray(p, float); y = np.asarray(y, float)
    return (p - y) ** 2


def logloss_rows(p, y, eps=1e-6):
    p = np.clip(np.asarray(p, float), eps, 1 - eps); y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def crps_pmf(pmf, y) -> float:
    """Discrete CRPS for an integer-support pmf given as a 1-D array over 0..K (mass above K folded into K)."""
    cdf = np.minimum(np.cumsum(np.asarray(pmf, float)), 1.0)
    k = np.arange(len(cdf))
    return float(np.sum((cdf - (k >= y)) ** 2) + max(0.0, y - (len(cdf) - 1)))


def calibration_slope(p, y, iters=50):
    """Logistic recalibration y ~ a + b*logit(p). b<1 = overconfident, b>1 = underconfident. Returns (a, b)."""
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); y = np.asarray(y, float)
    x = np.log(p / (1 - p)); a, b = 0.0, 1.0
    for _ in range(iters):
        q = 1 / (1 + np.exp(-(a + b * x))); w = np.clip(q * (1 - q), 1e-9, None)
        g = np.array([np.sum(y - q), np.sum((y - q) * x)])
        H = np.array([[np.sum(w), np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x)]]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g); a += step[0]; b += step[1]
        if np.max(np.abs(step)) < 1e-9:
            break
    return float(a), float(b)


def paired_cluster_bootstrap(diff_rows, clusters, n_boot=2000, seed=7):
    """Mean of per-row paired differences (challenger - reference; negative = challenger better for loss metrics)
    with a cluster bootstrap over ``clusters`` (use the GAME id so correlated rows inside a game are resampled
    together). Returns dict(mean, lo, hi, p_two_sided, n_rows, n_clusters)."""
    d = np.asarray(diff_rows, float); c = np.asarray(clusters)
    uniq, inv = np.unique(c, return_inverse=True)
    sums = np.bincount(inv, weights=d, minlength=len(uniq)); cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    boots = sums[idx].sum(1) / cnts[idx].sum(1)
    mean = float(d.mean())
    p = 2 * min(float((boots >= 0).mean()), float((boots <= 0).mean()))
    return dict(mean=mean, lo=float(np.quantile(boots, 0.025)), hi=float(np.quantile(boots, 0.975)), p_two_sided=min(1.0, max(p, 1.0 / n_boot)),
                n_rows=int(len(d)), n_clusters=int(len(uniq)))


def holm(pvals):
    order = np.argsort(pvals); m = len(pvals); out = [0.0] * m; run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * float(pvals[i]))); out[int(i)] = run
    return out


def verdict_from(ci_lo, ci_hi, p_holm, replicated: bool) -> str:
    """Pre-registered rule for LOSS metrics (lower is better; diff = challenger - reference).
    VALIDATED_IMPROVEMENT needs: CI entirely below 0, Holm-adjusted p < 0.05 AND the sign replicated in every
    independent chronological cohort. A favourable single cohort is only IMPROVED_NOT_VALIDATED."""
    if ci_hi < 0 and p_holm < 0.05:
        return "VALIDATED_IMPROVEMENT" if replicated else "IMPROVED_NOT_VALIDATED"
    if ci_lo > 0 and p_holm < 0.05:
        return "NOT_IMPROVED"
    return "INCONCLUSIVE"


CHECK_BASES = ("COMPUTED", "ATTESTED")
ATTESTED = "ATTESTED"   # pass as ``passed`` for a design statement that the run does not independently compute


def check(name, passed, detail, basis="COMPUTED") -> dict:
    """One data/feature check. ``basis`` says how ``passed`` was obtained: COMPUTED = derived from the data in this run;
    ATTESTED = a statement about the design (e.g. "fitted on train only") that the code does not independently verify.
    Attested checks are reported separately everywhere and never counted as verified evidence."""
    if passed is ATTESTED or basis == ATTESTED:
        return {"name": name, "passed": True, "detail": str(detail), "basis": ATTESTED}
    return {"name": name, "passed": bool(passed), "detail": str(detail), "basis": "COMPUTED"}


def validate_evaluation(doc: dict) -> list:
    """Return a list of contract violations (empty = valid)."""
    errs = []
    need = ["schema", "status", "sport", "challenger_id", "incumbent_id", "data", "features", "design", "results", "verdict", "limitations",
            "input_stage_claims", "source_commits"]
    for k in need:
        if k not in doc:
            errs.append(f"missing key {k}")
    if errs:
        return errs
    if doc["schema"] != EVAL_SCHEMA:
        errs.append("bad schema")
    if doc["status"] != "RESEARCH_ONLY":
        errs.append("status must be RESEARCH_ONLY")
    for d in doc["data"]:
        for k in ("dataset_id", "repo", "path", "rows", "first", "last", "rights_tier", "kind"):
            if k not in d:
                errs.append(f"data {d.get('dataset_id')}: missing {k}")
        if d.get("kind") not in ("HISTORICAL_BACKFILL", "PROSPECTIVE_CAPTURE", "WALK_FORWARD_REPRODUCTION"):
            errs.append(f"data {d.get('dataset_id')}: bad kind")
    for f in doc["features"]:
        for k in ("feature_id", "catalog_inputs", "description", "pit_rule", "checks"):
            if k not in f:
                errs.append(f"feature {f.get('feature_id')}: missing {k}")
        for c in f.get("checks", []):
            if not {"name", "passed", "detail", "basis"} <= set(c) or c.get("basis") not in CHECK_BASES:
                errs.append(f"feature {f.get('feature_id')}: malformed check (needs name, passed, detail, basis in {CHECK_BASES})")
            elif c["basis"] == "ATTESTED" and c["passed"] is not True:
                errs.append(f"feature {f.get('feature_id')}: an attested check cannot fail; compute it instead")
    for r in doc["results"]:
        for k in ("market_family", "archetypes", "metric", "reference", "n_rows", "n_clusters", "challenger", "reference_value", "diff", "ci95", "p_holm", "verdict"):
            if k not in r:
                errs.append(f"result {r.get('market_family')}/{r.get('metric')}: missing {k}")
        if r.get("verdict") not in VERDICTS:
            errs.append(f"result {r.get('market_family')}: bad verdict {r.get('verdict')}")
    if doc["verdict"].get("overall") not in VERDICTS:
        errs.append("bad overall verdict")
    for c in doc["input_stage_claims"]:
        if c.get("stage") not in STAGES or c.get("outcome") not in OUTCOMES or ":" not in str(c.get("input", "")):
            errs.append(f"bad input_stage_claim {c}")
    return errs

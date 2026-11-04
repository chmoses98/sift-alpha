"""Shared helpers for the CBB / soccer / tennis outcome-intelligence audits (RESEARCH_ONLY, numpy only).

Re-uses research/outcome_intel/incremental.py unchanged (chronological holdout, game-cluster bootstrap, Holm, negative control).
Rows are dicts: game, t, mid, q, y (+ free extra keys). Nothing here ever trades or touches execution code.
"""
from __future__ import annotations
import hashlib, os, sys, math
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import incremental as I

POWER_MIN_HOLDOUT_GAMES = 30      # below this a null is "underpowered", not a negative result
PROMISING_RAW_P = 0.10            # raw (unadjusted) game-cluster p for "promising"


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def pdt(s):
    if s is None:
        return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def brier_ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(((p - y) ** 2).mean()), float(I.ll(p, y).mean())


def market_only(rows, train_frac=2 / 3, ridge=1.0, min_games=12):
    """Market-only baseline: raw and train-calibrated logloss/Brier on the chronological holdout + whole-sample raw metrics."""
    if not rows:
        return dict(status="NO_ROWS")
    y = np.array([r["y"] for r in rows], float)
    m = np.array([r["mid"] for r in rows], float)
    b, l = brier_ll(m, y)
    games = len({r["game"] for r in rows})
    ci = I.cluster_ci(I.ll(np.clip(m, 1e-6, 1 - 1e-6), y), [r["game"] for r in rows])
    out = dict(n_rows=len(rows), n_games=games, base_rate=float(y.mean()), all_rows_raw=dict(brier=b, logloss=l, logloss_ci=[ci["lo"], ci["hi"]]))
    tr_g, te_g = I.split_games(rows, train_frac)
    tr = [r for r in rows if r["game"] in tr_g]
    te = [r for r in rows if r["game"] in te_g]
    if len(tr_g) < min_games or len(te_g) < min_games or len(tr) < 50:
        out["holdout"] = dict(status="UNDERPOWERED", train_games=len(tr_g), holdout_games=len(te_g))
        return out
    ytr, yte = np.array([r["y"] for r in tr], float), np.array([r["y"] for r in te], float)
    w = I.fit_logistic(I._X(tr, False), ytr, ridge)
    pB = I.sigmoid(I._X(te, False) @ w)
    pR = np.array([r["mid"] for r in te], float)
    out["holdout"] = dict(status="OK", train_games=len(tr_g), holdout_games=len(te_g), n_holdout=len(te), coef=[float(x) for x in w],
                          raw=dict(zip(("brier", "logloss"), brier_ll(pR, yte))), calibrated=dict(zip(("brier", "logloss"), brier_ll(pB, yte))))
    return out


def calibration_bins(rows, k=5):
    m = np.array([r["mid"] for r in rows], float)
    y = np.array([r["y"] for r in rows], float)
    if len(m) < 20:
        return []
    qs = np.quantile(m, np.linspace(0, 1, k + 1))
    out = []
    for i in range(k):
        sel = (m >= qs[i]) & ((m <= qs[i + 1]) if i == k - 1 else (m < qs[i + 1]))
        if sel.sum():
            out.append(dict(lo=float(qs[i]), hi=float(qs[i + 1]), n=int(sel.sum()), mean_mid=float(m[sel].mean()), freq=float(y[sel].mean())))
    return out


def run_challenger(rows):
    """incremental_test + negative control (game-shuffled challenger) + positive control (planted outcome-informed challenger on the SAME rows,
    uses y by construction: it only proves the pipeline can detect a real signal at this sample size)."""
    c = I.incremental_test(rows)
    if c["status"] != "OK":
        return c
    nc = I.negative_control(rows)
    c["negative_control_gain"] = nc.get("gain_vs_calibrated_market_logloss")
    rng = np.random.default_rng(5)
    pos = []
    for r in rows:
        lm = float(I.logit([r["mid"]])[0])
        pos.append(dict(r, q=float(I.sigmoid(lm + 0.8 * (2 * r["y"] - 1) * 0.5 + rng.normal(0, 0.3)))))
    pc = I.incremental_test(pos)
    c["positive_control_gain"] = pc.get("gain_vs_calibrated_market_logloss")
    return c


def classify(c, holm_p):
    """Fixed, pre-declared status rule. c = run_challenger output.
    A significant negative control invalidates only cells that would otherwise claim an improvement (a chance exceedance is expected in ~5% of
    cells, so it is noted on the others and summarised globally by neg_control_summary)."""
    if c is None:
        return "MISSING_DATA", "no challenger rows"
    if c.get("status") != "OK":
        return "INCONCLUSIVE_UNDERPOWERED", "train/holdout split too small (train_games=%s holdout_games=%s)" % (c.get("train_games"), c.get("holdout_games"))
    g = c["gain_vs_calibrated_market_logloss"]
    nc = c.get("negative_control_gain")
    nc_sig = bool(nc and nc["lo"] > 0 and nc["p"] < 0.05)
    note = " [negative control also nominally significant: chance exceedance or leakage, interpret nothing from this cell]" if nc_sig else ""
    if g["lo"] > 0 and holm_p is not None and holm_p <= 0.05:
        return ("INVALID_EVIDENCE", "claimed gain but negative control (shuffled challenger) is also significant") if nc_sig else \
               ("VALIDATED_IMPROVEMENT", "holdout gain CI excludes 0 and Holm p<=0.05 over all cells tried (retrospective chronological holdout, not prospective-confirmed)")
    if g["mean"] > 0 and g["p"] < PROMISING_RAW_P:
        if nc_sig:
            return "INVALID_EVIDENCE", "positive-looking gain but negative control (shuffled challenger) is also significant"
        return "PROMISING_INSUFFICIENT", "positive holdout gain (raw p=%.3f) but CI includes 0 and/or Holm p=%.3f > 0.05" % (g["p"], holm_p if holm_p is not None else float("nan"))
    if c["holdout_games"] >= POWER_MIN_HOLDOUT_GAMES:
        return "NO_DEMONSTRATED_IMPROVEMENT", "holdout gain %.4f [%.4f, %.4f] over %d holdout games; not shown to help (absence of evidence, power limited)%s" % (g["mean"], g["lo"], g["hi"], c["holdout_games"], note)
    return "INCONCLUSIVE_UNDERPOWERED", "only %d holdout games (<%d); gain %.4f [%.4f, %.4f] cannot distinguish zero from a modest effect%s" % (c["holdout_games"], POWER_MIN_HOLDOUT_GAMES, g["mean"], g["lo"], g["hi"], note)


def neg_control_summary(chal):
    """Global view: share of testable cells whose shuffled-challenger control is nominally significant (expect ~2.5% one-sided under the null)."""
    ok = [c for c in chal.values() if c.get("status") == "OK" and c.get("negative_control_gain")]
    sig = [c for c in ok if c["negative_control_gain"]["lo"] > 0 and c["negative_control_gain"]["p"] < 0.05]
    pos = [c for c in chal.values() if c.get("status") == "OK" and c.get("positive_control_gain")]
    det = [c for c in pos if c["positive_control_gain"]["lo"] > 0]
    return dict(testable_cells=len(ok), negative_control_nominally_significant=len(sig), expected_under_null_approx=round(0.025 * len(ok), 1),
                positive_control_detected=len(det), positive_control_cells=len(pos))


def gain_block(c, holm_p):
    if not c or c.get("status") != "OK":
        return dict(mean=None, lo=None, hi=None, holm_p=None)
    g = c["gain_vs_calibrated_market_logloss"]
    return dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], p_raw=g["p"], holm_p=holm_p, n_rows=g["n"], n_games=g["n_games"])


def holm_over(cells):
    """cells: dict name -> challenger result. Holm over EVERY cell tried: cells that could not be tested (status != OK) count in the
    family with p=1 (conservative; they can never be rejected). Returns dict name->adjusted p for OK cells."""
    names = list(cells)
    p = [cells[k]["gain_vs_calibrated_market_logloss"]["p"] if cells[k].get("status") == "OK" else 1.0 for k in names]
    adj = I.holm(p) if names else []
    return {k: float(a) for k, a in zip(names, adj) if cells[k].get("status") == "OK"}


def model_metrics(rows):
    """Standalone (uncalibrated) metrics of the challenger probability q on the same rows."""
    if not rows:
        return None
    y = np.array([r["y"] for r in rows], float)
    q = np.array([r["q"] for r in rows], float)
    b, l = brier_ll(q, y)
    return dict(n_rows=len(rows), brier=b, logloss=l)


CELL_KEYS = ("sport", "family", "horizon", "inputs_available", "n_games", "n_contracts", "price_coverage", "settlement_source", "market_metrics", "model_metrics", "incremental_gain", "status", "reason")


def normalize_cells(cells):
    """Guarantee the delivery schema on every cell (absent -> None, never silently dropped)."""
    for c in cells:
        for k in CELL_KEYS:
            c.setdefault(k, None)
        g = c.get("incremental_gain") or {}
        c["incremental_gain"] = dict(g, **{k: g.get(k) for k in ("mean", "lo", "hi", "holm_p")})
    return cells

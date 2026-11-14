"""CBB challenger ``alpha-cbb-joint-periods-0.1``: one coherent joint distribution over half scores (RESEARCH_ONLY).

The incumbent (``pure-0.2.0`` in chmoses98/cbb-edge-finder) freezes a projected margin / total with two SDs per game and
prices only full-game winner, spread and total. Its panel marks first-half, team-total and overtime contracts as
``no_half_distribution_in_frozen_model`` / ``no_team_score_distribution_in_frozen_model`` / ``no_overtime_model``.
This slice does NOT touch the incumbent's full-game means (margin SD calibration and roster centring are other
workstreams). It adds the missing STRUCTURE: a 4-variate normal over

    X = (home 1H points, away 1H points, home rest-of-game points, away rest-of-game points)

where "rest of game" = final minus first half (second half plus any overtime). Means are ``share x`` the incumbent's
frozen team means; the 4x4 residual second-moment matrix, the first-half shares and two continuity factors (first-half
tie, regulation tie = overtime) are estimated WALK-FORWARD from games that were already archived before the first tip
of the slate being forecast. Every derived probability (team total, 1H winner / spread / total, 2H as the remainder,
overtime, full-game moneyline / spread / total) is a functional of that ONE distribution, so they cannot contradict
each other.

Inputs (read-only; nothing is fetched from the network). Extract the archive branches of the owner's repository once:

    R=/home/user/repos/cbb-edge-finder; A=<scratch>/cbb_arch
    for b in projections-archive period-scores-archive schedule-archive kalshi-panel-archive; do
        mkdir -p $A/$b && git -C $R archive origin/$b | tar -x -C $A/$b
    done
    python -m alpha_engine.foundation.cbb_joint_periods --arch $A      # or SIFT_CBB_ARCH_DIR=$A

Outputs (aggregates only, never raw rows):
``research/data_foundation_ops/CBB/alpha-cbb-joint-periods-0.1/{evaluation.json,predictions_summary.json}``.
Re-running on the same extracted archives is byte-identical (fixed seeds, sorted iteration, no clock).

Unit-testable core (numpy + pandas only): ``select_latest_pretip``, ``fit_params``, ``walk_forward_params``,
``model_arrays``, ``row_probs``, ``settle_rows``.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import contract as C

CHALLENGER_ID = "alpha-cbb-joint-periods-0.1"
INCUMBENT_ID = "pure-0.2.0"
REPO = "chmoses98/cbb-edge-finder"
MAIN_SHA = "2d932f978994bc98c86ad8ffb0cb2af6986231bd"
BRANCHES = ["projections-archive", "period-scores-archive", "schedule-archive", "kalshi-panel-archive"]
OUT_DIR = C.OPS / "CBB" / CHALLENGER_ID

# ------------------------------------------------------------------ documented priors (used alone on the first slates)
# sd_team / rho_home_away: WAVE13_GAME_NUMBER.md section 4 ("implied team-score SD 10.38 ... implied home/away error
# correlation 0.32", the incumbent family's own score_distribution). Those two numbers are functions of the FROZEN
# margin_sd / total_sd only (sqrt((16.95^2 + 12.02^2)/4) = 10.39, (16.95^2 - 12.02^2)/(16.95^2 + 12.02^2) = 0.33), so
# they carry no outcome information even though the report was written inside the evaluation window. The share, the
# independence of the two halves and both continuity factors have NO number in the owner's reports; they are stated
# structural assumptions, given a small pseudo-count so the walk-forward data replace them within a few slates.
PRIOR = dict(
    sd_team=10.38, rho_home_away=0.32,          # WAVE13_GAME_NUMBER.md section 4
    share_1h=0.47,                              # ASSUMPTION (first halves score a bit less than half of the final)
    rho_1h_2h=0.0,                              # ASSUMPTION (independent halves until data say otherwise)
    kappa_1h_tie=1.0, kappa_ot=1.0,             # ASSUMPTION (plain continuity correction, no end-game adjustment)
    ot_base_rate=0.05,                          # ASSUMPTION for the constant-rate overtime reference only
    n0_games=30.0, kappa_k0=3.0, points_per_team_game=72.0,
)
SLATE_SHIFT_H = 10          # slate day = calendar date of (tip - 10h) UTC, i.e. the US evening slate (boundary 05:00 ET)
TIGHT_SPREAD = 0.10         # market mid is used only when 0 < bid < ask < 1 and ask - bid <= 0.10
N_BOOT = 2000
PERIODS = ("1H", "2H", "FULL")
ARCH = {"game_moneyline": ["CBB:game_moneyline_spread"], "game_spread": ["CBB:game_moneyline_spread"],
        "game_total": ["CBB:game_total"], "team_total": ["CBB:team_total"], "overtime": ["CBB:overtime_periods"],
        "first_half_winner": ["CBB:first_half"], "first_half_spread": ["CBB:first_half"], "first_half_total": ["CBB:first_half"],
        "second_half_winner": ["CBB:first_half"], "second_half_spread": ["CBB:first_half"], "second_half_total": ["CBB:first_half"]}
FAMILY = {("WINNER", "FULL"): "game_moneyline", ("MARGIN", "FULL"): "game_spread", ("TOTAL", "FULL"): "game_total",
          ("TEAM_TOTAL", "FULL"): "team_total", ("OVERTIME", "FULL"): "overtime",
          ("WINNER", "1H"): "first_half_winner", ("MARGIN", "1H"): "first_half_spread", ("TOTAL", "1H"): "first_half_total",
          ("WINNER", "2H"): "second_half_winner", ("MARGIN", "2H"): "second_half_spread", ("TOTAL", "2H"): "second_half_total"}
FAMILY_ORDER = list(ARCH)

_erf = np.vectorize(math.erf, otypes=[float])


def phi(z):
    return 0.5 * (1.0 + _erf(np.asarray(z, float) / math.sqrt(2.0)))


def _ts(x):
    return pd.to_datetime(x, utc=True, format="ISO8601")


# ================================================================== pure core (unit-tested on synthetic fixtures)
def select_latest_pretip(runs: pd.DataFrame):
    """``runs``: one row per (game_id, projection run) with tz-aware ``as_of`` and ``tip``.
    Returns (selected, dropped_game_ids): for each game the LATEST run with ``as_of < tip`` (strict); games with no
    such run are dropped and listed."""
    ok = runs[runs["as_of"] < runs["tip"]].sort_values(["game_id", "as_of"], kind="mergesort")
    sel = ok.groupby("game_id", sort=True).tail(1).reset_index(drop=True)
    dropped = sorted(set(runs["game_id"]) - set(sel["game_id"]))
    return sel, dropped


def prior_cov(prior=PRIOR):
    """4x4 prior second-moment matrix for residuals of (h1, a1, h2, a2): each half carries half of the team variance,
    same-half cross-team correlation = rho_home_away, 1H-2H correlation = rho_1h_2h."""
    v = prior["sd_team"] ** 2 / (2.0 * (1.0 + prior["rho_1h_2h"]))
    r, q = prior["rho_home_away"], prior["rho_1h_2h"]
    return v * np.array([[1, r, q, r * q], [r, 1, r * q, q], [q, r * q, 1, r], [r * q, q, r, 1]], float)


def _tie_mass(m, s):
    s = np.maximum(np.asarray(s, float), 1e-9)
    return phi((0.5 - m) / s) - phi((-0.5 - m) / s)


def _resid4(train, sh, sa):
    return np.column_stack([train["h1"] - sh * train["mu_h"], train["a1"] - sa * train["mu_a"],
                            (train["fh"] - train["h1"]) - (1 - sh) * train["mu_h"],
                            (train["fa"] - train["a1"]) - (1 - sa) * train["mu_a"]]).astype(float)


def fit_params(train: pd.DataFrame, prior=PRIOR) -> dict:
    """Estimate every challenger parameter from ``train`` (completed games only; columns mu_h, mu_a, h1, a1, fh, fa, ot).
    Shrinkage is by pseudo-counts so an empty ``train`` returns exactly the documented prior."""
    n = len(train); n0 = prior["n0_games"]; p0 = n0 * prior["points_per_team_game"]
    sh = (prior["share_1h"] * p0 + train["h1"].sum()) / (p0 + train["fh"].sum()) if n else prior["share_1h"]
    sa = (prior["share_1h"] * p0 + train["a1"].sum()) / (p0 + train["fa"].sum()) if n else prior["share_1h"]
    # level-following share for an ablation: first-half points per PROJECTED point (absorbs the incumbent's level bias)
    lh = (prior["share_1h"] * p0 + train["h1"].sum()) / (p0 + train["mu_h"].sum()) if n else prior["share_1h"]
    la = (prior["share_1h"] * p0 + train["a1"].sum()) / (p0 + train["mu_a"].sum()) if n else prior["share_1h"]
    cov = prior_cov(prior)
    sig2 = prior["sd_team"] ** 2
    k1 = prior["kappa_1h_tie"]; kot = prior["kappa_ot"]; ot_rate = prior["ot_base_rate"]
    if n:
        r = _resid4(train, sh, sa)
        cov = (n0 * cov + r.T @ r) / (n0 + n)
        e = np.concatenate([train["fh"] - train["mu_h"], train["fa"] - train["mu_a"]]).astype(float)
        sig2 = (n0 * sig2 + 0.5 * float(e @ e)) / (n0 + n)
        k0 = prior["kappa_k0"]
        w1 = np.array([1.0, -1.0, 0.0, 0.0]); wf = np.array([1.0, -1.0, 1.0, -1.0])
        m1 = (sh * train["mu_h"] - sa * train["mu_a"]).to_numpy(float); mf = (train["mu_h"] - train["mu_a"]).to_numpy(float)
        e1 = float(_tie_mass(m1, math.sqrt(w1 @ cov @ w1)).sum()); ef = float(_tie_mass(mf, math.sqrt(wf @ cov @ wf)).sum())
        k1 = (float((train["h1"] == train["a1"]).sum()) + k0) / (e1 + k0)
        kot = (float((train["ot"] > 0).sum()) + k0) / (ef + k0)
        ot_rate = (prior["ot_base_rate"] * n0 + float((train["ot"] > 0).sum())) / (n0 + n)
    return dict(share_h=float(sh), share_a=float(sa), level_share_h=float(lh), level_share_a=float(la), cov=cov,
                sigma_naive=float(math.sqrt(sig2)), kappa_1h=float(k1), kappa_ot=float(kot), ot_rate=float(ot_rate), n_train=int(n))


def walk_forward_params(games: pd.DataFrame, prior=PRIOR) -> dict:
    """Expanding walk-forward. For slate day D the training set is: games on slates < D whose verified period score
    was ALREADY archived (``obs_at``) before the first tip of slate D. Returns {slate: params + audit fields}."""
    out = {}
    for d in sorted(games["slate"].unique()):
        first_tip = games.loc[games["slate"] == d, "tip"].min()
        earlier = games[games["slate"] < d]
        train = earlier[earlier["obs_at"] < first_tip]
        p = fit_params(train, prior)
        p["train_max_slate"] = None if train.empty else str(train["slate"].max())
        p["n_not_yet_archived"] = int(len(earlier) - len(train))
        out[d] = p
    return out


def model_arrays(games: pd.DataFrame, params: dict, variant="challenger", prior=PRIOR) -> dict:
    """Per-game mean (n,4), covariance (n,4,4) and continuity factors for a model variant.
    Variants: challenger | naive (uncorrelated team scores, fixed 0.5 share, SD/sqrt(2) per half) and the ablations
    no_cross_team_corr | share_050 | level_share | kappa_1 | prior_only."""
    n = len(games); mean = np.zeros((n, 4)); cov = np.zeros((n, 4, 4)); k1 = np.ones(n); kot = np.ones(n)
    mu_h = games["mu_h"].to_numpy(float); mu_a = games["mu_a"].to_numpy(float); slates = games["slate"].to_numpy()
    pri = fit_params(games.iloc[0:0], prior)
    for d in pd.unique(slates):
        i = np.where(slates == d)[0]; p = pri if variant == "prior_only" else params[d]
        sh, sa, cv, a, b = p["share_h"], p["share_a"], p["cov"], p["kappa_1h"], p["kappa_ot"]
        if variant == "naive":
            sh = sa = 0.5; cv = np.eye(4) * p["sigma_naive"] ** 2 / 2.0; a = b = 1.0
        elif variant == "no_cross_team_corr":
            cv = cv.copy()
            for x, y in ((0, 1), (0, 3), (2, 1), (2, 3)):
                cv[x, y] = cv[y, x] = 0.0
        elif variant == "share_050":
            sh = sa = 0.5
        elif variant == "level_share":
            sh, sa = p["level_share_h"], p["level_share_a"]
        elif variant == "kappa_1":
            a = b = 1.0
        mean[i] = np.column_stack([sh * mu_h[i], sa * mu_a[i], (1 - sh) * mu_h[i], (1 - sa) * mu_a[i]])
        cov[i] = cv; k1[i] = a; kot[i] = b
    return dict(mean=mean, cov=cov, k1=k1, kot=kot)


def _weights(rows: pd.DataFrame):
    """Linear functional w.X per contract row. Margins are always HOME minus AWAY; the subject side is applied later."""
    per = rows["period"].to_numpy(); mt = rows["mtype"].to_numpy(); side = rows["side"].to_numpy()
    p1 = np.isin(per, ["1H", "FULL"]).astype(float); p2 = np.isin(per, ["2H", "FULL"]).astype(float)
    ch = np.ones(len(rows)); ca = np.ones(len(rows))
    diff = np.isin(mt, ["MARGIN", "WINNER", "OVERTIME"]); ca[diff] = -1.0
    tt = mt == "TEAM_TOTAL"; ch[tt & (side == "away")] = 0.0; ca[tt & (side == "home")] = 0.0
    return np.column_stack([p1 * ch, p1 * ca, p2 * ch, p2 * ca])


def row_moments(rows, arr):
    w = _weights(rows); gi = rows["gi"].to_numpy(int)
    m = np.einsum("ij,ij->i", w, arr["mean"][gi])
    v = np.einsum("ij,ijk,ik->i", w, arr["cov"][gi], w)
    return m, np.sqrt(np.maximum(v, 1e-12))


def row_probs(rows: pd.DataFrame, arr: dict) -> np.ndarray:
    """P(YES) for every contract row from the ONE joint normal in ``arr``.

    Scores are integers, so every threshold event is evaluated at a half-integer boundary. For margins the cell
    "margin = 0" (mass ``raw0`` under the normal) is re-weighted to ``kappa * raw0`` and the remaining cells are scaled
    by (1 - kappa*raw0)/(1 - raw0): kappa = walk-forward first-half tie factor for 1H, 1 for 2H, and 0 for the full
    game (a final cannot be tied; that regulation-tie mass, times the walk-forward factor kappa_ot, IS the overtime
    probability). Winner / tie / spread rows of one game therefore sum and nest exactly."""
    m, s = row_moments(rows, arr); gi = rows["gi"].to_numpy(int)
    per = rows["period"].to_numpy(); mt = rows["mtype"].to_numpy(); side = rows["side"].to_numpy()
    k = rows["strike"].to_numpy(float)
    p = np.full(len(rows), np.nan)
    tot = np.isin(mt, ["TOTAL", "TEAM_TOTAL"])
    p[tot] = 1.0 - phi((k[tot] - m[tot]) / s[tot])
    mg = np.isin(mt, ["MARGIN", "WINNER", "OVERTIME"])
    raw0 = np.clip(_tie_mass(m, s), 0.0, 1.0 - 1e-9)
    kap = np.where(per == "1H", arr["k1"][gi], np.where(per == "2H", 1.0, 0.0))
    tie = np.clip(kap * raw0, 0.0, 1.0); scale = (1.0 - tie) / (1.0 - raw0)
    ot = mt == "OVERTIME"; p[ot] = np.clip(arr["kot"][gi][ot] * raw0[ot], 0.0, 1.0)
    # home-margin threshold t (half-integer): P(D > t)
    win = mt == "WINNER"; mar = mt == "MARGIN"
    t = np.where(win, 0.5, k)
    home_gt = np.where(t > 0, scale * (1.0 - phi((t - m) / s)), 1.0 - scale * phi((t - m) / s))       # P(D > t)
    away_gt = np.where(t > 0, scale * phi((-t - m) / s), 1.0 - scale * (1.0 - phi((-t - m) / s)))     # P(D < -t)
    sel = (win | mar) & (side == "home"); p[sel] = home_gt[sel]
    sel = (win | mar) & (side == "away"); p[sel] = away_gt[sel]
    sel = win & (side == "tie"); p[sel] = tie[sel]
    return np.clip(p, 0.0, 1.0)


def settle_rows(rows: pd.DataFrame, games: pd.DataFrame) -> np.ndarray:
    """Realised YES (1/0) per row from verified half scores, in the projection's home/away frame."""
    gi = rows["gi"].to_numpy(int); per = rows["period"].to_numpy(); mt = rows["mtype"].to_numpy()
    side = rows["side"].to_numpy(); k = rows["strike"].to_numpy(float)
    h1 = games["h1"].to_numpy(float)[gi]; a1 = games["a1"].to_numpy(float)[gi]
    fh = games["fh"].to_numpy(float)[gi]; fa = games["fa"].to_numpy(float)[gi]; ot = games["ot"].to_numpy(float)[gi]
    H = np.where(per == "1H", h1, np.where(per == "2H", fh - h1, fh)); A = np.where(per == "1H", a1, np.where(per == "2H", fa - a1, fa))
    d = H - A; y = np.full(len(rows), np.nan)
    s = mt == "TOTAL"; y[s] = (H + A)[s] > k[s]
    s = (mt == "TEAM_TOTAL") & (side == "home"); y[s] = H[s] > k[s]
    s = (mt == "TEAM_TOTAL") & (side == "away"); y[s] = A[s] > k[s]
    s = (mt == "MARGIN") & (side == "home"); y[s] = d[s] > k[s]
    s = (mt == "MARGIN") & (side == "away"); y[s] = -d[s] > k[s]
    s = (mt == "WINNER") & (side == "home"); y[s] = d[s] > 0
    s = (mt == "WINNER") & (side == "away"); y[s] = d[s] < 0
    s = (mt == "WINNER") & (side == "tie"); y[s] = d[s] == 0
    s = mt == "OVERTIME"; y[s] = ot[s] > 0
    return y


def incumbent_probs(rows: pd.DataFrame, games: pd.DataFrame):
    """Reference probabilities the incumbent actually defines: frozen home_win_prob, Phi((margin-line)/margin_sd),
    Phi((total-line)/total_sd) (full game only). ``shadow`` = its unvalidated score_distribution team totals,
    RECONSTRUCTED from the frozen SDs by the documented formula (uncorrelated total and margin errors)."""
    gi = rows["gi"].to_numpy(int); per = rows["period"].to_numpy(); mt = rows["mtype"].to_numpy(); side = rows["side"].to_numpy()
    k = rows["strike"].to_numpy(float); g = {c: games[c].to_numpy(float)[gi] for c in ("margin", "total", "msd", "tsd", "hw", "mu_h", "mu_a")}
    p = np.full(len(rows), np.nan); sh = np.full(len(rows), np.nan); full = per == "FULL"
    s = full & (mt == "WINNER") & (side == "home"); p[s] = g["hw"][s]
    s = full & (mt == "WINNER") & (side == "away"); p[s] = 1 - g["hw"][s]
    s = full & (mt == "MARGIN") & (side == "home"); p[s] = phi((g["margin"][s] - k[s]) / g["msd"][s])
    s = full & (mt == "MARGIN") & (side == "away"); p[s] = phi((-g["margin"][s] - k[s]) / g["msd"][s])
    s = full & (mt == "TOTAL"); p[s] = phi((g["total"][s] - k[s]) / g["tsd"][s])
    sd = np.sqrt((g["tsd"] ** 2 + g["msd"] ** 2) / 4.0)
    s = full & (mt == "TEAM_TOTAL") & (side == "home"); sh[s] = phi((g["mu_h"][s] - k[s]) / sd[s])
    s = full & (mt == "TEAM_TOTAL") & (side == "away"); sh[s] = phi((g["mu_a"][s] - k[s]) / sd[s])
    return p, sh


def _half(x):
    return np.floor(np.asarray(x, float)) + 0.5


def synthetic_rows(games: pd.DataFrame, prior=PRIOR) -> pd.DataFrame:
    """Outcome-scoring ladder for EVERY game (market or not). Strikes are fixed functions of the frozen incumbent
    means and the documented prior share only, so they are identical for every model and use no outcome."""
    out = []
    def add(mtype, period, side, strike):
        out.append(pd.DataFrame(dict(gi=np.arange(len(games)), mtype=mtype, period=period, side=side, strike=strike)))
    s0 = prior["share_1h"]
    add("WINNER", "FULL", "home", np.nan); add("OVERTIME", "FULL", "none", np.nan)
    for off in (-6, -3, 0, 3, 6):
        add("MARGIN", "FULL", "home", _half(games["margin"]) + off)
        add("TEAM_TOTAL", "FULL", "home", _half(games["mu_h"]) + off); add("TEAM_TOTAL", "FULL", "away", _half(games["mu_a"]) + off)
        add("MARGIN", "1H", "home", _half(s0 * games["margin"]) + off)
        add("TOTAL", "1H", "none", _half(s0 * games["total"]) + off)
    for off in (-8, -4, 0, 4, 8):
        add("TOTAL", "FULL", "none", _half(games["total"]) + off)
    for side in ("home", "away", "tie"):
        add("WINNER", "1H", side, np.nan)
    r = pd.concat(out, ignore_index=True); r["universe"] = "all_games"
    return r


# ================================================================== archive loaders
def load_projection_runs(arch: Path) -> pd.DataFrame:
    base = arch / "projections-archive" / "projections"
    rows = []
    for f in sorted(glob.glob(str(base / "[0-9]*" / "*" / "*" / "*.json"))):
        d = json.load(open(f)); p = d["projection"]; pr = d["prospective"]
        rows.append(dict(game_id=d["game"]["game_id"], espn=d["game"].get("espn_game_id"), as_of=pr["as_of"], generated_at=d.get("generated_at"),
                         start=d["game"].get("start_time_utc"), site=d["game"].get("site"), version=d["model"]["version"],
                         home_tid=d["home"]["team_id"], away_tid=d["away"]["team_id"], margin=p.get("margin"), total=p.get("total"),
                         mu_h=p.get("home_score"), mu_a=p.get("away_score"), msd=p.get("margin_sd"), tsd=p.get("total_sd"), hw=p.get("home_win_prob"),
                         rel=os.path.relpath(f, base), stamp=os.path.basename(f)[:-5]))
    r = pd.DataFrame(rows)
    for c in ("as_of", "generated_at", "start"):
        r[c] = _ts(r[c])
    return r


def load_manifest_shas(arch: Path) -> dict:
    out = {}
    for f in sorted(glob.glob(str(arch / "projections-archive" / "projections" / "manifests" / "*.json"))):
        out.update(json.load(open(f)).get("files", {}))
    return out


def load_period_scores(arch: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(arch / "period-scores-archive" / "periods" / "*" / "*" / "*" / "*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    q = pd.DataFrame(rows); q["observed_at"] = _ts(q["observed_at"])
    return q


def load_schedule_rows(arch: Path) -> pd.DataFrame:
    keep = ["game_id", "date", "observed_at", "status_type_name", "status_type_state", "home_score", "away_score", "home_id", "away_id", "neutral_site", "time_valid"]
    rows = []
    for f in sorted(glob.glob(str(arch / "schedule-archive" / "rows" / "*" / "*" / "*" / "*.jsonl*"))):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    d = json.loads(line); rows.append({k: d.get(k) for k in keep})
    r = pd.DataFrame(rows); r["observed_at"] = _ts(r["observed_at"]); r["date"] = _ts(r["date"])
    return r


_TK = re.compile(rb'"kalshi_ticker": "([^"]+)"')


def _scan_panel(path: str):
    """One panel partition -> (compact PRETIP rows, {ticker: result}, mapped tickers, unmapped per-game-series tickers)."""
    pre, res, mapped, unmapped = [], {}, [], []
    with gzip.open(path, "rb") as fh:
        for line in fh:
            if b'"mapping_reason": "ok"' not in line:
                if b'"non_game_market"' not in line:
                    m = _TK.search(line)
                    if m:
                        unmapped.append(m.group(1).decode())
                continue
            is_pre = b'"market_phase": "PRETIP"' in line; has_res = b'"result": ""' not in line
            if not (is_pre or has_res):
                m = _TK.search(line)
                if m:
                    mapped.append(m.group(1).decode())
                continue
            r = json.loads(line); tk = r["kalshi_ticker"]; mapped.append(tk)
            if has_res and r.get("result") in ("yes", "no"):
                res[tk] = r["result"]
            if is_pre:
                cs = r.get("contract_semantics") or {}
                inc = ((r.get("market_specific_model_probability") or {}).get(INCUMBENT_ID) or {})
                ver = (((r.get("models_as_of_capture") or {}).get("versions") or {}).get(INCUMBENT_ID) or {})
                pre.append((tk, r["series_ticker"], r["canonical_game_id"], r["captured_at"], r.get("game_start_utc"),
                            r.get("yes_bid_dollars"), r.get("yes_ask_dollars"), cs.get("market_type"), cs.get("period"),
                            cs.get("subject_side"), cs.get("strike"), cs.get("direction"), cs.get("yes_condition"), cs.get("status"),
                            inc.get("probability"), ver.get("as_of"), cs.get("subject_team_id")))
    return pre, res, mapped, unmapped


PANEL_COLS = ["ticker", "series", "game_id", "captured_at", "panel_start", "yes_bid", "yes_ask", "mtype", "period", "side", "strike",
              "direction", "yes_condition", "parse_status", "panel_inc_prob", "panel_inc_as_of", "subject_tid"]


def load_panel(arch: Path, tips: dict, workers=None):
    """Latest PRE-TIP panel observation per Kalshi contract (captured_at < this module's tip when the game is known,
    else the panel's own game_start), plus Kalshi's settled result and the per-series contract inventory."""
    files = sorted(glob.glob(str(arch / "kalshi-panel-archive" / "panels" / "*" / "*" / "*" / "*.panel.jsonl.gz")))
    last, res, mapped, unmapped, late = {}, {}, set(), set(), 0
    with ProcessPoolExecutor(max_workers=workers or min(8, os.cpu_count() or 1)) as ex:
        for pre, r, mp, um in ex.map(_scan_panel, files, chunksize=4):
            res.update(r); mapped.update(mp); unmapped.update(um)
            for row in pre:
                tip = tips.get(row[2]); cap = row[3]
                if tip is None:
                    tip = row[4]
                if tip is not None and cap < tip:        # ISO-8601 UTC strings with identical layout compare correctly
                    last[row[0]] = row
                else:
                    late += 1
    df = pd.DataFrame([last[k] for k in sorted(last)], columns=PANEL_COLS)
    return df, res, mapped, unmapped, dict(panel_files=len(files), first=os.path.basename(files[0])[11:27] if files else None,
                                           last=os.path.basename(files[-1])[11:27] if files else None, pretip_rows_at_or_after_tip=late)


def git_shas(repo: Path) -> dict:
    out = {"cbb-edge-finder": MAIN_SHA}
    for b in BRANCHES:
        try:
            out[f"cbb-edge-finder@origin/{b}"] = subprocess.run(["git", "-C", str(repo), "rev-parse", f"origin/{b}"], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            out[f"cbb-edge-finder@origin/{b}"] = None
    return out


# ================================================================== game table
def build_games(arch: Path, teams_csv: Path):
    """Join frozen incumbent projections <-> verified period scores <-> schedule finals. Returns (games, audit)."""
    runs = load_projection_runs(arch); runs = runs[runs["version"] == INCUMBENT_ID].reset_index(drop=True)
    ps = load_period_scores(arch); sched = load_schedule_rows(arch); man = load_manifest_shas(arch)
    audit, checks = {}, []

    def chk(name, passed, detail):
        checks.append(dict(name=name, passed=bool(passed), detail=str(detail)))

    # ---- scheduled tip: last pre-game ESPN schedule observation with a valid time; never later than the projection's own listed start
    pre = sched[(sched["status_type_state"] == "pre") & (sched["time_valid"] == True)].sort_values(["game_id", "observed_at"], kind="mergesort")  # noqa: E712
    sched_tip = pre.groupby("game_id")["date"].last()
    last_start = runs.sort_values(["game_id", "as_of"], kind="mergesort").groupby("game_id")["start"].last()
    espn_of = runs.groupby("game_id")["espn"].first()
    tip = {}
    n_sched = n_agree = 0
    for gid, st in last_start.items():
        t2 = sched_tip.get(espn_of[gid])
        if t2 is not None and not pd.isna(t2):
            n_sched += 1; n_agree += int(t2 == st)
            st = min(st, t2) if not pd.isna(st) else t2
        tip[gid] = st
    runs["tip"] = runs["game_id"].map(tip)
    audit["tip_source"] = dict(games=len(tip), with_schedule_archive_pre_tip_obs=n_sched, schedule_equals_projection_listed_start=n_agree)

    # ---- period scores: checks and de-duplication
    n_dup = int(ps.duplicated("espn_game_id").sum())
    ps = ps.sort_values(["espn_game_id", "observed_at"], kind="mergesort").drop_duplicates("espn_game_id", keep="last").reset_index(drop=True)
    hp = ps["home_periods"].map(list); ap = ps["away_periods"].map(list)
    sum_ok = (hp.map(sum) == ps["final_home"]) & (ap.map(sum) == ps["final_away"])
    h1_ok = (hp.map(lambda x: x[0]) == ps["first_half_home"]) & (ap.map(lambda x: x[0]) == ps["first_half_away"])
    reg_ok = (hp.map(lambda x: x[0] + x[1]) == ps["regulation_home"]) & (ap.map(lambda x: x[0] + x[1]) == ps["regulation_away"])
    ot_ok = (hp.map(len) == 2 + ps["overtime_periods"]) & (ap.map(len) == 2 + ps["overtime_periods"]) & \
            (hp.map(lambda x: sum(x[2:])) == ps["overtime_home"]) & (ap.map(lambda x: sum(x[2:])) == ps["overtime_away"])
    tie_ok = ((ps["overtime_periods"] > 0) == (ps["regulation_home"] == ps["regulation_away"])) & (ps["final_home"] != ps["final_away"])
    flagged = (~ps["verified"].astype(bool)) | (ps["flags"].map(len) > 0) | (~ps["completed"].astype(bool))
    chk("period_scores_duplicate_game_ids", n_dup == 0, f"{n_dup} duplicate espn_game_id rows in {len(ps) + n_dup} period-score rows (latest observation kept)")
    chk("half_and_ot_periods_sum_to_final", bool(sum_ok.all()), f"{int((~sum_ok).sum())} of {len(ps)} games where sum(periods) != final (home or away)")
    chk("first_half_field_equals_first_period", bool(h1_ok.all()), f"{int((~h1_ok).sum())} mismatches of {len(ps)}")
    chk("regulation_equals_two_halves", bool(reg_ok.all()), f"{int((~reg_ok).sum())} mismatches of {len(ps)}")
    chk("overtime_points_and_period_count_consistent", bool(ot_ok.all()), f"{int((~ot_ok).sum())} mismatches of {len(ps)}; {int((ps['overtime_periods'] > 0).sum())} overtime games")
    chk("overtime_iff_regulation_tie_and_no_tied_final", bool(tie_ok.all()), f"{int((~tie_ok).sum())} violations of {len(ps)}")
    chk("period_scores_all_verified_unflagged_final", not bool(flagged.any()), f"{int(flagged.sum())} unverified / flagged / incomplete rows (excluded)")
    plaus = ps["final_home"].between(30, 160) & ps["final_away"].between(20, 160) & ps["first_half_home"].between(8, 90) & ps["first_half_away"].between(5, 90)
    chk("score_plausibility", bool(plaus.all()), f"{int((~plaus).sum())} of {len(ps)} games outside final 20-160 (home 30-160) / first-half 5-90 (home 8-90), of which {int((~plaus & ps['espn_game_id'].isin(runs['espn'])).sum())} have an incumbent projection (kept: scores verified and cross-checked); min final {int(min(ps['final_home'].min(), ps['final_away'].min()))}, max final {int(max(ps['final_home'].max(), ps['final_away'].max()))}")
    ps_ok = ps[sum_ok & h1_ok & reg_ok & ot_ok & tie_ok & ~flagged].copy()

    # ---- finals cross-check against the independent schedule-archive ESPN final rows
    fin = sched[sched["status_type_name"] == "STATUS_FINAL"].sort_values(["game_id", "observed_at"], kind="mergesort").drop_duplicates("game_id", keep="last")
    x = ps_ok.merge(fin, left_on="espn_game_id", right_on="game_id", how="left")
    have = x["game_id"].notna()
    same = have & (x["final_home"] == x["home_score"]) & (x["final_away"] == x["away_score"]) & (x["home_team_id"].astype(float) == x["home_id"].astype(float))
    chk("period_finals_match_schedule_archive_finals", bool((same | ~have).all()),
        f"{int(have.sum())} of {len(x)} period-score games have a schedule-archive STATUS_FINAL row; {int((have & ~same).sum())} disagree on final score or home team id")

    # ---- latest pre-tip projection
    all_games = sorted(runs["game_id"].unique())
    sel, no_pretip = select_latest_pretip(runs[runs["tip"].notna()])
    no_tip = sorted(set(all_games) - set(runs.loc[runs["tip"].notna(), "game_id"]))
    val_cols = ["margin", "total", "mu_h", "mu_a", "msd", "tsd", "hw"]
    miss = sel[val_cols].isna().any(axis=1)
    chk("used_projection_missing_values", not bool(miss.any()), f"{int(miss.sum())} of {len(sel)} selected projections with a null margin/total/team mean/SD/win probability (dropped)")
    recomposed = (np.abs(sel["mu_h"] + sel["mu_a"] - sel["total"]) < 1e-6) & (np.abs(sel["mu_h"] - sel["mu_a"] - sel["margin"]) < 1e-6)
    chk("team_means_recompose_to_total_and_margin", bool(recomposed.all()), f"{int((~recomposed).sum())} of {len(sel)} projections where home+away != total or home-away != margin (1e-6)")
    sel = sel[~miss].reset_index(drop=True)

    # ---- orientation (canonical team id -> ESPN id) and outcome join
    teams = pd.read_csv(teams_csv, usecols=["team_id", "espn_team_id"]).dropna()
    t2e = dict(zip(teams["team_id"], teams["espn_team_id"].astype(int)))
    g = sel.merge(ps_ok, left_on="espn", right_on="espn_game_id", how="left")
    scored = g["espn_game_id"].notna()
    last_scored_tip = g.loc[scored, "tip"].max()
    eh = g["home_tid"].map(t2e); ea = g["away_tid"].map(t2e); ph = pd.to_numeric(g["home_team_id"], errors="coerce"); pa = pd.to_numeric(g["away_team_id"], errors="coerce")
    same_o = scored & (eh == ph) & (ea == pa)
    swap_o = scored & (eh == pa) & (ea == ph) & (g["site"] == "neutral")
    unver = scored & ~same_o & ~swap_o
    g["orientation"] = np.where(same_o, "SAME", np.where(swap_o, "SWAPPED", np.where(unver, "UNVERIFIED", "NO_SCORE")))
    for a, b, c in (("fh", "final_home", "final_away"), ("h1", "first_half_home", "first_half_away")):
        g[a] = np.where(swap_o, g[c], g[b])
    for a, b, c in (("fa", "final_away", "final_home"), ("a1", "first_half_away", "first_half_home")):
        g[a] = np.where(swap_o, g[c], g[b])
    g["ot"] = g["overtime_periods"]; g["obs_at"] = g["observed_at"]
    used = g[same_o | swap_o].copy()
    used["slate"] = (used["tip"] - pd.Timedelta(hours=SLATE_SHIFT_H)).dt.strftime("%Y-%m-%d")
    used["lead_h"] = (used["tip"] - used["as_of"]).dt.total_seconds() / 3600.0
    used = used.sort_values(["tip", "game_id"], kind="mergesort").reset_index(drop=True)

    # ---- point-in-time checks on the used projections
    asof_ok = used["as_of"] < used["tip"]
    chk("as_of_before_scheduled_tip_for_every_used_projection", bool(asof_ok.all()), f"{int((~asof_ok).sum())} violations in {len(used)} used games; minimum lead {used['lead_h'].min() * 60:.1f} minutes")
    gen_ok = (used["generated_at"] >= used["as_of"]) & (used["generated_at"] < used["tip"])
    chk("generated_at_between_as_of_and_tip", bool(gen_ok.all()), f"{int((~gen_ok).sum())} of {len(used)} used projection files whose generated_at is before as_of or not before tip")
    stamp_ok = used["stamp"] == used["as_of"].dt.strftime("%Y-%m-%dT%H%M%S.%fZ")
    chk("file_name_stamp_equals_as_of", bool(stamp_ok.all()), f"{int((~stamp_ok).sum())} of {len(used)} mismatches")
    base = arch / "projections-archive" / "projections"
    in_man = used["rel"].map(lambda r: r in man); sha_ok = [(man.get(r) == C.sha256_file(base / r)) for r in used["rel"]]
    chk("used_projection_files_match_manifest_sha256", bool(np.all(sha_ok)), f"{int(in_man.sum())} of {len(used)} used files listed in the archive's run manifests; {int(np.sum(sha_ok))} match their manifest sha256")
    obs_ok = used["obs_at"] > used["tip"]
    chk("period_score_observed_after_tip", bool(obs_ok.all()), f"{int((~obs_ok).sum())} of {len(used)} outcomes observed at or before tip")
    lo, hi = used.groupby("slate")["tip"].min(), used.groupby("slate")["tip"].max()
    gap = [(lo.iloc[i] - hi.iloc[i - 1]).total_seconds() / 3600.0 for i in range(1, len(lo))]
    chk("slates_do_not_overlap_in_time", bool(min(gap) > 2.5) if gap else True, f"minimum gap between the last tip of a slate and the first tip of the next: {min(gap):.2f} h" if gap else "single slate")
    chk("projection_period_score_join_rate", True,
        f"{int(scored.sum())} of {int((g['tip'] <= last_scored_tip).sum())} projected games tipping on or before the last scored tip have a verified period score; "
        f"{int(ps_ok['espn_game_id'].isin(runs['espn']).sum())} of {len(ps_ok)} period-score games have an incumbent projection "
        f"({int((~ps_ok['espn_game_id'].isin(runs['espn'])).sum())} without one, i.e. never projected by the incumbent)")
    chk("home_away_orientation_verified_by_team_id", int(unver.sum()) == 0, f"SAME {int(same_o.sum())}, SWAPPED on a neutral site (scores remapped) {int(swap_o.sum())}, UNVERIFIED (dropped) {int(unver.sum())}")

    not_scored = g[~scored]
    audit["games"] = dict(
        incumbent_projection_games=len(all_games), incumbent_projection_files=int(len(runs)),
        period_score_games=int(len(ps)), used=int(len(used)),
        dropped=dict(no_scheduled_tip=len(no_tip), no_projection_before_tip=len(no_pretip), projection_missing_values=int(miss.sum()),
                     no_verified_period_score_tip_after_last_scored=int((not_scored["tip"] > last_scored_tip).sum()),
                     no_verified_period_score_tip_within_scored_range=int((not_scored["tip"] <= last_scored_tip).sum()),
                     orientation_unverified=int(unver.sum()), period_score_failed_integrity=int(len(ps) - len(ps_ok))),
        period_score_games_without_incumbent_projection=int((~ps_ok["espn_game_id"].isin(runs["espn"])).sum()),
        neutral_site_used=int((used["site"] == "neutral").sum()), overtime_games_used=int((used["ot"] > 0).sum()),
        first_tip=str(used["tip"].min()), last_tip=str(used["tip"].max()))
    q = used["lead_h"].quantile([0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    audit["projection_lead_hours"] = {f"q{int(k * 100):03d}": float(v) for k, v in q.items()} | {"mean": float(used["lead_h"].mean())}
    audit["data_rows"] = dict(proj_files=int(len(runs)), proj_first=str(runs["as_of"].min()), proj_last=str(runs["as_of"].max()),
                              ps_rows=int(len(ps) + n_dup), ps_first=str(ps["observed_at"].min()), ps_last=str(ps["observed_at"].max()),
                              sched_rows=int(len(sched)), sched_first=str(sched["observed_at"].min()), sched_last=str(sched["observed_at"].max()))
    keep = ["game_id", "espn", "tip", "as_of", "slate", "lead_h", "site", "orientation", "home_tid", "away_tid", "margin", "total", "mu_h", "mu_a", "msd", "tsd", "hw", "h1", "a1", "fh", "fa", "ot", "obs_at"]
    used = used[keep].copy()
    for c in ("h1", "a1", "fh", "fa", "ot"):
        used[c] = used[c].astype(float)
    return used, audit, checks, {gid: t.isoformat() for gid, t in tip.items() if not pd.isna(t)}


# ================================================================== evaluation helpers
def _score(p, y, metric):
    return C.brier_rows(p, y) if metric == "brier" else C.logloss_rows(p, y)


def _cohort_of(slates):
    days = sorted(set(slates)); d0, d1 = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    cut = d0 + pd.Timedelta(days=((d1 - d0).days + 1) // 2)
    return cut.strftime("%Y-%m-%d")


def compare(rows, p_ch, p_ref, ref_name, universe, headline_refs):
    """Result rows (pooled + two chronological cohorts, Brier + log loss) for one reference on rows where it is defined."""
    out = []
    ok = np.isfinite(p_ch) & np.isfinite(p_ref) & np.isfinite(rows["y"].to_numpy(float))
    for fam in FAMILY_ORDER:
        fm = ok & (rows["family"].to_numpy() == fam)
        if fm.sum() == 0 or rows.loc[fm, "game_id"].nunique() < 10:
            continue
        for metric in ("brier", "logloss"):
            per = {}
            for coh in ("pooled", "cohort_1", "cohort_2"):
                m = fm if coh == "pooled" else fm & (rows["cohort"].to_numpy() == coh)
                if m.sum() == 0 or rows.loc[m, "game_id"].nunique() < 3:
                    continue
                y = rows.loc[m, "y"].to_numpy(float); a = _score(p_ch[m], y, metric); b = _score(p_ref[m], y, metric)
                bs = C.paired_cluster_bootstrap(a - b, rows.loc[m, "game_id"].to_numpy(), n_boot=N_BOOT, seed=7)
                per[coh] = dict(bs=bs, ch=float(a.mean()), ref=float(b.mean()))
            signs = [np.sign(per[c]["bs"]["mean"]) for c in ("pooled", "cohort_1", "cohort_2") if c in per]
            replicated = bool(len(signs) == 3 and signs[0] != 0 and signs[0] == signs[1] == signs[2])
            for coh, v in per.items():
                bs = v["bs"]
                out.append(dict(market_family=fam, archetypes=ARCH[fam], universe=universe, metric=metric, reference=ref_name, cohort=coh,
                                n_rows=bs["n_rows"], n_clusters=bs["n_clusters"], challenger=v["ch"], reference_value=v["ref"], diff=bs["mean"],
                                ci95=[bs["lo"], bs["hi"]], p_raw=bs["p_two_sided"], p_holm=1.0, replicated=replicated,
                                headline=bool(coh == "pooled" and metric == "brier" and ref_name in headline_refs), verdict="INCONCLUSIVE"))
    return out


def finalize_verdicts(results):
    hl = [r for r in results if r["headline"]]
    for r, ph in zip(hl, C.holm([r["p_raw"] for r in hl])):
        r["p_holm"] = float(ph)
    for r in results:
        r["verdict"] = C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"])
    return results


def _corr_ci(a, b, seed=11, n_boot=N_BOOT):
    a = np.asarray(a, float); b = np.asarray(b, float); n = len(a)
    r = float(np.corrcoef(a, b)[0, 1]); rng = np.random.default_rng(seed); idx = rng.integers(0, n, size=(n_boot, n))
    A = a[idx]; B = b[idx]; A = A - A.mean(1, keepdims=True); B = B - B.mean(1, keepdims=True)
    bs = (A * B).sum(1) / np.sqrt((A * A).sum(1) * (B * B).sum(1))
    return dict(estimate=r, ci95=[float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))], n_games=int(n))


def _pit(y, m, s):
    z = (np.asarray(y, float) - m) / s; u = phi(z)
    return dict(n=int(len(u)), hist10=[int(v) for v in np.histogram(u, bins=np.linspace(0, 1, 11))[0]], cover80=float(((u >= 0.1) & (u <= 0.9)).mean()),
                cover50=float(((u >= 0.25) & (u <= 0.75)).mean()), z_mean=float(z.mean()), z_sd=float(z.std(ddof=0)), mean_error=float((np.asarray(y, float) - m).mean()))


def pit_block(games, arr):
    """PIT histogram / interval coverage of the continuous marginals (normal PIT at the integer outcome)."""
    n = len(games); gi = np.arange(n); out = {}

    def one(name, mtype, period, side, y, rows_gi=gi):
        r = pd.DataFrame(dict(gi=rows_gi, mtype=mtype, period=period, side=side, strike=np.nan)); m, s = row_moments(r, arr)
        res = {"pooled": _pit(y, m, s)}
        for coh in ("cohort_1", "cohort_2"):
            k = games["cohort"].to_numpy()[rows_gi] == coh
            res[coh] = _pit(np.asarray(y)[k], m[k], s[k])
        out[name] = res
    one("first_half_total", "TOTAL", "1H", "none", games["h1"] + games["a1"])
    one("first_half_margin", "MARGIN", "1H", "home", games["h1"] - games["a1"])
    one("game_total", "TOTAL", "FULL", "none", games["fh"] + games["fa"])
    one("game_margin", "MARGIN", "FULL", "home", games["fh"] - games["fa"])
    r = pd.DataFrame(dict(gi=np.concatenate([gi, gi]), mtype="TEAM_TOTAL", period="FULL", side=["home"] * n + ["away"] * n, strike=np.nan)); m, s = row_moments(r, arr)
    y = np.concatenate([games["fh"], games["fa"]]); coh = np.concatenate([games["cohort"], games["cohort"]])
    out["team_total"] = {"pooled": _pit(y, m, s), "cohort_1": _pit(y[coh == "cohort_1"], m[coh == "cohort_1"], s[coh == "cohort_1"]),
                         "cohort_2": _pit(y[coh == "cohort_2"], m[coh == "cohort_2"], s[coh == "cohort_2"])}
    return out


def _cov_summary(cv):
    sd = np.sqrt(np.diag(cv)); wH = np.array([1, 0, 1, 0.0]); wA = np.array([0, 1, 0, 1.0]); wT = wH + wA; wM = wH - wA
    w1T = np.array([1, 1, 0, 0.0]); w2T = np.array([0, 0, 1, 1.0]); w1M = np.array([1, -1, 0, 0.0]); w2M = np.array([0, 0, 1, -1.0])
    c = lambda a, b: float(a @ cv @ b / math.sqrt((a @ cv @ a) * (b @ cv @ b)))
    s = lambda a: float(math.sqrt(a @ cv @ a))
    return dict(sd_home_final=s(wH), sd_away_final=s(wA), sd_total=s(wT), sd_margin=s(wM), corr_home_away_final=c(wH, wA), corr_total_margin=c(wT, wM),
                sd_home_1h=float(sd[0]), sd_away_1h=float(sd[1]), sd_total_1h=s(w1T), sd_margin_1h=s(w1M), corr_home_away_1h=c(np.eye(4)[0], np.eye(4)[1]),
                corr_1h_2h_home=c(np.eye(4)[0], np.eye(4)[2]), corr_1h_2h_away=c(np.eye(4)[1], np.eye(4)[3]), corr_1h_2h_total=c(w1T, w2T), corr_1h_2h_margin=c(w1M, w2M))


# ================================================================== main run
def run(arch: Path, teams_csv: Path, repo: Path, out_dir: Path = OUT_DIR, workers=None):
    games, audit, checks, tips = build_games(arch, teams_csv)
    cut = _cohort_of(games["slate"])
    games["cohort"] = np.where(games["slate"] < cut, "cohort_1", "cohort_2")
    params = walk_forward_params(games)
    leak_ok = all(p["train_max_slate"] is None or p["train_max_slate"] < d for d, p in params.items())
    checks.append(dict(name="walk_forward_training_strictly_before_slate", passed=bool(leak_ok),
                       detail="for every slate D the newest training game is on a slate < D and its period score was archived before the first tip of D; "
                              + "; ".join(f"{d}: n={p['n_train']} (not yet archived {p['n_not_yet_archived']})" for d, p in params.items())))
    variants = ["challenger", "naive", "no_cross_team_corr", "share_050", "level_share", "kappa_1", "prior_only"]
    arrs = {v: model_arrays(games, params, v) for v in variants}
    gidx = {g: i for i, g in enumerate(games["game_id"])}

    # ---------------- rows: synthetic ladder on every used game
    syn = synthetic_rows(games)
    # ---------------- rows: Kalshi-listed contracts, latest pre-tip snapshot
    panel, kres, mapped, unmapped, pmeta = load_panel(arch, tips, workers)
    panel["bid"] = pd.to_numeric(panel["yes_bid"], errors="coerce"); panel["ask"] = pd.to_numeric(panel["yes_ask"], errors="coerce")
    panel["two_sided"] = (panel["bid"] > 0) & (panel["ask"] < 1) & (panel["ask"] > panel["bid"])
    panel["tight"] = panel["two_sided"] & ((panel["ask"] - panel["bid"]) <= TIGHT_SPREAD + 1e-9)
    panel["mid"] = np.where(panel["tight"], (panel["bid"] + panel["ask"]) / 2.0, np.nan)
    panel["side"] = panel["side"].fillna("none"); panel["strike"] = pd.to_numeric(panel["strike"], errors="coerce")
    panel["family"] = [FAMILY.get((a, b)) for a, b in zip(panel["mtype"], panel["period"])]
    panel["in_used_game"] = panel["game_id"].isin(gidx)
    kal = panel[panel["family"].notna() & panel["in_used_game"]].copy()
    strike_needed = kal["mtype"].isin(["MARGIN", "TOTAL", "TEAM_TOTAL"])
    bad_strike = strike_needed & ~((kal["strike"] * 2) % 2 == 1) | (strike_needed & (kal["direction"] != "greater"))
    checks.append(dict(name="kalshi_strikes_are_half_integer_greater_than", passed=not bool(bad_strike.any()),
                       detail=f"{int(bad_strike.sum())} of {int(strike_needed.sum())} listed threshold contracts in used games with a non-half-integer strike or a direction other than 'greater' (excluded)"))
    kal = kal[~bad_strike].copy()
    kal["gi"] = kal["game_id"].map(gidx).astype(int); kal["universe"] = "kalshi_listed"
    # subject side by TEAM IDENTITY in the projection's frame (the panel's home/away is the schedule's, which is reversed for SWAPPED games)
    teamed = kal["side"].isin(["home", "away"]); ht = games["home_tid"].to_numpy()[kal["gi"]]; at = games["away_tid"].to_numpy()[kal["gi"]]
    by_id = np.where(kal["subject_tid"].to_numpy() == ht, "home", np.where(kal["subject_tid"].to_numpy() == at, "away", "unresolved"))
    n_flip = int((teamed & (by_id != kal["side"]) & (by_id != "unresolved")).sum()); n_unres = int((teamed & (by_id == "unresolved")).sum())
    kal["side"] = np.where(teamed, by_id, kal["side"]); kal = kal[kal["side"] != "unresolved"].copy()
    checks.append(dict(name="kalshi_subject_side_resolved_by_team_id", passed=n_unres == 0,
                       detail=f"{int(teamed.sum())} team-sided contracts in used games: {n_flip} had the panel's home/away label reversed relative to the projection frame (neutral-site SWAPPED games) and were re-labelled by subject_team_id; {n_unres} unresolved (dropped)"))
    kal["lead_min"] = (games["tip"].to_numpy()[kal["gi"]] - _ts(kal["captured_at"]).to_numpy()) / np.timedelta64(1, "m")
    rows = pd.concat([syn, kal[["gi", "mtype", "period", "side", "strike", "universe", "ticker", "mid", "two_sided", "tight", "lead_min", "panel_inc_prob", "panel_inc_as_of"]]], ignore_index=True)
    rows["game_id"] = games["game_id"].to_numpy()[rows["gi"]]; rows["cohort"] = games["cohort"].to_numpy()[rows["gi"]]
    rows["family"] = [FAMILY[(a, b)] for a, b in zip(rows["mtype"], rows["period"])]
    rows["y"] = settle_rows(rows, games)
    P = {v: row_probs(rows, arrs[v]) for v in variants}
    p_inc, p_shadow = incumbent_probs(rows, games)
    p_otbase = np.where(rows["mtype"] == "OVERTIME", np.array([params[s]["ot_rate"] for s in games["slate"]])[rows["gi"]], np.nan)
    p_mkt = np.where(rows["universe"] == "kalshi_listed", rows["mid"].to_numpy(float), np.nan)

    # ---------------- data checks that need the panel
    isk = (rows["universe"] == "kalshi_listed").to_numpy()
    kr = rows.loc[isk, "ticker"].map(kres)
    have = kr.notna().to_numpy(); agree = (kr[have] == "yes").to_numpy() == (rows.loc[isk, "y"].to_numpy()[have] == 1)
    fam_k = rows.loc[isk, "family"].to_numpy()[have]
    dis = {f: int((~agree[fam_k == f]).sum()) for f in FAMILY_ORDER if (fam_k == f).any() and (~agree[fam_k == f]).any()}
    checks.append(dict(name="own_settlement_matches_kalshi_settled_result", passed=bool(agree.all()),
                       detail=f"{int(have.sum())} listed contracts in used games carry a Kalshi result in a later panel; {int(agree.sum())} agree with the outcome settled here from verified half scores"
                              f" (first-half TIE contracts included: a tied half settles both team contracts NO); disagreements by family {dis}"))
    same_asof = isk & (_ts(rows["panel_inc_as_of"]).to_numpy() == games["as_of"].to_numpy()[rows["gi"]]) & np.isfinite(pd.to_numeric(rows["panel_inc_prob"], errors="coerce").to_numpy(float))
    dmax = float(np.nanmax(np.abs(pd.to_numeric(rows["panel_inc_prob"], errors="coerce").to_numpy(float)[same_asof] - p_inc[same_asof]))) if same_asof.any() else float("nan")
    checks.append(dict(name="incumbent_probability_reproduces_panel", passed=bool(same_asof.any() and dmax < 1e-9),
                       detail=f"{int(same_asof.sum())} full-game contracts where the panel's as-of incumbent record is the same frozen file used here: max |panel probability - recomputed| = {dmax:.2e}"))
    checks.append(dict(name="panel_quote_strictly_before_tip", passed=bool((rows.loc[isk, 'lead_min'] > 0).all()),
                       detail=f"all {int(isk.sum())} used quotes captured before this module's tip; {pmeta['pretip_rows_at_or_after_tip']} panel rows labelled PRETIP but captured at/after the tip used here were discarded"))

    # ---------------- results
    rows_all = rows[rows["universe"] == "all_games"]; ia = (rows["universe"] == "all_games").to_numpy()
    rows_k = rows[isk]
    results = []
    results += compare(rows_all, P["challenger"][ia], P["naive"][ia], "naive:independent-halves", "all_games", {"naive:independent-halves"})
    results += compare(rows_all, P["challenger"][ia], p_inc[ia], "incumbent:pure-0.2.0", "all_games", {"incumbent:pure-0.2.0"})
    results += compare(rows_all, P["challenger"][ia], p_shadow[ia], "incumbent-shadow:score_distribution(reconstructed)", "all_games", {"incumbent-shadow:score_distribution(reconstructed)"})
    results += compare(rows_all, P["challenger"][ia], p_otbase[ia], "naive:walk-forward-ot-base-rate", "all_games", set())
    results += compare(rows_k, P["challenger"][isk], p_mkt[isk], "market:kalshi_mid", "kalshi_listed", {"market:kalshi_mid"})
    results += compare(rows_k, P["challenger"][isk], np.where(np.isfinite(p_mkt[isk]), P["naive"][isk], np.nan), "naive:independent-halves", "kalshi_listed", set())
    results += compare(rows_k, P["challenger"][isk], np.where(np.isfinite(p_mkt[isk]), p_inc[isk], np.nan), "incumbent:pure-0.2.0", "kalshi_listed", set())
    results = finalize_verdicts(results)

    # ---------------- ablations (ablation - challenger; positive = the challenger's component helps)
    ablations = []
    desc = {"no_cross_team_corr": "home-away residual covariances set to 0 (correlation off)",
            "share_050": "walk-forward first-half share replaced by a fixed 0.5",
            "level_share": "share = first-half points per PROJECTED point (absorbs the incumbent's scoring-level bias into the first half; breaks the pure split)",
            "kappa_1": "walk-forward tie / overtime continuity factors replaced by 1.0",
            "prior_only": "no walk-forward learning at all: documented prior for every slate"}
    for v in ("no_cross_team_corr", "share_050", "level_share", "kappa_1", "prior_only"):
        for fam in FAMILY_ORDER:
            m = ia & (rows["family"].to_numpy() == fam)
            if not m.any() or np.allclose(P[v][m], P["challenger"][m]):
                continue
            y = rows.loc[m, "y"].to_numpy(float)
            bs = C.paired_cluster_bootstrap(C.brier_rows(P[v][m], y) - C.brier_rows(P["challenger"][m], y), rows.loc[m, "game_id"].to_numpy(), n_boot=N_BOOT, seed=7)
            ablations.append(dict(ablation=v, description=desc[v], market_family=fam, universe="all_games", metric="brier", n_rows=bs["n_rows"], n_clusters=bs["n_clusters"],
                                  ablation_value=float(C.brier_rows(P[v][m], y).mean()), challenger=float(C.brier_rows(P["challenger"][m], y).mean()),
                                  diff_ablation_minus_challenger=bs["mean"], ci95=[bs["lo"], bs["hi"]], p_raw=bs["p_two_sided"]))

    # ---------------- calibration
    calib = []
    for uni, mask in (("all_games", ia), ("kalshi_listed", isk & np.isfinite(p_mkt))):
        for fam in FAMILY_ORDER:
            m = mask & (rows["family"].to_numpy() == fam)
            if m.sum() < 30:
                continue
            y = rows.loc[m, "y"].to_numpy(float); ent = dict(universe=uni, market_family=fam, n_rows=int(m.sum()), n_games=int(rows.loc[m, "game_id"].nunique()), base_rate=float(y.mean()))
            for name, p in (("challenger", P["challenger"]), ("naive", P["naive"]), ("incumbent", p_inc), ("incumbent_shadow", p_shadow), ("market_mid", p_mkt)):
                pm = p[m]
                if np.isfinite(pm).all() and 0 < y.mean() < 1:
                    a, b = C.calibration_slope(pm, y); ent[name] = dict(intercept=a, slope=b, mean_p=float(pm.mean()), brier=float(C.brier_rows(pm, y).mean()))
            calib.append(ent)
    pit = {"challenger": pit_block(games, arrs["challenger"]), "naive": pit_block(games, arrs["naive"])}

    # ---------------- correlations (descriptive, full sample, residuals around the incumbent means; NOT used for forecasting)
    lastp = params[sorted(params)[-1]]; r4 = _resid4(games, lastp["share_h"], lastp["share_a"])
    eH, eA = r4[:, 0] + r4[:, 2], r4[:, 1] + r4[:, 3]
    corr = dict(
        note="Full-sample descriptive correlations of residuals around the frozen incumbent means (game bootstrap, 2000 draws). Forecasts use only the walk-forward estimates in predictions_summary.json.",
        home_away_final_error=_corr_ci(eH, eA), total_error_vs_margin_error=_corr_ci(eH + eA, eH - eA),
        home_away_first_half_residual=_corr_ci(r4[:, 0], r4[:, 1]),
        first_half_vs_rest_same_team_home=_corr_ci(r4[:, 0], r4[:, 2]),
        first_half_vs_rest_same_team_away=_corr_ci(r4[:, 1], r4[:, 3]),
        first_half_total_vs_rest_total=_corr_ci(r4[:, 0] + r4[:, 1], r4[:, 2] + r4[:, 3]),
        first_half_margin_vs_rest_margin=_corr_ci(r4[:, 0] - r4[:, 1], r4[:, 2] - r4[:, 3]),
        incumbent_assumption_total_margin_uncorrelated="see total_error_vs_margin_error: the incumbent's score_distribution assumes 0",
        observed=dict(first_half_share_home=float(games["h1"].sum() / games["fh"].sum()), first_half_share_away=float(games["a1"].sum() / games["fa"].sum()),
                      sd_home_error=float(np.sqrt(np.mean(eH ** 2))), sd_away_error=float(np.sqrt(np.mean(eA ** 2))), mean_total_error=float((eH + eA).mean()), mean_margin_error=float((eH - eA).mean()),
                      overtime_rate=float((games["ot"] > 0).mean()), first_half_tie_rate=float((games["h1"] == games["a1"]).mean())))

    # ---------------- Kalshi family inventory
    inv = []
    series_all = sorted({t.split("-")[0] for t in mapped} | {t.split("-")[0] for t in unmapped if t.split("-")[0] in {x.split("-")[0] for x in mapped}})
    game_series = {t.split("-")[0] for t in mapped}
    for s in series_all:
        ps_ = panel[panel["series"] == s]; ku = kal[kal["series"] == s]
        fam = sorted({f for f in ps_["family"].dropna()})
        inv.append(dict(series=s, family=fam[0] if fam else None, modelled=bool(fam),
                        contracts_mapped_to_a_game=int(sum(1 for t in mapped if t.split("-")[0] == s)),
                        contracts_unmapped=int(sum(1 for t in unmapped if t.split("-")[0] == s)),
                        contracts_with_pretip_observation=int(len(ps_)), games_with_pretip_observation=int(ps_["game_id"].nunique()),
                        contracts_in_used_games=int(len(ku)), games_used=int(ku["game_id"].nunique()),
                        two_sided_at_last_pretip=int(ku["two_sided"].sum()), two_sided_spread_le_10c=int(ku["tight"].sum()),
                        games_with_usable_mid=int(ku.loc[ku["tight"], "game_id"].nunique()),
                        median_quote_lead_minutes=float(ku.loc[ku["tight"], "lead_min"].median()) if ku["tight"].any() else None,
                        median_bid_ask_spread=float((ku.loc[ku["two_sided"], "ask"] - ku.loc[ku["two_sided"], "bid"]).median()) if ku["two_sided"].any() else None))
    lead = rows.loc[isk & np.isfinite(p_mkt), "lead_min"]
    market_lead = {f"q{int(k * 100):03d}": float(v) for k, v in lead.quantile([0, 0.1, 0.5, 0.9, 1.0]).items()} if len(lead) else {}

    # ---------------- documents
    sp = {d: dict(n_train=p["n_train"], n_not_yet_archived=p["n_not_yet_archived"], train_max_slate=p["train_max_slate"], n_games_forecast=int((games["slate"] == d).sum()),
                  share_home=p["share_h"], share_away=p["share_a"], kappa_1h_tie=p["kappa_1h"], kappa_overtime=p["kappa_ot"], ot_base_rate=p["ot_rate"],
                  sigma_naive_team=p["sigma_naive"], **_cov_summary(p["cov"])) for d, p in params.items()}
    fam_sum = []
    for uni, mask in (("all_games", ia), ("kalshi_listed", isk)):
        for fam in FAMILY_ORDER:
            m = mask & (rows["family"].to_numpy() == fam)
            if m.any():
                fam_sum.append(dict(universe=uni, market_family=fam, n_rows=int(m.sum()), n_games=int(rows.loc[m, "game_id"].nunique()), yes_rate=float(rows.loc[m, "y"].mean()),
                                    mean_p_challenger=float(P["challenger"][m].mean()), mean_p_naive=float(P["naive"][m].mean()),
                                    min_p_challenger=float(P["challenger"][m].min()), max_p_challenger=float(P["challenger"][m].max()),
                                    rows_with_market_mid=int(np.isfinite(p_mkt[m]).sum())))
    # coherence audit on the real forecasts
    w = rows[ia & (rows["family"] == "first_half_winner").to_numpy()]
    s3 = pd.Series(P["challenger"][w.index]).groupby(w["gi"].to_numpy()).sum()
    hm = rows[ia & (rows["mtype"] == "WINNER").to_numpy() & (rows["period"] == "FULL").to_numpy()]
    mw = np.array([1, -1, 1, -1.0]); mm = arrs["challenger"]["mean"] @ mw; ms = np.sqrt(np.einsum("j,ijk,k->i", mw, arrs["challenger"]["cov"], mw))
    coh = dict(first_half_winner_three_way_sum_max_abs_dev=float(np.abs(s3 - 1).max()),
               moneyline_vs_normal_margin_marginal_max_abs_dev=float(np.abs(P["challenger"][hm.index] - phi(mm / ms)[hm["gi"].to_numpy()]).max()),
               team_means_sum_to_total_max_abs_dev=float(np.abs(arrs["challenger"]["mean"].sum(1) - games["total"].to_numpy()).max()),
               halves_sum_to_team_mean_max_abs_dev=float(np.abs(arrs["challenger"]["mean"][:, 0] + arrs["challenger"]["mean"][:, 2] - games["mu_h"].to_numpy()).max()),
               all_probabilities_in_unit_interval=bool(((P["challenger"] >= 0) & (P["challenger"] <= 1)).all()))
    checks.append(dict(name="joint_distribution_coherence_on_real_forecasts", passed=bool(coh["first_half_winner_three_way_sum_max_abs_dev"] < 1e-9 and coh["team_means_sum_to_total_max_abs_dev"] < 1e-6 and coh["all_probabilities_in_unit_interval"]),
                       detail=json.dumps(C._clean(coh), sort_keys=True)))

    shas = git_shas(repo); a = audit["games"]; dr = audit["data_rows"]
    hl = [r for r in results if r["headline"]]
    n_val = sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in hl); n_imp = sum(r["verdict"] == "IMPROVED_NOT_VALIDATED" for r in hl); n_bad = sum(r["verdict"] == "NOT_IMPROVED" for r in hl)
    vs_naive = [r for r in hl if r["reference"] == "naive:independent-halves"]
    cov_fams = sorted({r["market_family"] for r in vs_naive if r["verdict"] in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED")})
    bad = [f"{r['market_family']} vs {r['reference']}" for r in hl if r["verdict"] == "NOT_IMPROVED"]
    good = [f"{r['market_family']} vs {r['reference']} ({r['verdict']})" for r in hl if r["verdict"] in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED")]
    overall = "INCONCLUSIVE"
    reason = (f"{len(hl)} headline pooled Brier comparisons (Holm-adjusted): {n_val} VALIDATED_IMPROVEMENT, {n_imp} IMPROVED_NOT_VALIDATED, {n_bad} NOT_IMPROVED, "
              f"{len(hl) - n_val - n_imp - n_bad} INCONCLUSIVE. Favourable: {good or 'none'}. Unfavourable: {bad or 'none'}. "
              "The incumbent publishes no probability for first-half, team-total or overtime contracts, so the challenger's contribution there is COVERAGE with measured calibration, "
              "not an accuracy gain over the incumbent; any gain is over a naive construction, on about two weeks of November games, and the overall verdict stays INCONCLUSIVE "
              "unless every market-facing comparison is also favourable. The incumbent's full-game probabilities are retained.")
    if n_val and not n_bad and all(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in hl):
        overall = "VALIDATED_IMPROVEMENT"
    claims_stage = "EVALUATED"
    fam_text = lambda f: next((f"{r['market_family']}: Brier {r['challenger']:.4f} vs naive {r['reference_value']:.4f}, diff {r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}], {r['verdict']}" for r in vs_naive if r["market_family"] == f), f"{f}: not scored")
    doc = dict(
        schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="CBB", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID,
        source_commits=shas,
        data=[
            dict(dataset_id="cbb.projections_archive.pure-0.2.0", repo=REPO, path="origin/projections-archive:projections/<season>/<date>/<game_id>/<as_of>.json", rows=dr["proj_files"],
                 rows_unit="frozen incumbent forecast files (one per game x run)", games=a["incumbent_projection_games"], first=dr["proj_first"], last=dr["proj_last"], sha256=None,
                 kind="PROSPECTIVE_CAPTURE", rights_tier="UNRESOLVED_INTERNAL_ONLY",
                 verified="README states append-only, written before tip-off. Verified here for every USED file: prospective.as_of < scheduled tip, as_of <= generated_at < tip, file-name stamp == as_of, sha256 equals the archive's own run manifest. NOT verified: git commit times (the branch was fetched at depth 1, so history is not available)."),
            dict(dataset_id="cbb.period_scores_archive", repo=REPO, path="origin/period-scores-archive:periods/YYYY/MM/DD/<stamp>.jsonl", rows=dr["ps_rows"], rows_unit="verified final games with per-period scores",
                 first=dr["ps_first"], last=dr["ps_last"], sha256=None, kind="PROSPECTIVE_CAPTURE", rights_tier="UNRESOLVED_INTERNAL_ONLY",
                 verified="README: append-only JSONL written by a scheduled workflow. Verified: every row STATUS_FINAL, verified=true, no flags, observed_at after the game's tip; observed_at is what gates the walk-forward training set. Finals cross-checked against schedule-archive ESPN final rows."),
            dict(dataset_id="cbb.schedule_archive.espn_rows", repo=REPO, path="origin/schedule-archive:rows/YYYY/MM/DD/<stamp>_espn_schedule.jsonl", rows=dr["sched_rows"], rows_unit="ESPN scoreboard observations (pre-game, live, final)",
                 first=dr["sched_first"], last=dr["sched_last"], sha256=None, kind="PROSPECTIVE_CAPTURE", rights_tier="UNRESOLVED_INTERNAL_ONLY",
                 verified="README: append-only schedule-time observations. Used for the scheduled tip (last pre-game observation with a valid time) and as an independent final-score cross-check."),
            dict(dataset_id="cbb.kalshi_panel_archive", repo=REPO, path="origin/kalshi-panel-archive:panels/YYYY/MM/DD/kalshi_cbb_<UTC>.panel.jsonl.gz", rows=pmeta["panel_files"], rows_unit="panel partitions (one per capture; each row = one Kalshi contract joined to as-of model records)",
                 contracts_with_pretip_observation=int(len(panel)), first=pmeta["first"], last=pmeta["last"], sha256=None, kind="PROSPECTIVE_CAPTURE", rights_tier="UNRESOLVED_INTERNAL_ONLY",
                 verified="README/docs: immutable joins of each public Kalshi snapshot (captured_at = capture time) to frozen projections as of that capture. Verified: every quote used is captured before the tip used here; the panel's incumbent probability is reproduced exactly from the frozen file; Kalshi's own settled result agrees with settlement from verified half scores. The panel carries parsed contract_semantics, not the raw rules text."),
            dict(dataset_id="cbb.team_id_crosswalk", repo=REPO, path="main:cbb_edge/data/ids/teams.csv", rows=int(len(pd.read_csv(teams_csv))), rows_unit="canonical team ids", first=None, last=None,
                 sha256=C.sha256_file(teams_csv), kind="HISTORICAL_BACKFILL", rights_tier="UNRESOLVED_INTERNAL_ONLY", verified="Static id table at main 2d932f9; used only to verify home/away orientation between projections and ESPN half scores."),
        ],
        features=[
            dict(feature_id="cbb.joint_half_score_distribution", catalog_inputs=["CBB:cbb.half_split", "CBB:cbb.score_resid"],
                 description="4-variate normal over (home 1H, away 1H, home rest-of-game, away rest-of-game) points. Means = walk-forward first-half share x the incumbent's frozen team means; 4x4 residual second-moment matrix, shares and two continuity factors (first-half tie, regulation tie -> overtime) estimated on previously archived games with pseudo-count shrinkage to a documented prior.",
                 pit_rule="Game inputs: latest pure-0.2.0 projection with prospective.as_of strictly before the scheduled tip. Parameters for slate day D (date of tip - 10h UTC): only games on slates < D whose verified period score had observed_at before the first tip of slate D.",
                 checks=checks),
            dict(feature_id="cbb.kalshi_last_pretip_mid", catalog_inputs=["CBB:m.quote_history", "CBB:m.settlement_truth", "CBB:m.rules_text", "CBB:m.ladder_structure"],
                 description="Per Kalshi contract: mid of yes bid/ask at the latest panel snapshot captured before tip, only when 0 < bid < ask < 1 and ask - bid <= 0.10. Reference only (never an input to the challenger). Contract meaning from the panel's parsed contract_semantics; settlement from verified half scores.",
                 pit_rule="captured_at strictly before the scheduled tip; no fallback to an earlier snapshot when the last pre-tip quote is one-sided or wide.",
                 checks=[c for c in checks if c["name"] in ("own_settlement_matches_kalshi_settled_result", "panel_quote_strictly_before_tip", "kalshi_strikes_are_half_integer_greater_than", "incumbent_probability_reproduces_panel", "kalshi_subject_side_resolved_by_team_id")]),
        ],
        design=dict(
            question="Can the incumbent's frozen full-game projection be extended, without touching its means, into one coherent joint distribution that gives calibrated probabilities for first-half, team-total and overtime contracts?",
            model="X=(h1,a1,h2,a2) ~ N(mean, Sigma4). mean=(s_h*mu_home, s_a*mu_away, (1-s_h)*mu_home, (1-s_a)*mu_away) with mu from the frozen incumbent; Sigma4 = walk-forward uncentred second moments of the four residuals. Totals/team totals: normal tail at the half-integer strike. Margins: the zero cell is re-weighted by kappa (first half: walk-forward tie factor; full game: 0, a final cannot be tied) and other cells rescaled; overtime probability = kappa_ot x normal mass of the full-game margin in (-0.5, 0.5). Second-half contracts (Kalshi: overtime included) are the remainder final - first half.",
            priors=dict(values=PRIOR, source="sd_team 10.38 and rho_home_away 0.32: WAVE13_GAME_NUMBER.md section 4 (the values IMPLIED by the incumbent's frozen margin_sd / total_sd; they depend on no game result, so quoting a report written inside the evaluation window leaks nothing). share_1h 0.47, rho_1h_2h 0, kappa 1.0 and ot_base_rate 0.05 are this slice's structural ASSUMPTIONS (no number in the owner's reports); pseudo-count 30 games (kappa: 3 expected ties)."),
            point_in_time="Latest incumbent projection with as_of < scheduled tip; scheduled tip = min(last pre-game ESPN schedule observation, the projection's own listed start). Walk-forward by slate day; a training game must also have had its period score archived before the first tip of the slate (the first three slates therefore run on the prior alone).",
            universes=dict(all_games="Every used game, outcome-scored on a fixed synthetic ladder: strikes = floor(center)+0.5 + offsets, center from the frozen incumbent mean (first half: 0.47 x mean), offsets (-6,-3,0,3,6) for spreads / team totals / first-half lines and (-8,-4,0,4,8) for the game total; first-half winner = home / away / tie rows; one moneyline row and one overtime row per game.",
                           kalshi_listed="Contracts Kalshi actually listed, at their listed strikes, restricted to rows with a usable mid at the latest pre-tip snapshot."),
            references=["naive:independent-halves (uncorrelated team scores, fixed 0.5 share, walk-forward team SD / sqrt(2) per half, no tie calibration)",
                        "incumbent:pure-0.2.0 (frozen home_win_prob; Phi((margin-line)/margin_sd); Phi((total-line)/total_sd); full-game families only: it publishes nothing else)",
                        "incumbent-shadow:score_distribution(reconstructed) (team totals from the frozen SDs under the incumbent's documented uncorrelated total/margin assumption; reconstructed here, the archive stores no such probability)",
                        "naive:walk-forward-ot-base-rate (constant overtime rate, non-headline)",
                        "market:kalshi_mid (latest pre-tip snapshot, two-sided, spread <= 0.10)"],
            statistics=f"Per-row paired loss difference (challenger - reference; negative = challenger better), cluster bootstrap by game_id ({N_BOOT} draws, seed 7). Cohorts: slates before {cut} vs from {cut} (two chronological halves of the date range). 'replicated' = same non-zero sign in pooled and both cohorts. Holm across the headline rows (pooled Brier vs naive, incumbent, incumbent-shadow and market); all other rows carry p_holm = 1.0. Verdict = contract.verdict_from.",
            cohort_cut=cut, n_boot=N_BOOT, tight_spread=TIGHT_SPREAD, slate_shift_hours=SLATE_SHIFT_H,
            not_in_scope="Margin SD calibration (wave-15) and roster centring (wave-16) of the full-game model are other workstreams; the incumbent's mean margin and total are taken as given, including its known early-season total bias."),
        games=audit["games"], projection_lead_hours=audit["projection_lead_hours"], tip_source=audit["tip_source"],
        kalshi_family_inventory=dict(note="Per-game Kalshi series seen in the panel archive. Contracts = distinct tickers. 'used games' = games with a pre-tip incumbent projection and verified half scores.",
                                     series=inv, market_quote_lead_minutes=market_lead,
                                     not_modelled=["KXNCAAMBRACE (race to N points: needs a scoring-sequence model)", "KXNCAAMBWINMARGIN (winning-margin bands: the panel has no validated payoff parser)"],
                                     tie_handling="The panel has no rules text field. Tie handling is taken from contract_semantics.yes_condition: KXNCAAMB1H lists three contracts per game (home_wins_1H, away_wins_1H, tied_1H), so a tied half settles both team contracts NO; this is confirmed against Kalshi's settled results (see check own_settlement_matches_kalshi_settled_result)."),
        results=results, ablations=ablations, calibration=dict(slopes=calib, pit=pit), correlations=corr, coherence=coh,
        input_stage_claims=[
            dict(input="CBB:cbb.half_split", stage=claims_stage, outcome="OK", evidence="Walk-forward first-half share built from verified period scores and scored out of sample. " + "; ".join(fam_text(f) for f in ("first_half_total", "first_half_spread", "first_half_winner")) + ". No validated improvement is claimed."),
            dict(input="CBB:cbb.score_resid", stage=claims_stage, outcome="OK", evidence="Walk-forward 4x4 residual covariance (team-score SD, home-away and half correlations) built and scored. " + "; ".join(fam_text(f) for f in ("team_total", "overtime")) + f". Total-vs-margin error correlation {corr['total_error_vs_margin_error']['estimate']:+.3f} [{corr['total_error_vs_margin_error']['ci95'][0]:+.3f}, {corr['total_error_vs_margin_error']['ci95'][1]:+.3f}]."),
            dict(input="CBB:m.quote_history", stage="EVALUATED", outcome="PARTIAL", evidence="Only the latest pre-tip panel snapshot mid is used, as a reference; no quote path, depth or fills. Coverage per family is in kalshi_family_inventory."),
            dict(input="CBB:m.settlement_truth", stage="VERIFIED", outcome="OK" if agree.all() else "PARTIAL", evidence=next(c["detail"] for c in checks if c["name"] == "own_settlement_matches_kalshi_settled_result")),
            dict(input="CBB:m.rules_text", stage="SOURCE_LOCATED", outcome="PARTIAL", evidence="The panel exposes parsed contract_semantics (period, overtime treatment, tie contract) but not the versioned rules_primary text; the raw text lives on the kalshi-archive branch, which this slice did not read."),
        ],
        verdict=dict(overall=overall, reason=reason, retain_incumbent=True),
        limitations=[
            f"{a['used']} games on {len(params)} slate days ({sorted(params)[0]} to {sorted(params)[-1]}): about two weeks of early-season play. Every interval here is wide and no result should be read as settled.",
            "November-only, mostly non-conference schedule with many mismatches; first-half share, half correlations and tie rates may differ in conference play and in March.",
            "The first three slates are forecast from the documented prior alone because no verified period score had been archived before those tips; several prior values (first-half share 0.47, independent halves, continuity factors 1.0) are this slice's assumptions, not owner-published numbers, and they were chosen by the author after the season had started.",
            "The incumbent publishes no probability for first-half, team-total or overtime contracts, so against the incumbent the challenger adds coverage, not accuracy. Accuracy claims are only relative to a naive construction and to the Kalshi mid.",
            "The Kalshi reference is a snapshot mid (two-sided, spread at most 10 cents) from the last capture before tip, typically minutes before tip, while the challenger uses a projection frozen hours earlier. A mid is not an executable fill; no fees, depth or slippage are modelled and nothing here is a betting result.",
            "Kalshi lists first-half spread / total, team-total and overtime contracts for only a small subset of games, so those market comparisons rest on a few dozen games or fewer.",
            "The incumbent's mean total and margin are taken as given, including its documented early-season scoring-level bias; that bias flows into first-half and team-total probabilities.",
            "Scores are modelled with a normal approximation plus a re-weighted zero-margin cell; other key-number effects and skew in blowouts are not modelled. Second-half contracts are priced only as the remainder (final minus first half).",
            "The synthetic all-games ladder is not a set of traded lines; rows inside a game are strongly dependent (handled by the game-cluster bootstrap) and the effective sample is the number of games.",
            "Race-to-N and winning-margin-band contracts are not modelled. The raw Kalshi rules text was not read; contract meaning comes from the panel's parsed semantics.",
            "Archive git history was not audited (depth-1 fetch); the prospective claim rests on in-file freeze timestamps and manifest hashes.",
        ],
    )
    errs = C.validate_evaluation(doc)
    if errs:
        raise SystemExit("evaluation contract violations: " + "; ".join(errs))
    summary = dict(schema="sift-foundation-predictions-summary/1", status="RESEARCH_ONLY", sport="CBB", challenger_id=CHALLENGER_ID,
                   note="Aggregates only: no per-game or per-contract rows.", games_used=a["used"], cohort_cut=cut,
                   games_per_cohort={c: int((games["cohort"] == c).sum()) for c in ("cohort_1", "cohort_2")},
                   walk_forward_parameters_by_slate=sp, prior=dict(PRIOR, **_cov_summary(prior_cov())),
                   families=fam_sum, pit=pit, coherence=coh, projection_lead_hours=audit["projection_lead_hours"], market_quote_lead_minutes=market_lead)
    C.write_json(out_dir / "evaluation.json", doc)
    C.write_json(out_dir / "predictions_summary.json", summary)
    return doc, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arch", default=os.environ.get("SIFT_CBB_ARCH_DIR"), help="root holding the extracted archive branches (one directory per branch)")
    ap.add_argument("--repo", default=str(C.repos_dir() / "cbb-edge-finder"), help="clone of the owner's repo (read-only: team id table and branch shas)")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args(argv)
    if not a.arch:
        ap.error("--arch or SIFT_CBB_ARCH_DIR is required")
    repo = Path(a.repo)
    doc, _ = run(Path(a.arch), repo / "cbb_edge" / "data" / "ids" / "teams.csv", repo, Path(a.out), a.workers)
    print(f"games used {doc['games']['used']}; overall {doc['verdict']['overall']}")
    for r in doc["results"]:
        if r["headline"]:
            print(f"  {r['universe']:13s} {r['market_family']:20s} vs {r['reference'][:34]:34s} n={r['n_rows']:5d}/{r['n_clusters']:3d} ch={r['challenger']:.4f} ref={r['reference_value']:.4f} "
                  f"diff={r['diff']:+.4f} [{r['ci95'][0]:+.4f},{r['ci95'][1]:+.4f}] p_holm={r['p_holm']:.3f} rep={r['replicated']} {r['verdict']}")


if __name__ == "__main__":
    main()

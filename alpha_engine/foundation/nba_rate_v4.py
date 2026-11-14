"""Operation Data Foundation, NBA: challenger ``alpha-nba-rate-0.4`` (minutes-coherent rates + Phase 15 archive inputs).

RESEARCH_ONLY. Builds on ``alpha-nba-rate-0.3`` (``nba_rate``), which is re-run unchanged in-process and kept as a reference.

Mechanism behind the 0.3 finding "pf over-forecasts the per-minute rate when its minutes forecast is 4+ below the recent
average" (diagnosed here, see ``design.mechanism``):

* The production stat mean is a stack ``F = wA*A + wD*D + wE*E`` (``research/projection_foundation/nba/stats.py``, frozen
  weights in ``results/frozen_params.json``). ``D`` = minutes forecast x per-minute rate scales one-for-one with the minutes
  forecast; ``E`` (LightGBM, weight 0.33-0.52) sees the minutes forecast only as one tree feature next to per-game EWMA
  means, so it barely moves when the live minutes forecast departs from recent minutes (trees do not extrapolate and the
  training rows rarely had such departures). Measured on the frozen forecasts alone (no outcomes), the per-minute rate
  implied by ``pf`` has a slope of about -0.3 (assists -0.5) on log(forecast minutes / recent minutes): ``pf``'s stat
  forecast moves only ~0.7x as much as its own minutes forecast.
* Actual per-minute rates do not rise when minutes fall (slope 0 to +0.15 on the same regressor), so the incoherence is
  an over-forecast whenever ``pf`` cuts minutes and an under-forecast whenever it raises them.

What 0.4 does (each component switched on only if it lowers TRAIN-window CRPS / abs error; TRAIN = games before 2026-11-01):

M  minutes-coherence: ``pf_mean * (fm / mpg) ** (-s_pf)``, where ``s_pf`` is the slope above re-estimated walk-forward
   from FORECASTS ONLY on strictly earlier dates (no outcome enters it).
K  residual minutes elasticity: an extra ``(fm / mpg) ** b`` with ``b`` fitted on TRAIN outcomes (Poisson, offset). It nets the
   true per-minute coupling against the regression of ACTUAL minutes toward recent minutes when pf's minutes forecast
   departs from them, so a negative ``b`` is expected even though per-minute rates do not fall with minutes.
I  independent rate: 0.3's rate or the Phase 15 builder ``nba.stat_rate_posterior`` (per-36 posterior, season to date
   shrunk 400 minutes to the previous season), times the frozen minutes forecast and the 0.3 opponent factor; blend weight
   on a 0..1 grid (0.3's grid stopped at 0.5 and its weight sat on the edge).
L  0.3's online level ratio, re-decided on TRAIN.
T  team points: frozen pf team mean, normalised challenger player sum, and the Phase 15 builder
   ``nba.own_model_team_totals`` (pace x efficiency from the owner's box archive); weights on a simplex grid, TRAIN abs error.

Player pmfs are pf's own pmfs exponentially tilted to the new mean (PRA tilts pf's PRA pmf by the sum of the three
component shifts, so pf's within-player correlation structure is kept). Team pmfs are shifted (shape unchanged); spread
and total probabilities use pf's own normal approximation with its archived rho, so the cross-team correlation is pf's.

``python -m alpha_engine.foundation.nba_rate_v4`` writes ``research/data_foundation_ops/NBA/alpha-nba-rate-0.4/``.
Raw rows never leave the process.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import contract as C
from . import nba_availability as V1
from . import nba_frozen as F
from . import nba_rate as R
from ..features import nba_ext3 as E3
from ..features import nba_player_ext3 as P3

CHALLENGER_ID = "alpha-nba-rate-0.4"
INCUMBENT_ID = F.INCUMBENT_ID
REF03 = "challenger:alpha-nba-rate-0.3"
ARM = "C4_" + CHALLENGER_ID
OUT_DIR = C.OPS / "NBA" / CHALLENGER_ID
STATS = F.STATS
COH1, COH2, POOLED, ALLG = F.COH1, F.COH2, F.POOLED, F.ALLG
W_GRID = [round(0.1 * i, 1) for i in range(11)]
SRP = {"points": "srp_pts36_pre", "rebounds": "srp_reb36_pre", "assists": "srp_ast36_pre", "threes": "srp_fg3m36_pre"}
MIN_SLOPE_ROWS = 300
GAP_BINS = [-99, -4, -1, 1, 4, 8, 99]


def _chk(name, passed, detail):
    return C.check(name, passed, detail)


# =============================================================================================== pure helpers (tested)
def walkforward_slope(dates, x, z, ok, min_rows: int = MIN_SLOPE_ROWS) -> np.ndarray:
    """OLS slope of z on x per row, fitted on rows with ``ok`` and a date STRICTLY earlier than the row's own date.
    Rows whose earlier sample is smaller than ``min_rows`` get slope 0 (no correction)."""
    dates = np.asarray(dates); x = np.asarray(x, float); z = np.asarray(z, float); ok = np.asarray(ok, bool) & np.isfinite(x) & np.isfinite(z)
    out = np.zeros(len(dates)); ud = np.unique(dates)
    for d in ud:
        m = ok & (dates < d)
        if m.sum() >= min_rows and np.var(x[m]) > 0:
            out[dates == d] = np.cov(x[m], z[m], bias=True)[0, 1] / np.var(x[m])
    return out


def poisson_offset_slope(y, offset, x, iters: int = 40) -> float:
    """MLE of b in log E[y] = offset + b*x (no intercept)."""
    y = np.asarray(y, float); off = np.asarray(offset, float); x = np.asarray(x, float); b = 0.0
    for _ in range(iters):
        mu = np.exp(off + b * x); g = float(np.sum((y - mu) * x)); h = float(np.sum(mu * x * x))
        if h <= 0:
            break
        step = g / h; b += step
        if abs(step) < 1e-10:
            break
    return float(b)


def simplex_grid(step: float = 0.1):
    n = int(round(1 / step))
    return [(round(i * step, 2), round(j * step, 2)) for i in range(n + 1) for j in range(n + 1 - i)]


# =============================================================================================== Phase 15 features
def phase15_features(pg: pd.DataFrame, tg: pd.DataFrame, upto=None) -> tuple:
    """Run the Phase 15 builders on the same in-memory box archive 0.3 reads. ``upto`` truncates to dates < upto
    (used by the leak check). Returns (player table keyed entity_id/game_id, team table keyed tricode/game_id)."""
    pgx = pg[P3.PG_COLS].copy(); tgx = tg[E3.TG_COLS].copy(); pge = pg[E3.PG_COLS].copy()
    if upto is not None:
        pgx = pgx[pgx.game_date_et < upto]; tgx = tgx[tgx.game_date_et < upto]; pge = pge[pge.game_date_et < upto]
    pl = P3.compute({"player_games": pgx})["team"]
    pl = pl.assign(entity_id="espn:" + (-pl.team.astype("int64")).astype(str))[["game_id", "entity_id"] + list(SRP.values())]
    tm = E3.compute({"team_games": tgx, "player_games": pge})["team"]
    tm = tm.assign(tricode=tm.team.map(V1.TEAM_TRICODES))[["game_id", "tricode", "ot_exp_pts_pre"]]
    return pl, tm


# =============================================================================================== run
def run(repo: Path | None = None, verbose: bool = True) -> dict:
    say = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    S = R.run(repo, verbose=verbose)                      # 0.3 exactly as committed (reproduction checked by its tests)
    X, fs, base, masks, train, hist = S["X"], S["fs"], S["base"], S["masks"], S["train"], S["hist"]
    N = len(X); date_s = X.date_s.to_numpy(); gid = X.game_id.to_numpy()
    chk = dict(mech=[], feat=[], level=[], coh=[])
    say("phase 15 features")
    pl, tm = phase15_features(S["pg"], S["tg"])
    Xi = X[["game_id", "entity_id"]].reset_index().merge(pl, on=["game_id", "entity_id"], how="left").set_index("index").loc[X.index]
    srp = {s: Xi[SRP[s]].to_numpy(float) / 36.0 for s in STATS}
    cov = float(np.isfinite(srp["points"][base]).mean())
    chk["feat"].append(_chk("phase15_stat_rate_posterior_joins_played_rows", cov > 0.95,
                            f"{int(np.isfinite(srp['points'][base]).sum())} of {int(base.sum())} played frame rows carry srp_pts36_pre (share {cov:.4f})"))
    # leak check: recompute with the archive truncated before a TEST date; rows of that date must be identical
    d0 = sorted(set(date_s[masks[POOLED]]))[len(set(date_s[masks[POOLED]])) // 2]
    pl_t, tm_t = pl, tm
    pl_c, tm_c = phase15_features(S["pg"][S["pg"].game_date_et <= d0], S["tg"][S["tg"].game_date_et <= d0])
    a = pl_t.merge(pl_c, on=["game_id", "entity_id"], suffixes=("", "_c"))
    a = a[a.game_id.isin(set(gid[date_s == d0]))]
    dmax = max(float(np.nanmax(np.abs(a[c] - a[c + "_c"]))) for c in SRP.values()) if len(a) else np.inf
    b_ = tm_t.merge(tm_c, on=["game_id", "tricode"], suffixes=("", "_c")); b_ = b_[b_.game_id.isin(set(gid[date_s == d0]))]
    tmax = float(np.nanmax(np.abs(b_.ot_exp_pts_pre - b_.ot_exp_pts_pre_c))) if len(b_) else np.inf
    chk["feat"].append(_chk("leak_guard_phase15_values_unchanged_when_later_games_removed", dmax < 1e-9 and tmax < 1e-9 and len(a) > 50 and len(b_) > 10,
                            f"features of the {d0} slate recomputed from an archive cut after {d0}: {len(a)} player rows max |diff| {dmax:.2e}; {len(b_)} team rows max |diff| {tmax:.2e}"))

    # ------------------------------------------------------------------ mechanism: pf's minutes elasticity, forecast-only
    fm = X.pf_mean_minutes.to_numpy(float); mpg = fs["mpg"]; npg = fs["n_prior_games"]
    has = X.has_pf.to_numpy() & np.isfinite(fm) & (npg >= 10) & (mpg > 0)
    xg = np.where(has, np.log(np.maximum(fm, 1.0) / np.maximum(mpg, 1.0)), 0.0)
    pf_pmf = {s: F._stack(X[f"pf_pmf_{s}"], F.KMAX[s]) for s in STATS + ["pra"]}
    kk = {s: np.arange(F.KMAX[s] + 1, dtype=float) for s in STATS + ["pra"]}
    of = {}
    opp_id = np.array([V1.TRICODE_TO_TEAM.get(o, -1) if o else -1 for o in S["opp"]])
    ok_h = lambda s, name: S["hv"].get((F.FAMILY[s], f"H_{name}")) == "VALIDATED_IMPROVEMENT"
    for s in STATS:
        of[s] = R.opponent_lookup(hist["opp_tabs"][s], opp_id, pd.to_datetime(date_s)) ** hist["params"][s]["opponent_beta"] if ok_h(s, "opponent_factor") else np.ones(N)
    mech = {}
    s_pf = {}
    for s in STATS:
        br = fs[f"base_{s}"]; pfr = X[f"pf_mean_{s}"].to_numpy(float) / np.maximum(fm, 1.0)
        okz = has & (br > 0) & (pfr > 0)
        z = np.where(okz, np.log(np.maximum(pfr, 1e-6) / np.maximum(br, 1e-6)), np.nan)
        s_pf[s] = walkforward_slope(date_s, xg, z, okz)
        full = lambda m: float(np.polyfit(xg[m], z[m], 1)[0]) if m.sum() > 50 else None
        y = X[f"y_{s}"].to_numpy(float); ym = X.y_min.to_numpy(float); oka = okz & base & (ym >= 1)
        act = lambda m: poisson_offset_slope(y[m], np.log(br[m] * ym[m]) + np.log(y[m].sum() / (br[m] * ym[m]).sum()), xg[m]) if m.sum() > 50 else None
        mech[s] = dict(pf_rate_slope_on_log_minutes_ratio=dict(train=full(okz & train), test=full(okz & masks[POOLED]), all_frozen_rows=full(okz)),
                       actual_rate_slope_given_actual_minutes=dict(train=act(oka & train), test=act(oka & masks[POOLED])),
                       walkforward_slope_first_test_day=float(s_pf[s][masks[POOLED]][0]) if masks[POOLED].any() else None,
                       walkforward_slope_last_day=float(s_pf[s][-1]))
    leak = [s for s in STATS if not np.all(s_pf[s][date_s == date_s.min()] == 0.0)]
    chk["mech"].append(_chk("minutes_coherence_slope_uses_forecasts_on_strictly_earlier_dates_only", not leak,
                            "first-slate slope is exactly 0 for every stat (no earlier forecasts); the slope regresses log(pf rate / archive rate) on log(pf minutes / recent "
                            "minutes) over has_pf rows of earlier dates, with no outcome column read"))
    P = X[base]; gap = mpg[base] - fm[base]; binc = pd.cut(pd.Series(gap), GAP_BINS)
    ym_b = P.y_min.to_numpy(float); br_b = fs["base_points"][base]; prate = P.pf_mean_points.to_numpy(float) / np.maximum(fm[base], 1.0)
    okb = (npg[base] >= 10) & (br_b > 0)
    bins = []
    for lab in binc.cat.categories:
        m = okb & (binc == lab).to_numpy()
        if m.sum() < 30:
            continue
        bins.append(dict(recent_minus_forecast_minutes=str(lab), n=int(m.sum()), recent_mpg=float(mpg[base][m].mean()), forecast_minutes=float(fm[base][m].mean()),
                         actual_minutes=float(ym_b[m].mean()), pf_rate_over_recent_rate=float((prate * ym_b)[m].sum() / (br_b * ym_b)[m].sum()),
                         actual_rate_over_recent_rate=float(P.y_points.to_numpy(float)[m].sum() / (br_b * ym_b)[m].sum()),
                         pf_rate_x_actual_minutes_over_actual=float((prate * ym_b)[m].sum() / P.y_points.to_numpy(float)[m].sum())))
    mech_doc = dict(per_stat=mech, points_by_minutes_gap=bins,
                    stack_weights_frozen_params={"points": {"A": 0.045, "D": 0.499, "E": 0.456}, "rebounds": {"A": 0.031, "D": 0.636, "E": 0.333},
                                                 "assists": {"D": 0.479, "E": 0.521}, "threes": {"A": 0.018, "D": 0.501, "E": 0.481}},
                    stack_weights_source=f"{F.NBA_REPO}@{F.MAIN_COMMIT[:12]} research/projection_foundation/results/frozen_params.json (families.*.params.F_weights)",
                    reading="pf's stat forecast responds to its own minutes forecast with elasticity ~0.7 (rate slope ~-0.3); D (minutes x rate) is fully elastic and A is "
                            "minutes-free but near zero weight, so the shortfall sits in the LightGBM rung E. Actual per-minute rates do not rise when minutes fall, so "
                            "pf over-forecasts when it cuts minutes. This is a coherence defect of the stack, not a basketball effect.")

    # ------------------------------------------------------------------ player means
    def crps_tilt(pm, pmean, pfm, mu, mk, y):
        return float(R._crps(R.tilt_pmf(pm[mk], pmean[mk] * mu[mk] / pfm[mk]), y[mk]).mean())
    sel = {}; mu4 = {}; c4_pmf = {}; c3_pmf = {}
    Rz = R.Results()
    for s in STATS:
        y = X[f"y_{s}"].to_numpy(float); pm = pf_pmf[s]; pmean = np.where(base, np.nan_to_num(pm) @ kk[s], np.nan); pfm = X[f"pf_mean_{s}"].to_numpy(float)
        bt = base & train
        mM = pfm * np.exp(-s_pf[s] * xg)
        c_pf, c_M = crps_tilt(pm, pmean, pfm, pfm, bt, y), crps_tilt(pm, pmean, pfm, mM, bt, y)
        use_M = c_M < c_pf; m0 = mM if use_M else pfm
        r03 = fs["ue_points"] if (s == "points" and ok_h(s, "usage_x_efficiency")) else fs[f"base_{s}"]
        cands = {"rate_0.3": r03, "nba.stat_rate_posterior": np.where(np.isfinite(srp[s]), srp[s], r03)}
        grid = {}
        for nm, rate in cands.items():
            ind = rate * fm * of[s]
            for w in W_GRID:
                grid[(nm, w)] = crps_tilt(pm, pmean, pfm, (1 - w) * m0 + w * ind, bt, y)
        (rname, w), _ = min(grid.items(), key=lambda kv: (kv[1], kv[0][1], kv[0][0]))
        blend = (1 - w) * m0 + w * cands[rname] * fm * of[s]
        okk = bt & (blend > 0) & np.isfinite(y)
        b = poisson_offset_slope(y[okk], np.log(blend[okk]) + np.log(y[okk].sum() / blend[okk].sum()), xg[okk])
        c_noK = grid[(rname, w)]; c_K = crps_tilt(pm, pmean, pfm, blend * np.exp(b * xg), bt, y); use_K = c_K < c_noK
        blend = blend * (np.exp(b * xg) if use_K else 1.0)
        K = hist["params"][s]["online_k_player_games"] * hist["params"][s]["mean_stat_train"]
        L = R.online_level(date_s, np.zeros(N), np.where(base, y, np.nan), np.where(base, blend, np.nan), K)
        c_L = crps_tilt(pm, pmean, pfm, blend * L, bt, y); use_L = c_L < crps_tilt(pm, pmean, pfm, blend, bt, y)
        mu = blend * (L if use_L else 1.0); mu4[s] = mu
        c4_pmf[s] = pm.copy(); c4_pmf[s][base] = R.tilt_pmf(pm[base], pmean[base] * mu[base] / pfm[base])
        c3_pmf[s] = pm.copy(); c3_pmf[s][base] = R.tilt_pmf(pm[base], pmean[base] * S["mu_c"][s][base] / pfm[base])
        sel[s] = dict(minutes_coherence_on=bool(use_M), train_crps_pf=c_pf, train_crps_minutes_coherent=c_M, independent_rate=rname, weight_on_independent_rate=w,
                      train_crps_best_blend=c_noK, coupling_b=b, coupling_on=bool(use_K), train_crps_with_coupling=c_K, online_level_on=bool(use_L), online_level_train_crps=c_L,
                      train_crps_by_rate_and_weight={f"{k[0]}|{k[1]}": v for k, v in grid.items()}, n_train_rows=int(bt.sum()))
        cm = {k: v & base for k, v in masks.items()}
        Rz.add(F.FAMILY[s], [F.ARCH[s]], "crps_given_played", ARM, "pf_frozen", R._crps(c4_pmf[s], y), R._crps(pm, y), gid, cm, headline=True)
        Rz.add(F.FAMILY[s], [F.ARCH[s]], "crps_given_played", ARM, REF03, R._crps(c4_pmf[s], y), R._crps(c3_pmf[s], y), gid, cm)
        Rz.add(F.FAMILY[s], [F.ARCH[s]], "abs_error_mean_given_played", ARM, "pf_frozen", np.abs(y - mu), np.abs(y - pfm), gid, cm)
        cut = (mpg - fm >= 4) & (npg >= 10)
        Rz.add(F.FAMILY[s], [F.ARCH[s]], "crps_given_played_pf_minutes_4_plus_below_recent", ARM, "pf_frozen", R._crps(c4_pmf[s], y), R._crps(pm, y), gid,
               {k: v & base & cut for k, v in masks.items()}, note="the slice the 0.3 diagnosis flagged")
    chk["level"].append(_chk("challenger_pmfs_sum_to_one", max(float(np.nanmax(np.abs(c4_pmf[s][base].sum(1) - 1))) for s in STATS) < 1e-6,
                             "every tilted player pmf sums to one within 1e-6"))
    chk["level"].append(_chk("component_switches_decided_on_train_window_only", int((train & masks[POOLED]).sum()) == 0,
                             f"TRAIN rows {int(train.sum())} and TEST rows {int(masks[POOLED].sum())} overlap: {int((train & masks[POOLED]).sum())}"))
    shift = lambda m: sum(m[s] - X[f"pf_mean_{s}"].to_numpy(float) for s in ("points", "rebounds", "assists"))
    bp = base & X.pf_pmf_pra.notna().to_numpy(); pmean_pra = np.nan_to_num(pf_pmf["pra"]) @ kk["pra"]; pfpra = X.pf_mean_pra.to_numpy(float)
    for tag, mm, store in (("c4", mu4, c4_pmf), ("c3", S["mu_c"], c3_pmf)):
        tgt = pfpra + shift(mm)
        store["pra"] = pf_pmf["pra"].copy(); store["pra"][bp] = R.tilt_pmf(pf_pmf["pra"][bp], pmean_pra[bp] * np.maximum(tgt[bp], 0.05) / pfpra[bp])
    ypra = X.y_pra.to_numpy(float); cmp_ = {k: v & bp for k, v in masks.items()}
    Rz.add("player_pra", ["NBA:player_pra"], "crps_given_played", ARM, "pf_frozen", R._crps(c4_pmf["pra"], ypra), R._crps(pf_pmf["pra"], ypra), gid, cmp_, headline=True)
    Rz.add("player_pra", ["NBA:player_pra"], "crps_given_played", ARM, REF03, R._crps(c4_pmf["pra"], ypra), R._crps(c3_pmf["pra"], ypra), gid, cmp_)

    # ------------------------------------------------------------------ prop rungs vs pf, 0.3 and the T-60 mid
    rr = S["rr"].copy(); ri = rr.row.to_numpy()
    rr["p_c4"] = np.nan
    for s in STATS + ["pra"]:
        mk = (rr.stat == s).to_numpy()
        rr.loc[mk, "p_c4"] = F._sf_dense(c4_pmf[s][ri[mk]], rr.k.to_numpy()[mk])
    mkt_counts = {}
    for s in STATS + ["pra"]:
        g = rr[(rr.stat == s) & rr.two & rr.p_pf.notna()].reset_index(drop=True); fam = F.FAMILY[s]; arch = [f"NBA:{fam}"]
        rm = F.cohort_masks(g.date_s); cl = g.gid.to_numpy(); bb = lambda p: C.brier_rows(p, g.y)
        Rz.add(fam, arch, "brier_ladder_given_played_two_sided", ARM, "pf_frozen", bb(g.p_c4), bb(g.p_pf), cl, rm)
        Rz.add(fam, arch, "brier_ladder_given_played_two_sided", ARM, REF03, bb(g.p_c4), bb(g.p_c), cl, rm)
        Rz.add(fam, arch, "brier_ladder_given_played_two_sided", ARM, "kalshi_t60_mid", bb(g.p_c4), bb(g.mid), cl, rm)
        mkt_counts[fam] = {c: dict(n_rungs=int(v.sum()), n_games=int(g.gid[v].nunique())) for c, v in rm.items()}

    # ------------------------------------------------------------------ team points: pf, normalised player sum, Phase 15 own-model totals
    T = S["T"].copy()
    Xp = X[X.has_pf.to_numpy()]; ep = np.nan_to_num(Xp.pf_p_play.to_numpy(float))
    agg = pd.DataFrame(dict(game_id=Xp.game_id.to_numpy(), team=Xp.team.to_numpy(), e_c=ep * np.nan_to_num(mu4["points"][X.has_pf.to_numpy()]),
                            e_min=ep * np.nan_to_num(Xp.pf_mean_minutes.to_numpy(float)))).groupby(["game_id", "team"]).sum()
    a2 = agg.reindex(pd.MultiIndex.from_arrays([T.game_id, T.team]))
    T["sum240_c4"] = np.where(a2.e_min.to_numpy() > 0, a2.e_c.to_numpy() * 240.0 / np.maximum(a2.e_min.to_numpy(), 1e-9), np.nan)
    T = T.merge(tm.rename(columns={"tricode": "team"}), on=["game_id", "team"], how="left")
    tcov = float(T.ot_exp_pts_pre.notna().mean())
    chk["coh"].append(_chk("phase15_own_model_team_totals_joins_team_games", tcov > 0.95, f"{int(T.ot_exp_pts_pre.notna().sum())} of {len(T)} team-games carry ot_exp_pts_pre ({tcov:.4f})"))
    own = T.ot_exp_pts_pre.fillna(T.pf).to_numpy(); ttrain = (T.date_s < F.TRAIN_END).to_numpy(); tmasks = F.cohort_masks(T.date_s); Kt = float(S["thist"]["k_team_games"])
    tgrid = {}
    for w1, w2 in simplex_grid():
        b0 = (1 - w1 - w2) * T.pf.to_numpy() + w1 * T.sum240_c4.fillna(T.pf).to_numpy() + w2 * own
        for on in (False, True):
            dl = R.online_level(T.date_s.to_numpy(), np.zeros(len(T)), T.y.to_numpy(), b0, Kt, additive=True) if on else 0.0
            tgrid[(w1, w2, on)] = float(np.abs(T.y.to_numpy() - b0 - dl)[ttrain].mean())
    w1, w2, onT = min(tgrid, key=lambda q: (tgrid[q], q[1], q[0], q[2]))
    b0 = (1 - w1 - w2) * T.pf.to_numpy() + w1 * T.sum240_c4.fillna(T.pf).to_numpy() + w2 * own
    T["c4"] = b0 + (R.online_level(T.date_s.to_numpy(), np.zeros(len(T)), T.y.to_numpy(), b0, Kt, additive=True) if onT else 0.0)
    sel["team_points"] = dict(weight_on_normalised_player_sum=w1, weight_on_phase15_own_model_team_totals=w2, online_level_on=bool(onT), n_train_team_games=int(ttrain.sum()),
                              train_abs_error_best=tgrid[(w1, w2, onT)], train_abs_error_pf=tgrid[(0.0, 0.0, False)],
                              train_abs_error_own_model_only=tgrid[(0.0, 1.0, False)])
    tg_ = T.game_id.to_numpy()
    Rz.add("team_total", ["NBA:team_total"], "abs_error_team_points", ARM, "pf_frozen", np.abs(T.y - T.c4), np.abs(T.y - T.pf), tg_, tmasks, headline=True)
    Rz.add("team_total", ["NBA:team_total"], "abs_error_team_points", ARM, REF03, np.abs(T.y - T.c4), np.abs(T.y - T.c), tg_, tmasks)
    Gm = T.groupby("game_id", sort=False).agg(date_s=("date_s", "first"), y=("y", "sum"), pf=("pf", "sum"), c=("c", "sum"), c4=("c4", "sum")).reset_index()
    hm = T[T.home].set_index("game_id"); aw = T[~T.home].set_index("game_id")
    Gm["ym"] = Gm.game_id.map(hm.y - aw.y); Gm["pfm"] = Gm.game_id.map(hm.pf - aw.pf); Gm["cm"] = Gm.game_id.map(hm.c - aw.c); Gm["c4m"] = Gm.game_id.map(hm.c4 - aw.c4)
    gm = F.cohort_masks(Gm.date_s); gg = Gm.game_id.to_numpy()
    Rz.add("game_total", ["NBA:game_total"], "abs_error_total", ARM, "pf_frozen", np.abs(Gm.y - Gm.c4), np.abs(Gm.y - Gm.pf), gg, gm, headline=True)
    Rz.add("game_total", ["NBA:game_total"], "abs_error_total", ARM, REF03, np.abs(Gm.y - Gm.c4), np.abs(Gm.y - Gm.c), gg, gm)
    Rz.add("game_spread", ["NBA:game_spread"], "abs_error_home_margin", ARM, "pf_frozen", np.abs(Gm.ym - Gm.c4m), np.abs(Gm.ym - Gm.pfm), gg, gm)
    cmean = {(g, t): c for g, t, c in zip(T.game_id, T.team, T.c4)}
    gf, M, tout = S["gf"], S["M"], S["tout"]
    new = []
    for r in gf.itertuples():
        tt = {}
        for t, x in r.teams.items():
            if (r.game_id, t) in cmean:
                p = np.asarray(x["probs"], float); mu0 = float(p / p.sum() @ (np.arange(len(p)) + int(x["lo"])))
                lo, pr = R.shift_pmf(int(x["lo"]), p, cmean[(r.game_id, t)] - mu0); tt[t] = dict(x, lo=lo, probs=list(pr), mean=cmean[(r.game_id, t)])
            else:
                tt[t] = x
        new.append(tt)
    gf4 = gf.copy(); gf4["teams"] = new
    G0 = S["G0"].copy(); G4 = F.game_rungs(M, gf4, tout)
    aligned = bool(len(G0) == len(G4) and (G0.ticker.to_numpy() == G4.ticker.to_numpy()).all())
    chk["coh"].append(_chk("challenger_game_rungs_aligned_with_incumbent_and_0.3", aligned, f"{len(G0)} game rungs, ticker by ticker: {aligned}"))
    G0["p_c4"] = G4.p.to_numpy() if aligned else np.nan
    for fam in ("game_spread", "game_total", "team_total"):
        g = G0[(G0.family == fam) & (G0.quote_class == "TWO_SIDED") & G0.bid.notna() & G0.ask.notna()].reset_index(drop=True)
        g["mid"] = (g.bid.astype(float) + g.ask.astype(float)) / 2
        rm = F.cohort_masks(g.date_s); cl = g.game_id.to_numpy(); bb = lambda p: C.brier_rows(p, g.y)
        Rz.add(fam, [f"NBA:{fam}"], "brier_two_sided", ARM, "pf_frozen", bb(g.p_c4), bb(g.p), cl, rm)
        Rz.add(fam, [f"NBA:{fam}"], "brier_two_sided", ARM, REF03, bb(g.p_c4), bb(g.p_c), cl, rm)
        Rz.add(fam, [f"NBA:{fam}"], "brier_two_sided", ARM, "kalshi_t60_mid", bb(g.p_c4), bb(g.mid), cl, rm)
        mkt_counts[fam] = {c: dict(n_rungs=int(v.sum()), n_games=int(g.game_id[v].nunique())) for c, v in rm.items()}
    rows = Rz.finalize()
    return dict(S=S, rows=rows, sel=sel, chk=chk, mech=mech_doc, mkt_counts=mkt_counts, T=T, Gm=Gm, rr=rr)


def _fmt(r):
    return "n/a" if r is None else f"{r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] {r['verdict']} (n={r['n_clusters']} games)"


def build_document(V: dict) -> tuple:
    S, rows, sel, chk = V["S"], V["rows"], V["sel"], V["chk"]
    X, masks = S["X"], S["masks"]
    find = lambda fam, metric, ref, coh=POOLED: next((r for r in rows if (r["market_family"], r["metric"], r["reference"], r["cohort"]) == (fam, metric, ref, coh)), None)
    fams_p = [F.FAMILY[s] for s in STATS] + ["player_pra"]; fams_g = ["game_spread", "game_total", "team_total"]
    bm = lambda f: "brier_two_sided" if f in fams_g else "brier_ladder_given_played_two_sided"
    head = [r for r in rows if r["headline"]]
    hv = {r["market_family"] + ":" + r["metric"]: r["verdict"] for r in head}
    vm = {f: find(f, bm(f), "kalshi_t60_mid") for f in fams_p + fams_g}
    v3 = {f: find(f, "crps_given_played", REF03) for f in fams_p}
    v3.update({"team_total": find("team_total", "abs_error_team_points", REF03), "game_total": find("game_total", "abs_error_total", REF03)})
    n_val = sum(v == "VALIDATED_IMPROVEMENT" for v in hv.values()); worse_mkt = [f for f, r in vm.items() if r and r["verdict"] == "NOT_IMPROVED"]
    any_bad = any(v == "NOT_IMPROVED" for v in hv.values())
    overall = ("VALIDATED_IMPROVEMENT" if n_val == len(hv) and not worse_mkt else "IMPROVED_NOT_VALIDATED" if n_val else "NOT_IMPROVED" if any_bad else "INCONCLUSIVE")
    beats03 = sorted(f for f, r in v3.items() if r and r["verdict"] in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED"))
    worse03 = sorted(f for f, r in v3.items() if r and r["verdict"] == "NOT_IMPROVED")
    verdict = dict(overall=overall, retain_incumbent=True,
                   rule="contract.verdict_from on every row (95% game-clustered CI below zero, Holm p < 0.05, same sign in both TEST cohorts). Overall VALIDATED_IMPROVEMENT only if "
                        "every headline row (vs frozen pf) is validated AND the challenger is not significantly worse than the Kalshi T-60 mid on any family.",
                   headline_c4_vs_pf_frozen=hv, c4_vs_alpha_nba_rate_0_3={f: _fmt(r) for f, r in v3.items()}, c4_vs_kalshi_t60_mid={f: _fmt(r) for f, r in vm.items()},
                   better_than_0_3=beats03, worse_than_0_3=worse03,
                   reason=f"{n_val} of {len(hv)} headline rows validated against the frozen production forecasts; vs 0.3 better on {beats03 or 'none'}, worse on {worse03 or 'none'}; "
                          f"significantly worse than the Kalshi T-60 mid on {worse_mkt or 'none'}",
                   evidence_sufficiency=f"{int(X[masks[POOLED]].game_id.nunique())} TEST games in two cohorts of about one week (the same window as 0.3); one month of one season")
    features = [
        dict(feature_id="minutes_coherent_pf_mean", catalog_inputs=["NBA:nba.minutes"],
             description="pf stat mean x (pf minutes / recent minutes)^(-s_pf); s_pf = walk-forward OLS slope of log(pf per-minute rate / archive per-minute rate) on "
                         "log(pf minutes / recent minutes), from forecasts on strictly earlier dates only. Removes the minutes incoherence of pf's stacked mean.",
             pit_rule="frozen pf forecasts (T-60) and box history of strictly earlier dates; no outcome enters s_pf; switch decided on TRAIN",
             parameters={s: dict(on=sel[s]["minutes_coherence_on"], slope_last_day=V["mech"]["per_stat"][s]["walkforward_slope_last_day"]) for s in STATS}, checks=chk["mech"]),
        dict(feature_id="phase15_stat_rate_posterior_as_independent_rate", catalog_inputs=["NBA:nba.stat_rate_posterior"],
             description="Phase 15 builder nba.stat_rate_posterior (per-36 posterior, season to date shrunk 400 minutes to the previous season) offered as the independent "
                         "rate next to 0.3's rate; the better one on TRAIN CRPS is used, times the pf minutes forecast and the 0.3 opponent factor.",
             pit_rule="builder uses the player's strictly earlier games (replay-gated and blind-matched in Phase 15; re-checked here by truncation)",
             parameters={s: dict(independent_rate=sel[s]["independent_rate"], weight=sel[s]["weight_on_independent_rate"]) for s in STATS}, checks=chk["feat"]),
        dict(feature_id="minutes_rate_coupling", catalog_inputs=["NBA:nba.minutes"],
             description="extra (pf minutes / recent minutes)^b, b fitted on TRAIN outcomes (Poisson with offset); kept only if TRAIN CRPS falls. b nets the per-minute "
                         "coupling against actual minutes regressing toward recent minutes when pf's minutes forecast departs from them (a negative b is expected).",
             pit_rule="b fitted on games before 2026-11-01", parameters={s: dict(b=sel[s]["coupling_b"], on=sel[s]["coupling_on"]) for s in STATS}, checks=chk["level"]),
        dict(feature_id="team_points_three_way_blend_with_phase15_own_model_totals", catalog_inputs=["NBA:nba.own_model_team_totals"],
             description="team points = simplex blend of the frozen pf team mean, the normalised challenger player sum and the Phase 15 builder nba.own_model_team_totals "
                         "(pace x efficiency from the owner's box archive); optional additive online level; pf team pmf shifted to the new mean",
             pit_rule="builder uses strictly earlier games; weights fitted on TRAIN team-games", parameters=sel["team_points"], checks=chk["coh"]),
    ]
    S3 = S
    data = [F._ds("pf_frozen_player_forecasts", "forecasts/nba/", int(X.has_pf.sum()), str(X.date_s.min()), str(X.date_s.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
            F._ds("pf_frozen_team_points_forecasts", "game_forecasts/nba/", len(S3["gf"]), str(X.date_s.min()), str(X.date_s.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
            F._ds("final_player_and_team_outcomes", "outcomes/nba/ + team_outcomes/nba/", len(S3["out"]), str(X.date_s.min()), str(X.date_s.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
            F._ds("kalshi_t60_quotes_projection_data_plus_restored", "market_snapshots/nba/ + kalshi/markets(_delta)/", len(S3["M"]), str(X.date_s.min()), str(X.date_s.max()),
                  "PROSPECTIVE_CAPTURE", R.DA_COMMIT, R.DA_BRANCH),
            F._ds("espn_box_archive_2023-24_to_2026-27_phase15_builders", "data/history/espn/ (main) + history/espn/ (data-archive)", len(S3["pg"]), str(S3["pg"].game_date_et.min()),
                  str(S3["pg"].game_date_et.max()), "HISTORICAL_BACKFILL", F.MAIN_COMMIT, "main")]
    cs = {c: dict(games=int(X[m].game_id.nunique()), played_rows=int((m & S["base"]).sum())) for c, m in masks.items()}
    design = dict(incumbent_reference="ACTUAL frozen production forecasts (pf-nba) archived on projection-data; prior challenger alpha-nba-rate-0.3 re-run in-process unchanged",
                  mechanism=V["mech"], selection_on_train_window=sel, market_counts=V["mkt_counts"], cohort_sizes=cs, headline_rows=len(head),
                  windows=dict(train=f"< {F.TRAIN_END}", test_cohort_1=COH1, test_cohort_2=COH2),
                  arms={ARM: "minutes-coherent pf mean, blended with an independent rate (0.3's or Phase 15 stat_rate_posterior), optional coupling and online level; team "
                             "points three-way blend with Phase 15 own-model totals", "pf_frozen": "production forecasts as archived", REF03: "0.3 re-run in-process",
                        "kalshi_t60_mid": "(yes_bid + yes_ask) / 2 on two-sided T-60 quotes"},
                  statistics=f"paired game-clustered bootstrap (2000 draws, seed {F.SEED}); Holm across the {len(head)} headline rows (vs pf_frozen, TEST pooled); other rows Holm within "
                             "(arm, reference, cohort)",
                  correlations="player pmfs are pf's own pmfs tilted to the new mean; PRA tilts pf's PRA pmf by the summed component shifts; team pmfs shifted; spread/total use pf's "
                               "archived rho", economics="fees, spreads and execution out of scope; no profitability claim")
    limitations = [
        "Same one-month window as 0.3 (TEST = 88 games, two cohorts of about a week). A validated row means the contract rule passed on this window only.",
        "The mechanism is read from the frozen forecasts and the owner's model source; the production stack itself was not re-run (its LightGBM rung has no archived inputs).",
        "Component switches and weights are chosen on the 2026-27 TRAIN window (about 1,980 played rows, 88 games); grids were fixed before the TEST read.",
        "The W grid was widened to 0..1 relative to 0.3 because 0.3's weight sat on its 0.5 edge; this is a design change made after 0.3's result was known and is disclosed.",
        "Spread and total probabilities use pf's normal approximation with the archived rho; a common shift of both teams leaves spreads unchanged.",
        "No new external data was collected. No fees, no execution, no profitability claim.",
    ]
    fp = lambda s: find(F.FAMILY[s] if s in F.FAMILY else s, "crps_given_played", "pf_frozen")
    claims = [
        dict(input="NBA:nba.stat_rate_posterior", stage="CHALLENGER_INTEGRATED" if any(sel[s]["independent_rate"] == "nba.stat_rate_posterior" for s in STATS) else "EVALUATED",
             outcome="OK" if any(sel[s]["independent_rate"] == "nba.stat_rate_posterior" for s in STATS) else "REJECTED",
             evidence="Phase 15 builder offered as the independent rate; TRAIN selection: " + json.dumps({s: sel[s]["independent_rate"] for s in STATS})
                      + "; C4 vs pf TEST CRPS: " + "; ".join(f"{s} {_fmt(fp(s))}" for s in STATS)),
        dict(input="NBA:nba.own_model_team_totals", stage="EVALUATED",
             outcome="PARTIAL" if sel["team_points"]["weight_on_phase15_own_model_team_totals"] > 0 else "REJECTED",
             evidence=f"Phase 15 builder weight {sel['team_points']['weight_on_phase15_own_model_team_totals']} in the TRAIN-selected team blend; team total vs pf "
                      + _fmt(find("team_total", "abs_error_team_points", "pf_frozen")) + "; game total " + _fmt(find("game_total", "abs_error_total", "pf_frozen"))),
        dict(input="NBA:nba.minutes", stage="EVALUATED", outcome="PARTIAL",
             evidence="minutes-coherence correction of pf's stack (mechanism in design.mechanism); points slice pf minutes 4+ below recent: "
                      + _fmt(find("player_points", "crps_given_played_pf_minutes_4_plus_below_recent", "pf_frozen"))),
    ]
    doc = dict(schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="NBA", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID, data=data, features=features, design=design,
               results=rows, ablations=[], verdict=verdict, limitations=limitations, input_stage_claims=claims,
               source_commits={f"nba-edge-finder@{F.PD_BRANCH}": F.PD_COMMIT, "nba-edge-finder@main": F.MAIN_COMMIT, f"nba-edge-finder@{R.DA_BRANCH}": R.DA_COMMIT})
    summ = dict(challenger_id=CHALLENGER_ID, cohort_sizes=cs, frame_digest=F.digest(sorted(zip(X.game_id, X.entity_id))), rung_digest=F.digest(sorted(V["rr"].ticker.tolist())))
    return doc, summ


def evaluate(repo: Path | None = None, out_dir: Path | None = None, verbose: bool = True) -> dict:
    V = run(repo, verbose)
    doc, summ = build_document(V)
    errs = C.validate_evaluation(doc)
    if errs:
        raise RuntimeError(f"evaluation violates the contract: {errs}")
    od = Path(out_dir) if out_dir else OUT_DIR
    C.write_json(od / "evaluation.json", doc)
    C.write_json(od / "predictions_summary.json", summ)
    return doc


def main(argv=None) -> int:
    doc = evaluate()
    print(f"{CHALLENGER_ID}: overall {doc['verdict']['overall']}; {len(doc['results'])} result rows")
    for r in doc["results"]:
        if r["cohort"] == POOLED:
            print(f"  {'*' if r['headline'] else ' '} {r['market_family']:16s} {r['metric'][:40]:40s} vs {r['reference'][:30]:30s} n={r['n_clusters']:3d} d={r['diff']:+.4f} "
                  f"[{r['ci95'][0]:+.4f},{r['ci95'][1]:+.4f}] {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

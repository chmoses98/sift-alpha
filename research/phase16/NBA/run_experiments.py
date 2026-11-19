"""Phase 16 NBA bounded experiments E1-E3 on pbp-derived possession/lineup features (RESEARCH_ONLY).

    cd <nba-edge-finder worktree @ ef91cea> && python <this> --c15 $W/cache15 --ps $W/period_scores.parquet \
        --feat data/pbp_pregame_features.csv.gz --frozen docs/research/nba_phase15/periods_frozen.json --out results.json

Pre-stated design (fixed before any result was seen; nothing is tuned on 2024-25 or later):
  split  : dev = seasons <= 2023-24 (walk-forward: residual model for season s trained on seasons < s);
           holdout = 2024-25, 2025-26 (active list known, as in #114/#116) and 2026-27 to date (pregame, tip, archived p_play),
           residual model trained once on all dev seasons. Same seasons as NBA_PHASE14/15 docs.
  model  : ridge (lam=20 on standardised features) on the residual of the incumbent forecast; nothing else refitted.
  E1     : full game. Incumbent = frozen PAG. Features = home-away (margin) / home+away (total) of pregame pace, ORtg, DRtg,
           starting-unit net + share, bench net. Winner prob: logistic stack on [logit p_PAG, residual-adjusted margin delta]
           vs logistic on [logit p_PAG] alone (so calibration-only gains are not counted as accuracy). Also vs pf-1.3 on 2026-27.
  E2     : Q1 and H1. Incumbent = #116 frozen chosen period model (Q1 M3s, H1 M1). Variant A = pregame lineup features only
           (rolling starting-unit net, starters' Q1 minutes); variant B = A + ACTUAL starters (their prior on-court net, number
           of unexpected starters) = upper bound of confirmed-starter capture. Side residuals -> team totals, totals, spreads.
  E3     : Q1/H1 spread ladders. Calibration slope of split (the #116 recommended spread source) and chosen, and whether the
           margin adjustment from starting-unit strength (variant B margin part applied to split) moves the slope toward 1.
Metrics: MAE/RMSE, ladder Brier/log loss (lines +-1.5 SD around the split mean, model-neutral, as #116), calibration slope,
game-clustered bootstrap 95% CIs on paired deltas.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, "scripts")
import nba_phase15_periods as S15  # noqa: E402

from nba_edge.research import p15eval as E  # noqa: E402
from nba_edge.research import period_game as PGm  # noqa: E402

DEV_EVAL = range(2018, 2025)
HOLD = (2025, 2026)
LAM = 20.0
LADDER = np.arange(-9.5, 10.0, 1.0)


def ridge_fit(X, y, lam=LAM):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    A = np.column_stack([np.ones(len(Z)), Z])
    pen = lam * np.eye(A.shape[1]); pen[0, 0] = 0
    return {"b": np.linalg.solve(A.T @ A + pen, A.T @ y), "mu": mu, "sd": sd}


def ridge_pred(m, X):
    return np.column_stack([np.ones(len(X)), (X - m["mu"]) / m["sd"]]) @ m["b"]


def logit_fit(X, y, l2=1e-3):
    A = np.column_stack([np.ones(len(X)), X]); b = np.zeros(A.shape[1])
    for _ in range(50):
        q = 1 / (1 + np.exp(-A @ b))
        H = A.T @ (A * (q * (1 - q))[:, None]) + l2 * np.eye(len(b))
        b += np.linalg.solve(H, A.T @ (y - q) - l2 * b)
    return b


def logit_pred(b, X):
    return 1 / (1 + np.exp(-np.column_stack([np.ones(len(X)), X]) @ b))


def lg(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def ci(new, old, g):
    r = E.paired_delta(new, old, g)
    return {k: (round(float(v), 5) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()} if isinstance(r, dict) else r


def side_feats(F):
    F = F.copy()
    F["pre_net"] = F.pre_ortg - F.pre_drtg
    return F


# ---------------------------------------------------------------- E1
def e1(c15, F):
    x = pd.read_parquet(f"{c15}/pag_hist.parquet")
    x = x[x.season_type == 2].copy()
    F = side_feats(F)
    cols = ["pre_pace48", "pre_ortg", "pre_drtg", "pre_net", "pre_su_net", "pre_su_share", "pre_bn_net"]
    f = F[["game_id", "home", "pre_n_games"] + cols]
    x = x.merge(f[f.home == 1].drop(columns="home").add_prefix("h_").rename(columns={"h_game_id": "game_id"}), on="game_id", how="left")
    x = x.merge(f[f.home == 0].drop(columns="home").add_prefix("a_").rename(columns={"a_game_id": "game_id"}), on="game_id", how="left")
    cov = float(x.h_pre_ortg.notna().mean() * x.a_pre_ortg.notna().mean())
    x = x[(x.h_pre_n_games >= 5) & (x.a_pre_n_games >= 5)].dropna(subset=["h_pre_ortg", "a_pre_ortg", "margin_pag"]).reset_index(drop=True)
    for c in ("pre_su_net", "pre_bn_net", "pre_su_share"):
        x[f"h_{c}"], x[f"a_{c}"] = x[f"h_{c}"].fillna(0), x[f"a_{c}"].fillna(0)
    Xm = np.column_stack([x[f"h_{c}"] - x[f"a_{c}"] for c in ("pre_net", "pre_su_net", "pre_bn_net", "pre_su_share", "pre_ortg")])
    Xt = np.column_stack([x[f"h_{c}"] + x[f"a_{c}"] for c in ("pre_pace48", "pre_ortg", "pre_drtg")])
    x["rm"], x["rt"] = x.margin - x.margin_pag, x.total - x.total_pag
    x["win"] = (x.margin > 0).astype(float)

    def run(tr, te):
        mm, mt = ridge_fit(Xm[tr], x.rm[tr].to_numpy()), ridge_fit(Xt[tr], x.rt[tr].to_numpy())
        dm, dt = ridge_pred(mm, Xm[te]), ridge_pred(mt, Xt[te])
        sig_b = float(x.rm[tr].std()); sig_a = float((x.rm[tr] - ridge_pred(mm, Xm[tr])).std())
        dtr = ridge_pred(mm, Xm[tr])
        b0 = logit_fit(lg(x.p_home_pag[tr].to_numpy())[:, None], x.win[tr].to_numpy())
        b1 = logit_fit(np.column_stack([lg(x.p_home_pag[tr].to_numpy()), dtr]), x.win[tr].to_numpy())
        z = x[te].copy()
        z["m_aug"], z["t_aug"] = z.margin_pag + dm, z.total_pag + dt
        z["p_raw"] = z.p_home_pag
        z["p_cal"] = logit_pred(b0, lg(z.p_home_pag.to_numpy())[:, None])
        z["p_aug"] = logit_pred(b1, np.column_stack([lg(z.p_home_pag.to_numpy()), dm]))
        return z, sig_b, sig_a, {"margin_coef": np.round(mm["b"][1:], 3).tolist(), "total_coef": np.round(mt["b"][1:], 3).tolist()}

    def metrics(z, sb, sa):
        g = z.game_id.to_numpy()
        eb, ea = (z.margin - z.margin_pag).to_numpy(), (z.margin - z.m_aug).to_numpy()
        tb, ta = (z.total - z.total_pag).to_numpy(), (z.total - z.t_aug).to_numpy()
        y = z.win.to_numpy()
        lad = lambda mu, s: np.stack([norm.sf((k - mu) / s) for k in LADDER], 1)  # noqa: E731
        Y = np.stack([(z.margin.to_numpy() > k) for k in LADDER], 1).astype(float)
        lb, la = lad(z.margin_pag.to_numpy(), sb), lad(z.m_aug.to_numpy(), sa)
        ll = lambda p, yy: -(yy * np.log(np.clip(p, 1e-6, 1)) + (1 - yy) * np.log(np.clip(1 - p, 1e-6, 1)))  # noqa: E731
        o = {"n": len(z),
             "margin_mae": [round(np.abs(eb).mean(), 3), round(np.abs(ea).mean(), 3)], "margin_mae_delta": ci(np.abs(ea), np.abs(eb), g),
             "margin_rmse": [round(np.sqrt((eb ** 2).mean()), 3), round(np.sqrt((ea ** 2).mean()), 3)],
             "total_mae": [round(np.abs(tb).mean(), 3), round(np.abs(ta).mean(), 3)], "total_mae_delta": ci(np.abs(ta), np.abs(tb), g),
             "total_rmse": [round(np.sqrt((tb ** 2).mean()), 3), round(np.sqrt((ta ** 2).mean()), 3)],
             "winner_brier_raw_cal_aug": [round(((z[c] - y) ** 2).mean(), 5) for c in ("p_raw", "p_cal", "p_aug")],
             "winner_logloss_raw_cal_aug": [round(ll(z[c].to_numpy(), y).mean(), 5) for c in ("p_raw", "p_cal", "p_aug")],
             "winner_logloss_aug_vs_cal (accuracy)": ci(ll(z.p_aug.to_numpy(), y), ll(z.p_cal.to_numpy(), y), g),
             "winner_logloss_cal_vs_raw (calibration only)": ci(ll(z.p_cal.to_numpy(), y), ll(z.p_raw.to_numpy(), y), g),
             "winner_calib_slope_raw_cal_aug": [round(E.calibration_slope(z[c], y), 3) for c in ("p_raw", "p_cal", "p_aug")],
             "spread_ladder_logloss": [round(ll(lb, Y).mean(), 5), round(ll(la, Y).mean(), 5)],
             "spread_ladder_logloss_delta": ci(ll(la, Y).mean(1), ll(lb, Y).mean(1), g),
             "spread_ladder_brier": [round(((lb - Y) ** 2).mean(), 5), round(((la - Y) ** 2).mean(), 5)],
             "spread_ladder_slope": [round(E.calibration_slope(lb.ravel(), Y.ravel()), 3), round(E.calibration_slope(la.ravel(), Y.ravel()), 3)],
             "total_bias": [round(-tb.mean(), 2), round(-ta.mean(), 2)]}
        return o

    out = {"feature_coverage_pairs": round(cov, 4), "pairs_note": "[PAG, PAG+pbp]; winner [raw PAG, recalibrated PAG, PAG+pbp]"}
    dev = []
    for s in DEV_EVAL:
        tr = ((x.season < s) & (x.season >= 2016)).to_numpy(); te = (x.season == s).to_numpy()
        if tr.sum() < 500:
            continue
        z, sb, sa, _ = run(tr, te); z["sb"], z["sa"] = sb, sa; dev.append(z)
    D = pd.concat(dev)
    out["dev_walkforward_2018_2024"] = metrics(D, float(D.sb.iloc[0]), float(D.sa.iloc[0])) | {"note": "PAG is in-sample on these seasons"}
    trd = (x.season <= 2024).to_numpy()
    for s in (2025, 2026, 2027):
        z, sb, sa, coef = run(trd, (x.season == s).to_numpy())
        out[f"holdout_{s}"] = metrics(z, sb, sa)
    out["coef_frozen_dev"] = coef
    # 2026-27 pregame (tip): PAG pre variant vs PAG pre + pbp vs pf-1.3, identical games
    pr = pd.read_parquet(f"{c15}/pag_pre_0h.parquet"); pf = pd.read_parquet(f"{c15}/pf_0h.parquet")
    z = x.merge(pr, on="game_id").merge(pf, on="game_id")
    if len(z):
        idx = x.index[x.game_id.isin(z.game_id)]
        xx = x.copy()
        xx.loc[idx, "margin_pag"] = xx.loc[idx, "game_id"].map(pr.set_index("game_id").margin_pre)
        xx.loc[idx, "total_pag"] = xx.loc[idx, "game_id"].map(pr.set_index("game_id").total_pre)
        xx.loc[idx, "p_home_pag"] = xx.loc[idx, "game_id"].map(pr.set_index("game_id").p_home_pre)
        x0 = x
        x = xx
        zz, sb, sa, _ = run(trd, x.game_id.isin(z.game_id).to_numpy())
        x = x0
        zz = zz.merge(pf[["game_id", "pred_margin", "pred_total", "p_home"]], on="game_id")
        g, y = zz.game_id.to_numpy(), zz.win.to_numpy()
        ll = lambda p: -(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))  # noqa: E731
        out["pregame_2027_tip_vs_pf13"] = {
            "n": len(zz),
            "margin_mae_pf_pag_aug": [round((zz.margin - zz[c]).abs().mean(), 3) for c in ("pred_margin", "margin_pag", "m_aug")],
            "total_mae_pf_pag_aug": [round((zz.total - zz[c]).abs().mean(), 3) for c in ("pred_total", "total_pag", "t_aug")],
            "winner_logloss_pf_pag_aug": [round(ll(zz[c].to_numpy()).mean(), 4) for c in ("p_home", "p_raw", "p_aug")],
            "aug_minus_pf_margin_mae": ci((zz.margin - zz.m_aug).abs(), (zz.margin - zz.pred_margin).abs(), g),
            "aug_minus_pag_margin_mae": ci((zz.margin - zz.m_aug).abs(), (zz.margin - zz.margin_pag).abs(), g),
            "aug_minus_pag_total_mae": ci((zz.total - zz.t_aug).abs(), (zz.total - zz.total_pag).abs(), g),
            "aug_minus_pf_winner_logloss": ci(ll(zz.p_aug.to_numpy()), ll(zz.p_home.to_numpy()), g)}
    return out


# ---------------------------------------------------------------- E2 / E3
def period_frame(c15, ps_path, F, pre=None):
    allps = PGm.segment_points(pd.read_parquet(ps_path))
    allps = allps[(allps["h_final"] + allps["a_final"]) > 0].reset_index(drop=True)
    hist = pd.read_parquet(f"{c15}/pag_hist.parquet")
    dates = allps["game_id"].map(hist.set_index("game_id")["date"])
    allps, dates = allps[dates.notna()].reset_index(drop=True), dates[dates.notna()].reset_index(drop=True)
    return allps, dates


def lineup_cols(z, F):
    F = side_feats(F)
    keep = ["pre_su_net", "pre_su_share", "pre_st_min_q1", "pre_st_min_q2", "st5_net", "st5_min", "st5_n_unexpected", "pre_ortg", "pre_drtg", "pre_pace48"]
    f = F[["game_id", "team_id"] + keep]
    for side, col in (("h", "home_id"), ("a", "away_id")):
        z = z.merge(f.rename(columns={"team_id": col, **{k: f"L{side}_{k}" for k in keep}}), on=["game_id", col], how="left")
    return z


VAR_A = ["pre_su_net", "pre_su_share", "pre_st_min_q1"]          # pregame-only lineup features
VAR_B = VAR_A + ["st5_net", "st5_n_unexpected"]                   # + actual starters (upper bound of lineup capture)


def xmat(z, cols, seg):
    H = np.column_stack([z[f"Lh_{c}"].fillna(0) for c in cols])
    A = np.column_stack([z[f"La_{c}"].fillna(0) for c in cols])
    return np.column_stack([H, A]), np.column_stack([A, H])   # home side: own, opp ; away side: own, opp


def e2e3(c15, ps_path, F, frozen):
    fr = json.load(open(frozen))
    models, shares = fr["models"], fr["shares"]
    allps, dates = period_frame(c15, ps_path, F)
    sets = {}
    z = S15.add_tendencies(S15.frame(c15, ps_path, None), allps, dates, shares)
    z = lineup_cols(z, F)
    zp = lineup_cols(S15.add_tendencies(S15.frame(c15, ps_path, "0h"), allps, dates, shares), F)
    chosen = {"Q1": "M3s", "H1": "M1"}
    out = {}
    for seg in ("Q1", "H1"):
        n = 70 if seg == "Q1" else 120
        res = {}
        def predict(zz):
            base = S15._pred(zz, models[seg][chosen[seg]], shares).reset_index(drop=True)
            spl = S15._pred(zz, models[seg]["split"], shares).reset_index(drop=True)
            return base, spl
        zall = z.reset_index(drop=True)
        base_all, spl_all = predict(zall)
        rh = zall[f"h_{seg}"] - base_all.h_mu
        ra = zall[f"a_{seg}"] - base_all.a_mu
        rms = (zall[f"h_{seg}"] - zall[f"a_{seg}"]) - (spl_all.h_mu - spl_all.a_mu)

        def fit_side(tr, cols):
            Xh, Xa = xmat(zall[tr], cols, seg)
            X = np.vstack([Xh, Xa]); y = np.r_[rh[tr], ra[tr]]
            return ridge_fit(X, y)

        def fit_split_margin(tr, cols):
            Xh, Xa = xmat(zall[tr], cols, seg)
            return ridge_fit(Xh - Xa, rms[tr].to_numpy())

        def evaluate(zz, base, spl, mA, mB, mS):
            zz = zz.reset_index(drop=True)
            P = {"chosen": base}
            for nm, m, cols in (("A", mA, VAR_A), ("B", mB, VAR_B)):
                Xh, Xa = xmat(zz, cols, seg)
                q = base.copy(); q["h_mu"] = base.h_mu + ridge_pred(m, Xh); q["a_mu"] = base.a_mu + ridge_pred(m, Xa)
                P[nm] = q
            Xh, Xa = xmat(zz, VAR_B, seg)
            q = spl.copy(); d = ridge_pred(mS, Xh - Xa)
            q["h_mu"], q["a_mu"] = spl.h_mu + d / 2, spl.a_mu - d / 2
            P["split_startB"] = q
            P["split"] = spl
            pm = {k: S15.pmfs(v, n) for k, v in P.items()}
            sm, st = S15._sds(models[seg]["split"])
            # score() compares every model against the key "split"; ladders centred on split means
            r = S15.score(zz, seg, pm, spl, (sm, st))
            yh, ya = zz[f"h_{seg}"].to_numpy(), zz[f"a_{seg}"].to_numpy(); g = zz.game_id.to_numpy()
            ae = lambda v: {"tot": np.abs(yh + ya - v.h_mu - v.a_mu), "mar": np.abs(yh - ya - v.h_mu + v.a_mu), "team": (np.abs(yh - v.h_mu) + np.abs(ya - v.a_mu)) / 2}  # noqa: E731
            A0 = ae(P["chosen"])
            o = {"n_games": int(len(zz))}
            for k in ("chosen", "A", "B", "split", "split_startB"):
                rr = r[k]
                Ak = ae(P[k])
                o[k] = {m: rr[m] for m in ("spread_ladder_logloss", "total_ladder_logloss", "team_total_ladder_logloss", "spread_ladder_brier", "ladder_calib_slope")}
                o[k]["mae_total_margin_team"] = [round(float(Ak[c].mean()), 3) for c in ("tot", "mar", "team")]
                o[k]["rmse_total"] = round(float(np.sqrt(((yh + ya - P[k].h_mu - P[k].a_mu) ** 2).mean())), 3)
            # spread-only calibration slope (ladder_calib_slope mixes spread+total rungs) for E3
            km = lambda mm, i: np.round(mm[i]) + np.arange(-np.ceil(1.5 * sm), np.ceil(1.5 * sm) + 1) - 0.5  # noqa: E731
            mm = (spl.h_mu - spl.a_mu).to_numpy()
            for k in ("chosen", "split", "split_startB", "B"):
                pp, yy = [], []
                for i, p_ in enumerate(pm[k]):
                    kk = km(mm, i)
                    pp += [p_.p_margin_gt(t) for t in kk]; yy += list((yh[i] - ya[i]) > kk)
                o[k]["spread_calib_slope"] = round(E.calibration_slope(np.array(pp), np.array(yy, float)), 3)
                o[k]["spread_mean_p_vs_rate"] = [round(float(np.mean(pp)), 4), round(float(np.mean(yy)), 4)]
            # paired deltas vs the chosen incumbent (lower = better); split_startB vs split
            o["deltas"] = {}
            for k in ("A", "B"):
                o["deltas"][f"{k}_vs_chosen"] = {
                    "total_mae": ci(ae(P[k])["tot"], A0["tot"], g), "team_total_mae": ci(ae(P[k])["team"], A0["team"], g),
                    "margin_mae": ci(ae(P[k])["mar"], A0["mar"], g)}
            o["deltas"]["B_vs_A_total_mae"] = ci(ae(P["B"])["tot"], ae(P["A"])["tot"], g)
            o["deltas"]["split_startB_vs_split_margin_mae"] = ci(ae(P["split_startB"])["mar"], ae(P["split"])["mar"], g)
            o["vs_split_from_score"] = {k: {kk: r[k]["vs_split"][kk] for kk in ("spread_ladder_logloss", "total_ladder_logloss", "team_total_ladder_logloss")}
                                        for k in ("chosen", "A", "B", "split_startB")}
            return o

        dev = []
        for s in (2022, 2023, 2024):
            tr = ((zall.season < s) & (zall.season >= 2020)).to_numpy()
            te = (zall.season == s).to_numpy()
            mA, mB, mS = fit_side(tr, VAR_A), fit_side(tr, VAR_B), fit_split_margin(tr, VAR_B)
            dev.append((s, mA, mB, mS))
        # dev pooled 2022-2024 (walk-forward residual models; period models in-sample on these seasons)
        Zd, Bd, Sd = [], [], []
        for s, mA, mB, mS in dev:
            te = (zall.season == s).to_numpy()
            Zd.append(zall[te]); Bd.append(base_all[te]); Sd.append(spl_all[te])
        # evaluate per season and pool via concatenation using each season's own residual models
        res["dev_by_season"] = {}
        for (s, mA, mB, mS), zz, b_, s_ in zip(dev, Zd, Bd, Sd):
            res["dev_by_season"][s] = evaluate(zz, b_.reset_index(drop=True), s_.reset_index(drop=True), mA, mB, mS)
        trd = ((zall.season >= 2020) & (zall.season <= 2024)).to_numpy()
        mA, mB, mS = fit_side(trd, VAR_A), fit_side(trd, VAR_B), fit_split_margin(trd, VAR_B)
        res["coef_B_side_frozen"] = dict(zip([f"own_{c}" for c in VAR_B] + [f"opp_{c}" for c in VAR_B], np.round(mB["b"][1:], 3).tolist()))
        for s in HOLD:
            te = (zall.season == s).to_numpy()
            res[f"holdout_{s}"] = evaluate(zall[te], base_all[te].reset_index(drop=True), spl_all[te].reset_index(drop=True), mA, mB, mS)
        zq = zp[zp.season == 2027].reset_index(drop=True)
        bq, sq = predict(zq)
        res["holdout_2027_pregame_tip"] = evaluate(zq, bq, sq, mA, mB, mS)
        out[seg] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--c15", required=True); ap.add_argument("--ps", required=True); ap.add_argument("--feat", required=True)
    ap.add_argument("--frozen", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    F = pd.read_csv(a.feat)
    F = F[F.season_type == 2] if "season_type" in F else F
    rep = {"E1_full_game": e1(a.c15, F)}
    print(json.dumps(rep["E1_full_game"], indent=1, default=float)[:4000], flush=True)
    rep["E2_E3_periods"] = e2e3(a.c15, a.ps, F, a.frozen)
    json.dump(rep, open(a.out, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()

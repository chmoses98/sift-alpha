"""NBA batch 13 (RESEARCH_ONLY): owner-authorized reconsideration of two inputs downgraded for INADEQUATE_HISTORICAL_COVERAGE (c_class_reconsideration.json). Built on the shared
derived engine (alpha_engine.derived.basketball: own-model expected margin / possessions / total, no market line anywhere) and the sift-data-vault NBA archive
(espn_nba_team_boxscores 2002-2027, espn_nba_schedules with linescores 2020-2027; ESPN-derived, UNRESOLVED_INTERNAL_ONLY).

Rows keyed (game_id, team), team perspective. B = basketball.features(team_games) gives exp_margin_pre (mu), exp_poss_pre (ep), exp_total_pre (et), sd_margin_pre (sd); each uses only
earlier games / earlier seasons. Season = ESPN season label (2025 = 2024-25). Fits are walk-forward by season: fit on seasons S-5..S-1, apply to season S.

nba.margin_heteroscedasticity (table team)
  sd_margin_pre as the engine (a + b sqrt(ep) + c |mu|, five earlier seasons, NaN until 3 seasons). z = (margin - mu) / sd on every team-row of the fit window (min 3 seasons).
  QZ_k = numpy linear quantile of z, k in (.10, .25, .50, .75, .90). Heavy favourites: fit rows with mu >= 8; QH_k = their z quantiles; mh_skew_fav_pre = population skewness of those z.
  mh_qK_pre = mu + sd QH_k if mu >= 8; mu - sd QH_(1-k) if mu <= -8; else mu + sd QZ_k.  PIT validation per |mu| bucket: pit_by_bucket() (reported, not a column).
nba.period_margin_pmf (table period; seasons whose fit window holds 5 linescore seasons, i.e. 2025+)
  Periods P: q1, q2, q3, q4 (regulation quarters), h1 = q1 + q2, h2 = q3 + q4 + all OT points. m_P / T_P = team-perspective period margin / total from the schedule linescores.
  Pair covariate: z2 = ((margin - mu) / sd)^2 per team-row (finite only); vr_team = (sum z2 + 20) / (n + 20) over the team's rows of season S-1 and earlier rows (strictly earlier date)
  of season S; pair = (vr_team + vr_opp) / 2.
  Fit rows: home rows of the window with a 4+ period linescore and finite mu, ep, et, pair. Means: b_P = sum(m mu) / sum(mu^2); a_P = sum(T et) / sum(et^2); mean = b_P mu (margin), a_P et (total).
  Discrete mixture pmf: P(y) = (1 - w) D(y; mean, s) + w D(y; mean, k s), D(y; m, s) = Phi((y + .5 - m)/s) - Phi((y - .5 - m)/s); s = s0 (ep/100)^t1 pair^g.
  Grid maximum likelihood (exact, deterministic): t1 in (0, .5, 1), g in (0, .5, 1), w in (0, .1, .2, .3), k in (1.5, 2, 3), s0 = s_ref 1.05^j, j = -10..10,
  s_ref = sqrt(mean r^2) / mean((ep/100)^t1 pair^g), r = y - mean; loglik = sum log(max(P, 1e-300)); loop order t1, g, w, k, j; a later point replaces only on strictly larger loglik.
  Columns per P: pm_P_mu_pre, pm_P_sd_pre (row s), pm_P_tie_pre = P(m_P = 0), pm_P_ge8_pre = P(m_P >= 8) = (1-w) Phi((mean-7.5)/s) + w Phi((mean-7.5)/(k s)); the same
  mixture fitted to T_P: pm_P_tot_mu_pre, pm_P_tot_sd_pre. (w, k) are season constants kept in PARAMS, not columns. pm_pace_tercile_pre = 1/2/3 by ep against the fit rows' ep tertiles (numpy linear quantiles 1/3, 2/3; ep <= q1 -> 1, <= q2 -> 2, else 3).
  pmf(mu, sd, w, k) gives the integer pmf on -25..25.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import ndtr

from ..derived import basketball as B
from ..derived import foundation_ext as _F
from .core import FeatureSpec

S = "NBA"
QS = (0.10, 0.25, 0.50, 0.75, 0.90)
HEAVY = 8.0
PER = ("q1", "q2", "q3", "q4", "h1", "h2")
PM_FIRST_FIT_SEASONS = 5
T1, GG, WW, KK, JJ = (0.0, 0.5, 1.0), (0.0, 0.5, 1.0), (0.0, 0.1, 0.2, 0.3), (1.5, 2.0, 3.0), range(-10, 11)
MH = ["sd_margin_pre"] + [f"mh_q{int(q * 100)}_pre" for q in QS] + ["mh_skew_fav_pre"]
PM = [f"pm_{p}_{c}_pre" for p in PER for c in ("mu", "sd", "tie", "ge8", "tot_mu", "tot_sd")] + ["pm_pace_tercile_pre"]
PARAMS: dict = {}   # (season, period, "margin" | "total") -> fitted (s0, t1, g, w, k) of the last compute(); w / k are season constants, so they are not row columns
BOX_CONTENT, SCHED_CONTENT = _F.BOX_CONTENT, _F.SCHED_CONTENT


def load_raw(root) -> dict:
    return _F.load_raw(root, S)


def disc(y, m, s):
    return ndtr((y + 0.5 - m) / s) - ndtr((y - 0.5 - m) / s)


def pmf(mu, sd, w, k, lo=-25, hi=25):
    y = np.arange(lo, hi + 1, dtype=float)
    return y, (1 - w) * disc(y, mu, sd) + w * disc(y, mu, k * sd)


def grid_mle(y, mean, ep, pair):
    r = y - mean; rms = np.sqrt(np.mean(r ** 2)); best = (-np.inf, None)
    for t1 in T1:
        for g in GG:
            base = (ep / 100.0) ** t1 * pair ** g; sref = rms / np.mean(base)
            for w in WW:
                for k in KK:
                    for j in JJ:
                        s = sref * 1.05 ** j * base
                        ll = float(np.sum(np.log(np.maximum((1 - w) * disc(y, mean, s) + w * disc(y, mean, k * s), 1e-300))))
                        if ll > best[0]:
                            best = (ll, (sref * 1.05 ** j, t1, g, w, k))
    return best[1]


def _periods(sched: pd.DataFrame) -> pd.DataFrame:
    s = sched.drop_duplicates("game_id").copy(); s["game_id"] = s.game_id.astype("int64")
    hl, al = s.home_linescores.map(B.parse_linescores), s.away_linescores.map(B.parse_linescores)
    ok = (hl.map(len) >= 4) & (al.map(len) >= 4)
    o = pd.DataFrame({"game_id": s.game_id[ok]})
    for side, L in (("h", hl[ok]), ("a", al[ok])):
        for i in range(4):
            o[f"{side}_q{i + 1}"] = L.map(lambda x, i=i: x[i]).to_numpy()
        o[f"{side}_ot"] = L.map(lambda x: float(sum(x[4:]))).to_numpy()
    return o


def _pair(f: pd.DataFrame) -> pd.Series:
    z2 = ((f.margin - f.exp_margin_pre) / f.sd_margin_pre) ** 2
    d = pd.DataFrame({"team": f.team, "season": f.season, "date": f.date, "z2": z2.where(np.isfinite(z2), 0.0), "n": np.isfinite(z2).astype(float)}, index=f.index)
    d = d.sort_values(["team", "date"], kind="mergesort")
    g = d.groupby(["team", "season"], sort=False)
    cz, cn = g.z2.cumsum() - d.z2, g.n.cumsum() - d.n
    tot = d.groupby(["team", "season"]).agg(z2=("z2", "sum"), n=("n", "sum"))
    prev = tot.reindex(list(zip(d.team, d.season - 1)))
    vr = (cz + prev.z2.fillna(0).to_numpy() + 20.0) / (cn + prev.n.fillna(0).to_numpy() + 20.0)
    return vr.reindex(f.index)


def compute(raw: dict) -> dict:
    t = B.team_games(raw, S); f = B.features(t, S)
    f = f.assign(margin=t.margin.to_numpy(), opp=t.opp.to_numpy(), home=t.home.to_numpy())
    mu, sd = f.exp_margin_pre, f.sd_margin_pre
    f["z"] = (f.margin - mu) / sd
    # ---- margin heteroscedasticity: quantile curves and heavy-favourite skew (walk-forward by season)
    for c in MH[1:]:
        f[c] = np.nan
    for Sn in sorted(f.season.unique()):
        tr = f[(f.season < Sn) & (f.season >= Sn - 5)]
        zz = tr.z[np.isfinite(tr.z)]
        if tr.season.nunique() < 3 or not len(zz):
            continue
        zh = tr.z[(tr.exp_margin_pre >= HEAVY) & np.isfinite(tr.z)].to_numpy()
        QZ, QH = np.quantile(zz.to_numpy(), QS), np.quantile(zh, QS)
        sk = float(np.mean((zh - zh.mean()) ** 3) / np.std(zh) ** 3)
        ix = f.index[f.season == Sn]; m_, s_ = mu.loc[ix].to_numpy(), sd.loc[ix].to_numpy()
        for i, q in enumerate(QS):
            f.loc[ix, f"mh_q{int(q * 100)}_pre"] = np.where(m_ >= HEAVY, m_ + s_ * QH[i], np.where(m_ <= -HEAVY, m_ - s_ * QH[len(QS) - 1 - i], m_ + s_ * QZ[i]))
        f.loc[ix, "mh_skew_fav_pre"] = sk
    team = f[["game_id", "team", "date", "season"] + MH].reset_index(drop=True)
    # ---- period pmf
    f["pair"] = _pair(f)
    op = f[["game_id", "team", "pair"]].rename(columns={"team": "opp", "pair": "opp_pair"})
    f = f.merge(op, on=["game_id", "opp"], how="left"); f["pair"] = (f.pair + f.opp_pair) / 2.0
    per = _periods(raw["sched"]); f = f.merge(per, on="game_id", how="left")
    H = f.home == 1
    for i in range(1, 5):
        own, opp_ = np.where(H, f[f"h_q{i}"], f[f"a_q{i}"]), np.where(H, f[f"a_q{i}"], f[f"h_q{i}"])
        f[f"m_q{i}"], f[f"T_q{i}"] = own - opp_, own + opp_
    oto, otp = np.where(H, f.h_ot, f.a_ot), np.where(H, f.a_ot, f.h_ot)
    f["m_h1"], f["T_h1"] = f.m_q1 + f.m_q2, f.T_q1 + f.T_q2
    f["m_h2"], f["T_h2"] = f.m_q3 + f.m_q4 + oto - otp, f.T_q3 + f.T_q4 + oto + otp
    f["has_ls"] = f.h_q1.notna()
    ok_cov = np.isfinite(f[["exp_margin_pre", "exp_poss_pre", "exp_total_pre", "pair"]]).all(axis=1)
    ls_seasons = sorted(f.season[f.has_ls].unique())
    rows = []
    for Sn in sorted(f.season.unique()):
        win = [x for x in ls_seasons if Sn - 5 <= x < Sn]
        if len(win) < PM_FIRST_FIT_SEASONS:
            continue
        tr = f[(f.season < Sn) & (f.season >= Sn - 5) & (f.home == 1) & f.has_ls & ok_cov]
        cur = f[f.season == Sn].copy()
        mu_t, ep_t, et_t, pr_t = (tr[c].to_numpy(float) for c in ("exp_margin_pre", "exp_poss_pre", "exp_total_pre", "pair"))
        mu_c, ep_c, et_c, pr_c = (cur[c].to_numpy(float) for c in ("exp_margin_pre", "exp_poss_pre", "exp_total_pre", "pair"))
        q1_, q2_ = np.quantile(ep_t, [1 / 3, 2 / 3])
        cur["pm_pace_tercile_pre"] = np.where(np.isnan(ep_c), np.nan, np.where(ep_c <= q1_, 1.0, np.where(ep_c <= q2_, 2.0, 3.0)))
        for p in PER:
            y_m, y_t = tr[f"m_{p}"].to_numpy(float), tr[f"T_{p}"].to_numpy(float)
            b = float(np.sum(y_m * mu_t) / np.sum(mu_t ** 2)); a = float(np.sum(y_t * et_t) / np.sum(et_t ** 2))
            s0, t1, g, w, k = grid_mle(y_m, b * mu_t, ep_t, pr_t)
            sc = s0 * (ep_c / 100.0) ** t1 * pr_c ** g
            PARAMS[(int(Sn), p, "margin")] = (s0, t1, g, w, k); m_ = b * mu_c
            cur[f"pm_{p}_mu_pre"], cur[f"pm_{p}_sd_pre"] = m_, sc
            cur[f"pm_{p}_tie_pre"] = (1 - w) * disc(0.0, m_, sc) + w * disc(0.0, m_, k * sc)
            cur[f"pm_{p}_ge8_pre"] = (1 - w) * ndtr((m_ - 7.5) / sc) + w * ndtr((m_ - 7.5) / (k * sc))
            s0, t1, g, w, k = grid_mle(y_t, a * et_t, ep_t, pr_t); PARAMS[(int(Sn), p, "total")] = (s0, t1, g, w, k)
            cur[f"pm_{p}_tot_mu_pre"], cur[f"pm_{p}_tot_sd_pre"] = a * et_c, s0 * (ep_c / 100.0) ** t1 * pr_c ** g
        rows.append(cur[["game_id", "team", "date", "season"] + PM])
    period = (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["game_id", "team", "date", "season"] + PM))
    return {"team": team.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True),
            "period": period.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def pit_by_bucket(team: pd.DataFrame, margin: pd.Series, mu: pd.Series) -> dict:
    """Share of realised margins at or below each reported quantile, by |own-model mean margin| bucket (validation; nominal = the quantile level)."""
    d = team.assign(margin=margin.to_numpy(), amu=mu.abs().to_numpy()).dropna(subset=MH[1:6] + ["margin"])
    out = {}
    for lo, hi in ((0, 4), (4, 8), (8, 12), (12, 99)):
        b = d[(d.amu >= lo) & (d.amu < hi)]
        out[f"{lo}-{hi}"] = {"n": int(len(b)), **{f"q{int(q * 100)}": round(float((b.margin <= b[f"mh_q{int(q * 100)}_pre"]).mean()), 4) for q in QS}}
    return out


def specs() -> list[FeatureSpec]:
    """nba.margin_heteroscedasticity only (table team); nba.period_margin_pmf lives in nba_pmf_ext13 (the replay checks one table per family)."""
    src = ["sift-data-vault:archives/NBA/espn_pbp_boxes_schedules/2002-2027/sportsdataverse/snapshot-20261116 (espn_nba_team_boxscores, espn_nba_schedules)"]
    return [FeatureSpec(S, "nba.margin_heteroscedasticity", "team", MH, "FULL",
                        "Own-model margin sd = a + b sqrt(expected possessions) + c |expected margin| (five earlier seasons, no lines), with walk-forward quantile curves (10/25/50/75/90) from "
                        "standardized residuals, heavy-favourite (|mu| >= 8) oriented quantiles and skewness; PIT validation by |mu| bucket",
                        ["sd regression on sqrt(possessions) and |mean margin|", "own predictions only", "five-season fit", "quantile curves (10/25/50/75/90)",
                         "skew parameter for heavy favourites", "PIT validation per bucket"], [], src)]


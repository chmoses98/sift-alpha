"""Phase 14 MLB challenger: one reproducible script.

  python -m research.phase14_mlb.run_phase14 --stage freeze   # dev fit (2022 burn-in, 2023-24 dev), validate 2025,
                                                              # writes frozen_params.json + results.json (dev/val)
  python -m research.phase14_mlb.run_phase14 --stage holdout  # requires frozen_params.json; scores 2026 ONCE,
                                                              # incl. paired comparison vs archived production
Raw data: vault postgame_feed_compact restored under --scratch (never committed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

from . import baselines as B
from . import engine as E
from . import metrics as M
from . import sim as S

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "frozen_params.json")
RESULTS = os.path.join(HERE, "results.json")
DEV, VAL, HOLD = (2023, 2024), (2025,), (2026,)
# rate hyper-parameters chosen by coordinate search on dev (2023-24) PA log-loss (see tune_rates); frozen here
RATE_PARAMS = {"tau": 480, "tau_lg": 300, "carry": 0.8, "k_pl": 600, "k_park": 10000, "k_def": 20000}
N_SIMS, BF_SD, SEED = 400, 4.5, 14
KR, KT, KK = 21, 31, 16          # pmf sizes: team runs, total, strikeouts
KH, KTB, KHR = 6, 13, 4           # batter hits, total bases, HR
THR = {"total": [8, 9, 10], "K": [5, 6, 7], "H": [1, 2], "TB": [2, 3], "HR": [1]}  # P(X >= t)


def load(scratch: str):
    ext = os.path.join(scratch, "ext")
    if not os.path.exists(os.path.join(ext, "pa.parquet")):
        from .extract import extract
        extract(scratch, ext)
    G = pd.read_parquet(os.path.join(ext, "games.parquet"))
    P = pd.read_parquet(os.path.join(ext, "pa.parquet"))
    SP = pd.read_parquet(os.path.join(ext, "sp.parquet"))
    BT = pd.read_parquet(os.path.join(ext, "bat.parquet"))
    for side in ("home", "away"):
        s = SP[SP.side == side].set_index("game_pk")
        G[f"{side}_sp_bf"] = s.BF.reindex(G.game_pk).values
        G[f"{side}_sp_k"] = s.K.reindex(G.game_pk).values
    G = G.dropna(subset=["home_sp_bf", "away_sp_bf"]).reset_index(drop=True)
    P = P[P.game_pk.isin(G.game_pk)].reset_index(drop=True)
    return G, P, SP, BT


def bats_lookup(G):
    out = {}
    for side in ("home", "away"):
        for o, b in zip(G[f"{side}_order"], G[f"bats_{side}"]):
            out.update(dict(zip(o, b)))
    return out


def tune_rates(G, P):
    """Coordinate search on dev PA log-loss (2022 burn-in, scored on 2023-24). Not run by default (slow-ish)."""
    g = G[G.season <= 2024].reset_index(drop=True)
    p = P[P.game_pk.isin(g.game_pk)].reset_index(drop=True)
    m = (p.date >= "2023-01-01").values
    y = p.ev.values[m]
    ll = lambda pp: -np.log(E.run(g, p, pp, want_game_inputs=False)[0][m, y]).mean()
    best = dict(E.DEFAULTS)
    bl = ll(best)
    grid = {"tau": [120, 240, 480, 960], "carry": [0.6, 0.8, 1.0], "k_mult_bat": [0.5, 1, 2], "k_mult_pit": [0.5, 1, 2],
            "k_pl": [100, 250, 600, 2000], "k_park": [1000, 3000, 10000], "tau_lg": [60, 120, 300],
            "k_def": [1e9, 20000, 5000]}
    for _ in range(2):
        for k, vals in grid.items():
            for v in vals:
                t = {**best, k: v}
                l_ = ll(t)
                if l_ < bl - 1e-6:
                    bl, best = l_, t
    return best, bl


def pmf_of(x, K):
    """Row-wise empirical pmf of integer samples x (n,S) clipped into K bins."""
    n = x.shape[0]
    out = np.zeros((n, K))
    xc = np.clip(x, 0, K - 1)
    np.add.at(out, (np.repeat(np.arange(n), x.shape[1]), xc.ravel()), 1)
    return out / x.shape[1]


def simulate_all(G, inputs, cells, cdf, extras, seasons, variant, chunk=400):
    rng = np.random.default_rng(SEED)
    T = G[G.season.isin(seasons)].reset_index(drop=True)
    acc = {k: [] for k in ("pwin", "mh", "ma", "ph", "pa", "pt", "medm", "kh", "ka", "bh", "ba")}
    for s0 in range(0, len(T), chunk):
        pks = T.game_pk.values[s0:s0 + chunk]
        res = {}
        for side in ("home", "away"):
            Psp = np.stack([inputs[pk][side][variant]["sp"] for pk in pks])
            Pbp = np.stack([inputs[pk][side][variant]["bp"] for pk in pks])
            mu = np.array([inputs[pk][side]["bf_mu"] for pk in pks])
            res[side] = S.simulate_offense(Psp, Pbp, mu, BF_SD, cells, cdf, N_SIMS, rng)
        h, a = S.combine_game(res["home"][0], res["away"][0], extras, rng)
        acc["pwin"].append((h > a).mean(1))
        acc["mh"].append(h.mean(1))
        acc["ma"].append(a.mean(1))
        acc["ph"].append(pmf_of(h, KR))
        acc["pa"].append(pmf_of(a, KR))
        acc["pt"].append(pmf_of(h + a, KT))
        acc["medm"].append(np.median(h - a, 1))
        acc["kh"].append(pmf_of(res["away"][1], KK))   # home starter Ks (faced by away offense)
        acc["ka"].append(pmf_of(res["home"][1], KK))
        for side, key in (("home", "bh"), ("away", "ba")):
            _, _, H, TB, HR = res[side]
            acc[key].append({"H": np.stack([pmf_of(H[:, :, j], KH) for j in range(9)], 1),
                             "TB": np.stack([pmf_of(TB[:, :, j], KTB) for j in range(9)], 1),
                             "HR": np.stack([pmf_of(HR[:, :, j], KHR) for j in range(9)], 1)})
    out = {k: np.concatenate(v) for k, v in acc.items() if k not in ("bh", "ba")}
    for key in ("bh", "ba"):
        out[key] = {s: np.concatenate([d[s] for d in acc[key]]) for s in ("H", "TB", "HR")}
    out["game_pk"] = T.game_pk.values
    return out


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_logistic(X, y, iters=60):
    X = np.c_[np.ones(len(X)), X]
    w = np.zeros(X.shape[1])
    w[1:] = 1.0
    for _ in range(iters):
        q = 1 / (1 + np.exp(-X @ w))
        H = X.T @ (X * (q * (1 - q))[:, None]) + 1e-6 * np.eye(X.shape[1])
        w = w + np.linalg.solve(H, X.T @ (y - q))
    return w.tolist()


def apply_logistic(w, X):
    X = np.c_[np.ones(len(X)), X]
    return 1 / (1 + np.exp(-X @ np.asarray(w)))


def pge(pmf, t):
    return pmf[:, t:].sum(1)


def build_frame(G, BT, inputs, sims, base):
    """Game-level and player-level evaluation frames for seasons present in sims."""
    games = G.set_index("game_pk").loc[sims["posted"]["game_pk"]].reset_index()
    gf = {"game_pk": games.game_pk.values, "season": games.season.values, "yh": games.home_runs.values,
          "ya": games.away_runs.values, "start": games.start_utc.values}
    gf = pd.DataFrame(gf)
    bidx = base["G"].set_index("game_pk").loc[gf.game_pk]
    gf["ridge_h"], gf["ridge_a"], gf["elo"] = bidx.ridge_h.values, bidx.ridge_a.values, bidx.elo.values
    # starter K rows
    kr = []
    for side, key in (("home", "kh"), ("away", "ka")):
        kr.append(pd.DataFrame({"game_pk": gf.game_pk, "season": gf.season, "side": side,
                                "player": games[f"{side}_sp"].values, "y": games[f"{side}_sp_k"].values,
                                "row": np.arange(len(gf)), "key": key}))
    kr = pd.concat(kr, ignore_index=True)
    # batter rows: starters whose (variant) predicted slot is known
    bt = BT[BT.game_pk.isin(gf.game_pk)].copy()
    rowmap = pd.Series(np.arange(len(gf)), index=gf.game_pk)
    bt["row"] = rowmap.loc[bt.game_pk].values
    bt["season"] = gf.season.values[bt.row.values]
    for v in ("posted", "typical"):
        slot = []
        for pk, side, pid in zip(bt.game_pk.values, bt.side.values, bt.player.values):
            lu = inputs[pk][side][v]["lineup"]
            slot.append(lu.index(pid) if pid in lu else -1)
        bt[f"slot_{v}"] = slot
    return gf, kr, bt


def evaluate(gf, kr, bt, sims, cal, base, seasons, prod=None):
    """All metrics for seasons; returns dict. Paired comparisons vs the strongest simple baseline."""
    res = {}
    gm = gf.season.isin(seasons).values
    g = gf[gm]
    yh, ya = g.yh.values, g.ya.values
    yw = (yh > ya).astype(float)
    cl = g.game_pk.values
    # ---- baselines (game) ----
    r = cal["ridge_nb_r"]
    bph, bpa = M.nb_pmf(g.ridge_h, r, KR), M.nb_pmf(g.ridge_a, r, KR)
    bpt = M.nb_pmf(g.ridge_h + g.ridge_a, cal["ridge_nb_r_tot"], KT)
    bw_raw = (bph[:, :, None] * bpa[:, None, :])
    ii = np.arange(KR)
    pw_r = (bw_raw * (ii[:, None] > ii[None, :])).sum((1, 2)) + 0.5 * (bw_raw * (ii[:, None] == ii[None, :])).sum((1, 2))
    base_w = {"elo": g.elo.values, "ridge": apply_logistic(cal["ridge_win"], logit(pw_r)[:, None])}
    for v in ("posted", "typical"):
        sv = sims[v]
        chal = apply_logistic(cal[f"{v}_win"], logit(sv["pwin"][gm])[:, None])
        stack = apply_logistic(cal[f"{v}_stack"], np.c_[logit(sv["pwin"][gm]), logit(g.elo.values)])
        out = {}
        probs = {"challenger_raw": sv["pwin"][gm], "challenger_cal": chal, "challenger_stack_elo": stack, **base_w}
        out["win"] = {k: {"brier": float(M.brier(p, yw).mean()), "logloss": float(M.logloss(p, yw).mean()),
                          "calib_slope": M.calib_slope(p, yw)} for k, p in probs.items()}
        best_b = min(base_w, key=lambda k: M.brier(base_w[k], yw).mean())
        out["win"]["paired_vs_" + best_b] = {
            k: {"brier": M.paired_ci(M.brier(base_w[best_b], yw), M.brier(probs[k], yw), cl),
                "logloss": M.paired_ci(M.logloss(base_w[best_b], yw), M.logloss(probs[k], yw), cl)}
            for k in ("challenger_cal", "challenger_stack_elo")}
        # ---- runs / total / margin ----
        cr = {}
        for name, ch_pmf, b_pmf, y in (("home_runs", sv["ph"][gm], bph, yh), ("away_runs", sv["pa"][gm], bpa, ya),
                                       ("total", sv["pt"][gm], bpt, yh + ya)):
            a_l, c_l = M.crps_pmf(b_pmf, y), M.crps_pmf(ch_pmf, y)
            am, cm = np.abs(M.pmf_median(b_pmf) - y), np.abs(M.pmf_median(ch_pmf) - y)
            cr[name] = {"crps_ridge": float(a_l.mean()), "crps_challenger": float(c_l.mean()),
                        "mae_ridge": float(am.mean()), "mae_challenger": float(cm.mean()),
                        "paired_crps": M.paired_ci(a_l, c_l, cl), "paired_mae": M.paired_ci(am, cm, cl)}
            if name == "total":
                for t in THR["total"]:
                    yt = (y >= t).astype(float)
                    cr[name][f"over{t - 0.5}"] = {
                        "brier_ridge": float(M.brier(pge(b_pmf, t), yt).mean()),
                        "brier_challenger": float(M.brier(pge(ch_pmf, t), yt).mean()),
                        "slope_challenger": M.calib_slope(pge(ch_pmf, t), yt),
                        "paired": M.paired_ci(M.brier(pge(b_pmf, t), yt), M.brier(pge(ch_pmf, t), yt), cl)}
        bm = np.abs((g.ridge_h - g.ridge_a).values - (yh - ya))
        cm = np.abs(sv["medm"][gm] - (yh - ya))
        cr["margin"] = {"mae_ridge": float(bm.mean()), "mae_challenger": float(cm.mean()),
                        "paired_mae": M.paired_ci(bm, cm, cl)}
        out["runs"] = cr
        # ---- pitcher strikeouts ----
        k = kr[kr.season.isin(seasons) & kr.y.notna()]
        rowsel = k.row.values
        ch = np.where((k.key == "kh").values[:, None], sv["kh"][rowsel], sv["ka"][rowsel])
        bmu = base["K"].loc[list(zip(k.game_pk, k.player))].values
        bp = M.pois_pmf(bmu, KK)
        y = k.y.values.astype(int)
        out["pitcher_K"] = {"n": int(len(k)), "mae_seasonavg_mean": float(np.abs(bmu - y).mean()),
                            "mae_seasonavg": float(np.abs(M.pmf_median(bp) - y).mean()),
                            "mae_challenger": float(np.abs(M.pmf_median(ch) - y).mean()),
                            "crps_seasonavg": float(M.crps_pmf(bp, y).mean()),
                            "crps_challenger": float(M.crps_pmf(ch, y).mean()),
                            "paired_crps": M.paired_ci(M.crps_pmf(bp, y), M.crps_pmf(ch, y), k.game_pk.values),
                            "paired_mae": M.paired_ci(np.abs(M.pmf_median(bp) - y), np.abs(M.pmf_median(ch) - y),
                                                      k.game_pk.values)}
        for t in THR["K"]:
            yt = (y >= t).astype(float)
            out["pitcher_K"][f"over{t - 0.5}"] = {
                "brier_seasonavg": float(M.brier(pge(bp, t), yt).mean()),
                "brier_challenger": float(M.brier(pge(ch, t), yt).mean()),
                "slope_challenger": M.calib_slope(pge(ch, t), yt),
                "paired": M.paired_ci(M.brier(pge(bp, t), yt), M.brier(pge(ch, t), yt), k.game_pk.values)}
        # ---- batters ----
        b = bt[bt.season.isin(seasons) & (bt[f"slot_{v}"] >= 0)]
        out["batters"] = {"n": int(len(b))}
        for stat, K_ in (("H", KH), ("TB", KTB), ("HR", KHR)):
            home = (b.side == "home").values[:, None]
            ph_ = sv["bh"][stat][b.row.values, b[f"slot_{v}"].values]
            pa_ = sv["ba"][stat][b.row.values, b[f"slot_{v}"].values]
            ch = np.where(home, ph_, pa_)
            bmu = base[stat].loc[list(zip(b.game_pk, b.player))].values
            bp = M.pois_pmf(bmu, K_)
            y = b[stat].values.astype(int)
            o = {"crps_seasonavg": float(M.crps_pmf(bp, y).mean()), "crps_challenger": float(M.crps_pmf(ch, y).mean()),
                 "paired_crps": M.paired_ci(M.crps_pmf(bp, y), M.crps_pmf(ch, y), b.game_pk.values),
                 "mean_pred_challenger": float((ch * np.arange(K_)).sum(1).mean()), "mean_actual": float(y.mean())}
            for t in THR[stat]:
                yt = (y >= t).astype(float)
                o[f"over{t - 0.5}"] = {"brier_seasonavg": float(M.brier(pge(bp, t), yt).mean()),
                                       "brier_challenger": float(M.brier(pge(ch, t), yt).mean()),
                                       "slope_challenger": M.calib_slope(pge(ch, t), yt),
                                       "paired": M.paired_ci(M.brier(pge(bp, t), yt), M.brier(pge(ch, t), yt),
                                                             b.game_pk.values)}
            out["batters"][stat] = o
        res[v] = out
    res["n_games"] = int(gm.sum())
    return res


def compare_production(gf, kr, bt, sims, cal, prod, G):
    """2026 holdout: identical-game paired comparison vs archived production model outputs."""
    out = {}
    v = sims["posted"]
    g = gf[gf.season == 2026].reset_index(drop=True)
    row = pd.Series(np.arange(len(gf)), index=gf.game_pk)
    start = pd.Series(G.start_utc.values, index=G.game_pk)
    # team runs (mean forecasts)
    t = prod["team"].merge(g[["game_pk", "yh", "ya", "start"]], on="game_pk")
    if len(t):
        t["pregame"] = pd.to_datetime(t.prod_ts) < pd.to_datetime(t.start)
        for subset, tt in (("all", t), ("pregame_timestamped", t[t.pregame])):
            if not len(tt):
                continue
            ri = row.loc[tt.game_pk].values
            mh, ma = v["mh"][ri], v["ma"][ri]
            o = {"n_games": int(len(tt))}
            for name, pp, cc, y in (("home_runs", tt.prod_home, mh, tt.yh), ("away_runs", tt.prod_away, ma, tt.ya),
                                    ("total", tt.prod_home + tt.prod_away, mh + ma, tt.yh + tt.ya),
                                    ("margin", tt.prod_home - tt.prod_away, mh - ma, tt.yh - tt.ya)):
                a_, c_ = np.abs(pp.values - y.values), np.abs(cc - y.values)
                o[name] = {"mae_production": float(a_.mean()), "mae_challenger": float(c_.mean()),
                           "paired": M.paired_ci(a_, c_, tt.game_pk.values)}
            out[f"team_runs_{subset}"] = o
    w = prod["win"].merge(g[["game_pk", "yh", "ya", "start", "elo"]], on="game_pk")
    if len(w):
        w["pregame"] = pd.to_datetime(w.prod_ts) < pd.to_datetime(w.start)
        for subset, ww in (("all", w), ("pregame_timestamped", w[w.pregame])):
            if not len(ww):
                continue
            ri = row.loc[ww.game_pk].values
            y = (ww.yh > ww.ya).values.astype(float)
            ch = apply_logistic(cal["posted_win"], logit(v["pwin"][ri])[:, None])
            pp = ww.prod_pwin.values
            out[f"win_{subset}"] = {"n_games": int(len(ww)), "brier_production": float(M.brier(pp, y).mean()),
                                    "brier_challenger": float(M.brier(ch, y).mean()),
                                    "logloss_production": float(M.logloss(pp, y).mean()),
                                    "logloss_challenger": float(M.logloss(ch, y).mean()),
                                    "slope_production": M.calib_slope(pp, y), "slope_challenger": M.calib_slope(ch, y),
                                    "paired_brier": M.paired_ci(M.brier(pp, y), M.brier(ch, y), ww.game_pk.values),
                                    "paired_logloss": M.paired_ci(M.logloss(pp, y), M.logloss(ch, y),
                                                                  ww.game_pk.values)}
    h = prod["hitters"]
    if len(h):
        h = h[h.game_pk.isin(g.game_pk)].copy()
        h["start"] = start.loc[h.game_pk].values
        h = h[pd.to_datetime(h.prod_ts) < pd.to_datetime(h.start)]
        h = h.sort_values("prod_ts").drop_duplicates(["game_pk", "player", "stat", "thr"], keep="last")
        b = bt[bt.season == 2026]
        h = h.merge(b[["game_pk", "player", "side", "row", "slot_posted", "H", "TB"]], on=["game_pk", "player"])
        h = h[h.slot_posted >= 0]
        o = {}
        for stat in ("H", "TB"):
            hs = h[h.stat == stat]
            if not len(hs):
                continue
            pm = np.where((hs.side == "home").values[:, None], v["bh"][stat][hs.row.values, hs.slot_posted.values],
                          v["ba"][stat][hs.row.values, hs.slot_posted.values])
            ch = np.array([pm[i, t:].sum() for i, t in enumerate(hs.thr.values)])
            y = (hs[stat].values >= hs.thr.values).astype(float)
            o[stat] = {"n": int(len(hs)), "brier_production": float(M.brier(hs.prod_p.values, y).mean()),
                       "brier_challenger": float(M.brier(ch, y).mean()),
                       "paired": M.paired_ci(M.brier(hs.prod_p.values, y), M.brier(ch, y), hs.game_pk.values)}
        out["hitter_props_pregame"] = o
    p = prod["pitchers"]
    if len(p):
        p = p[p.game_pk.isin(g.game_pk)].copy()
        p["start"] = start.loc[p.game_pk].values
        p = p[pd.to_datetime(p.prod_ts) < pd.to_datetime(p.start)]
        p = p.sort_values("prod_ts").drop_duplicates(["game_pk", "player"], keep="last")
        k = kr[kr.season == 2026].merge(p, on=["game_pk", "player"])
        k = k[k.y.notna()]
        if len(k):
            ch = np.where((k.key == "kh").values[:, None], v["kh"][k.row.values], v["ka"][k.row.values])
            y = k.y.values
            cmean = (ch * np.arange(KK)).sum(1)
            o = {"n": int(len(k)), "mae_production_mean": float(np.abs(k.prod_mean - y).mean()),
                 "mae_challenger_mean": float(np.abs(cmean - y).mean()),
                 "paired_mae": M.paired_ci(np.abs(k.prod_mean.values - y), np.abs(cmean - y), k.game_pk.values)}
            for t in (5, 6, 7):
                pp = np.array([lad.get(t, np.nan) for lad in k.prod_ladder])
                yt = (y >= t).astype(float)
                o[f"over{t - 0.5}"] = {"brier_production": float(M.brier(pp, yt).mean()),
                                       "brier_challenger": float(M.brier(pge(ch, t), yt).mean())}
            out["pitcher_K_pregame"] = o
    return out


def baselines(G, SP, BT):
    g = G.copy()
    g["ridge_h"], g["ridge_a"] = B.ridge_ratings(g)
    g["elo"] = B.elo(g)
    sp = SP.merge(G[["game_pk", "season"]], on="game_pk").sort_values(["date", "game_pk"]).reset_index(drop=True)
    sp["mu"] = B.season_avg(sp, "K")
    bt = BT.merge(G[["game_pk", "season"]], on="game_pk").sort_values(["date", "game_pk"]).reset_index(drop=True)
    out = {"G": g, "K": sp.set_index(["game_pk", "player"]).mu}
    for stat in ("H", "TB", "HR"):
        bt[f"mu_{stat}"] = B.season_avg(bt, stat)
        out[stat] = bt.set_index(["game_pk", "player"])[f"mu_{stat}"]
    out["K"] = out["K"][~out["K"].index.duplicated()]
    for stat in ("H", "TB", "HR"):
        out[stat] = out[stat][~out[stat].index.duplicated()]
    return out


def calibrate(gf, sims, dev):
    """Fit on DEV seasons only: logistic recalibration of win probs; NB dispersions for ridge."""
    m = gf.season.isin(dev).values
    g = gf[m]
    y = (g.yh > g.ya).values.astype(float)
    cal = {}
    for v in ("posted", "typical"):
        p = sims[v]["pwin"][m]
        cal[f"{v}_win"] = fit_logistic(logit(p)[:, None], y)
        cal[f"{v}_stack"] = fit_logistic(np.c_[logit(p), logit(g.elo.values)], y)
    best = None
    for r in (2, 3, 4, 5, 6, 8, 10, 15, 25):
        l_ = M.crps_pmf(M.nb_pmf(g.ridge_h, r, KR), g.yh).mean() + M.crps_pmf(M.nb_pmf(g.ridge_a, r, KR), g.ya).mean()
        best = (l_, r) if best is None or l_ < best[0] else best
    cal["ridge_nb_r"] = best[1]
    best = None
    for r in (3, 5, 8, 10, 15, 20, 30, 50):
        l_ = M.crps_pmf(M.nb_pmf(g.ridge_h + g.ridge_a, r, KT), g.yh + g.ya).mean()
        best = (l_, r) if best is None or l_ < best[0] else best
    cal["ridge_nb_r_tot"] = best[1]
    r = cal["ridge_nb_r"]
    bph, bpa = M.nb_pmf(g.ridge_h, r, KR), M.nb_pmf(g.ridge_a, r, KR)
    ii = np.arange(KR)
    j = bph[:, :, None] * bpa[:, None, :]
    pw = (j * (ii[:, None] > ii[None, :])).sum((1, 2)) + 0.5 * (j * (ii[:, None] == ii[None, :])).sum((1, 2))
    cal["ridge_win"] = fit_logistic(logit(pw)[:, None], y)
    return cal


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["freeze", "holdout"], required=True)
    ap.add_argument("--scratch", default="/tmp/mlb_work")
    ap.add_argument("--prod-repo", default="/home/user/edge-finder-api")
    ap.add_argument("--tune", action="store_true")
    a = ap.parse_args(argv)
    G, P, SP, BT = load(a.scratch)
    rate = RATE_PARAMS
    if a.stage == "holdout":
        fz = json.load(open(FROZEN))
        rate = fz["rate_params"]
    elif a.tune:
        rate, _ = tune_rates(G, P)
    cache = os.path.join(a.scratch, "phase14_sims.npz")
    _, inputs, _ = E.run(G, P, rate, want_pa_probs=False, bats_lookup=bats_lookup(G))
    dev_pa = P[P.date < "2025-01-01"]
    cells, cdf = S.build_transitions(dev_pa)
    extras = S.build_extras(dev_pa, G)
    seasons = DEV + VAL + (HOLD if a.stage == "holdout" else ())
    sims = {v: simulate_all(G, inputs, cells, cdf, extras, seasons, v) for v in ("posted", "typical")}
    base = baselines(G, SP, BT)
    gf, kr, bt = build_frame(G, BT, inputs, sims, base)
    if a.stage == "freeze":
        cal = calibrate(gf, sims, DEV)
        frozen = {"rate_params": rate, "sim": {"n_sims": N_SIMS, "bf_sd": BF_SD, "seed": SEED,
                                               "transitions_from": "2022-2024 PAs innings 1-9"},
                  "calibration": cal, "baselines": {"ridge": {"tau": 150, "lam": 30, "carry": 0.7},
                                                    "elo": {"K": 4, "hfa": 24, "revert": 1 / 3}},
                  "splits": {"burn_in": 2022, "dev": list(DEV), "validate": list(VAL), "holdout": list(HOLD)}}
        blob = json.dumps(frozen, sort_keys=True)
        frozen["sha256"] = hashlib.sha256(blob.encode()).hexdigest()
        json.dump(frozen, open(FROZEN, "w"), indent=1)
        results = {"dev_2023_2024": evaluate(gf, kr, bt, sims, cal, base, DEV),
                   "validate_2025": evaluate(gf, kr, bt, sims, cal, base, VAL)}
    else:
        cal = fz["calibration"]
        results = json.load(open(RESULTS))
        if "holdout_2026" in results:
            sys.exit("holdout already scored; refusing to re-score")
        prod = __import__("research.phase14_mlb.prod", fromlist=["load"]).load(a.prod_repo)
        results["holdout_2026"] = evaluate(gf, kr, bt, sims, cal, base, HOLD)
        results["holdout_2026"]["frozen_sha256"] = fz["sha256"]
        results["production_vs_challenger_2026"] = compare_production(gf, kr, bt, sims, cal, prod, G)
    json.dump(results, open(RESULTS, "w"), indent=1, default=float)
    print(json.dumps({k: (v.get("posted", {}).get("win") if isinstance(v, dict) else v) for k, v in results.items()},
                     indent=1, default=float)[:4000])


if __name__ == "__main__":
    main()

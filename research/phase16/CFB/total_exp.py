"""Phase 16 bounded experiment: full-game TOTAL over-projection of the #307/#308 challenger (research only).

    CFB_WORK=/tmp/cfb_work python total_exp.py RESEARCH_DIR P15EVAL_DIR

RESEARCH_DIR = research/cfb_challenger of cfb-edge-finder @ 7ebddfc6 (branch claude/sift-phase-15-sports-forecasting-rz966p).
Inputs in CFB_WORK: team_games.parquet, feat_s<season>.parquet (feats.py), prod_2026_ext.parquet (production 0.5.0
extension, challenger/production.build_2026), 2014-2026/ (vault CFBD cache).
Dev = 2016-2024 excl. 2020 (challenger totals out-of-season = leave-one-season-out layer refits); holdout = 2025 + 2026
FBS-vs-FBS games with a production forecast, scored ONCE after every choice below was fixed on dev.
Ladder = 28 half-point strikes floor(mu_challenger) - 13.5 ... + 13.5 per game (identical rows for every model).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R, PEV = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(R), str(R / "phase15"), str(PEV)]
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import p15eval as PE  # noqa: E402
import run_challenger as RC  # noqa: E402
from challenger import model as M  # noqa: E402

WORK = Path(os.environ.get("CFB_WORK", "/tmp/cfb_work"))
HERE = Path(__file__).resolve().parent
DEV = [2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024]
HOLD = [2025, 2026]
FZ = json.loads((R / "phase15" / "frozen_p15.json").read_text())
K_GRID = [10, 25, 50, 100, 200, 400, 1e9]       # shrinkage (games) of the in-season residual mean; 1e9 = no recentring
J = np.arange(-14, 14) + 0.5


def load():
    tg = pd.read_parquet(WORK / "team_games.parquet")
    games = M.games_table(tg)
    F = pd.concat([pd.read_parquet(WORK / f"feat_s{s}.parquet") for s in DEV + HOLD])
    g = games[(games.home_div == "fbs") & (games.away_div == "fbs") & games.season.isin(DEV + HOLD)].merge(F, on="game_id")
    g["y_t"], g["y_m"] = g.home_pts + g.away_pts, g.home_pts - g.away_pts
    g["navg"] = (g.n_h + g.n_a) / 2
    # challenger means: dev = leave-one-season-out layer (honest), holdout = frozen layer (fit on DEV)
    parts = []
    for s in DEV:
        tr = g[g.season.isin([x for x in DEV if x != s])]
        c = M.fit_layer(tr, tr.y_m.to_numpy(), tr.y_t.to_numpy(), 1.0, 3.0)
        parts.append(M.predict(c, g[g.season == s]))
    parts.append(M.predict(FZ["fg"]["layer"], g[g.season.isin(HOLD)]))
    g = g.merge(pd.concat(parts), on="game_id")
    prod = RC.production_table(games)[["game_id", "prod_margin", "prod_total"]]
    hist = g.merge(prod, on="game_id", how="left")
    hist = hist[hist.season.isin(DEV) | hist.prod_total.notna()].reset_index(drop=True)
    sig = FZ["prod_pack"]
    hist["sd_t_ch"] = np.exp(FZ["fg"]["sigma"]["total"]["g0"] + FZ["fg"]["sigma"]["total"]["g1"] * 3 / (3 + hist.navg))
    hist["sd_t_prod"] = sig["sd_total_const"]
    return hist.sort_values(["date", "game_id"]).reset_index(drop=True)


def recentre(d: pd.DataFrame, k0: float) -> np.ndarray:
    """Walk-forward offset: shrunk mean of (actual - challenger) over same-season FBS games dated strictly before."""
    off = np.zeros(len(d))
    for s, q in d.groupby("season"):
        r = (q.y_t - q.ch_total).to_numpy()
        dates = q.date.to_numpy()
        ud = np.unique(dates)
        cs = {}
        for x in ud:
            m = dates < x
            cs[x] = r[m].sum() / (m.sum() + k0)
        off[q.index] = [cs[x] for x in dates]
    return off


def ladder(d, mu, cdf_over):
    """p(total > k) for k in floor(mu_ch) + J; cdf_over(mu, k) vectorised. Returns p, y, game ids (rows)."""
    k = np.floor(d.ch_total.to_numpy())[:, None] + J[None, :]
    p = cdf_over(np.asarray(mu)[:, None], k)
    y = (d.y_t.to_numpy()[:, None] > k).astype(float)
    g = np.repeat(d.game_id.to_numpy(), len(J))
    return np.clip(p.ravel(), 1e-6, 1 - 1e-6), y.ravel(), g


def normal_over(sd):
    from scipy.stats import norm
    sd = np.asarray(sd)[:, None]
    # discretised: integer total T > k (k half-integer) under N(mu, sd) rounded to integers = P(N > k)
    return lambda mu, k: norm.sf((k - mu) / sd)


def empirical_over(resid):
    r = np.sort(np.asarray(resid))
    return lambda mu, k: 1.0 - np.searchsorted(r, k - mu, side="right") / len(r)


def scores(d, mu, over):
    p, y, g = ladder(d, mu, over)
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    return {"ae": np.abs(d.y_t.to_numpy() - mu), "se": (d.y_t.to_numpy() - mu) ** 2, "ll": ll, "br": (p - y) ** 2,
            "p": p, "y": y, "g": g}


def summ(S, gids):
    return {"total_mae": PE.cluster_ci(S["ae"], gids, n_boot=1000)[0], "total_rmse": float(np.sqrt(S["se"].mean())),
            "ladder_logloss": float(S["ll"].mean()), "ladder_brier": float(S["br"].mean()),
            "cal_slope": round(PE.calibration_slope(S["p"], S["y"]), 3), "cal_bias": round(float(np.mean(S["p"] - S["y"])), 4),
            "p_over_at_mean_obs": None}


def delta(A, B, gids):
    return {"total_mae": PE.paired_delta(A["ae"], B["ae"], gids), "total_mse": PE.paired_delta(A["se"], B["se"], gids),
            "ladder_logloss": PE.paired_delta(A["ll"], B["ll"], A["g"]), "ladder_brier": PE.paired_delta(A["br"], B["br"], A["g"]),
            "cal_bias": PE.paired_delta(A["p"] - A["y"], B["p"] - B["y"], A["g"])}


def diagnose(d):
    r = (d.y_t - d.ch_total)
    out = {"n": int(len(d)), "mean_resid": round(float(r.mean()), 3), "median_resid": round(float(r.median()), 3),
           "skew": round(float(((r - r.mean()) ** 3).mean() / r.std() ** 3), 3), "sd": round(float(r.std()), 3),
           "by_season": {str(s): round(float(x), 2) for s, x in r.groupby(d.season).mean().items()}}
    out["by_phase"] = {k: round(float(r[m].mean()), 2) for k, m in
                       (("navg<3", d.navg < 3), ("3-7", (d.navg >= 3) & (d.navg < 7)), (">=7", d.navg >= 7),
                        ("postseason", d.postseason))}
    q = pd.qcut(d.ch_total, 3, labels=["low", "mid", "high"])
    out["by_pred_total_tercile"] = {str(k): round(float(x), 2) for k, x in r.groupby(q, observed=True).mean().items()}
    pace = pd.qcut(d.plays_h + d.plays_a, 3, labels=["slow", "mid", "fast"])
    out["by_pregame_pace_tercile"] = {str(k): round(float(x), 2) for k, x in r.groupby(pace, observed=True).mean().items()}
    blow = d.y_m.abs() >= 28                         # outcome-defined, diagnostic only (garbage-time exposure)
    out["blowout_ge28_vs_rest"] = [round(float(r[blow].mean()), 2), round(float(r[~blow].mean()), 2), round(float(blow.mean()), 3)]
    out["p_over_at_challenger_mean_obs"] = round(float((d.y_t > d.ch_total).mean()), 3)
    return out


def main():
    d = load()
    dev, hold = d[d.season.isin(DEV)].reset_index(drop=True), d[d.season.isin(HOLD)].reset_index(drop=True)
    res = {"cfb_research_commit": "7ebddfc6e3e07c6840288ff7e658df68b0301134", "dev_seasons": DEV, "holdout_seasons": HOLD,
           "diagnosis": {"dev_oof": diagnose(dev), "holdout": diagnose(hold)}}
    # ---- choose k0 on dev only (ladder log loss with the challenger normal shape)
    grid = {}
    for k0 in K_GRID:
        mu = dev.ch_total + recentre(dev, k0)
        grid[str(k0)] = float(scores(dev, mu, normal_over(dev.sd_t_ch))["ll"].mean())
    k0 = float(min(grid, key=grid.get))
    res["dev_k0_grid_logloss"], res["k0"] = grid, k0
    dev_off = recentre(dev, k0)
    resid_dev = (dev.y_t - dev.ch_total).to_numpy()
    # F3: linear shrinkage of the challenger total toward the league mean, fitted on dev out-of-season predictions
    b, a = np.polyfit(dev.ch_total.to_numpy(), dev.y_t.to_numpy(), 1)
    res["shrink_fit_dev"] = {"a": float(a), "b": float(b)}
    resid_dev_sh = (dev.y_t - (a + b * dev.ch_total)).to_numpy()
    models = {
        "prod_0.5.0": lambda q, off: (q.prod_total.to_numpy(), normal_over(q.sd_t_prod)),
        "challenger_p307_p308": lambda q, off: (q.ch_total.to_numpy(), normal_over(q.sd_t_ch)),
        "F1_recentre": lambda q, off: (q.ch_total.to_numpy() + off, normal_over(q.sd_t_ch)),
        "F2_empirical_shape": lambda q, off: (q.ch_total.to_numpy(), empirical_over(resid_dev)),
        "F3_shrink+empirical": lambda q, off: (a + b * q.ch_total.to_numpy(), empirical_over(resid_dev_sh)),
        "F1_recentre_k400_NOT_SELECTED": lambda q, off: (q.ch_total.to_numpy() + recentre(q, 400.0),
                                                         normal_over(q.sd_t_ch)),
    }
    for name, q in (("dev", dev[dev.prod_total.notna()].reset_index(drop=True)), ("holdout", hold)):
        off = recentre(q, k0) if name == "holdout" else dev_off[dev.prod_total.notna().to_numpy()]
        S = {m: scores(q, *f(q, off)) for m, f in models.items()}
        gids = q.game_id.to_numpy()
        res[name] = {"n_games": int(len(q)), "models": {m: summ(s, gids) for m, s in S.items()},
                     "vs_prod": {m: delta(S[m], S["prod_0.5.0"], gids) for m in S if m != "prod_0.5.0"},
                     "vs_challenger": {m: delta(S[m], S["challenger_p307_p308"], gids) for m in S if m.startswith("F")}}
    (HERE / "results_total.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res[k] for k in ("diagnosis", "k0", "dev_k0_grid_logloss")}, indent=1))
    for name in ("dev", "holdout"):
        print(name, res[name]["n_games"])
        for m, v in res[name]["models"].items():
            print(f"  {m:24s}", {k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items() if x is not None})
        for m, v in res[name]["vs_challenger"].items():
            print("  vs ch", m, {k: x for k, x in v.items()})
        for m, v in res[name]["vs_prod"].items():
            print("  vs prod", m, {k: x for k, x in v.items()})


if __name__ == "__main__":
    main()

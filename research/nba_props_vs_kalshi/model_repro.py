"""Stage 1: reproduce the frozen NBA Projection Foundation holdout configuration and export 2025-26 pmfs.

Runs the pf package from a COPY of research/projection_foundation (WORK/repo/...), so its .cache writes stay in WORK.
Box data: sportsdataverse/hoopR mirror restored from sift-data-vault (no network: PF_NBA_OFFLINE=1).

Outputs (WORK/out/):
  pmf_<family>.npz       2025-26 played player-games: keys game_id, pid, P (n x K pmf over 0..K-1), y, minutes, date
  rows_2026.parquet      identity columns for those rows (game_id, pid, name, team, opp, date, tip_utc, stats)
  repro_check.json       recomputed vs frozen: best model, distribution, parameters, holdout CRPS / MAE
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
PF = WORK / "repo" / "research" / "projection_foundation"
OUT = WORK / "out"
os.environ["PF_NBA_OFFLINE"] = "1"
sys.path.insert(0, str(PF))

FAMS = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m"}


def _close(a, b, tol=1e-4):
    if isinstance(a, dict) and isinstance(b, dict):
        return all(_close(a.get(k), b.get(k), tol) for k in set(a) | set(b))
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float, np.floating)) and isinstance(b, (int, float, np.floating)):
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    return a == b


def main() -> int:
    from nba import backtest as B, pipeline
    from pf_core import metrics
    OUT.mkdir(exist_ok=True)
    frozen = json.loads((PF / "results" / "frozen_params.json").read_text())
    raw = json.loads((PF / "results" / "backtest_raw.json").read_text())
    ctx = pipeline.run_compute(force=False)
    f, best_min = ctx["f"], ctx["best_min"]
    f = B.attach(f, B.load_incumbent())          # no incumbent cache in WORK -> NaN incumbent columns (unused here)
    check = {"best_minutes_model": {"recomputed": best_min, "frozen": frozen["best_minutes_model"]},
             "minutes_params_match": _close(ctx["mprm"], frozen["minutes_params"]), "families": {}}
    S26 = None
    for fam, col in FAMS.items():
        sp, sprm = ctx["stats"][col]
        r = B.eval_family(f, fam, sp, None, best_min)
        fz = frozen["families"][fam]
        P = r["P"]
        y = P[col].to_numpy()
        hold = np.where((P["split"] == "holdout").to_numpy())[0]
        d_h = r["dist_for"](fz["dist"], hold)
        crps_h = float(np.mean(d_h.crps(y[hold])))
        mae_h = float(np.mean(np.abs(P[f"s_{fz['best']}"].to_numpy()[hold] - y[hold])))
        dm = metrics.dist_metrics(y[hold], d_h)
        raw_row = next(rw for rw in raw[fam]["rows"] if rw["split"] == "holdout" and rw["verdict"] == "best")
        c = {"best": {"recomputed": r["best"], "frozen": fz["best"]},
             "dist": {"recomputed": r["chosen_dist"], "frozen": fz["dist"]},
             "params_match": _close({k: v for k, v in sprm.items()}, fz["params"]),
             "alpha_given_minutes": {"recomputed": round(float(r["alpha_given_minutes"]), 6), "frozen": fz["alpha_given_minutes"]},
             "min_res_match": _close(r["min_res"], fz["min_res"]),
             "dist_params_match": (_close(r["fams"].get(fz["dist"]), fz["dist_params"]) if fz["dist_params"] else None),
             "holdout": {"n": int(len(hold)), "crps": round(crps_h, 4), "mae": round(mae_h, 4),
                         "cover_80": round(float(dm["cover_80"]), 4),
                         "published": {"n": raw_row["n_obs"], "crps": raw_row["crps"], "mae": raw_row["mae"],
                                       "cover_80": raw_row["cover_80"], "model": raw_row["model"]}}}
        # Frozen-parameter version (primary, decided before any outcome join): the recomputed ladder means, but the
        # stack weights, distribution parameters, minutes residuals and alpha taken verbatim from frozen_params.json.
        from nba import distributions as Dm
        from nba.common import SUPPORT_K
        K = SUPPORT_K[col]
        if fz["best"] == "F":
            w = np.array([fz["params"]["F_weights"][k] for k in "ABCDE"])
            mu_fz = P[[f"s_{k}" for k in "ABCDE"]].to_numpy() @ w
        else:
            mu_fz = P[f"s_{fz['best']}"].to_numpy()
        if fz["dist"] == "mixture":
            scen = Dm.minutes_scenarios(fz["min_res"], P["m_best"].to_numpy())
            rate = P["s_rate"].to_numpy()
            scale = mu_fz / np.maximum(rate * scen.mean(axis=1), 1e-6)
            dist_fz = lambda idx: Dm.mixture(rate[idx], scen[idx], fz["alpha_given_minutes"], K, scale[idx])
        else:
            dist_fz = lambda idx: Dm.make(fz["dist_params"], mu_fz[idx])
        dh = dist_fz(hold)
        c["holdout_frozen_params"] = {"crps": round(float(np.mean(dh.crps(y[hold]))), 4),
                                      "mae": round(float(np.mean(np.abs(mu_fz[hold] - y[hold]))), 4),
                                      "cover_80": round(float(metrics.dist_metrics(y[hold], dh)["cover_80"]), 4)}
        i26 = np.where((P["season"] == 2026).to_numpy())[0]
        d26r = r["dist_for"](fz["dist"], i26)
        d26 = dist_fz(i26)
        c["season_2026_frozen_params"] = {"crps": round(float(np.mean(d26.crps(y[i26]))), 4),
                                          "mae": round(float(np.mean(np.abs(mu_fz[i26] - y[i26]))), 4),
                                          "max_abs_rung_prob_diff_vs_refit": round(float(np.max(np.abs(
                                              np.cumsum(d26.P, 1) - np.cumsum(d26r.P, 1)))), 4)}
        np.savez_compressed(OUT / f"pmf_refit_{fam}.npz", game_id=P["game_id"].to_numpy(np.int64)[i26],
                            pid=P["pid"].to_numpy(np.int64)[i26], P=d26r.P.astype(np.float32), lo=d26r.lo)
        c["season_2026"] = {"n": int(len(i26)), "crps": round(float(np.mean(d26.crps(y[i26]))), 4),
                            "mae": round(float(np.mean(np.abs(P[f"s_{fz['best']}"].to_numpy()[i26] - y[i26]))), 4)}
        S = P.iloc[i26]
        np.savez_compressed(OUT / f"pmf_{fam}.npz", game_id=S["game_id"].to_numpy(np.int64),
                            pid=S["pid"].to_numpy(np.int64), P=d26.P.astype(np.float32), lo=d26.lo,
                            y=y[i26], mean_best=mu_fz[i26], minutes=S["minutes"].to_numpy(),
                            min_best=S["min_best"].to_numpy())
        if S26 is None:
            S26 = S[["game_id", "pid", "name", "team", "opp", "home", "date", "tip_utc", "minutes", "started",
                     "pts", "reb", "ast", "fg3m"]].copy()
        check["families"][fam] = c
        pipeline.log(f"{fam}: best {r['best']} dist {r['chosen_dist']} holdout crps {crps_h:.4f} "
                     f"(published {raw_row['crps']})")
    S26.reset_index(drop=True).to_parquet(OUT / "rows_2026.parquet")
    (OUT / "repro_check.json").write_text(json.dumps(check, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

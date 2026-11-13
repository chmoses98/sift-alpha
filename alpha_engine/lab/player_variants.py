"""Pre-declared player-probability variants, scored side by side on the 2025 contracts (RESEARCH_ONLY).  2025 has already been looked at, so every number here is a DIAGNOSTIC,
not a holdout result; the adoption decision is deferred to the prospective 2026 test.

  v0_incumbent      p_act (raw appearance rate) x NB conditional                      (what produced the original 'systematically low' probabilities)
  v1_inv_model      P_inv (logistic, trained on seasons<2025, market-free) x NB
  v2_listed_active  1[not reported Out] x NB     assumption: a player the exchange lists is expected to play (conditions on the EXISTENCE of the contract, not on a price)
  v3_listed_emp     1[not reported Out] x local-empirical conditional for yardage families (shape chosen on 2022-24 validation); NB for receptions / any-TD
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import shape as SH

YARDAGE = ("rec_yds", "rush_yds", "pass_yds")


def add_variants(d: pd.DataFrame, pools: dict, inv: pd.DataFrame) -> pd.DataFrame:
    """d: one row per (ticker, horizon) with family, pid, game_id, floor, mu, p_act, model_p, inj_out(optional).  pools[family] = (mu_oos, y_oos) from seasons <= 2024."""
    x = d.copy()
    x = x.merge(inv[["pid", "game_id", "p_inv", "inj_out"]].drop_duplicates(["pid", "game_id"]), on=["pid", "game_id"], how="left")
    x["p_cond"] = (x["model_p"] / x["p_act"].clip(lower=1e-6)).clip(0, 1)
    x["v0_incumbent"] = x["model_p"]
    x["v1_inv_model"] = x["p_inv"] * x["p_cond"]
    notout = (~x["inj_out"].fillna(False).astype(bool)).astype(float)
    x["v2_listed_active"] = notout * x["p_cond"]
    x["p_cond_emp"] = np.nan
    for fam in YARDAGE:
        m = (x["family"] == fam).to_numpy()
        if m.any() and fam in pools:
            mu_p, y_p = pools[fam]
            R = SH.local_ratios(mu_p, y_p, x.loc[m, "mu"].to_numpy(float))
            k = x.loc[m, "floor"].to_numpy(float) + 0.5
            hit = (x.loc[m, "mu"].to_numpy(float)[:, None] * R >= (k[:, None] - 0.5)).sum(1)
            x.loc[m, "p_cond_emp"] = (hit + 0.5) / (R.shape[1] + 1.0)
    x["v3_listed_emp"] = notout * x["p_cond_emp"].fillna(x["p_cond"])
    return x

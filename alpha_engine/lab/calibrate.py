"""Walk-forward calibration of a fitted game model: for season S, regress the realised outcome on the model mean using ONLY seasons < S (out-of-sample predictions), then
re-estimate sigma from the calibrated out-of-sample residuals.  One extra degree of freedom per target; judged on the validation seasons, market-free."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import dists


def calibrate(P: pd.DataFrame, first=2016) -> pd.DataFrame:
    P = P.sort_values(["season", "week"]).reset_index(drop=True).copy()
    mu_c = np.full(len(P), np.nan); sig_c = np.full(len(P), np.nan); slope = {}
    for s in sorted(P["season"].unique()):
        if s < first:
            continue
        tr = (P["season"] < s) & P["y"].notna() & P["mu"].notna()
        te = P["season"] == s
        x, y = P.loc[tr, "mu"].to_numpy(), P.loc[tr, "y"].to_numpy()
        b = float(np.cov(x, y, bias=True)[0, 1] / np.var(x)); a = float(y.mean() - b * x.mean())
        slope[int(s)] = round(b, 4)
        res = y - (a + b * x)
        mu_c[te.to_numpy()] = a + b * P.loc[te, "mu"].to_numpy()
        sig_c[te.to_numpy()] = float(np.std(res))
    P["mu_cal"], P["sigma_cal"] = mu_c, sig_c
    P.attrs["slopes"] = slope
    return P


def gain(P: pd.DataFrame, seasons) -> np.ndarray:
    m = P["season"].isin(seasons) & P["y"].notna() & P["mu_cal"].notna()
    kind = P["dist"].iloc[0]
    raw = dists.int_logscore(kind, P.loc[m, "y"].to_numpy(), P.loc[m, "mu"].to_numpy(), P.loc[m, "sigma"].to_numpy())
    cal = dists.int_logscore(kind, P.loc[m, "y"].to_numpy(), P.loc[m, "mu_cal"].to_numpy(), P.loc[m, "sigma_cal"].to_numpy())
    return cal - raw

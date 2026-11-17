#!/usr/bin/env python
"""Independent NBA player-box feature builder.

Written from docs/certification/NBA_PLAYER_BOX_SPEC.md v1.1 alone.

Usage: python nba_player_box_independent.py --root <dir> --out <file.parquet>
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

COLS = ["game_id", "season", "season_type", "game_date", "athlete_id", "team_id",
        "minutes", "points", "rebounds", "assists", "starter"]


def load(root):
    files = sorted(glob.glob(os.path.join(root, "**", "player_box_*.parquet"), recursive=True))
    parts = [pd.read_parquet(f, columns=COLS) for f in files]
    df = pd.concat(parts, ignore_index=True)  # preserves file-path then row order
    df = df[(df["season_type"] == 2) & df["athlete_id"].notna() & df["team_id"].notna()].copy()
    for c in ["game_id", "athlete_id", "team_id", "season"]:
        df[c] = df[c].astype("int64")
    gd = df["game_date"]
    if pd.api.types.is_datetime64_any_dtype(gd):
        df["date"] = gd.dt.strftime("%Y-%m-%d")
    else:
        df["date"] = gd.astype(str).str.slice(0, 10)
    df = df.drop_duplicates(["game_id", "athlete_id"], keep="first")
    n = df.groupby(["season", "team_id"])["game_id"].transform("nunique")
    df = df[n >= 5].copy()
    mins = pd.to_numeric(df["minutes"], errors="coerce")
    df["minutes"] = mins
    df["appeared"] = mins.notna() & (mins > 0)
    df["starter_b"] = df["starter"].map(lambda v: v is True or (isinstance(v, (bool, np.bool_)) and bool(v)))
    for c in ["points", "rebounds", "assists"]:
        df[c + "_f"] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df.reset_index(drop=True)


def pre_sum(df, keys, vals, date_col="date"):
    """df sorted by keys+date+game_id. Returns dict name->sum over rows of same keys with strictly earlier date."""
    blk = (df[keys + [date_col]]).ne(df[keys + [date_col]].shift()).any(axis=1).cumsum()
    out = {}
    for name, v in vals.items():
        v = pd.Series(np.asarray(v, dtype="float64"), index=df.index)
        cum = v.groupby([df[k] for k in keys]).cumsum()
        excl = cum - v
        out[name] = excl.groupby(blk).transform("first").to_numpy()
    return out


def player_features(df):
    df = df.sort_values(["athlete_id", "season", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    app = df["appeared"].to_numpy()
    m = df["minutes"].fillna(0.0).to_numpy()
    mA = np.where(app, m, 0.0)
    x = df["points_f"].to_numpy()
    y = df["rebounds_f"].to_numpy()
    z = df["assists_f"].to_numpy()
    gkey = df.groupby(["athlete_id", "season"]).ngroup().to_numpy()
    # center per group (covariance invariant) for numeric stability
    def cen(a):
        s = pd.Series(a).groupby(gkey).transform("mean").to_numpy()
        return a - s
    xc, yc, zc = cen(x), cen(y), cen(z)
    A = app.astype(float)
    f30 = app & (m >= 30)
    vals = {
        "n_rows": np.ones(len(df)),
        "n_app": A,
        "min_sum": mA,
        "start": (app & df["starter_b"].to_numpy()).astype(float),
        "heavy": (app & (m >= 38)).astype(float),
        "f30": f30.astype(float),
        "g25": (f30 & (x >= 25)).astype(float),
        "g30": (f30 & (x >= 30)).astype(float),
        "sx": A * xc, "sy": A * yc, "sz": A * zc,
        "sxx": A * xc * xc, "syy": A * yc * yc, "szz": A * zc * zc,
        "sxy": A * xc * yc, "sxz": A * xc * zc, "syz": A * yc * zc,
    }
    keys = ["athlete_id", "season"]
    P = pre_sum(df, keys, vals)
    out = pd.DataFrame({"game_id": df["game_id"], "athlete_id": df["athlete_id"],
                        "team_id": df["team_id"], "season": df["season"], "date": df["date"]})
    n_rows = P["n_rows"]
    n_app = P["n_app"]
    with np.errstate(divide="ignore", invalid="ignore"):
        def div(a, b):
            return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)
        out["n_rows_pre"] = n_rows
        out["n_app_pre"] = n_app
        out["app_rate_pre"] = div(n_app, n_rows)
        out["min_mean_pre"] = div(P["min_sum"], n_app)

        # last 5 prior appearances minutes mean
        blk_idx = np.arange(len(df))
        appidx = np.flatnonzero(app)
        csum = np.concatenate([[0.0], np.cumsum(m[appidx])])
        capp = np.concatenate([[0], np.cumsum(app.astype(np.int64))])  # exclusive count globally
        # group start (global appearance count before group start)
        gstart_pos = pd.Series(blk_idx).groupby(gkey).transform("first").to_numpy()
        s = capp[gstart_pos]
        k = n_app.astype(np.int64)
        tot = csum[s + k] - csum[s + np.maximum(0, k - 5)]
        cnt5 = np.minimum(k, 5)
        out["min_last5_pre"] = div(tot, cnt5)

        out["start_rate_pre"] = div(P["start"], n_app)
        out["heavy38_rate_pre"] = div(P["heavy"], n_app)
        f30n = P["f30"]
        out["full30_n_pre"] = f30n
        out["pts_ge25_full30_pre"] = div(P["g25"], f30n)
        out["pts_ge30_full30_pre"] = div(P["g30"], f30n)

        # p90 over prior full30 appearances (strict-date prefix)
        p90 = np.full(len(df), np.nan)
        fi = np.flatnonzero(f30)
        if len(fi):
            fg = gkey[fi]
            # position within group's f30 list
            pos = pd.Series(np.arange(len(fi))).groupby(fg).cumcount().to_numpy()
            ug, ginv = np.unique(fg, return_inverse=True)
            cnts = np.bincount(ginv)
            kmax = int(cnts.max())
            M = np.full((len(ug), kmax), np.nan)
            M[ginv, pos] = x[fi]
            table = np.full((len(ug), kmax + 1), np.nan)
            for kk in range(5, kmax + 1):
                sel = np.flatnonzero(cnts >= kk)
                sub = np.sort(M[sel, :kk], axis=1)
                h = (kk - 1) * 0.9
                lo = int(np.floor(h))
                hi = min(lo + 1, kk - 1)
                fr = h - lo
                table[sel, kk] = sub[:, lo] + (sub[:, hi] - sub[:, lo]) * fr
            gidx = np.searchsorted(ug, gkey)
            gidx_c = np.clip(gidx, 0, len(ug) - 1)
            has = (ug[gidx_c] == gkey)
            kk_row = f30n.astype(np.int64)
            ok = has & (kk_row >= 5)
            p90[ok] = table[gidx_c[ok], kk_row[ok]]
        out["pts_p90_full30_pre"] = p90

        ok5 = n_app >= 5
        nn = np.where(ok5, n_app, np.nan)
        den = nn - 1
        vx = (P["sxx"] - P["sx"] ** 2 / nn) / den
        vy = (P["syy"] - P["sy"] ** 2 / nn) / den
        vz = (P["szz"] - P["sz"] ** 2 / nn) / den
        cxy = (P["sxy"] - P["sx"] * P["sy"] / nn) / den
        cxz = (P["sxz"] - P["sx"] * P["sz"] / nn) / den
        cyz = (P["syz"] - P["sy"] * P["sz"] / nn) / den
        vpra = vx + vy + vz + 2 * (cxy + cxz + cyz)
        vpra = np.where(ok5 & (vpra < 0), 0.0, vpra)
        out["cov_pts_reb_pre"] = cxy
        out["cov_pts_ast_pre"] = cxz
        out["cov_reb_ast_pre"] = cyz
        out["var_pra_pre"] = vpra
        d = vx + vy + vz
        out["pra_var_ratio_pre"] = np.where(ok5 & (d > 1e-9), vpra / np.where(d > 1e-9, d, 1), np.nan)
    return out


def team_features(df):
    d = df.copy()
    d["bm"] = np.where(d["appeared"] & ~d["starter_b"], d["minutes"].fillna(0.0), 0.0)
    d["am"] = np.where(d["appeared"], d["minutes"].fillna(0.0), 0.0)
    tg = d.groupby(["season", "team_id", "game_id"], sort=False).agg(
        date=("date", "min"), bench_min=("bm", "sum"), all_min=("am", "sum")).reset_index()
    tg["share"] = np.where(tg["all_min"] > 0, tg["bench_min"] / tg["all_min"].where(tg["all_min"] > 0, 1), np.nan)
    tg = tg.sort_values(["team_id", "season", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    sh = tg["share"].to_numpy()
    bm = tg["bench_min"].to_numpy()
    bmc = bm - pd.Series(bm).groupby([tg["team_id"], tg["season"]]).transform("mean").to_numpy()
    vals = {"n": np.ones(len(tg)), "ns": (~np.isnan(sh)).astype(float), "ss": np.nan_to_num(sh),
            "b": bmc, "bb": bmc * bmc}
    P = pre_sum(tg, ["team_id", "season"], vals)
    n = P["n"]
    res = pd.DataFrame({"team_id": tg["team_id"], "season": tg["season"], "game_id": tg["game_id"]})
    with np.errstate(divide="ignore", invalid="ignore"):
        res["team_games_pre"] = n
        res["team_bench_share_pre"] = np.where(P["ns"] > 0, P["ss"] / np.where(P["ns"] > 0, P["ns"], 1), np.nan)
        # mean of bench_min: recover from centred sums + group mean
        gm = pd.Series(bm).groupby([tg["team_id"], tg["season"]]).transform("mean").to_numpy()
        res["team_bench_min_mean_pre"] = np.where(n > 0, P["b"] / np.where(n > 0, n, 1) + gm, np.nan)
        nn = np.where(n >= 2, n, np.nan)
        v = (P["bb"] - P["b"] ** 2 / nn) / (nn - 1)
        res["team_bench_min_sd_pre"] = np.sqrt(np.maximum(v, 0.0))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    df = load(a.root)
    pf = player_features(df)
    tf = team_features(df)
    pf = pf.merge(tf, on=["team_id", "season", "game_id"], how="left")
    lab = df[["game_id", "athlete_id", "appeared", "starter_b", "minutes",
              "points_f", "rebounds_f", "assists_f"]]
    pf = pf.merge(lab, on=["game_id", "athlete_id"], how="left")
    ap_ = pf["appeared"].to_numpy()
    pf["y_appeared"] = ap_.astype(float)
    pf["y_minutes"] = np.where(ap_, pf["minutes"].fillna(0.0), 0.0)
    pf["y_points"] = np.where(ap_, pf["points_f"], np.nan)
    pf["y_rebounds"] = np.where(ap_, pf["rebounds_f"], np.nan)
    pf["y_assists"] = np.where(ap_, pf["assists_f"], np.nan)
    pf["y_starter"] = pf["starter_b"].astype(float)
    pf["key"] = pf["game_id"].astype(str) + ":" + pf["athlete_id"].astype(str)
    cols = (["key", "game_id", "athlete_id", "team_id", "season", "date",
             "n_rows_pre", "n_app_pre", "app_rate_pre", "min_mean_pre", "min_last5_pre",
             "start_rate_pre", "heavy38_rate_pre", "full30_n_pre", "pts_ge25_full30_pre",
             "pts_ge30_full30_pre", "pts_p90_full30_pre", "cov_pts_reb_pre", "cov_pts_ast_pre",
             "cov_reb_ast_pre", "var_pra_pre", "pra_var_ratio_pre",
             "team_games_pre", "team_bench_share_pre", "team_bench_min_mean_pre", "team_bench_min_sd_pre",
             "y_appeared", "y_minutes", "y_points", "y_rebounds", "y_assists", "y_starter"])
    out = pf[cols].sort_values(["date", "game_id", "athlete_id"], kind="mergesort").reset_index(drop=True)
    for c in cols[6:]:
        out[c] = out[c].astype("float64")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out.to_parquet(a.out, index=False)
    print(len(out), "rows written to", a.out)


if __name__ == "__main__":
    main()

"""Blind re-implementation of docs/certification/NBA_TEAM_BOX_SPEC.md.

Written from the specification alone, without reading the primary builder.
Imports only the standard library, numpy and pandas (pyarrow as parquet engine).

Usage: python nba_team_box_independent.py --root <root> --out <file.parquet>
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

NUM = ["team_score", "opponent_team_score", "field_goals_made", "field_goals_attempted",
       "three_point_field_goals_made", "three_point_field_goals_attempted",
       "free_throws_made", "free_throws_attempted", "offensive_rebounds",
       "defensive_rebounds", "turnovers"]
BOX_COLS = ["game_id", "season", "season_type", "game_date", "team_id", "team_home_away"] + NUM
SHORT = dict(zip(NUM, ["PTS", "OPP_SCORE", "FGM", "FGA", "TPM", "TPA", "FTM", "FTA", "ORB", "DRB", "TOV"]))
STATS = ["FGM", "FGA", "TPM", "TPA", "FTM", "FTA", "ORB", "DRB", "TOV", "PTS"]
FEATS = ["n_pre", "off_rtg_pre", "def_rtg_pre", "net_rtg_pre", "pace_pre", "efg_pre", "tov_pre",
         "orb_pre", "ftr_pre", "d_efg_pre", "d_tov_pre", "d_orb_pre", "d_ftr_pre", "three_rate_pre",
         "miss2_pg_pre", "miss3_pg_pre", "missft_pg_pre", "win_pct_pre", "pyth_pct_pre",
         "pyth_resid_pre", "close_n_pre", "close_win_pct_pre", "net_l10_pre", "rest_days", "b2b",
         "prev_net_prior"]


def find(root, prefix):
    out = []
    for d, _, files in os.walk(root):
        for f in files:
            stem = f[len(prefix):-len(".parquet")]
            if f.startswith(prefix) and f.endswith(".parquet") and len(stem) == 4 and stem.isdigit():
                out.append((f, os.path.join(d, f)))
    return [p for _, p in sorted(out)]


def div(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.full(a.shape, np.nan)
    ok = b != 0
    out[ok] = a[ok] / b[ok]
    return out


def build(root):
    stats = {}
    box = pd.concat([pd.read_parquet(p, columns=BOX_COLS) for p in find(root, "team_box_")],
                    ignore_index=True)
    box = box[box["season_type"] == 2].copy()
    usable = box[NUM].notna().all(axis=1) & (box["field_goals_attempted"] > 0)
    u = box[usable.fillna(False).astype(bool)].copy()
    stats["season_type_2_rows"] = len(box)
    stats["unusable_rows"] = len(box) - len(u)
    stats["games_with_any_row"] = box["game_id"].nunique()

    cnt = u.groupby(["season", "team_id"]).size()
    league = set(cnt[cnt >= 5].index)

    gsize = u.groupby("game_id").size()
    two = set(gsize[gsize == 2].index)
    stats["drop_not_exactly_two_usable_rows"] = stats["games_with_any_row"] - len(two)
    u = u[u["game_id"].isin(two)]
    ha = u["team_home_away"].astype(object)
    home = u[(ha == "home").to_numpy(dtype=bool, na_value=False)]
    away = u[(ha == "away").to_numpy(dtype=bool, na_value=False)]
    home = home[~home["game_id"].duplicated(keep=False)]
    away = away[~away["game_id"].duplicated(keep=False)]
    g = home.merge(away, on="game_id", suffixes=("_h", "_a"))
    stats["drop_not_one_home_one_away"] = len(two) - len(g)
    isl = np.array([((s, h) in league) and ((s, a) in league)
                    for s, h, a in zip(g["season_h"], g["team_id_h"], g["team_id_a"])], dtype=bool)
    stats["drop_non_league_team"] = int((~isl).sum())
    g = g[isl].reset_index(drop=True)
    stats["kept_games"] = len(g)

    games = pd.DataFrame({
        "game_id": g["game_id"].astype("int64"),
        "season": g["season_h"].astype("int64"),
        "dt": pd.to_datetime(g["game_date_h"]).dt.normalize(),
        "home_team_id": g["team_id_h"].astype("int64"),
        "away_team_id": g["team_id_a"].astype("int64"),
    })
    for c in NUM:
        if SHORT[c] in STATS:
            games["h_" + SHORT[c]] = g[c + "_h"].astype(float)
            games["a_" + SHORT[c]] = g[c + "_a"].astype(float)
    games = games.sort_values(["dt", "game_id"], kind="mergesort").reset_index(drop=True)
    games["gi"] = np.arange(len(games))

    # schedule
    sch = pd.concat([pd.read_parquet(p, columns=["game_id", "date", "neutral_site"])
                     for p in find(root, "nba_schedule_")], ignore_index=True)
    sch = sch.drop_duplicates("game_id", keep="first")
    ts = pd.to_datetime(sch["date"], utc=True, errors="coerce")
    sch = pd.DataFrame({
        "game_id": sch["game_id"].astype("int64").to_numpy(),
        "cutoff_utc": ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ").astype(object).where(ts.notna(), "").to_numpy(),
        "neutral": np.where(sch["neutral_site"].astype(object).to_numpy() == True, 1.0, 0.0),  # noqa: E712
    })
    games = games.merge(sch, on="game_id", how="left")
    stats["no_schedule_row"] = int(games["cutoff_utc"].isna().sum())
    games["cutoff_utc"] = games["cutoff_utc"].fillna("")
    games["neutral"] = games["neutral"].fillna(0.0)

    # team-game long table
    parts = []
    for me, op, side in (("h", "a", "home"), ("a", "h", "away")):
        d = pd.DataFrame({"gi": games["gi"], "game_id": games["game_id"], "season": games["season"],
                          "dt": games["dt"], "team": games[side + "_team_id"], "side": side})
        for s in STATS:
            d[s] = games[me + "_" + s]
            d["o" + s] = games[op + "_" + s]
        parts.append(d)
    tg = pd.concat(parts, ignore_index=True)
    tg["poss_T"] = tg["FGA"] - tg["ORB"] + tg["TOV"] + 0.44 * tg["FTA"]
    tg["poss_U"] = tg["oFGA"] - tg["oORB"] + tg["oTOV"] + 0.44 * tg["oFTA"]
    tg["POSS"] = (tg["poss_T"] + tg["poss_U"]) / 2
    tg["MISS2"] = (tg["FGA"] - tg["TPA"]) - (tg["FGM"] - tg["TPM"])
    tg["MISS3"] = tg["TPA"] - tg["TPM"]
    tg["MISSFT"] = tg["FTA"] - tg["FTM"]
    tg["WIN"] = (tg["PTS"] > tg["oPTS"]).astype(float)
    tg["CLOSE"] = ((tg["PTS"] - tg["oPTS"]).abs() <= 5).astype(float)
    tg["CLOSEWIN"] = tg["WIN"] * tg["CLOSE"]
    tg["ONE"] = 1.0
    sumcols = STATS + ["o" + s for s in STATS] + ["poss_T", "poss_U", "POSS", "MISS2", "MISS3",
                                                    "MISSFT", "WIN", "CLOSE", "CLOSEWIN", "ONE"]

    tg = tg.sort_values(["season", "team", "dt", "game_id"], kind="mergesort").reset_index(drop=True)
    N = len(tg)
    pos = np.arange(N)
    grp = tg.groupby(["season", "team"], sort=False)
    gstart = pos - grp.cumcount().to_numpy()
    # index (global) of first row of the same team-season with the same date => rows before are prior
    dstart = pos - tg.groupby(["season", "team", "dt"], sort=False).cumcount().to_numpy()
    n = dstart - gstart
    l10start = np.maximum(dstart - 10, gstart)
    vals = tg[sumcols].to_numpy(dtype=float)
    # within-group prefix sums: P[i] = sum of rows gstart..i-1 of the group
    P = np.zeros((N + 1, len(sumcols)))
    for st, en in zip(*_bounds(gstart)):
        P[st + 1:en + 1] = np.cumsum(vals[st:en], axis=0)
        # P[st] stays as-is for previous group end; handled via explicit zero below
    ci = {c: i for i, c in enumerate(sumcols)}

    def pref(idx, c):
        v = P[idx, ci[c]].copy()
        v[idx == gstart] = 0.0
        return v

    def S(c):
        return pref(dstart, c)

    def L10(c):
        return S(c) - pref(l10start, c)

    has = n > 0
    nf = n.astype(float)

    def m(x):
        x = np.asarray(x, dtype=float).copy()
        x[~has] = np.nan
        return x

    F = pd.DataFrame({"gi": tg["gi"], "side": tg["side"]})
    F["n_pre"] = n.astype("int64")
    F["off_rtg_pre"] = m(100 * div(S("PTS"), S("POSS")))
    F["def_rtg_pre"] = m(100 * div(S("oPTS"), S("POSS")))
    F["net_rtg_pre"] = F["off_rtg_pre"] - F["def_rtg_pre"]
    F["pace_pre"] = m(div(S("POSS"), nf))
    F["efg_pre"] = m(div(S("FGM") + 0.5 * S("TPM"), S("FGA")))
    F["tov_pre"] = m(div(S("TOV"), S("poss_T")))
    F["orb_pre"] = m(div(S("ORB"), S("ORB") + S("oDRB")))
    F["ftr_pre"] = m(div(S("FTA"), S("FGA")))
    F["d_efg_pre"] = m(div(S("oFGM") + 0.5 * S("oTPM"), S("oFGA")))
    F["d_tov_pre"] = m(div(S("oTOV"), S("poss_U")))
    F["d_orb_pre"] = m(div(S("oORB"), S("oORB") + S("DRB")))
    F["d_ftr_pre"] = m(div(S("oFTA"), S("oFGA")))
    F["three_rate_pre"] = m(div(S("TPA"), S("FGA")))
    F["miss2_pg_pre"] = m(div(S("MISS2"), nf))
    F["miss3_pg_pre"] = m(div(S("MISS3"), nf))
    F["missft_pg_pre"] = m(div(S("MISSFT"), nf))
    F["win_pct_pre"] = m(div(S("WIN"), nf))
    p14 = S("PTS") ** 14
    a14 = S("oPTS") ** 14
    F["pyth_pct_pre"] = m(div(p14, p14 + a14))
    F["pyth_resid_pre"] = F["win_pct_pre"] - F["pyth_pct_pre"]
    F["close_n_pre"] = np.rint(S("CLOSE")).astype("int64")
    F["close_win_pct_pre"] = div(S("CLOSEWIN"), S("CLOSE"))
    F["net_l10_pre"] = m(100 * div(L10("PTS") - L10("oPTS"), L10("POSS")))
    dts = tg["dt"].to_numpy()
    last = dts[np.maximum(dstart - 1, 0)]
    rest = m((dts - last) / np.timedelta64(1, "D"))
    F["rest_days"] = rest
    F["b2b"] = m(np.where(rest == 1, 1.0, 0.0))
    # previous-season final net rating over all kept games
    tot = tg.groupby(["season", "team"], sort=False)[["PTS", "oPTS", "POSS"]].sum()
    prevnet = pd.Series(100 * div(tot["PTS"] - tot["oPTS"], tot["POSS"]), index=tot.index)
    key = pd.MultiIndex.from_arrays([tg["season"] - 1, tg["team"]])
    F["prev_net_prior"] = prevnet.reindex(key).to_numpy()

    # league prior sets per (season, date)
    lcols = ["FGM", "TPM", "FGA", "TOV", "poss_T", "ORB", "oDRB", "FTA", "POSS", "ONE"]
    lg = tg.groupby(["season", "dt"], sort=True)[lcols].sum()
    lg = lg.groupby(level=0).cumsum() - lg  # strictly earlier dates in the season
    lgk = lg.reindex(pd.MultiIndex.from_arrays([games["season"], games["dt"]]))
    lv = {c: lgk[c].to_numpy() for c in lcols}
    empty = lv["ONE"] == 0

    def ml(x):
        x = np.asarray(x, dtype=float).copy()
        x[empty] = np.nan
        return x

    lgv = {"efg": ml(div(lv["FGM"] + 0.5 * lv["TPM"], lv["FGA"])),
           "tov": ml(div(lv["TOV"], lv["poss_T"])),
           "orb": ml(div(lv["ORB"], lv["ORB"] + lv["oDRB"])),
           "ftr": ml(div(lv["FTA"], lv["FGA"]))}
    lg_pace = ml(div(lv["POSS"], lv["ONE"]))

    out = games[["game_id", "season"]].copy()
    out["date"] = games["dt"].dt.strftime("%Y-%m-%d")
    out["cutoff_utc"] = games["cutoff_utc"].astype(str)
    out["neutral"] = games["neutral"].astype(float)
    out["home_team_id"] = games["home_team_id"]
    out["away_team_id"] = games["away_team_id"]
    cols = {}
    for side in ("home", "away"):
        f = F[F["side"] == side].set_index("gi").reindex(games["gi"])
        for c in FEATS:
            cols[side + "_" + c] = f[c].to_numpy()
    for side, opp in (("home", "away"), ("away", "home")):
        for f in ("efg", "tov", "orb", "ftr"):
            cols[f"{side}_exp_{f}"] = cols[f"{side}_{f}_pre"] + cols[f"{opp}_d_{f}_pre"] - lgv[f]
    for k in ("miss2", "miss3", "missft"):
        cols["exp_" + k] = cols[f"home_{k}_pg_pre"] + cols[f"away_{k}_pg_pre"]
    cols["exp_reb_pool"] = cols["exp_miss2"] + cols["exp_miss3"]
    cols["exp_poss"] = div(cols["home_pace_pre"] * cols["away_pace_pre"], lg_pace)
    cols["y_home_margin"] = (games["h_PTS"] - games["a_PTS"]).to_numpy(dtype=float)
    cols["y_total"] = (games["h_PTS"] + games["a_PTS"]).to_numpy(dtype=float)
    cols["y_home_win"] = (cols["y_home_margin"] > 0).astype("int64")
    out = pd.concat([out, pd.DataFrame(cols, index=out.index)], axis=1)
    ints = ["game_id", "season", "home_team_id", "away_team_id", "home_n_pre", "away_n_pre",
            "home_close_n_pre", "away_close_n_pre", "y_home_win"]
    for c in out.columns:
        if c in ints:
            out[c] = out[c].astype("int64")
        elif c not in ("date", "cutoff_utc"):
            out[c] = out[c].astype("float64")
    return out.reset_index(drop=True), stats


def _bounds(gstart):
    starts = np.unique(gstart)
    ends = np.append(starts[1:], len(gstart))
    return starts, ends


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out, stats = build(a.root)
    d = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(d, exist_ok=True)
    out.to_parquet(a.out, index=False)
    for k, v in stats.items():
        print(f"{k}: {v}")
    print(f"rows: {len(out)}  cols: {out.shape[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""SIFT NFL study (RESEARCH_ONLY): do certified SIFT Alpha NFL inputs improve the operating model's market-free projection?

Usage (from WORK, with the venv that has polars):  PYTHONDONTWRITEBYTECODE=1 venv/bin/python run.py [prep|dev|test|all]
  prep : certified features (sift-alpha-ops nfl.py on vault data), silver + playoff ratings, baseline walk-forward + fidelity check
  dev  : fit 2012-2021, validation 2022-2023, candidate selection, validation residual SDs (no test rows touched)
  test : verifies protocol.sha256, scores TEST 2024-2025 once, situations, playoffs, price-aware 2025 -> report.json
Read-only inputs: /home/user/nfl-edge-finder, /home/user/sift-alpha-ops, /home/user/sift-data-vault. Never touches /home/user/sift-alpha.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
WORK = os.path.dirname(os.path.abspath(__file__))
NEF = "/home/user/nfl-edge-finder"
OPS = "/home/user/sift-alpha-ops"
RAW = os.path.join(WORK, "raw")
CACHE = os.path.join(WORK, "nflcache")
# AMENDMENT A4: VARIANT=fixed_builder runs the same frozen protocol with the upstream-fixed certified builder copied into
# WORK/fixed_builder (alpha_engine/features/{nfl,core}.py); outputs go to data_fixed/ and report_fixed_builder.json.
VARIANT = os.environ.get("VARIANT", "original")
BUILDER = os.path.join(WORK, "fixed_builder") if VARIANT == "fixed_builder" else OPS
OUT = os.path.join(WORK, "data_fixed" if VARIANT == "fixed_builder" else "data")
REPORT = os.path.join(WORK, "report_fixed_builder.json" if VARIANT == "fixed_builder" else "report.json")
BACKFILL = os.path.join(WORK, "nfl-data", "data", "kalshi", "backfill")
os.makedirs(OUT, exist_ok=True)

FIT = (2012, 2021); VAL = (2022, 2023); TEST = (2024, 2025)
TARGETS = ["team_points", "game_total", "margin", "first_half_total"]
GAME_COLS = ["game_id", "season", "game_type", "week", "gameday", "gametime", "home_team", "away_team", "home_score", "away_score", "result", "total",
             "home_rest", "away_rest", "div_game", "roof", "location"]          # whitelist: no market column is ever loaded
BASE_FEATS = ["epa", "sr", "db_epa", "rush_epa", "epa_ng", "explosive", "sack_rate", "to_rate", "proe", "st_epa", "ed_epa"]
MARGIN_FEATURES = [f"d_{f}" for f in BASE_FEATS] + ["rest_diff", "div_game", "neutral"]
TOTAL_FEATURES = [f"m_h_{f}" for f in BASE_FEATS] + [f"m_a_{f}" for f in BASE_FEATS] + ["indoor", "rest_diff"]

# ---- certified inputs (catalog id -> columns), exactly as protocol.json
PAIRS_C1 = [("nfl.off_epa", "epa_pre", "nfl.def_epa", "def_epa_pre"), ("nfl.off_epa", "pass_epa_pre", "nfl.def_epa", "def_pass_epa_pre"),
            ("nfl.off_epa", "rush_epa_pre", "nfl.def_epa", "def_rush_epa_pre"), ("nfl.success_rate", "success_pre", "nfl.success_rate", "def_success_pre"),
            ("nfl.explosive", "expl_pre", "nfl.explosive", "def_expl_pre"), ("nfl.redzone", "rz_epa_pre", "nfl.redzone", "def_rz_epa_pre"),
            ("nfl.turnovers", "to_rate_pre", "nfl.turnovers", "def_to_rate_pre"), ("nfl.q_scoring", "pts_pre", "nfl.q_scoring", "pts_a_pre")]
SINGLES_C1 = [("nfl.redzone", "rz_td_pre"), ("nfl.points_vs_expected", "pts_vs_exp_pre"), ("nfl.ratings", "margin_pre")]
SINGLES_C2 = [("nfl.pace", "plays_pre"), ("nfl.pace", "nohud_pre"), ("nfl.drives", "drives_pre")]
SCHED_C2 = [("nfl.rest_travel", "rest_gap"), ("nfl.rest_travel", "short_rest"), ("nfl.rest_travel", "bye"), ("nfl.venue", "outdoors"), ("nfl.venue", "home"),
            ("nfl.divisional_familiarity", "div_game")]


def inputs_used() -> dict:
    d = {}
    for a, x, b, y in PAIRS_C1:
        d.setdefault(a, []).append(x); d.setdefault(b, []).append(y)
    for cid, c in SINGLES_C1 + SINGLES_C2 + SCHED_C2:
        d.setdefault(cid, []).append(c)
    return {k: sorted(set(v)) for k, v in d.items()}


def check_certified() -> dict:
    v = json.load(open(os.path.join(OPS, "research/input_research/data_foundation/verified_coverage.json")))
    rows = {r["id"]: r for r in v["rows"] if r["sport"] == "NFL"}
    sys.path.insert(0, BUILDER)
    from alpha_engine.features import nfl as N
    spec = {s.catalog_id: s for s in N.specs()}
    out = {}
    for cid, cols in inputs_used().items():
        r = rows[cid]
        assert r["verified_status"].startswith("VERIFIED_"), cid
        assert set(cols) <= set(spec[cid].columns), (cid, cols, spec[cid].columns)
        assert spec[cid].pit != "final_postgame", cid
        out[cid] = {"columns": cols, "verified_status": r["verified_status"], "pit_verdict": r["pit_verdict"], "builder": "alpha_engine/features/nfl.py", "spec_level": spec[cid].level}
    return out


# ================================================================================================ prep
def prep():
    # nflcache layout expected by alpha_engine.features.core.Paths
    os.makedirs(os.path.join(CACHE, "pbp"), exist_ok=True)
    for f in glob.glob(os.path.join(RAW, "pbp", "pbp", "play_by_play_*.parquet")):
        y = os.path.basename(f).split("_")[-1].split(".")[0]; dst = os.path.join(CACHE, "pbp", f"pbp_{y}.parquet")
        if not os.path.exists(dst):
            os.symlink(f, dst)
    if not os.path.exists(os.path.join(CACHE, "games.csv")):
        os.symlink(os.path.join(RAW, "ipt", "schedules", "games.csv"), os.path.join(CACHE, "games.csv"))
    sys.path.insert(0, BUILDER)
    from alpha_engine.features import nfl as N
    from alpha_engine.features.core import Paths
    team = N.compute(N.load_raw(Paths(nfl=CACHE)))["team"]
    team.to_parquet(os.path.join(OUT, "certified_team_features.parquet"))

    games = pd.read_csv(os.path.join(RAW, "ipt", "schedules", "games.csv"), usecols=GAME_COLS)
    games = games[(games.season >= 2010) & (games.season <= 2025) & games.result.notna()].copy()
    # first-half totals from vault pbp
    h1 = []
    for f in sorted(glob.glob(os.path.join(RAW, "pbp", "pbp", "play_by_play_*.parquet"))):
        p = pd.read_parquet(f, columns=["game_id", "qtr", "total_home_score", "total_away_score"])
        p = p[p.qtr <= 2]
        h1.append(p.assign(s=p.total_home_score + p.total_away_score).groupby("game_id").s.max().rename("first_half_total").reset_index())
    games = games.merge(pd.concat(h1), on="game_id", how="left")

    # ---- baseline: DATA_ONLY / Milestone-E (nfl-edge-finder), REG from the committed feature table
    import polars as pl
    sys.path.insert(0, NEF)
    from nfl_edge.data import silver as SV
    from nfl_edge.research.team_ratings import prepare_rows, snapshot_ratings
    gf = pl.read_parquet(os.path.join(NEF, "research/game_model/game_features.parquet")).to_pandas()
    # playoff features: same rating code on silver rebuilt from vault pbp (REG rows only, seasons S-3..S)
    SV.RAW = os.path.join(RAW, "pbp")
    tg = pl.concat([SV.team_game_from_pbp(s) for s in range(2010, 2026)], how="diagonal_relaxed")
    rows = prepare_rows(tg.filter(pl.col("season_type") == "REG"))
    fidelity = {}
    com = pl.read_parquet(os.path.join(NEF, "research/game_model/ratings_snapshots.parquet"))
    for s, w in [(2013, 5), (2020, 10), (2024, 12), (2025, 17)]:
        r = snapshot_ratings(rows, s, w, halflife_games=10.0, season_carry=0.4, ridge=4.0)
        j = r.join(com.filter((pl.col("season") == s) & (pl.col("week") == w)), on=["team", "season", "week"], suffix="_c")
        fidelity[f"ratings_{s}_w{w}_max_abs_diff_vs_committed"] = max(float((j[c] - j[c + "_c"]).abs().max()) for c in r.columns if c[:4] in ("off_", "def_"))
    post = games[(games.game_type != "REG") & (games.season >= 2013)].copy()
    tf = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "JAC": "JAX", "WSH": "WAS"}
    pr = []
    for (s, w), g in post.groupby(["season", "week"]):
        r = snapshot_ratings(rows, int(s), int(w), halflife_games=10.0, season_carry=0.4, ridge=4.0).to_pandas().set_index("team")
        for _, x in g.iterrows():
            h, a = tf.get(x.home_team, x.home_team), tf.get(x.away_team, x.away_team)
            rec = {"game_id": x.game_id}
            for f in BASE_FEATS:
                mh = r.loc[h, f"off_{f}"] + r.loc[a, f"def_{f}"]; ma = r.loc[a, f"off_{f}"] + r.loc[h, f"def_{f}"]
                rec.update({f"m_h_{f}": mh, f"m_a_{f}": ma, f"d_{f}": mh - ma})
            pr.append(rec)
    pf = post.merge(pd.DataFrame(pr), on="game_id")
    pf["rest_diff"] = pf.home_rest - pf.away_rest; pf["div_game"] = pf.div_game.astype(float)
    pf["indoor"] = pf.roof.isin(["dome", "closed"]).astype(float); pf["neutral"] = (pf.location == "Neutral").astype(float)

    def ridge_fit(X, y, lam=30.0):
        Xm = X.mean(0); Xs = X.std(0) + 1e-9; ym = y.mean(); Xc = (X - Xm) / Xs
        return np.linalg.solve(Xc.T @ Xc + lam * np.eye(X.shape[1]), Xc.T @ (y - ym)), Xm, Xs, ym

    def ridge_pred(m, X):
        b, Xm, Xs, ym = m; return ((X - Xm) / Xs) @ b + ym

    preds = []
    for S in range(FIT[0], 2026):
        tr = gf[(gf.season < S) & (gf.season >= S - 8)]
        mm = ridge_fit(tr[MARGIN_FEATURES].fillna(0).to_numpy(float), tr.result.to_numpy(float))
        mt = ridge_fit(tr[TOTAL_FEATURES].fillna(0).to_numpy(float), tr.total.to_numpy(float))
        for src, te in (("REG", gf[gf.season == S]), ("POST", pf[pf.season == S])):
            if len(te):
                preds.append(pd.DataFrame({"game_id": te.game_id.values, "base_margin": ridge_pred(mm, te[MARGIN_FEATURES].fillna(0).to_numpy(float)),
                                           "base_total": ridge_pred(mt, te[TOTAL_FEATURES].fillna(0).to_numpy(float)), "base_train_seasons": f"{max(2010, S - 8)}-{S - 1}"}))
    base = pd.concat(preds, ignore_index=True)
    cw = pl.read_parquet(os.path.join(NEF, "research/game_model/walkforward_predictions.parquet")).to_pandas().merge(base, on="game_id")
    fidelity["walkforward_rows_compared_2014_2025"] = int(len(cw))
    fidelity["max_abs_diff_margin_vs_committed"] = float((cw.model_margin - cw.base_margin).abs().max())
    fidelity["max_abs_diff_total_vs_committed"] = float((cw.model_total - cw.base_total).abs().max())
    assert fidelity["max_abs_diff_margin_vs_committed"] < 1e-6 and fidelity["max_abs_diff_total_vs_committed"] < 1e-6, fidelity
    games = games.merge(base, on="game_id", how="inner")
    games.to_parquet(os.path.join(OUT, "games_baseline.parquet"))
    json.dump(fidelity, open(os.path.join(OUT, "baseline_fidelity.json"), "w"), indent=1)
    print("prep done", games.shape, fidelity)


# ================================================================================================ design matrices
def load_frames():
    g = pd.read_parquet(os.path.join(OUT, "games_baseline.parquet"))
    t = pd.read_parquet(os.path.join(OUT, "certified_team_features.parquet"))
    keep = sorted({c for _, x, _, y in PAIRS_C1 for c in (x, y)} | {c for _, c in SINGLES_C1 + SINGLES_C2 + SCHED_C2})
    # AMENDMENT A1 (join key): the certified builder flags home by pbp team code == schedule code, which fails for STL/SD/OAK home games
    # 2010-2019 (pbp uses LA/LAC/LV). Rows are therefore matched to home/away by NORMALISED team code; the certified column values are kept as built.
    tf = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "JAC": "JAX", "WSH": "WAS"}
    t = t[["game_id", "team", "home_team"] + keep].copy()
    is_h = t.team.map(lambda x: tf.get(x, x)) == t.home_team.map(lambda x: tf.get(x, x))
    t = t.drop(columns=["team", "home_team"])
    h = t[is_h].add_prefix("h_").rename(columns={"h_game_id": "game_id"})
    a = t[~is_h].add_prefix("a_").rename(columns={"a_game_id": "game_id"})
    assert h.game_id.is_unique and a.game_id.is_unique
    g = g.merge(h, on="game_id", how="left").merge(a, on="game_id", how="left")
    g["post"] = (g.game_type != "REG").astype(int)
    g["home_pts"] = g.home_score; g["away_pts"] = g.away_score; g["margin"] = g.result; g["game_total"] = g.total
    g["base_home_pts"] = (g.base_total + g.base_margin) / 2; g["base_away_pts"] = (g.base_total - g.base_margin) / 2
    return g


def game_design(g: pd.DataFrame, target: str, level: str) -> pd.DataFrame:
    """level C1 or C2 feature block for a game-level target (game_total, first_half_total, margin)."""
    X = pd.DataFrame(index=g.index); tot = target != "margin"
    for _, x, _, y in PAIRS_C1:
        mh = g[f"h_{x}"] + g[f"a_{y}"]; ma = g[f"a_{x}"] + g[f"h_{y}"]
        X[f"pair_{x}"] = mh + ma if tot else mh - ma
    for _, c in SINGLES_C1 + (SINGLES_C2 if level == "C2" else []):
        if tot:
            X[f"s_{c}"] = (g[f"h_{c}"] - g[f"a_{c}"]).abs() if c == "margin_pre" else g[f"h_{c}"] + g[f"a_{c}"]
        else:
            X[f"s_{c}"] = g[f"h_{c}"] - g[f"a_{c}"]
    if level == "C2":
        X["rest_gap"] = g.h_rest_gap.abs() if tot else g.h_rest_gap
        for c in ("short_rest", "bye"):
            X[c] = g[f"h_{c}"] + g[f"a_{c}"] if tot else g[f"h_{c}"] - g[f"a_{c}"]
        X["outdoors"] = g.h_outdoors; X["div_game"] = g.h_div_game
    return X


def team_rows(g: pd.DataFrame) -> pd.DataFrame:
    """Two rows per game: own = home then away."""
    out = []
    for own, opp in (("h", "a"), ("a", "h")):
        d = g[["game_id", "season", "week", "game_type", "post", "div_game", "roof", "home_rest", "away_rest", "base_total"]].copy()
        d["y"] = g["home_pts" if own == "h" else "away_pts"]; d["base"] = g["base_home_pts" if own == "h" else "base_away_pts"]
        d["side"] = own
        for _, x, _, y in PAIRS_C1:
            d[f"pair_{x}"] = g[f"{own}_{x}"] + g[f"{opp}_{y}"]
        for _, c in SINGLES_C1 + SINGLES_C2:
            d[f"own_{c}"] = g[f"{own}_{c}"]; d[f"opp_{c}"] = g[f"{opp}_{c}"]
        d["rest_gap"] = g[f"{own}_rest_gap"]
        for c in ("short_rest", "bye"):
            d[f"own_{c}"] = g[f"{own}_{c}"]; d[f"opp_{c}"] = g[f"{opp}_{c}"]
        d["outdoors"] = g.h_outdoors; d["div_flag"] = g.h_div_game; d["home"] = g[f"{own}_home"]
        out.append(d)
    return pd.concat(out, ignore_index=True)


def cols_for(target: str, level: str, frame: pd.DataFrame) -> list:
    if target != "team_points":
        return [c for c in frame.columns if c not in ("y", "base") and not c.startswith("meta_")]
    c1 = [f"pair_{x}" for _, x, _, _ in PAIRS_C1] + [f"{s}_{c}" for _, c in SINGLES_C1 for s in ("own", "opp")]
    if level == "C1":
        return c1
    return c1 + [f"{s}_{c}" for _, c in SINGLES_C2 for s in ("own", "opp")] + ["rest_gap", "own_short_rest", "opp_short_rest", "own_bye", "opp_bye", "outdoors", "div_flag", "home"]


def frame_for(g: pd.DataFrame, target: str, level: str, b1h=None) -> pd.DataFrame:
    """Rows with y, base, meta_*, and the feature columns of `level`."""
    if target == "team_points":
        d = team_rows(g)
        f = d[["y", "base"] + cols_for(target, level, d)].copy()
        for m in ("game_id", "season", "week", "game_type", "post", "div_game", "roof", "home_rest", "away_rest", "base_total"):
            f[f"meta_{m}"] = d[m].values
        return f
    X = game_design(g, target, level)
    y = g[target]
    if target == "game_total":
        base = g.base_total
    elif target == "margin":
        base = g.base_margin
    else:
        base = b1h[0] + b1h[1] * g.base_total
    f = pd.concat([pd.DataFrame({"y": y, "base": base}), X], axis=1)
    for m in ("game_id", "season", "week", "game_type", "post", "div_game", "roof", "home_rest", "away_rest", "base_total"):
        f[f"meta_{m}"] = g[m].values
    return f.reset_index(drop=True)


# ================================================================================================ models
class Stack:
    """(y - base) ~ intercept + base + features; OLS (alpha=0) or ridge on standardised columns."""
    def __init__(self, alpha=0.0):
        self.alpha = alpha

    def fit(self, F: pd.DataFrame, cols: list):
        self.cols = ["base"] + list(cols); X = F[self.cols].astype(float)
        self.mu = X.mean(); X = X.fillna(self.mu).to_numpy(); self.xm = X.mean(0); self.xs = X.std(0) + 1e-12
        Z = (X - self.xm) / self.xs; r = (F.y - F.base).to_numpy(float); self.rm = r.mean()
        A = Z.T @ Z + self.alpha * np.eye(Z.shape[1])
        self.beta = np.linalg.lstsq(A, Z.T @ (r - self.rm), rcond=None)[0]
        return self

    def predict(self, F: pd.DataFrame):
        X = F[self.cols].astype(float).fillna(self.mu).to_numpy()
        return F.base.to_numpy(float) + ((X - self.xm) / self.xs) @ self.beta + self.rm


ALPHAS = np.logspace(-2, 4, 25)


def ts_cv_alpha(F: pd.DataFrame, cols: list) -> tuple:
    errs = []
    for a in ALPHAS:
        se = []
        for s in range(2016, FIT[1] + 1):
            tr = F[(F.meta_season >= FIT[0]) & (F.meta_season < s)]; va = F[F.meta_season == s]
            se.append(((Stack(a).fit(tr, cols).predict(va) - va.y) ** 2).to_numpy())
        errs.append(float(np.concatenate(se).mean()))
    i = int(np.argmin(errs)); return float(ALPHAS[i]), dict(zip([round(float(a), 4) for a in ALPHAS], [round(e, 4) for e in errs]))


def rmse(e):
    return float(np.sqrt(np.mean(np.square(e))))


def season_mask(F, lo, hi, post=0):
    return (F.meta_season >= lo) & (F.meta_season <= hi) & (F.meta_post == post) & ((F.meta_week <= 18) | (post == 1))


def all_frames(g):
    fitg = g[(g.season >= FIT[0]) & (g.season <= FIT[1]) & (g.post == 0)]
    b = np.polyfit(fitg.base_total.to_numpy(float), fitg.first_half_total.to_numpy(float), 1)
    b1h = (float(b[1]), float(b[0]))
    gg = g[g.first_half_total.notna()].reset_index(drop=True)
    fr = {}
    for t in TARGETS:
        fr[t] = {lvl: frame_for(gg if t == "first_half_total" else g.reset_index(drop=True), t, lvl, b1h) for lvl in ("C1", "C2")}
    return fr, b1h


def dev():
    g = load_frames(); fr, b1h = all_frames(g)
    res = {"first_half_baseline_map": {"intercept": b1h[0], "slope_on_baseline_total": b1h[1], "fit": "OLS on fit seasons 2012-2021 REG"}, "targets": {}}
    for t in TARGETS:
        r = {"n_fit": None, "candidates": {}}
        for name, lvl in (("C1", "C1"), ("C2", "C2"), ("C3", "C2")):
            F = fr[t][lvl]; cols = cols_for(t, lvl, F)
            fit = F[season_mask(F, *FIT)]; val = F[season_mask(F, *VAL)]
            alpha, cv = (0.0, None) if name != "C3" else ts_cv_alpha(fit, cols)
            m = Stack(alpha).fit(fit, cols); e = m.predict(val) - val.y
            eb = val.base - val.y
            r["n_fit"], r["n_val"] = int(len(fit)), int(len(val))
            r["candidates"][name] = {"columns": cols, "alpha": alpha, "cv_mse_by_alpha": cv, "val_rmse": rmse(e), "val_mae": float(np.abs(e).mean()),
                                     "val_resid_sd": float(np.std(e, ddof=1)), "val_bias": float(e.mean())}
            r["baseline_val_rmse"], r["baseline_val_mae"], r["baseline_val_resid_sd"] = rmse(eb), float(np.abs(eb).mean()), float(np.std(eb, ddof=1))
        sel = min(("C1", "C2", "C3"), key=lambda k: r["candidates"][k]["val_rmse"])
        r["selected"] = sel; r["selected_beats_baseline_on_validation"] = r["candidates"][sel]["val_rmse"] < r["baseline_val_rmse"]
        res["targets"][t] = r
        print(t, "baseline val rmse %.3f" % r["baseline_val_rmse"], {k: round(v["val_rmse"], 3) for k, v in r["candidates"].items()}, "->", sel)
    json.dump(res, open(os.path.join(OUT, "dev.json"), "w"), indent=1)
    return res


# ================================================================================================ test
def boot_ci(d: np.ndarray, clusters: np.ndarray, n=2000, seed=13):
    u, inv = np.unique(clusters, return_inverse=True); s = np.bincount(inv, weights=d); c = np.bincount(inv)
    rng = np.random.default_rng(seed); idx = rng.integers(0, len(u), (n, len(u)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))]


def paired(y, pb, pc, clusters):
    eb, ec = pb - y, pc - y; d = ec ** 2 - eb ** 2
    return {"n": int(len(y)), "clusters": int(len(np.unique(clusters))), "rmse_baseline": rmse(eb), "rmse_candidate": rmse(ec), "mae_baseline": float(np.abs(eb).mean()),
            "mae_candidate": float(np.abs(ec).mean()), "bias_baseline": float(eb.mean()), "bias_candidate": float(ec.mean()),
            "paired_delta_sq_err": float(d.mean()), "paired_delta_sq_err_95ci": boot_ci(d, clusters)}


def verify_protocol():
    sha = open(os.path.join(WORK, "protocol.sha256")).read().split()[0]
    got = hashlib.sha256(open(os.path.join(WORK, "protocol.json"), "rb").read()).hexdigest()
    assert sha == got, "protocol.json changed after freezing"
    return sha


def test():
    sha = verify_protocol()
    devr = json.load(open(os.path.join(OUT, "dev.json")))
    g = load_frames(); fr, b1h = all_frames(g)
    rep = {"status": "RESEARCH_ONLY", "protocol_sha256": sha, "variant": VARIANT, "builder_root": BUILDER, "baseline_fidelity": json.load(open(os.path.join(OUT, "baseline_fidelity.json"))),
           "inputs_used": inputs_used(), "inputs_certification": check_certified(), "dev": devr, "test": {}, "test_secondary": {}, "test_by_season": {},
           "situations_EXPLORATORY": {}, "playoffs": {}}
    preds_store = {}
    for t in TARGETS:
        sel = devr["targets"][t]["selected"]
        rep["test_secondary"][t] = {}
        for name, lvl in (("C1", "C1"), ("C2", "C2"), ("C3", "C2")):
            F = fr[t][lvl]; cols = cols_for(t, lvl, F); alpha = devr["targets"][t]["candidates"][name]["alpha"]
            m = Stack(alpha).fit(F[season_mask(F, FIT[0], VAL[1])], cols)
            te = F[season_mask(F, *TEST)]; pc = m.predict(te)
            cl = (te.meta_season.astype(str) + "-" + te.meta_week.astype(str)).to_numpy()
            res = paired(te.y.to_numpy(float), te.base.to_numpy(float), pc, cl)
            rep["test_secondary"][t][name] = res
            if name == sel:
                res = dict(res, candidate=sel); rep["test"][t] = res
                rep["test_by_season"][t] = {}
                for s in TEST:
                    k = (te.meta_season == s).to_numpy()
                    rep["test_by_season"][t][str(s)] = paired(te.y.to_numpy(float)[k], te.base.to_numpy(float)[k], pc[k], cl[k])
                # situations (EXPLORATORY)
                fitb = g[(g.season >= FIT[0]) & (g.season <= FIT[1]) & (g.post == 0)].base_total
                q1, q2 = float(fitb.quantile(1 / 3)), float(fitb.quantile(2 / 3))
                bt = te.meta_base_total.to_numpy(float)
                sit = {"projected_total_tercile": np.where(bt < q1, "low", np.where(bt < q2, "mid", "high")),
                       "divisional": np.where(te.meta_div_game.to_numpy(float) == 1, "divisional", "non_divisional"),
                       "rest_differential": np.where((te.meta_home_rest - te.meta_away_rest).abs().to_numpy(float) >= 3, "abs_ge_3", "lt_3"),
                       "dome": np.where(te.meta_roof.isin(["dome", "closed"]).to_numpy(), "dome_closed", "outdoor_open"),
                       "early_season": np.where(te.meta_week.to_numpy(int) <= 4, "weeks_1_4", "weeks_5_18")}
                rep["situations_EXPLORATORY"][t] = {"tercile_cuts_fit_seasons": [q1, q2]}
                for sname, lab in sit.items():
                    rep["situations_EXPLORATORY"][t][sname] = {str(v): paired(te.y.to_numpy(float)[lab == v], te.base.to_numpy(float)[lab == v], pc[lab == v], cl[lab == v])
                                                               for v in sorted(set(lab))}
                # playoffs
                po = F[(F.meta_season >= TEST[0]) & (F.meta_season <= TEST[1]) & (F.meta_post == 1)]
                if len(po):
                    pp = m.predict(po)
                    rep["playoffs"][t] = dict(paired(po.y.to_numpy(float), po.base.to_numpy(float), pp, po.meta_game_id.to_numpy()), candidate=sel,
                                              note="small sample; bootstrap clustered by game")
                # store predictions for price-aware (2025, REG + POST)
                allp = F[(F.meta_season == 2025)]
                preds_store[t] = pd.DataFrame({"game_id": allp.meta_game_id.values, 
                                               "cand": m.predict(allp), "base": allp.base.values, "y": allp.y.values, "post": allp.meta_post.values})
        print(t, {k: round(v, 3) if isinstance(v, float) else v for k, v in rep["test"][t].items()})
    rep["price_aware"] = price_aware(preds_store, devr, g)
    rep["notes"] = {"sigma_source": "validation (2022-2023) residual SD of the selected candidate (and of the baseline for the baseline arm), models fitted on 2012-2021",
                    "first_half_baseline": "linear map of the operating model's total (not an operating-model output)",
                    "baseline": "DATA_ONLY / Milestone-E market-free ridge (nfl-edge-finder), reproduced exactly from committed point-in-time features"}
    json.dump(rep, open(REPORT, "w"), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("report.json written")


# ================================================================================================ price-aware
def kickoff_ts(gameday, gametime):
    return int(datetime.fromisoformat(f"{gameday} {gametime}").replace(tzinfo=ZoneInfo("America/New_York")).timestamp())


def load_horizons():
    rows = []
    for f in sorted(glob.glob(os.path.join(BACKFILL, "horizons", "*.jsonl"))):
        if not os.path.basename(f)[0].isdigit():
            continue
        for line in open(f):
            r = json.loads(line)
            if r.get("series") in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL", "KXNFL1HTOTAL") and str(r.get("season")) == "2025":
                rows.append(r)
    return rows


def ml_quote_from_candles(ticker, kick):
    for d in ("candles_v2", "candles"):
        p = os.path.join(BACKFILL, d, "KXNFLGAME", f"{ticker}.json")
        if not os.path.exists(p):
            continue
        j = json.load(open(p)); best = None
        for arr in ("h60", "m1"):
            for c in j.get(arr) or []:
                ts = c.get("end_period_ts"); yb = (c.get("yes_bid") or {}).get("close"); ya = (c.get("yes_ask") or {}).get("close")
                if ts is None or yb is None or ya is None or ts > kick - 3600:
                    continue
                if best is None or ts > best[0]:
                    best = (ts, float(yb), float(ya), d, arr)
        if best:
            return best
    return None


MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def ml_rows(games25, st):
    """One pseudo-horizon row per KXNFLGAME 2025 ticker with a candle file, mapped to the schedule by date + team codes."""
    out, seen = [], set()
    for d in ("candles_v2", "candles"):
        for f in sorted(glob.glob(os.path.join(BACKFILL, d, "KXNFLGAME", "KXNFLGAME-*.json"))):
            tk = os.path.basename(f)[:-5]
            if tk in seen:
                continue
            seen.add(tk)
            ev, team = tk.split("-")[1], tk.split("-")[2]
            day = f"20{ev[:2]}-{MONTHS[ev[2:5]]:02d}-{ev[5:7]}"; codes = ev[7:]
            cand = games25[games25.gameday == day]
            k = lambda c: {"JAX": "JAC"}.get(c, c)          # Kalshi codes Jacksonville JAC
            gid = [i for i, x in cand.iterrows() if codes in (k(x.away_team) + k(x.home_team), k(x.home_team) + k(x.away_team))]
            if len(gid) != 1:
                continue
            out.append({"ticker": tk, "series": "KXNFLGAME", "game_id": gid[0], "team": team, "floor_strike": None, "anchor_kind": None, "anchor_ts": None, "result": None})
    return out


def settlements():
    out = {}
    for f in glob.glob(os.path.join(RAW, "kos", "NFL", "*.jsonl")):
        s = os.path.basename(f).split(".")[0]
        if s not in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL", "KXNFL1HTOTAL"):
            continue
        for line in open(f):
            r = json.loads(line)
            if r.get("result") in ("yes", "no"):
                out[r["ticker"]] = {"y": int(r["result"] == "yes"), "floor_strike": r.get("floor_strike"), "strike_type": r.get("strike_type"),
                                    "yes_sub_title": r.get("yes_sub_title"), "rules_primary": r.get("rules_primary")}
    return out


def price_aware(preds, devr, g):
    from scipy.stats import norm
    sys.path.insert(0, WORK)
    import selection as SEL
    proto = json.load(open(os.path.join(WORK, "protocol.json")))
    rules = proto["price_aware"]["rules"]
    st = settlements()
    games25 = g[g.season == 2025].set_index("game_id")
    # moneyline rows come from the candle files themselves (the horizons file has no Rams games); spread/total families from horizons T-90m
    hz = [r for r in load_horizons() if r["series"] != "KXNFLGAME"] + ml_rows(games25, st)
    sd = {t: {"cand": devr["targets"][t]["candidates"][devr["targets"][t]["selected"]]["val_resid_sd"], "base": devr["targets"][t]["baseline_val_resid_sd"]} for t in TARGETS}
    P = {t: preds[t] for t in TARGETS}
    gp = {}
    for t in ("game_total", "margin", "first_half_total"):
        gp[t] = P[t].set_index("game_id")
    tp = P["team_points"].copy()
    tp["side"] = np.where(tp.groupby("game_id").cumcount() == 0, "h", "a")
    tp = tp.set_index(["game_id", "side"])
    rows, skipped = [], {}
    def skip(k):
        skipped[k] = skipped.get(k, 0) + 1
    for r in hz:
        gid = r["game_id"]; tk = r["ticker"]; ser = r["series"]
        if gid not in games25.index:
            skip("game_not_in_schedule"); continue
        if tk not in st:
            skip("no_official_settlement"); continue
        x = games25.loc[gid]; kick = int(r["anchor_ts"]) if r.get("anchor_kind") == "kickoff" and r.get("anchor_ts") else kickoff_ts(x.gameday, x.gametime)
        if ser == "KXNFLGAME":
            q = ml_quote_from_candles(tk, kick)
            if q is None:
                skip("ml_no_candle_quote"); continue
            ts, yb, ya, src, arr = q; age = (kick - ts) / 60
        else:
            s = (r.get("snaps") or {}).get("T-90m")
            if not s or s.get("book_empty") or s.get("bid") is None or s.get("ask") is None or s["ts"] > kick - 3600 or (s.get("age_min") or 0) > 180:
                skip(f"{ser}_no_valid_T-90m"); continue
            ts, yb, ya, src, arr = s["ts"], float(s["bid"]), float(s["ask"]), "horizons", "T-90m"; age = (kick - ts) / 60
        if not (0 < yb < ya < 1):
            skip(f"{ser}_not_two_sided"); continue
        team = r.get("team"); k = r.get("floor_strike")
        is_home = None
        if team is not None:
            ht, at = x.home_team, x.away_team
            alias = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS"}
            tm = alias.get(team, team)
            is_home = True if tm == ht else False if tm == at else None
            if is_home is None:
                skip(f"{ser}_team_unmapped"); continue
        out = {}
        for arm in ("cand", "base"):
            if ser == "KXNFLGAME":
                mu = gp["margin"].loc[gid, arm]; sig = sd["margin"][arm]; p = norm.sf(0, loc=mu if is_home else -mu, scale=sig); fam = "moneyline"
            elif ser == "KXNFLSPREAD":
                mu = gp["margin"].loc[gid, arm]; sig = sd["margin"][arm]; p = norm.sf(float(k), loc=mu if is_home else -mu, scale=sig); fam = "spread"
            elif ser == "KXNFLTOTAL":
                mu = gp["game_total"].loc[gid, arm]; sig = sd["game_total"][arm]; p = norm.sf(float(k), loc=mu, scale=sig); fam = "total"
            elif ser == "KXNFL1HTOTAL":
                if gid not in gp["first_half_total"].index:
                    break
                mu = gp["first_half_total"].loc[gid, arm]; sig = sd["first_half_total"][arm]; p = norm.sf(float(k), loc=mu, scale=sig); fam = "first_half_total"
            else:
                mu = tp.loc[(gid, "h" if is_home else "a"), arm]; sig = sd["team_points"][arm]; p = norm.sf(float(k), loc=mu, scale=sig); fam = "team_total"
            out[arm] = float(p)
        if len(out) < 2:
            skip(f"{ser}_no_projection"); continue
        rows.append({"game_id": gid, "contract_id": tk, "family": fam, "yes_bid": yb, "yes_ask": ya, "model_p": out["cand"], "base_p": out["base"], "y": st[tk]["y"],
                     "date": x.gameday, "post": int(x.game_type != "REG"), "entry_age_min": age, "quote_source": f"{src}:{arr}", "floor_strike": k, "team": team,
                     "horizon_result": r.get("result")})
    C = pd.DataFrame(rows)
    C.to_parquet(os.path.join(OUT, "contracts_2025.parquet"))
    res = {"contracts_by_family": C.groupby(["post", "family"]).size().unstack(0).fillna(0).astype(int).to_dict(), "skipped": skipped,
           "settlement_agreement_with_backfill_result": float((C.y == (C.horizon_result == "yes").astype(int)).mean()),
           "entry_age_minutes_quantiles": {str(q): float(C.entry_age_min.quantile(q)) for q in (0, 0.5, 0.95, 1)},
           "sigma_used": sd, "regular_season": {}, "playoffs": {}}
    for lab, sub in (("regular_season", C[C.post == 0]), ("playoffs", C[C.post == 1])):
        if len(sub) == 0:
            continue
        res[lab]["selected_candidate"] = SEL.evaluate(sub, rules, boot=2000, seed=13)
        res[lab]["baseline_secondary"] = SEL.evaluate(sub.assign(model_p=sub.base_p), rules, boot=2000, seed=13)
        res[lab]["diagnostics_by_family"] = {f: {"selected": SEL.diagnostics(v), "baseline": SEL.diagnostics(v.assign(model_p=v.base_p))} for f, v in sub.groupby("family")}
    return res


def diag():
    """Post-scoring data-integrity diagnostics appended to report.json (no model, rule or selection is changed)."""
    rep = json.load(open(REPORT))
    C = pd.read_parquet(os.path.join(OUT, "contracts_2025.parquet")); g = load_frames().set_index("game_id")
    nm = C[C.family != "moneyline"]
    alias = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS"}

    def derived(r):
        x = g.loc[r.game_id]; tm = alias.get(r.team, r.team) if r.team else None; hm = x.home_score - x.away_score
        if r.family == "moneyline":
            return int((hm if tm == x.home_team else -hm) > 0)
        if r.family == "spread":
            return int((hm if tm == x.home_team else -hm) > r.floor_strike)
        if r.family == "total":
            return int(x.total > r.floor_strike)
        if r.family == "first_half_total":
            return int(x.first_half_total > r.floor_strike)
        return int((x.home_score if tm == x.home_team else x.away_score) > r.floor_strike)
    d = C.apply(derived, axis=1)
    rep["price_aware"]["settlement_agreement_with_backfill_result"] = {
        "non_moneyline_rows": int(len(nm)), "agreement": float((nm.y == (nm.horizon_result == "yes").astype(int)).mean()),
        "note": "moneyline rows are built from candle files and carry no backfill result; the earlier single number mixed them in and is superseded"}
    rep["price_aware"]["official_settlement_vs_box_score"] = {f: {"n": int((C.family == f).sum()), "agreement": float((C.y[C.family == f] == d[C.family == f]).mean())} for f in sorted(C.family.unique())}
    rep["price_aware"]["entry_age_minutes_by_family"] = {f: {"median": float(v.entry_age_min.median()), "max": float(v.entry_age_min.max())} for f, v in C.groupby("family")}
    rep["price_aware"]["games_covered"] = {f: int(v.game_id.nunique()) for f, v in C.groupby("family")}
    json.dump(rep, open(REPORT, "w"), indent=1)
    print(json.dumps({k: rep["price_aware"][k] for k in ("settlement_agreement_with_backfill_result", "official_settlement_vs_box_score", "games_covered")}, indent=0))


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("prep", "all"):
        prep()
    if stage in ("dev", "all"):
        dev()
    if stage in ("test", "all"):
        test()
    if stage in ("diag", "all"):
        diag()

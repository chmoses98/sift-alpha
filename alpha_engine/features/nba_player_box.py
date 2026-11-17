"""NBA player-box dataset: minutes tail, points ceiling, stat covariance and team bench minutes (RESEARCH_ONLY).

    python -m alpha_engine.features.nba_player_box --root <restored vault NBA archive> --out nba_player_box.parquet [--evidence OUT.json]

Specification: docs/certification/NBA_PLAYER_BOX_SPEC.md v1. PRIMARY builder; `certify/nba_player_box_independent.py` is written
from the spec alone. Source: sift-data-vault archives/NBA/espn_pbp_boxes_schedules (ESPN player boxes 2002-2027).
Every feature of a row uses only same-season rows on strictly earlier calendar dates.
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = "docs/certification/NBA_PLAYER_BOX_SPEC.md v1.1"
USE = ["game_id", "season", "season_type", "game_date", "athlete_id", "team_id", "minutes", "points", "rebounds", "assists", "starter"]
PLAYER_F = ["n_rows_pre", "n_app_pre", "app_rate_pre", "min_mean_pre", "min_last5_pre", "start_rate_pre", "heavy38_rate_pre", "full30_n_pre",
            "pts_ge25_full30_pre", "pts_ge30_full30_pre", "pts_p90_full30_pre", "cov_pts_reb_pre", "cov_pts_ast_pre", "cov_reb_ast_pre",
            "var_pra_pre", "pra_var_ratio_pre"]
TEAM_F = ["team_games_pre", "team_bench_share_pre", "team_bench_min_mean_pre", "team_bench_min_sd_pre"]
FEATURES = PLAYER_F + TEAM_F
LABELS = ["y_appeared", "y_minutes", "y_points", "y_rebounds", "y_assists", "y_starter"]
COLUMNS = ["key", "game_id", "athlete_id", "team_id", "season", "date"] + FEATURES + LABELS
CATALOG = {"nba.heavy_minutes_tail_prob": ["heavy38_rate_pre", "full30_n_pre", "n_app_pre"],
           "nba.points_upper_tail_rate": ["full30_n_pre", "pts_ge25_full30_pre", "pts_ge30_full30_pre", "pts_p90_full30_pre"],
           "nba.combo_covariance": ["cov_pts_reb_pre", "cov_pts_ast_pre", "cov_reb_ast_pre", "var_pra_pre", "pra_var_ratio_pre"],
           "nba.bench_minutes_distribution": ["team_bench_share_pre", "team_bench_min_mean_pre", "team_bench_min_sd_pre"]}


def load_raw(root) -> pd.DataFrame:
    files = sorted(glob.glob(str(Path(root) / "**" / "player_box_*.parquet"), recursive=True))
    return pd.concat([pd.read_parquet(f, columns=USE) for f in files], ignore_index=True)


def rows(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    drop = {}
    p = raw[(raw["season_type"] == 2) & raw["athlete_id"].notna() & raw["team_id"].notna()].copy()
    drop["not_regular_or_no_id"] = int(len(raw) - len(p))
    for c in ("game_id", "athlete_id", "team_id", "season"):
        p[c] = p[c].astype("int64")
    p["date"] = pd.to_datetime(p["game_date"]).dt.strftime("%Y-%m-%d")
    n0 = len(p)
    p = p.drop_duplicates(["game_id", "athlete_id"], keep="first")
    drop["duplicate_rows"] = int(n0 - len(p))
    ng = p.groupby(["season", "team_id"])["game_id"].transform("nunique")
    drop["non_league_team_rows"] = int((ng < 5).sum())
    p = p[ng >= 5].copy()
    p["appeared"] = p["minutes"].notna() & (p["minutes"] > 0)
    p["starter_b"] = p["starter"].map(lambda v: v is True or (isinstance(v, (bool, np.bool_)) and bool(v)))
    for c in ("points", "rebounds", "assists"):
        p[c + "_z"] = p[c].fillna(0.0).astype(float)
    p["minutes"] = p["minutes"].astype(float)
    return p.sort_values(["season", "athlete_id", "date", "game_id"]).reset_index(drop=True), drop


def _prior_cum(df: pd.DataFrame, group: list[str], cols: dict[str, pd.Series]) -> pd.DataFrame:
    """Cumulative sums over strictly earlier dates within group (rows sorted by group, date, game_id)."""
    out = {}
    g = df[group + ["date"]].copy()
    for name, s in cols.items():
        g[name] = s.to_numpy(float)
    # sum per (group, date) first so same-date rows never see each other, then shift the cumulative sum by one date
    day = g.groupby(group + ["date"], sort=False)[list(cols)].sum()
    cum = day.groupby(level=list(range(len(group))), sort=False).cumsum()
    prior = cum.groupby(level=list(range(len(group))), sort=False).shift(1).fillna(0.0)
    idx = pd.MultiIndex.from_frame(df[group + ["date"]])
    pr = prior.reindex(idx)
    for name in cols:
        out[name] = pr[name].to_numpy()
    return pd.DataFrame(out, index=df.index)


def _div(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)


def player_features(p: pd.DataFrame) -> pd.DataFrame:
    grp = ["season", "athlete_id"]
    a = p["appeared"].astype(float)
    m = p["minutes"].fillna(0.0) * a
    pts, reb, ast = p["points_z"] * a, p["rebounds_z"] * a, p["assists_z"] * a
    full = a * (p["minutes"].fillna(0) >= 30)
    pra = pts + reb + ast
    c = _prior_cum(p, grp, {"rows": pd.Series(1.0, index=p.index), "app": a, "min": m, "start": a * p["starter_b"], "h38": a * (p["minutes"].fillna(0) >= 38),
                            "f30": full, "f25": full * (p["points_z"] >= 25), "f30p": full * (p["points_z"] >= 30),
                            "sp": pts, "sr": reb, "sa": ast, "spp": pts * pts, "srr": reb * reb, "saa": ast * ast,
                            "spr": pts * reb, "spa": pts * ast, "sra": reb * ast, "sq": pra, "sqq": pra * pra})
    f = pd.DataFrame(index=p.index)
    f["n_rows_pre"] = c["rows"]
    f["n_app_pre"] = c["app"]
    f["app_rate_pre"] = _div(c["app"], c["rows"])
    f["min_mean_pre"] = _div(c["min"], c["app"])
    f["start_rate_pre"] = _div(c["start"], c["app"])
    f["heavy38_rate_pre"] = _div(c["h38"], c["app"])
    f["full30_n_pre"] = c["f30"]
    f["pts_ge25_full30_pre"] = _div(c["f25"], c["f30"])
    f["pts_ge30_full30_pre"] = _div(c["f30p"], c["f30"])
    n = c["app"].to_numpy()
    ok = n >= 5

    def cov(sxy, sx, sy):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = (sxy - sx * sy / np.where(n > 0, n, 1)) / np.where(n > 1, n - 1, 1)
        return np.where(ok, v, np.nan)

    f["cov_pts_reb_pre"] = cov(c["spr"].to_numpy(), c["sp"].to_numpy(), c["sr"].to_numpy())
    f["cov_pts_ast_pre"] = cov(c["spa"].to_numpy(), c["sp"].to_numpy(), c["sa"].to_numpy())
    f["cov_reb_ast_pre"] = cov(c["sra"].to_numpy(), c["sr"].to_numpy(), c["sa"].to_numpy())
    f["var_pra_pre"] = cov(c["sqq"].to_numpy(), c["sq"].to_numpy(), c["sq"].to_numpy())
    den = cov(c["spp"].to_numpy(), c["sp"].to_numpy(), c["sp"].to_numpy()) + cov(c["srr"].to_numpy(), c["sr"].to_numpy(), c["sr"].to_numpy()) \
        + cov(c["saa"].to_numpy(), c["sa"].to_numpy(), c["sa"].to_numpy())
    f["pra_var_ratio_pre"] = np.where(ok & (den > 0), f["var_pra_pre"].to_numpy() / np.where(den > 0, den, 1), np.nan)
    # last-5 prior appearances and the full-30 p90: computed on the appearance subsequence, carried to later dates
    app = p[p["appeared"]][grp + ["date", "game_id", "minutes", "points_z"]].copy()
    app["last5"] = app.groupby(grp, sort=False)["minutes"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    fu = app[app["minutes"] >= 30].copy()
    fu["p90"] = fu.groupby(grp, sort=False)["points_z"].transform(lambda s: s.expanding().quantile(0.9))
    fu["cnt"] = fu.groupby(grp, sort=False).cumcount() + 1
    fu.loc[fu["cnt"] < 5, "p90"] = np.nan
    f["min_last5_pre"] = _carry(p, app, "last5", grp)
    f["pts_p90_full30_pre"] = _carry(p, fu, "p90", grp)
    return f


def _carry(p: pd.DataFrame, sub: pd.DataFrame, col: str, grp: list[str]) -> np.ndarray:
    """Value of `col` at the last `sub` row of the same group dated strictly before each row of `p` (NaN when none)."""
    s = sub[grp + ["date", col]].copy()
    s = s.groupby(grp + ["date"], sort=False)[col].last().reset_index()
    s["_d"] = pd.to_datetime(s["date"]) + pd.Timedelta(days=1)     # usable from the next calendar date on
    left = p[grp + ["date"]].copy()
    left["_d"] = pd.to_datetime(left["date"])
    left["_i"] = np.arange(len(left))
    left = left.sort_values("_d")
    s = s.sort_values("_d")
    mg = pd.merge_asof(left, s[grp + ["_d", col]], on="_d", by=grp, direction="backward")
    out = np.full(len(p), np.nan)
    out[mg["_i"].to_numpy()] = mg[col].to_numpy(float)
    return out


def team_features(p: pd.DataFrame) -> pd.DataFrame:
    a = p[p["appeared"]]
    tg = (p[["season", "team_id", "game_id", "date"]].drop_duplicates(["game_id", "team_id"])
          .merge(a.assign(bm=np.where(a["starter_b"], 0.0, a["minutes"]))
                 .groupby(["game_id", "team_id"]).agg(bench_min=("bm", "sum"), all_min=("minutes", "sum")).reset_index(),
                 on=["game_id", "team_id"], how="left"))
    tg[["bench_min", "all_min"]] = tg[["bench_min", "all_min"]].fillna(0.0)
    tg["share"] = _div(tg["bench_min"], tg["all_min"])
    tg = tg.sort_values(["season", "team_id", "date", "game_id"]).reset_index(drop=True)
    has = tg["share"].notna().astype(float)
    c = _prior_cum(tg, ["season", "team_id"], {"n": pd.Series(1.0, index=tg.index), "sh_n": has, "sh": tg["share"].fillna(0.0),
                                                "bm": tg["bench_min"], "bm2": tg["bench_min"] ** 2})
    n = c["n"].to_numpy()
    tg["team_games_pre"] = n
    tg["team_bench_share_pre"] = _div(c["sh"], c["sh_n"])
    tg["team_bench_min_mean_pre"] = _div(c["bm"], c["n"])
    with np.errstate(divide="ignore", invalid="ignore"):
        var = (c["bm2"].to_numpy() - c["bm"].to_numpy() ** 2 / np.where(n > 0, n, 1)) / np.where(n > 1, n - 1, 1)
    tg["team_bench_min_sd_pre"] = np.where(n >= 2, np.sqrt(np.clip(var, 0, None)), np.nan)
    return tg[["game_id", "team_id"] + TEAM_F]


def build(raw: pd.DataFrame) -> pd.DataFrame:
    p, _ = rows(raw)
    f = player_features(p)
    d = pd.concat([p[["game_id", "athlete_id", "team_id", "season", "date"]], f[PLAYER_F]], axis=1)
    d = d.merge(team_features(p), on=["game_id", "team_id"], how="left")
    d["y_appeared"] = p["appeared"].astype(float).to_numpy()
    d["y_minutes"] = np.where(p["appeared"], p["minutes"], 0.0)
    for s in ("points", "rebounds", "assists"):
        d[f"y_{s}"] = np.where(p["appeared"], p[f"{s}_z"], np.nan)
    d["y_starter"] = p["starter_b"].astype(float).to_numpy()
    d["key"] = d["game_id"].astype(str) + ":" + d["athlete_id"].astype(str)
    d = d[COLUMNS].sort_values(["date", "game_id", "athlete_id"]).reset_index(drop=True)
    for c in FEATURES + LABELS:
        d[c] = d[c].astype("float64")
    return d


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    x, y = a[FEATURES].to_numpy(float), b[FEATURES].to_numpy(float)
    return bool(x.shape == y.shape and ((np.isnan(x) & np.isnan(y)) | np.isclose(x, y, rtol=1e-9, atol=1e-9)).all())


def leakage_checks(raw: pd.DataFrame, d: pd.DataFrame, dates: list[str], seed: int = 7) -> dict:
    """Per cut date D (same season): truncation (rebuild from rows dated <= D), future scramble (perturb minutes/points/rebounds/assists/
    starter of rows dated >= D) and own game (perturb rows dated == D): rows dated <= D (== D for own game) must be identical."""
    rng = np.random.default_rng(seed)
    gd = pd.to_datetime(raw["game_date"])
    by = d.set_index("key")
    out = {}
    for D in dates:
        cut = pd.Timestamp(D)
        dd = pd.to_datetime(d["date"])
        season = int(d[dd <= cut]["season"].max())
        keys = d[(dd <= cut) & (d["season"] == season)]["key"].tolist()
        own = d[dd == cut]["key"].tolist()
        later = d[(dd > cut) & (d["season"] == season)]["key"].tolist()
        tr = build(raw[gd <= cut]).set_index("key")

        def scr(mask):
            x = raw.copy()
            k = mask.to_numpy()
            for c in ("minutes", "points", "rebounds", "assists"):
                x[c] = x[c].to_numpy(float) + np.where(k, rng.integers(1, 9, size=len(x)), 0)
            x["starter"] = np.where(k, ~x["starter"].fillna(False).astype(bool), x["starter"])
            return build(x).set_index("key")
        fu, og = scr(gd >= cut), scr(gd == cut)
        out[D] = {"season": season, "rows_checked": len(keys), "truncation_identical": _same(tr.reindex(keys), by.reindex(keys)),
                  "future_scramble_identical": _same(fu.reindex(keys), by.reindex(keys)), "future_games_checked": len(keys),
                  "own_game_identical": _same(og.reindex(own), by.reindex(own)) if own else True, "own_rows": len(own),
                  "perturbation_reaches_later_games": bool(not _same(fu.reindex(later), by.reindex(later)))}
    return out


def evidence(raw: pd.DataFrame, d: pd.DataFrame, checks: dict) -> dict:
    from ..foundation.training_sets import canonical_hash

    _, drop = rows(raw)
    return {"schema": "nba-player-box-dataset-1.0", "status": "RESEARCH_ONLY", "spec": SPEC, "builder": "alpha_engine.features.nba_player_box",
            "rows": int(len(d)), "columns": len(d.columns), "features": len(FEATURES), "dropped": drop,
            "seasons": {str(k): int(v) for k, v in d["season"].value_counts().sort_index().items()}, "date_range": [d["date"].min(), d["date"].max()],
            "keys_unique": bool(not d["key"].duplicated().any()), "canonical_sha256": canonical_hash(d),
            "deterministic_regeneration": canonical_hash(build(raw)) == canonical_hash(d),
            "appeared_share": round(float(d["y_appeared"].mean()), 6), "leakage": checks, "catalog_columns": CATALOG}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--evidence")
    ap.add_argument("--dates", default="2008-01-12,2016-03-05,2024-12-14,2026-11-10")
    a = ap.parse_args(argv)
    raw = load_raw(a.root)
    d = build(raw)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(a.out, index=False)
    if a.evidence:
        ev = evidence(raw, d, leakage_checks(raw, d, a.dates.split(",")))
        Path(a.evidence).write_text(json.dumps(ev, indent=1, sort_keys=True) + "\n")
        print(json.dumps({k: ev[k] for k in ("rows", "canonical_sha256", "deterministic_regeneration", "dropped", "leakage")}, indent=1))
    else:
        print(len(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

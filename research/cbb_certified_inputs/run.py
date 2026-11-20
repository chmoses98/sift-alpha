"""SIFT CBB prediction experiment (RESEARCH_ONLY): do certified SIFT Alpha CBB inputs improve the
cbb-edge-finder incumbent (pure-0.2.0 / B9) pregame margin and total projections on unseen seasons?

Single entry point:  PYTHONDONTWRITEBYTECODE=1 python run.py [--stage all|data|incumbent|features|analyse]

Reads (never writes) /home/user/cbb-edge-finder, /home/user/sift-alpha-ops, /home/user/sift-data-vault.
Everything is written under WORK (this file's directory). The frozen protocol is protocol.json
(sha256 in protocol.sha256); this script refuses to analyse if the hash does not match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
CBB_REPO = Path("/home/user/cbb-edge-finder")
SIFT_REPO = Path("/home/user/sift-alpha-ops")
VAULT = Path("/home/user/sift-data-vault")
CODE = WORK / "cbb_code"                 # copy of cbb-edge-finder (caches and relative outputs land here)
DATA = WORK / "cbbdata"                  # CBB_DATA_DIR for the incumbent pipeline
VREST = WORK / "vault"
DL = WORK / "dl"
FEAT = WORK / "feat" / "cbb_derived_team.parquet"
DATASET = WORK / "feat" / "dataset.parquet"
REPORT = WORK / "report.json"
ARCH = {
    "espn_team_box_schedules": "archives/CBB/espn_team_box_schedules/2006-2027/sportsdataverse/snapshot-20261116",
    "espn_player_box_pbp_early_seasons": "archives/CBB/espn_player_box_pbp_early_seasons/2003-2027/sportsdataverse/snapshot-20261116",
}
CERT_COLS = ["off_efg_pre", "off_tov_pct_pre", "off_orb_pct_pre", "off_ftr100_pre", "def_efg_pre", "def_tov_pct_pre", "def_orb_pct_pre",
             "def_ftr100_pre", "mx_efg_pre", "mx_tov_pct_pre", "mx_orb_pct_pre", "mx_ftr100_pre", "ff_edge_pre", "pace_pre", "exp_poss_add_pre",
             "exp_poss_pre", "off_ortg_pre", "exp_pts_pre", "def_ortg_pre", "opp_exp_pts_pre", "exp_poss_elastic_pre", "exp_fta_pre", "exp_ft_pts_pre"]
FIT, VAL, TEST = list(range(2016, 2023)), [2023, 2024], [2025, 2026]
MX = ["mx_efg_pre", "mx_tov_pct_pre", "mx_orb_pct_pre", "mx_ftr100_pre", "exp_ft_pts_pre"]
ALPHAS = [0.1, 1, 10, 100, 1000, 10000, 100000]


def env() -> dict:
    e = dict(os.environ, CBB_DATA_DIR=str(DATA), PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(CODE))
    return e


def sh(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env(), check=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ stage: data
def stage_data() -> None:
    if not CODE.exists():
        CODE.mkdir(parents=True)
        subprocess.run(f"tar --exclude=.git -C {CBB_REPO} -cf - . | tar -xf - -C {CODE}", shell=True, check=True)
    for name, rel in ARCH.items():
        if not (VREST / name).exists():
            sh([sys.executable, str(VAULT / "tools/vault.py"), "restore", "--path", str(VAULT / rel), "--to", str(VREST / name)], cwd=VAULT)
    man = [json.loads(x) for x in (CBB_REPO / "manifests/bronze/sportsdataverse_releases.jsonl").read_text().splitlines()]
    pins = {(r["dataset"], r["season"]): r for r in man}
    DL.mkdir(exist_ok=True)
    B = DATA / "bronze" / "sportsdataverse_releases"
    for ds in ("schedules", "team_box", "player_box", "ncaa_lineups", "ncaa_possessions"):
        (B / ds).mkdir(parents=True, exist_ok=True)
    audit = {"ncaa_pin_match": 0, "ncaa_pin_mismatch": [], "espn_pin_match": [], "espn_pin_diff": []}
    for ds in ("ncaa_lineups", "ncaa_possessions"):
        for s in range(2010, 2027):
            r = pins[(ds, s)]
            fn = r["url"].split("/")[-1]
            dst = B / ds / fn
            if not dst.exists():
                tmp = DL / f"{ds}__{fn}"
                if not tmp.exists():
                    subprocess.run(["curl", "-sS", "-L", "--retry", "3", "-o", str(tmp), r["url"]], check=True)
                if sha(tmp) != r["sha256"]:
                    audit["ncaa_pin_mismatch"].append(fn)
                    continue
                dst.write_bytes(tmp.read_bytes())
            audit["ncaa_pin_match"] += int(sha(dst) == r["sha256"])
    if audit["ncaa_pin_mismatch"]:
        raise SystemExit(f"STOP: NCAA files differ from the incumbent's pins: {audit['ncaa_pin_mismatch']}")
    src = {"schedules": VREST / "espn_team_box_schedules/schedules", "team_box": VREST / "espn_team_box_schedules/team_box",
           "player_box": VREST / "espn_player_box_pbp_early_seasons/espn_mens_college_basketball_player_boxscores"}
    for ds, d in src.items():
        for f in sorted(d.glob("*.parquet")):
            dst = B / ds / f.name
            if not dst.exists():
                dst.write_bytes(f.read_bytes())
            s = int(f.stem[-4:])
            if (ds, s) in pins and 2006 <= s <= 2026:
                (audit["espn_pin_match"] if sha(dst) == pins[(ds, s)]["sha256"] else audit["espn_pin_diff"]).append(f"{ds}_{s}")
    (WORK / "feat").mkdir(exist_ok=True)
    (WORK / "feat" / "data_audit.json").write_text(json.dumps(audit, indent=1))
    if not (DATA / "silver" / "games.parquet").exists():
        sh([sys.executable, "-c", "from cbb_edge.data.silver.build import build; build(list(range(2006, 2027)), update_registry=False)"], cwd=CODE)
    if not (DATA / "silver" / "stints" / "_summary.csv").exists():
        (DATA / "silver" / "stints").mkdir(parents=True, exist_ok=True)
        sh([sys.executable, "-m", "cbb_edge.players.stints", "--seasons", "2011-2026"], cwd=CODE)
    if not (DATA / "silver" / "shot_profile.parquet").exists():
        sh([sys.executable, "-m", "cbb_edge.features.shot_profile", "--seasons", "2010-2026"], cwd=CODE)


# ------------------------------------------------------------------ stage: incumbent (walk-forward B9, unmodified repo script)
def stage_incumbent() -> None:
    if not (DATA / "research" / "wave2" / "pure_predictions.parquet").exists():
        sh([sys.executable, "scripts/research/run_wave2.py"], cwd=CODE)


# ------------------------------------------------------------------ stage: certified features (unmodified certified engine, read in place)
def stage_features() -> None:
    if FEAT.exists():
        return
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SIFT_REPO))
    from alpha_engine.derived import basketball as B  # noqa: E402
    _, _, f = B.build(VREST / "espn_team_box_schedules", "CBB")
    FEAT.parent.mkdir(exist_ok=True)
    f.to_parquet(FEAT, index=False)


# ------------------------------------------------------------------ fidelity
def fidelity(inc: pd.DataFrame) -> dict:
    committed = json.loads((CBB_REPO / "research/wave2/metrics.json").read_text())
    ours = json.loads((CODE / "research/wave2/metrics.json").read_text())
    rows = {}
    for split in ("validation", "historical"):
        c, o = committed["arms"]["B9"][split], ours["arms"]["B9"][split]
        rows[split] = {"committed": {"n": c["n"], "margin_rmse": c["margin"]["rmse"], "total_rmse": c["total"]["rmse"], "log_loss": c["wp"]["log_loss"]},
                       "reproduced": {"n": o["n"], "margin_rmse": o["margin"]["rmse"], "total_rmse": o["total"]["rmse"], "log_loss": o["wp"]["log_loss"]},
                       "by_season": {s: {"committed": [c["by_season"][s]["n"], round(c["by_season"][s]["margin_rmse"], 4), round(c["by_season"][s]["total_rmse"], 4)],
                                         "reproduced": [o["by_season"].get(s, {}).get("n"), round(o["by_season"].get(s, {}).get("margin_rmse", np.nan), 4),
                                                        round(o["by_season"].get(s, {}).get("total_rmse", np.nan), 4)]} for s in c["by_season"]}}
    fz_c = json.loads((CBB_REPO / "models/pure/pure-0.2.0.json").read_text())
    fz_o = json.loads((CODE / "models/pure/pure-0.2.0.json").read_text())
    fz = {}
    for t in ("margin", "total"):
        same_feat = fz_c[t]["features"] == fz_o[t]["features"]
        cc, co = np.array(fz_c[t]["coef"]), np.array(fz_o[t]["coef"])
        fz[t] = {"same_feature_list": same_feat, "n_features": len(cc), "max_abs_coef_diff": float(np.max(np.abs(cc - co))) if same_feat else None,
                 "corr_coef": float(np.corrcoef(cc, co)[0, 1]) if same_feat else None,
                 "intercept": [fz_c[t]["intercept"], fz_o[t]["intercept"]]}
    fz["sigma_margin"] = [fz_c["sigma_margin"], fz_o["sigma_margin"]]
    fz["sigma_total"] = [fz_c["sigma_total"], fz_o["sigma_total"]]
    fz["sha256_identical"] = fz_c["sha256"] == fz_o["sha256"]
    dm = max(abs(rows[s]["committed"]["margin_rmse"] - rows[s]["reproduced"]["margin_rmse"]) for s in rows)
    dt = max(abs(rows[s]["committed"]["total_rmse"] - rows[s]["reproduced"]["total_rmse"]) for s in rows)
    return {"walkforward_B9": rows, "frozen_artefact": fz, "max_abs_split_rmse_diff": {"margin": dm, "total": dt},
            "verdict": "FAITHFUL" if dm < 0.02 and dt < 0.02 else "NOT_FAITHFUL"}


# ------------------------------------------------------------------ dataset
def build_dataset() -> tuple[pd.DataFrame, dict]:
    sys.path.insert(0, str(CODE))
    os.environ["CBB_DATA_DIR"] = str(DATA)
    from cbb_edge.model import arms  # noqa: E402
    games = pd.read_parquet(DATA / "silver" / "games.parquet")
    pp = pd.read_parquet(DATA / "research" / "wave2" / "pure_predictions.parquet")
    st = pd.read_parquet(DATA / "research" / "wave2" / "states_shot.parquet", columns=["game_id", "h_games_seen", "a_games_seen"])
    df = pp[["game_id", "season", "B9_margin", "B9_total", "B9_home_wp"]].merge(st.drop_duplicates("game_id"), on="game_id", how="left")
    df = arms.attach_games(df, games)
    df = df.merge(games[["game_id", "home_espn_id", "away_espn_id"]], on="game_id", how="left").reset_index(drop=True)
    df["inc_margin_sd"] = arms.residual_sd(df, df["B9_margin"], "margin")
    df["inc_total_sd"] = arms.residual_sd(df, df["B9_total"], "total")
    df = df[df["season"].between(2016, 2026) & df["B9_margin"].notna() & df["B9_total"].notna() & df["margin"].notna()].copy()
    n_inc = len(df)
    f = pd.read_parquet(FEAT)
    f["game_id"] = f["game_id"].astype("int64")
    f["team"] = f["team"].astype("int64")
    keep = ["game_id", "team", "home", "neutral", "date"] + CERT_COLS
    fh = f[keep].add_suffix("_h").rename(columns={"game_id_h": "game_id", "team_h": "home_espn_id"})
    fa = f[keep].add_suffix("_a").rename(columns={"game_id_a": "game_id", "team_a": "away_espn_id"})
    df["home_espn_id"] = df["home_espn_id"].astype("int64")
    df["away_espn_id"] = df["away_espn_id"].astype("int64")
    df = df.merge(fh, on=["game_id", "home_espn_id"], how="left").merge(fa, on=["game_id", "away_espn_id"], how="left")
    have_h, have_a = df["exp_pts_pre_h"].notna(), df["exp_pts_pre_a"].notna()
    need = [f"{c}_{s}" for c in ["exp_pts_pre", "exp_poss_pre", "def_ortg_pre"] + MX for s in "ha"]
    complete = df[need].notna().all(axis=1)
    cov = {"incumbent_games_2016_2026": n_inc, "home_row_joined": int(have_h.sum()), "away_row_joined": int(have_a.sum()),
           "complete_feature_rows": int(complete.sum()),
           "by_season": {int(s): {"incumbent": int((df.season == s).sum()), "complete": int((complete & (df.season == s)).sum())} for s in sorted(df.season.unique())}}
    j = have_h & have_a
    cov["orientation"] = {
        "certified_home_flag_on_incumbent_home_row": float(df.loc[j, "home_h"].mean()),
        "certified_home_flag_on_incumbent_away_row": float(df.loc[j, "home_a"].mean()),
        "certified_neutral_eq_incumbent_neutral": float((df.loc[j, "neutral_h"].astype(bool) == df.loc[j, "neutral_site"].astype(bool)).mean()),
        "max_abs(home.opp_exp_pts_pre - away.exp_pts_pre)": float((df.loc[j, "opp_exp_pts_pre_h"] - df.loc[j, "exp_pts_pre_a"]).abs().max()),
        "max_abs(away.opp_exp_pts_pre - home.exp_pts_pre)": float((df.loc[j, "opp_exp_pts_pre_a"] - df.loc[j, "exp_pts_pre_h"]).abs().max()),
        "max_abs(exp_poss_pre_h - exp_poss_pre_a)": float((df.loc[j, "exp_poss_pre_h"] - df.loc[j, "exp_poss_pre_a"]).abs().max()),
        "corr(certified exp margin, incumbent margin)": float(np.corrcoef((df.loc[j, "exp_pts_pre_h"] - df.loc[j, "exp_pts_pre_a"]), df.loc[j, "B9_margin"])[0, 1]),
        "date_match_share(certified date == incumbent ET date)": float((pd.to_datetime(df.loc[j, "date_h"]).dt.date == df.loc[j, "game_date_et"]).mean()),
    }
    df = df[complete].reset_index(drop=True)
    df["inc_margin"], df["inc_total"] = df["B9_margin"], df["B9_total"]
    df["d_exp_pts"] = df.exp_pts_pre_h - df.exp_pts_pre_a
    df["s_exp_pts"] = df.exp_pts_pre_h + df.exp_pts_pre_a
    df["exp_poss_game"] = (df.exp_poss_pre_h + df.exp_poss_pre_a) / 2
    for c in MX:
        df[f"d_{c}"] = df[f"{c}_h"] - df[f"{c}_a"]
        df[f"s_{c}"] = df[f"{c}_h"] + df[f"{c}_a"]
    df["date_key"] = df["game_date_et"].astype(str)
    return df, cov


SPECS = {
    "margin": {"C1": ["inc_margin", "d_exp_pts"], "C2": ["inc_margin", "d_exp_pts"] + [f"d_{c}" for c in MX]},
    "total": {"C1": ["inc_total", "s_exp_pts", "exp_poss_game"], "C2": ["inc_total", "s_exp_pts", "exp_poss_game"] + [f"s_{c}" for c in MX]},
}


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.c_[np.ones(len(X)), X]
    return np.linalg.lstsq(A, y, rcond=None)[0]


def ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float, mu: np.ndarray, sd: np.ndarray):
    from sklearn.linear_model import Ridge
    return Ridge(alpha=alpha).fit((X - mu) / sd, y)


def fit_candidates(df: pd.DataFrame, target: str) -> dict:
    fit = df.season.isin(FIT)
    y = df[target].to_numpy(float)
    out = {}
    for name in ("C1", "C2"):
        cols = SPECS[target][name]
        b = ols(df.loc[fit, cols].to_numpy(float), y[fit.to_numpy()])
        out[name] = {"cols": cols, "coef": dict(zip(["intercept"] + cols, map(float, b))),
                     "pred": b[0] + df[cols].to_numpy(float) @ b[1:]}
    cols = SPECS[target]["C2"]
    X = df[cols].to_numpy(float)
    cv = {}
    for a in ALPHAS:
        errs = []
        for k in range(2018, 2023):
            tr = df.season.between(2016, k - 1).to_numpy()
            te = (df.season == k).to_numpy()
            mu, sd = X[tr].mean(0), X[tr].std(0)
            sd[sd == 0] = 1
            m = ridge_fit(X[tr], y[tr], a, mu, sd)
            errs.append(float(np.mean((y[te] - m.predict((X[te] - mu) / sd)) ** 2)))
        cv[a] = float(np.mean(errs))
    a_best = min(cv, key=cv.get)
    f = fit.to_numpy()
    mu, sd = X[f].mean(0), X[f].std(0)
    sd[sd == 0] = 1
    m = ridge_fit(X[f], y[f], a_best, mu, sd)
    out["C3"] = {"cols": cols, "alpha": a_best, "cv_mse": {str(k): v for k, v in cv.items()},
                 "coef_original_scale": dict(zip(["intercept"] + cols, [float(m.intercept_ - (m.coef_ * mu / sd).sum())] + list(map(float, m.coef_ / sd)))),
                 "pred": m.predict((X - mu) / sd)}
    return out


def boot_ci(d: np.ndarray, keys: np.ndarray, n: int = 2000, seed: int = 11) -> list[float]:
    uk, inv = np.unique(keys, return_inverse=True)
    s = np.bincount(inv, weights=d)
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uk), size=(n, len(uk)))
    means = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def point(y, p) -> dict:
    e = y - p
    return {"rmse": float(np.sqrt(np.mean(e ** 2))), "mae": float(np.mean(np.abs(e))), "bias": float(np.mean(e))}


def compare(df: pd.DataFrame, mask: np.ndarray, target: str, inc: np.ndarray, cand: np.ndarray, with_winner: bool = False) -> dict:
    y = df[target].to_numpy(float)[mask]
    pi, pc = inc[mask], cand[mask]
    d = (y - pc) ** 2 - (y - pi) ** 2
    out = {"n": int(mask.sum()), "n_dates": int(df.loc[mask, "date_key"].nunique()), "incumbent": point(y, pi), "candidate": point(y, pc),
           "paired_delta_sq_err_mean": float(d.mean()), "paired_delta_sq_err_95ci": boot_ci(d, df.loc[mask, "date_key"].to_numpy()),
           "rmse_delta": float(np.sqrt(np.mean((y - pc) ** 2)) - np.sqrt(np.mean((y - pi) ** 2)))}
    if with_winner:
        out["winner_accuracy"] = {"incumbent": float(np.mean(np.sign(pi) == np.sign(y))), "candidate": float(np.mean(np.sign(pc) == np.sign(y)))}
    return out


def coverage(y, mu, sd) -> dict:
    z = np.abs(y - mu) / sd
    return {"cov50": float(np.mean(z <= 0.6744897501960817)), "cov80": float(np.mean(z <= 1.2815515655446004)), "mean_sd": float(np.mean(sd))}


def stage_analyse(no_test: bool = False) -> None:
    prot = WORK / "protocol.json"
    if sha(prot) != (WORK / "protocol.sha256").read_text().split()[0]:
        raise SystemExit("STOP: protocol.json hash mismatch")
    fid = fidelity(None)
    print(json.dumps({"fidelity_verdict": fid["verdict"], "max_diff": fid["max_abs_split_rmse_diff"]}), flush=True)
    if fid["verdict"] != "FAITHFUL":
        REPORT.write_text(json.dumps({"status": "STOPPED_INCUMBENT_NOT_REPRODUCED", "fidelity": fid}, indent=1))
        raise SystemExit("STOP: incumbent not reproduced")
    df, cov = build_dataset()
    df.to_parquet(DATASET, index=False)
    rep: dict = {"status": "COMPLETE", "label": "RESEARCH_ONLY outcome prediction; no betting claim", "protocol_sha256": sha(prot),
                 "fidelity": fid, "coverage": cov, "data_audit": json.loads((WORK / "feat" / "data_audit.json").read_text()) if (WORK / "feat" / "data_audit.json").exists() else None}
    val = df.season.isin(VAL).to_numpy()
    tst = df.season.isin(TEST).to_numpy()
    rep["candidates"], rep["validation"], rep["chosen"], preds = {}, {}, {}, {}
    for target in ("margin", "total"):
        inc = df[f"inc_{target}"].to_numpy(float)
        c = fit_candidates(df, target)
        y = df[target].to_numpy(float)
        vrm = {k: float(np.sqrt(np.mean((y[val] - v["pred"][val]) ** 2))) for k, v in c.items()}
        vrm["incumbent"] = float(np.sqrt(np.mean((y[val] - inc[val]) ** 2)))
        chosen = min(["C1", "C2", "C3"], key=lambda k: vrm[k])
        rep["candidates"][target] = {k: {kk: vv for kk, vv in v.items() if kk != "pred"} for k, v in c.items()}
        rep["validation"][target] = {"rmse": vrm, "n": int(val.sum()),
                                     "chosen_vs_incumbent": compare(df, val, target, inc, c[chosen]["pred"], with_winner=target == "margin")}
        rep["chosen"][target] = chosen
        preds[target] = c[chosen]["pred"]
        df[f"cand_{target}"] = c[chosen]["pred"]
    if no_test:
        print(json.dumps({"DRY_RUN_NO_TEST": True, "coverage": cov, "chosen": rep["chosen"], "validation": rep["validation"], "candidates": rep["candidates"]}, indent=1, default=float))
        return
    # -------------------------------------------------- TEST (scored once)
    test = {}
    for target in ("margin", "total"):
        inc, cand = df[f"inc_{target}"].to_numpy(float), preds[target]
        r = compare(df, tst, target, inc, cand, with_winner=target == "margin")
        r["by_season"] = {str(s): compare(df, (df.season == s).to_numpy(), target, inc, cand, with_winner=target == "margin") for s in TEST}
        test[target] = r
    rep["test"] = test
    # -------------------------------------------------- situations (EXPLORATORY, TEST only)
    fitm = df.season.isin(FIT).to_numpy()
    q_pace = np.quantile(df.loc[fitm, "exp_poss_game"], [1 / 3, 2 / 3])
    rows_fit = pd.concat([df.loc[fitm, ["exp_pts_pre_h", "def_ortg_pre_h"]].set_axis(["e", "d"], axis=1),
                          df.loc[fitm, ["exp_pts_pre_a", "def_ortg_pre_a"]].set_axis(["e", "d"], axis=1)])
    q_e, q_d = float(rows_fit.e.quantile(2 / 3)), float(rows_fit.d.quantile(2 / 3))
    start = df.groupby("season")["game_date_et"].transform("min")
    early = (pd.to_datetime(df.game_date_et) - pd.to_datetime(start)).dt.days < 30
    sowd = ((df.exp_pts_pre_h >= q_e) & (df.def_ortg_pre_a >= q_d)) | ((df.exp_pts_pre_a >= q_e) & (df.def_ortg_pre_h >= q_d))
    am = df.inc_margin.abs()
    pace_t = np.searchsorted(q_pace, df.exp_poss_game.to_numpy())
    sit_masks = {
        "pace_tercile": {"slow": pace_t == 0, "mid": pace_t == 1, "fast": pace_t == 2},
        "abs_inc_margin": {"lt5": (am < 5).to_numpy(), "5to15": am.between(5, 15).to_numpy(), "gt15": (am > 15).to_numpy()},
        "early_season": {"first30days": early.to_numpy(), "rest": (~early).to_numpy()},
        "strong_off_vs_weak_def": {"yes": sowd.to_numpy(), "no": (~sowd).to_numpy()},
        "neutral_site": {"neutral": df.neutral_site.astype(bool).to_numpy(), "not_neutral": (~df.neutral_site.astype(bool)).to_numpy()},
    }
    sit = {"label": "EXPLORATORY (TEST seasons only; not multiplicity-corrected)",
           "cutpoints": {"exp_poss_game_terciles_fit": list(map(float, q_pace)), "exp_pts_pre_top_tercile_fit": q_e, "def_ortg_pre_top_tercile_fit": q_d}}
    for g, ms in sit_masks.items():
        sit[g] = {}
        for lvl, m in ms.items():
            mm = m & tst
            sit[g][lvl] = {t: compare(df, mm, t, df[f"inc_{t}"].to_numpy(float), preds[t], with_winner=t == "margin") for t in ("margin", "total")}
    rep["situations"] = sit
    # -------------------------------------------------- calibration
    cal = {}
    for t in ("margin", "total"):
        y = df[t].to_numpy(float)
        cand_sd = float(np.std(y[val] - preds[t][val], ddof=1))
        inc_sd = df[f"inc_{t}_sd"].to_numpy(float)
        ok = tst & np.isfinite(inc_sd)
        cal[t] = {"candidate_sd_from_validation": cand_sd, "n": int(ok.sum()),
                  "incumbent": coverage(y[ok], df[f"inc_{t}"].to_numpy(float)[ok], inc_sd[ok]),
                  "candidate": coverage(y[ok], preds[t][ok], np.full(ok.sum(), cand_sd)),
                  "by_season": {str(s): {"incumbent": coverage(y[ok & (df.season == s).to_numpy()], df[f"inc_{t}"].to_numpy(float)[ok & (df.season == s).to_numpy()], inc_sd[ok & (df.season == s).to_numpy()]),
                                         "candidate": coverage(y[ok & (df.season == s).to_numpy()], preds[t][ok & (df.season == s).to_numpy()], np.full((ok & (df.season == s).to_numpy()).sum(), cand_sd))} for s in TEST}}
    rep["calibration"] = cal
    REPORT.write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({"chosen": rep["chosen"], "validation": rep["validation"]["margin"]["rmse"], "val_total": rep["validation"]["total"]["rmse"],
                      "test_margin": {k: test["margin"][k] for k in ("n", "incumbent", "candidate", "paired_delta_sq_err_mean", "paired_delta_sq_err_95ci")},
                      "test_total": {k: test["total"][k] for k in ("n", "incumbent", "candidate", "paired_delta_sq_err_mean", "paired_delta_sq_err_95ci")}}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "data", "incumbent", "features", "analyse"])
    ap.add_argument("--no-test", action="store_true", help="dry run: stop before any TEST-season error is computed")
    a = ap.parse_args()
    if a.stage in ("all", "data"):
        stage_data()
    if a.stage in ("all", "incumbent"):
        stage_incumbent()
    if a.stage in ("all", "features"):
        stage_features()
    if a.stage in ("all", "analyse"):
        stage_analyse(a.no_test)


if __name__ == "__main__":
    main()

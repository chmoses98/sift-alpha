"""Before/after comparison of the FROZEN selected game configs on the repaired game table (R1: postseason games restored).  No re-selection, no grid."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine.input_research import stats as S
from . import game_lab as GL, dists


def scored(lab, t, cfg):
    P = lab.final_predictions(t, cfg)
    P["ls"] = dists.int_logscore(cfg["dist"], P["y"].to_numpy(), P["mu"].to_numpy(), P["sigma"].to_numpy())
    P["ls0"] = dists.int_logscore("normal", P["y"].to_numpy(), P["mu0"].to_numpy(), P["sigma0"].to_numpy())
    P["gain"] = P["ls"] - P["ls0"]
    return P


def summ(P, mask, seed_keys):
    d = P.loc[mask & P["gain"].notna(), :]
    if not len(d):
        return None
    b = S.ClusterBoot(d["season"].astype(str) + "_" + d["week"].astype(str), n_boot=1000).summarize(d["gain"].to_numpy())
    return {"n": int(len(d)), "gain_vs_climatology": b["mean"], "ci": b["ci_0.05"], "rmse": float(np.sqrt(np.mean((d["y"] - d["mu"]) ** 2)))}


GT_MAP: dict = {}


def run(old_dir: Path, new_dir: Path, report: Path, out: Path, work: Path, games_csv: Path, targets=("margin", "total", "home_pts", "away_pts")):
    GT_MAP.update(pd.read_csv(games_csv).set_index("game_id")["game_type"].to_dict())
    rep = json.load(open(report))["targets"]
    res = {"repair": "R1_postseason_games_restored", "targets": {}}
    for t in targets:
        cfg = rep[t]["selected"]["config"]
        row = {"config": cfg}
        for tag, d in (("before", old_dir), ("after", new_dir)):
            gt, tg = pd.read_parquet(d / "game_table.parquet"), pd.read_parquet(d / "tg.parquet")
            lab = GL.GameLab(gt, tg, work / f"_tmp_{tag}_{t}.jsonl", work / f"cache_{tag}")
            P = scored(lab, t, cfg)
            P["gt"] = P["game_id"].map(GT_MAP).replace({"WC": "POST", "DIV": "POST", "CON": "POST", "SB": "POST"})
            row[tag] = {"val_2022_24_all": summ(P, P.season.between(2022, 2024), None), "val_2022_24_reg": summ(P, P.season.between(2022, 2024) & (P["gt"] == "REG"), None),
                        "y2025_all": summ(P, P.season == 2025, None), "y2025_reg": summ(P, (P.season == 2025) & (P["gt"] == "REG"), None),
                        "y2025_post": summ(P, (P.season == 2025) & (P["gt"] == "POST"), None)}
            if tag == "after":
                P.drop(columns=["gt"]).to_parquet(work / f"game_predictions_repaired_{t}.parquet")
        res["targets"][t] = row
    out.write_text(json.dumps(res, indent=1, default=float))
    return res

"""Rebuild the player-probability frame and the market comparison on the repaired data (R1 postseason + R2 weather + identity), with declared variants.
usage: python -m alpha_engine.lab.repair_run --data DIR --work DIR --out DIR --kalshi DIR"""
from __future__ import annotations
import argparse, json, pickle
from pathlib import Path
import numpy as np
import pandas as pd
from . import player_lab as PL, player_run as PR, player_variants as PV, involvement as IV, market_run as MR


def run(data: Path, work: Path, out: Path, kalshi: Path, variant: str = "v3_listed_emp"):
    d, diag = PR.contract_probs(kalshi, data, work, out)
    pg, st = pd.read_parquet(work / "pg.parquet"), pd.read_parquet(work / "states.parquet")
    gt, gp = pd.read_parquet(work / "game_table.parquet"), pd.read_parquet(work / "game_predictions.parquet")
    ctx = PR.build_game_ctx(gt, gp); inj = PL.injury_status(data / "inj", PR.kickoffs(gt))
    pools = {}
    for t in PV.YARDAGE:
        lab = PL.PlayerLab(pg, st, ctx, inj, out / f"ledger_player_{t}.jsonl"); cfg = PR.selected_config(out, t); f = lab.frame(t)
        X = f[lab.columns(t, cfg["groups"], cfg["hl"])].to_numpy(float); y = f["y"].to_numpy(float); s = f["season"].to_numpy(int)
        mu = np.maximum(lab.wf(X, y, s, list(range(2017, 2025)), cfg["model"]), 0.05); ok = ~np.isnan(mu); pools[t] = (mu[ok], y[ok])
    atr = IV.add_injury(IV.at_risk_table(pg), inj); m = IV.fit(atr, range(2017, 2025))
    inv = atr[atr.season == 2025].copy(); inv["p_inv"] = IV.predict(m, inv)
    d = d[d["model_p"].notna()].copy()
    V = PV.add_variants(d, pools, inv)
    V.to_parquet(work / "player_variants.parquet")
    pp = V.assign(model_p_incumbent=V["v0_incumbent"], model_p=V[variant])
    pp = pp[pp["model_p"].notna()]
    rep = MR.run(kalshi, work, out, games=pd.read_csv(data / "games.csv"), player_probs=pp[["game_id", "week", "family", "ticker", "team", "player", "floor", "threshold", "outcome", "horizon", "bid", "ask", "age", "home", "away", "model_p"]])
    (out / "player_contract_diag.json").write_text(json.dumps(diag, indent=1, default=str))
    return rep, diag

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); [ap.add_argument(f"--{k}", required=True) for k in ("data", "work", "out", "kalshi")]
    a = ap.parse_args(); run(Path(a.data), Path(a.work), Path(a.out), Path(a.kalshi))

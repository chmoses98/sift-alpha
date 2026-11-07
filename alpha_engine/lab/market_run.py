"""Run the model-vs-Kalshi comparison on the 2025 season (evaluation only).  usage: python -m alpha_engine.lab.market_run --kalshi DIR --work DIR --out DIR"""
from __future__ import annotations
import argparse, glob, json
from pathlib import Path
import numpy as np
import pandas as pd
from . import market as MK


def run(kalshi: Path, work: Path, out: Path, player_probs: pd.DataFrame | None = None, name: str = "market_lab_report.json", games: pd.DataFrame | None = None) -> dict:
    rstats: dict = {}
    d = MK.load_contracts(sorted(glob.glob(str(kalshi / "horizons" / "*.jsonl"))), games=games, stats=rstats)
    gp = pd.read_parquet(work / "game_predictions.parquet")
    gp = gp[gp["season"] == 2025][["game_id", "target", "dist", "mu", "sigma"]]
    g = d[d["family"].isin(["moneyline", "spread", "total", "team_total"])].copy()
    g["model_p"] = MK.game_probs(g, gp)
    parts = [g]
    if player_probs is not None and len(player_probs):
        parts.append(player_probs)
    d = pd.concat(parts, ignore_index=True)
    inv = d.groupby("family").agg(contracts=("ticker", "nunique"), rows=("ticker", "size"), no_model=("model_p", lambda s: int(s.isna().sum()))).to_dict("index")
    d = d.dropna(subset=["model_p"])
    fresh = MK.freshness_table(d)
    d = MK.valid_quotes(d)
    d = MK.score(d)
    rep = dict(recovered_records=rstats.get("recovered", 0), season=2025, decision_horizons=list(MK.HORIZONS), primary_horizon=MK.PRIMARY, discovery_weeks=f"<= {MK.DISCOVERY_MAX_WEEK}",
               inventory=inv, usable_quotes={f: int(n) for f, n in d[d["horizon"] == MK.PRIMARY].groupby("family").size().items()},
               predictive=MK.predictive_table(d), strategy=MK.strategy_table(d), freshness=fresh)
    rep["segments_tau0"] = MK.segment_search(d, tau=0.0)
    rep["segments_tau2c"] = MK.segment_search(d, tau=0.02)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(rep, indent=1, default=float))
    d.to_parquet(work / "market_scored.parquet")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--kalshi", required=True); ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(); run(Path(a.kalshi), Path(a.work), Path(a.out))

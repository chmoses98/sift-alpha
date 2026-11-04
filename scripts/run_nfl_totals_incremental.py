#!/usr/bin/env python3
"""python scripts/run_nfl_totals_incremental.py NFL_EDGE_FINDER_CHECKOUT  -> research/audit/verification/NFL_totals_incremental.json"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from alpha_engine import nfl_totals_incremental as nt  # noqa: E402

repo = Path(sys.argv[1])
files = {"features": "research/signal_discovery_wave1/game_features.parquet", "market_and_outcome": "research/game_model/walkforward_predictions.parquet"}
g = pd.read_parquet(repo / files["features"])
w = pd.read_parquet(repo / files["market_and_outcome"])[["game_id", "total", "total_line"]]
m = g.merge(w, on="game_id", how="inner")
m = m[m["total_line"].notna() & m["total"].notna()].copy()
m["resid"] = m["total"] - m["total_line"]
res = nt.evaluate(m)
res.update({"schema_version": "nfl-totals-incremental-1.0", "family": "NFL/TOTAL", "question": "Do opponent-adjusted EPA, pace, QB, rest/context features improve on the near-close market total on chronological holdouts?",
            "source": {"repo": "chmoses98/nfl-edge-finder", "commit": subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                       "files": {k: {"path": v, "sha256": hashlib.sha256((repo / v).read_bytes()).hexdigest()} for k, v in files.items()}},
            "n_games_joined": int(len(m)), "games_by_season": {int(k): int(v) for k, v in m["season"].value_counts().sort_index().items()},
            "market_baseline": "schedule-file near-close consensus total_line (undocumented timing; not a point-in-time price at any pre-close horizon); no Kalshi prices, no fees",
            "caveats": ["features are as-of (history_through) from the wave-1 game_features table", "qb_change uses the REALISED starter: not pregame-knowable, reported separately", "game totals only: team totals and quarter/half were NOT tested",
                        "no execution or fee analysis: a gain in squared error is not an after-fee advantage"],
            "decision": "No input is wired into production by this study."})
(root / "research/audit/verification/NFL_totals_incremental.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
print({k: v["verdict"] for k, v in res["groups"].items()}, res["n_test_games"])

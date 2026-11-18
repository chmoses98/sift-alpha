"""Read-only loader for archived PRODUCTION MLB forecasts committed in edge-finder-api (2026 only).

  team runs  data/pipeline/<date>/projections.json        homeProjRuns/awayProjRuns (meta.createdAt = LAST write)
  win prob   data/pipeline/<date>/projection_board.json   game_result rows: modelFairProbabilityPct (model, not price)
  hitters    data/edgelab/hitter_projection_snapshots/*.jsonl   modelProbability of P(X >= threshold)
  pitchers   data/shadow_pure/mlb_pitcher/projections/*/*__champion.jsonl   pitcher_strikeouts mean + ladder
Only model outputs are read; Kalshi/sportsbook price fields are ignored. `pregame` flags whether the record's
own timestamp precedes first pitch (production team files are overwritten during the day, so many are not).
"""
from __future__ import annotations

import glob
import json
import os

import pandas as pd


def load(repo: str) -> dict:
    out = {}
    rows = []
    for f in sorted(glob.glob(os.path.join(repo, "data/pipeline/*/projections.json"))):
        d = json.load(open(f))
        ts = d.get("meta", {}).get("createdAt")
        for g in (d.get("data") or {}).get("games", []):
            if g.get("excludedFromSlate") or g.get("homeProjRuns") is None:
                continue
            rows.append(dict(game_pk=int(g["gameId"]), prod_home=g["homeProjRuns"], prod_away=g["awayProjRuns"],
                             prod_ts=ts))
    out["team"] = pd.DataFrame(rows).drop_duplicates("game_pk", keep="last")
    rows = []
    for f in sorted(glob.glob(os.path.join(repo, "data/pipeline/*/projection_board.json"))):
        d = json.load(open(f))
        ts = d.get("meta", {}).get("createdAt")
        for r in (d.get("data") or {}).get("rows", []):
            if r.get("marketFamily") == "game_result" and r.get("side") in ("Home", "Away") and \
                    r.get("modelFairProbabilityPct") is not None and r.get("gameId"):
                p = r["modelFairProbabilityPct"] / 100
                rows.append(dict(game_pk=int(r["gameId"]), prod_pwin=p if r["side"] == "Home" else 1 - p, prod_ts=ts))
    out["win"] = pd.DataFrame(rows).drop_duplicates("game_pk", keep="last")
    rows = []
    fam = {"hitter_hits": "H", "hitter_total_bases": "TB"}
    for f in sorted(glob.glob(os.path.join(repo, "data/edgelab/hitter_projection_snapshots/*.jsonl"))):
        for line in open(f):
            r = json.loads(line)
            if r.get("marketFamily") in fam and r.get("projectionStatus") == "PROJECTED" and \
                    r.get("modelProbability") is not None:
                rows.append(dict(game_pk=int(r["gameId"]), player=int(r["playerId"]), stat=fam[r["marketFamily"]],
                                 thr=int(r["threshold"]), prod_p=float(r["modelProbability"]),
                                 prod_ts=r.get("projectionGeneratedAt"), checkpoint=r.get("checkpoint")))
    h = pd.DataFrame(rows)
    out["hitters"] = h  # de-duplicated after the pregame filter by the caller
    rows = []
    for f in sorted(glob.glob(os.path.join(repo, "data/shadow_pure/mlb_pitcher/projections/*/*__champion.jsonl"))):
        for line in open(f):
            r = json.loads(line)
            if r.get("statistic") == "pitcher_strikeouts":
                rows.append(dict(game_pk=int(r["game_id"]), player=int(r["player_id"]),
                                 prod_mean=r["projection"]["mean"], prod_ts=r["as_of"],
                                 prod_ladder={t["at_least"]: t["probability"] for t in r["projection"]["thresholds"]}))
    p = pd.DataFrame(rows)
    out["pitchers"] = p
    return out

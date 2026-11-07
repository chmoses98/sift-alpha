"""Root-cause audit of the player-prop probability level (RESEARCH_ONLY).  Measures instead of assuming.  Market prices appear here only as a yardstick, never as a model input.

Questions, each answered from data:
  A  threshold semantics     does the settled result equal 1[stat >= threshold] using the realised box-score stat?  (rate of agreement; mismatches listed)
  B  population / zero-usage the training target exists only for player-games with >=1 recorded involvement (pbp rows).  How often is a contract player ABSENT from that
                             table in the contract game, and how often does the contract settle YES for such a player?
  C  probability level       mean model P vs realised YES rate vs mean market mid; the same restricted to settled rows where the player had a recorded stat;
                             decomposition P = P(active) * P(stat >= k | active)
  D  conditional shape       realised vs predicted P(stat>=k | had involvement) by threshold bucket
"""
from __future__ import annotations
import numpy as np
import pandas as pd

STAT_COL = {"rec_yds": "rec_yds", "receptions": "rec", "rush_yds": "rush_yds", "pass_yds": "pass_yds", "td_any": "td_any"}


def attach_actuals(c: pd.DataFrame, pg: pd.DataFrame, pid_map: dict[str, str]) -> pd.DataFrame:
    """c: one row per ticker with family, game_id, player/pid, floor.  Adds the realised stat and `in_pg` (player has a recorded involvement row in that game)."""
    x = c.copy()
    x["pid"] = x["ticker"].map(pid_map)
    key = pg.set_index(["game_id", "pid"])
    idx = pd.MultiIndex.from_arrays([x["game_id"], x["pid"]])
    x["in_pg"] = idx.isin(key.index)
    stat = np.full(len(x), np.nan)
    for fam, col in STAT_COL.items():
        m = (x["family"] == fam).to_numpy() & x["in_pg"].to_numpy()
        if m.any():
            stat[m] = key[col].reindex(idx[m]).to_numpy()
    x["stat"] = stat
    return x


def semantics(x: pd.DataFrame) -> dict:
    out = {}
    for fam, g in x[x["in_pg"] & x["stat"].notna()].groupby("family"):
        res = g["outcome"].to_numpy(float)
        ge = (g["stat"].to_numpy() >= g["floor"].to_numpy() + 0.5).astype(float)       # "k or more"
        gt = (g["stat"].to_numpy() > g["floor"].to_numpy() + 0.5).astype(float)        # "more than k"
        out[fam] = {"n": int(len(g)), "agree_ge": float((res == ge).mean()), "agree_gt": float((res == gt).mean())}
    return out


def level(x: pd.DataFrame) -> dict:
    out = {}
    for fam, g in x.groupby("family"):
        g = g[g["model_p"].notna()]
        a = g[g["in_pg"]]
        z = g[~g["in_pg"]]
        out[fam] = {"n": int(len(g)), "mean_model_p": float(g["model_p"].mean()), "realised_yes": float(g["outcome"].mean()), "mean_market_mid": float(((g["bid"] + g["ask"]) / 2).mean()),
                    "n_absent_from_pg": int(len(z)), "share_absent": float(len(z) / max(1, len(g))), "yes_rate_when_absent": float(z["outcome"].mean()) if len(z) else None,
                    "n_in_pg": int(len(a)), "model_p_in_pg": float(a["model_p"].mean()) if len(a) else None, "realised_in_pg": float(a["outcome"].mean()) if len(a) else None,
                    "market_mid_in_pg": float(((a["bid"] + a["ask"]) / 2).mean()) if len(a) else None}
    return out


def by_bucket(x: pd.DataFrame, fam: str, edges) -> list[dict]:
    g = x[(x["family"] == fam) & x["model_p"].notna()].copy()
    g["b"] = pd.cut(g["floor"], edges)
    rows = []
    for b, h in g.groupby("b", observed=True):
        rows.append({"bucket": str(b), "n": int(len(h)), "model": float(h["model_p"].mean()), "realised": float(h["outcome"].mean()), "market": float(((h["bid"] + h["ask"]) / 2).mean()),
                     "model_in_pg": float(h[h["in_pg"]]["model_p"].mean()) if h["in_pg"].any() else None, "realised_in_pg": float(h[h["in_pg"]]["outcome"].mean()) if h["in_pg"].any() else None})
    return rows

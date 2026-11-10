"""Tennis second-serve vulnerability (RESEARCH_ONLY): completes the catalog definition of ten.second_serve_vulnerability ("second-serve points won, opponent-adjusted; returner's points won vs second serves; pair product relative to tour mean").

Same data, key and date-batching rules as tennis_ext2 (Sackmann ATP/WTA files, CC BY-NC-SA 4.0 research use; a match sees only matches with tourney_date STRICTLY EARLIER).
Second-serve points of a player in a match = svpt - 1stIn; won = 2ndWon. A player-match row counts only if all four of w_/l_ svpt, 1stIn, 2ndWon are present for BOTH sides, both second-serve point counts are > 0 and the score is not a walkover.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .tennis_ext2 import _wsum, perturb as _perturb

S = "TENNIS"
COLS3 = ["tourney_id", "tourney_date", "match_num", "winner_id", "loser_id", "score", "w_svpt", "w_1stIn", "w_2ndWon", "l_svpt", "l_1stIn", "l_2ndWon"]
CONTENT = ["score", "winner_id", "loser_id", "w_svpt", "w_1stIn", "w_2ndWon", "l_svpt", "l_1stIn", "l_2ndWon"]


def load_raw(tennis_dir) -> dict:
    fs = sorted(glob.glob(str(Path(tennis_dir) / "[aw]t[pa]_matches_20*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=lambda c: c in COLS3, low_memory=False).assign(tour=Path(f).name[:3]) for f in fs], ignore_index=True)
    d = d.dropna(subset=["tourney_date", "winner_id", "loser_id"]).copy()
    d["date"] = pd.to_datetime(d.tourney_date.astype(int).astype(str), format="%Y%m%d", errors="coerce"); d = d.dropna(subset=["date"])
    d["game_id"] = d.tour + "|" + d.tourney_id.astype(str) + "|" + d.match_num.astype(str)
    d["game_id"] = d.game_id + "|" + d.groupby("game_id").cumcount().astype(str)
    d["season"] = d.date.dt.year
    return {"matches": d[["game_id", "tour", "date", "season"] + [c for c in COLS3 if c not in ("tourney_date",)]].reset_index(drop=True)}


def compute(raw: dict) -> dict:
    m = raw["matches"].copy()
    wo = m.score.astype(str).str.contains("W/O", regex=False)
    p2w, p2l = m.w_svpt - m.w_1stIn, m.l_svpt - m.l_1stIn
    ok = ~wo & (p2w > 0) & (p2l > 0) & m[["w_2ndWon", "l_2ndWon"]].notna().all(axis=1)
    rows = []
    for me, op, k_me, k_op in (("w", "l", "winner_id", "loser_id"), ("l", "w", "loser_id", "winner_id")):
        pm, po = (p2w, p2l) if me == "w" else (p2l, p2w)
        wm, wp = m[f"{me}_2ndWon"], m[f"{op}_2ndWon"]
        rows.append(pd.DataFrame({"game_id": m.game_id, "team": m.tour + ":" + m[k_me].astype(int).astype(str), "opp": m.tour + ":" + m[k_op].astype(int).astype(str), "tour": m.tour, "date": m.date, "season": m.season,
                                  "s_pts": np.where(ok, pm, np.nan), "s_won": np.where(ok, wm, np.nan), "r_pts": np.where(ok, po, np.nan), "r_won": np.where(ok, po - wp, np.nan)}))
    L = pd.concat(rows, ignore_index=True)
    dd = L.date.to_numpy()
    V = L[["s_won", "s_pts", "r_won", "r_pts"]].to_numpy(float)
    ps, pc = _wsum(L[["team"]], dd, V, 1095, hl_days=365.0)                    # player's own history, weights 0.5**(age/365), last 1095 days
    ts, tc = _wsum(L[["tour"]], dd, V[:, :2], 1095)                            # tour: plain server rate on second serves over the same window
    with np.errstate(all="ignore"):
        L["ssv_2nd_won_pre"] = ps[:, 0] / ps[:, 1]
        L["ssv_ret2_won_pre"] = ps[:, 2] / ps[:, 3]
        tm = ts[:, 0] / ts[:, 1]
    L["tm2"] = tm
    o = L[["game_id", "team", "ssv_2nd_won_pre", "ssv_ret2_won_pre"]].rename(columns={"team": "opp", "ssv_2nd_won_pre": "o_s", "ssv_ret2_won_pre": "o_r"})
    L = L.merge(o, on=["game_id", "opp"], how="left")
    L["ssv_adj_2nd_won_pre"] = L.ssv_2nd_won_pre + (L.o_r - (1 - L.tm2))
    L["ssv_pair_idx_pre"] = (L.ssv_2nd_won_pre / L.tm2) * (L.o_r / (1 - L.tm2))
    out = L[["game_id", "team", "date", "season", "ssv_2nd_won_pre", "ssv_ret2_won_pre", "ssv_adj_2nd_won_pre", "ssv_pair_idx_pre"]]
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def perturb(raw: dict, ids, seed: int) -> dict:
    return _perturb(raw, ids, seed, ["score", "w_svpt", "w_1stIn", "w_2ndWon", "l_svpt", "l_1stIn", "l_2ndWon"])


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "ten.second_serve_vulnerability", "team", ["ssv_2nd_won_pre", "ssv_ret2_won_pre", "ssv_adj_2nd_won_pre", "ssv_pair_idx_pre"], "FULL",
                        "second-serve points won (own, weighted half-life 365 days over the last 1095), returner's points won vs second serves, opponent-adjusted second-serve won = own + (opponent's return-vs-second-serve rate - (1 - tour second-serve server rate)), pair product relative to the tour mean",
                        ["second-serve points won", "returner's points won vs second serves", "opponent adjustment", "pair product relative to tour mean"], [], ["sackmann_atp_wta_matches"], "pregame_rolling")]

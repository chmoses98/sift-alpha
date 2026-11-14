"""Tennis extension builders from the owner's Sackmann ATP/WTA match archive (RESEARCH_ONLY): retirement / walkover / layoff features.

Sackmann stamps every match of a tournament with the tournament START date, and the order of rounds inside it is a convention, not a timestamp. So these builders are deliberately COARSE and conservative:
the unit is the player's TOURNAMENT; a match's features use only that player's tournaments that started strictly BEFORE this tournament started; nothing from the same tournament is ever used.
Score text gives the outcome type: 'W/O' walkover (loser did not play), 'RET'/'DEF'/'ABD' retirement or default by the loser. The loser of such a match is the player who withdrew. Player ids are NOT unique across the ATP and WTA files (the same number can be two different players), so the player key is tour:id.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "TENNIS"


def load_raw(tennis_dir) -> dict:
    fs = sorted(glob.glob(str(Path(tennis_dir) / "*_matches_*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=["tourney_id", "tourney_date", "match_num", "winner_id", "loser_id", "score", "round"], low_memory=False).assign(tour=Path(f).name[:3]) for f in fs], ignore_index=True)
    d = d.dropna(subset=["tourney_date", "winner_id", "loser_id"]).copy()
    d["date"] = pd.to_datetime(d.tourney_date.astype(int).astype(str), format="%Y%m%d", errors="coerce"); d = d.dropna(subset=["date"])
    d["game_id"] = d.tour + "|" + d.tourney_id.astype(str) + "|" + d.match_num.astype(str)
    d["game_id"] = d.game_id + "|" + d.groupby("game_id").cumcount().astype(str)      # match_num repeats inside some tournaments: make the id unique
    d["season"] = d.date.dt.year
    return {"matches": d[["game_id", "tour", "tourney_id", "date", "season", "winner_id", "loser_id", "score"]].reset_index(drop=True)}


def compute(raw: dict) -> dict:
    d = raw["matches"].copy(); sc = d.score.astype(str)
    d["wo"] = sc.str.contains("W/O", regex=False); d["ret"] = sc.str.contains("RET|DEF|ABD", regex=True) & ~d.wo
    rows = []
    for me, op, lost in (("winner_id", "loser_id", 0), ("loser_id", "winner_id", 1)):
        rows.append(pd.DataFrame({"game_id": d.game_id, "team": d.tour + ":" + d[me].astype(int).astype(str), "opp": d.tour + ":" + d[op].astype(int).astype(str), "date": d.date, "season": d.season, "tour": d.tour, "tourney_id": d.tourney_id,
                                  "wo_me": (d.wo & (lost == 1)).astype(float), "ret_me": (d.ret & (lost == 1)).astype(float)}))
    m = pd.concat(rows, ignore_index=True)
    m = m.sort_values(["date", "tour", "tourney_id", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    # one row per (player, tournament): the tournament's matches, withdrawals, start date
    tt = m.groupby(["team", "tour", "tourney_id"], sort=False).agg(date=("date", "first"), n=("game_id", "size"), wo=("wo_me", "sum"), ret=("ret_me", "sum")).reset_index().sort_values(["team", "date", "tour", "tourney_id"], kind="mergesort")
    tt["gap"] = (tt.date - tt.groupby("team").date.shift(1)).dt.days
    # strictly earlier TOURNAMENT START DATES only: shift within player, then collapse equal start dates so a simultaneous tournament (same start date) is never visible
    out = []
    for pid, g in tt.groupby("team", sort=False):
        g = g.sort_values(["date", "tour", "tourney_id"], kind="mergesort"); dts = g.date.to_numpy(); n = len(g)
        ret12 = np.full(n, np.nan); wo12 = np.full(n, np.nan); wo_rate = np.full(n, np.nan); layoff = np.full(n, np.nan); n_lay = np.full(n, np.nan); since_ret = np.full(n, np.nan)
        for i in range(n):
            prev = np.flatnonzero(dts < dts[i])             # strictly earlier start dates
            if len(prev) == 0: continue
            j = prev[-1]; last = dts[j]; w = prev[dts[prev] >= dts[i] - np.timedelta64(365, "D")]
            ret12[i] = g.ret.to_numpy()[w].sum(); wo12[i] = g.wo.to_numpy()[w].sum()
            wo_rate[i] = g.wo.to_numpy()[prev].sum() / max(g.n.to_numpy()[prev].sum(), 1)
            layoff[i] = (dts[i] - last) / np.timedelta64(1, "D")
            gp = np.diff(dts[prev]) / np.timedelta64(1, "D"); n_lay[i] = float((gp >= 30).sum()) + float(layoff[i] >= 30)
            r = prev[g.ret.to_numpy()[prev] > 0]
            since_ret[i] = (dts[i] - dts[r[-1]]) / np.timedelta64(1, "D") if len(r) else np.nan
        out.append(pd.DataFrame({"team": pid, "tour": g.tour.to_numpy(), "tourney_id": g.tourney_id.to_numpy(), "ret_12m_pre": ret12, "wo_12m_pre": wo12, "wo_share_pre": wo_rate, "layoff_days_pre": layoff, "n_layoffs_ge30_pre": n_lay, "days_since_ret_pre": since_ret,
                                 "n_prior_tourneys": np.arange(n)}))
    f = pd.concat(out, ignore_index=True)
    f["layoff_ge30_pre"] = np.where(f.layoff_days_pre.notna(), (f.layoff_days_pre >= 30).astype(float), np.nan)
    res = m[["game_id", "season", "team", "opp", "date", "tour", "tourney_id"]].merge(f, on=["team", "tour", "tourney_id"], how="left").drop(columns=["tour", "tourney_id"])
    res["week"] = 0
    return {"team": res.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    def F(cid, cols, d, done, miss):
        return FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, ["Sackmann ATP/WTA match archive (owner snapshot)"], "pregame_rolling")
    return [
        F("ten.fitness", ["ret_12m_pre", "wo_12m_pre", "days_since_ret_pre"], "retirements/defaults and walkovers by the player in tournaments that started in the previous 365 days, and days since the last retirement", ["trailing-year RET/W-O counts", "days since last RET"], ["minutes load of that match", "injury type / body part", "tournament-day (not match-day) resolution"]),
        F("ten.walkover_slot_hazard", ["wo_share_pre"], "share of the player's earlier matches that ended in a walkover against him", ["player walkover base rate"], ["round / tier / age / last-match-minutes hazard model", "tournament-day resolution"]),
        F("ten.layoff_survival_curve", ["layoff_days_pre", "layoff_ge30_pre", "n_layoffs_ge30_pre"], "days between this tournament's start and the player's previous tournament start, a >=30-day flag, and the count of earlier >=30-day gaps", ["layoff length", "gap history"], ["right-censored survival curve fit", "exact match dates (archive has tournament start dates only)"]),
    ]

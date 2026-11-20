"""NFL batch 8, score-path inputs (RESEARCH_ONLY, PROXY): blowout mass, second-half game-state exposure, largest lead, lead changes and big comebacks, as kernel-weighted
empirical frequencies of the previous three seasons conditioned on the market-free own-model expected margin and total of nfl_team_ext8 (no spread, total or price; no simulation).

Rows: the team-game rows of nfl_team_ext8 (seasons >= 2013); mtp_margin_pre / mtp_total_pre are computed exactly as there (same raw tables).
Per-game paths (outcomes; used only as reference rows of LATER seasons): pbp rows of the game ordered by play_id (numeric); m_k = total_home_score - total_away_score after row k
(missing -> 0), with m_0 = 0 prepended. Team perspective s = +1 home, -1 away (location does not matter here).
  q4_abs14   = |m at the last row with qtr <= 3| >= 14 (m_0 if none)
  any_abs21  = max_k |m_k| >= 21
  max_abs    = max_k |m_k|
  lead_chg   = number of changes of sign between consecutive NONZERO m_k (zeros are skipped)
  trailed24  = the final winner (sign of the last m; 0 = tie -> 0) had min over k of (winner sign x m_k) <= -24
  team_lead14 = max_k (s m_k) >= 14
  h2 shares  = the team's offensive plays (posteam = team, play_type pass or run) with qtr >= 3, by its score_differential before the play in bins <= -17, -16..-9, -8..-1, 0, 1..8,
               9..16, >= 17, divided by its number of such plays (missing when none)
Kernel: for a row of season S, reference = rows of seasons S-3 .. S-1 (>= 2011) with the outcome present; weight w = exp(-0.5 ((dm/4)^2 + (dt/5)^2)), dm = mtp_margin_pre difference,
dt = mtp_total_pre difference; value = sum w x / sum w.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import nfl_team_ext8 as T
from .core import FeatureSpec

S = "NFL"
OUT_FIRST = T.OUT_FIRST
BW_M, BW_T = 4.0, 5.0
EXTRA_PBP = ["play_id", "score_differential"]
CONTENT = T.CONTENT + ["score_differential"]
GAMES_CONTENT = T.GAMES_CONTENT
BINS = [(-1e9, -17), (-16, -9), (-8, -1), (0, 0), (1, 8), (9, 16), (17, 1e9)]
BIN_NAMES = ["m17", "m9", "m1", "z", "p1", "p9", "p17"]


def load_raw(pbp_dir, games_file) -> dict:
    import glob
    from pathlib import Path
    cols = T.PBP_COLS + EXTRA_PBP
    fs = sorted(glob.glob(str(Path(pbp_dir) / "play_by_play_*.parquet"))) or sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=cols) for f in fs], ignore_index=True)
    g = pd.read_csv(games_file, usecols=T.GAMES_COLS)
    g = g[(g.season >= T.HIST_FIRST) & g.home_score.notna()].drop_duplicates("game_id")
    pbp = pbp[pbp.game_id.isin(set(g.game_id))]
    warm = set(g.game_id[g.season < OUT_FIRST]); pw = pbp.game_id.isin(warm)
    return {"pbp": pbp[~pw].reset_index(drop=True), "games": g[g.season >= OUT_FIRST].reset_index(drop=True),
            "pbp_warm": pbp[pw].reset_index(drop=True), "games_warm": g[g.season < OUT_FIRST].reset_index(drop=True)}


def _paths(p: pd.DataFrame) -> pd.DataFrame:
    q = p[["game_id", "play_id", "qtr", "total_home_score", "total_away_score"]].copy()
    q["play_id"] = pd.to_numeric(q.play_id, errors="coerce")
    q = q.sort_values(["game_id", "play_id"], kind="mergesort")
    q["m"] = q.total_home_score.fillna(0.0).astype(float) - q.total_away_score.fillna(0.0).astype(float)
    out = []
    for gid, d in q.groupby("game_id", sort=True):
        m = np.concatenate([[0.0], d.m.to_numpy()]); qt = d.qtr.to_numpy(float)
        k3 = np.flatnonzero(qt <= 3); m3 = d.m.to_numpy()[k3[-1]] if len(k3) else 0.0
        nz = np.sign(m[m != 0]); lc = int((nz[1:] != nz[:-1]).sum()) if len(nz) > 1 else 0
        w = np.sign(m[-1]); tr = float(w != 0 and (w * m).min() <= -24)
        out.append((gid, float(abs(m3) >= 14), float(np.abs(m).max() >= 21), float(np.abs(m).max()), float(lc), tr, float(m.max()), float(-m.min())))
    return pd.DataFrame(out, columns=["game_id", "q4_abs14", "any_abs21", "max_abs", "lead_chg", "trailed24", "home_maxlead", "away_maxlead"])


def _h2(p: pd.DataFrame) -> pd.DataFrame:
    q = p[p.posteam.notna() & p.play_type.isin(["pass", "run"]) & (pd.to_numeric(p.qtr, errors="coerce") >= 3)].copy()
    q["team"] = T._fix(q.posteam); sd = pd.to_numeric(q.score_differential, errors="coerce")
    q = q[sd.notna()].assign(sd=sd[sd.notna()])
    for nm, (lo, hi) in zip(BIN_NAMES, BINS):
        q[nm] = ((q.sd >= lo) & (q.sd <= hi)).astype(float)
    a = q.groupby(["game_id", "team"])[BIN_NAMES].sum(); n = a.sum(axis=1)
    return a.div(n, axis=0).add_prefix("h2_").reset_index()


SSB = ["ssb_q4_abs14_pre", "ssb_any_abs21_pre"] + [f"ssb_h2_share_{b}_pre" for b in BIN_NAMES]
SPS = ["sps_exp_max_abs_margin_pre", "sps_exp_lead_changes_pre", "sps_p_lead_changes_ge2_pre", "sps_p_winner_trailed24_pre", "sps_p_team_max_lead_ge14_pre"]
ALL = SSB + SPS


def compute(raw: dict) -> dict:
    base = T.compute(raw)["team"]                    # output rows (season >= OUT_FIRST) with mtp_* ; reference rows need earlier seasons too
    full = _mtp_rows(raw)            # rows of seasons >= 2011 with mtp_margin / mtp_total exactly as nfl_team_ext8 builds them
    p = T._all(raw, "pbp")
    pa = _paths(p); h2 = _h2(p)
    full = full.merge(pa, on="game_id", how="left").merge(h2, on=["game_id", "team"], how="left")
    full["team_lead14"] = np.where(full.is_home == 1, full.home_maxlead >= 14, full.away_maxlead >= 14).astype(float)
    full.loc[full.home_maxlead.isna(), "team_lead14"] = np.nan
    full["lc_ge2"] = np.where(full.lead_chg.notna(), (full.lead_chg >= 2).astype(float), np.nan)
    outcome = {"ssb_q4_abs14_pre": "q4_abs14", "ssb_any_abs21_pre": "any_abs21", **{f"ssb_h2_share_{b}_pre": f"h2_{b}" for b in BIN_NAMES},
               "sps_exp_max_abs_margin_pre": "max_abs", "sps_exp_lead_changes_pre": "lead_chg", "sps_p_lead_changes_ge2_pre": "lc_ge2", "sps_p_winner_trailed24_pre": "trailed24",
               "sps_p_team_max_lead_ge14_pre": "team_lead14"}
    out = base[["game_id", "team", "opp", "season", "date", "mtp_margin_pre", "mtp_total_pre"]].copy()
    for c in ALL:
        out[c] = np.nan
    for s_ in sorted(out.season.unique()):
        ref = full[(full.season >= s_ - 3) & (full.season <= s_ - 1)]
        cur = (out.season == s_).to_numpy(); c = out[cur]
        dm = (c.mtp_margin_pre.to_numpy()[:, None] - ref.mtp_margin_pre.to_numpy()[None, :]) / BW_M
        dt = (c.mtp_total_pre.to_numpy()[:, None] - ref.mtp_total_pre.to_numpy()[None, :]) / BW_T
        K = np.exp(-0.5 * (dm ** 2 + dt ** 2))
        for col, src in outcome.items():
            x = ref[src].to_numpy(float); ok = ~np.isnan(x)
            out.loc[cur, col] = (K[:, ok] @ x[ok]) / K[:, ok].sum(axis=1)
    out = out[["game_id", "team", "opp", "season", "date"] + ALL]
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def _mtp_rows(raw: dict) -> pd.DataFrame:
    """nfl_team_ext8's rows for seasons >= HIST_FIRST + 1 (mtp_margin_pre, mtp_total_pre) with the home flag, for the reference windows."""
    return T._rows(raw)[["game_id", "team", "season", "is_home", "mtp_margin_pre", "mtp_total_pre"]]


def specs() -> list[FeatureSpec]:
    raw = T.RAW
    miss = ["drive-level score-path simulation (20,000 paths) and the Step 2 response-curve feedback", "starting-QB scenario mixture (nfl.qb: prospective)", "weather"]
    return [
        FeatureSpec(S, "nfl.market_free_score_state_blowout_mass", "team", SSB, "PROXY",
                    "Kernel-weighted (previous 3 seasons; bandwidths 4 points of own-model expected margin and 5 of expected total) frequency of a 14+ point margin entering the 4th quarter, a 21+ "
                    "point margin at any time, and the team's share of second-half offensive plays by its own margin bin", ["P(|margin| >= 14 at the start of Q4)", "P(|margin| >= 21 at any time)",
                    "second-half snap share by margin bin", "calibration to empirical frequencies by own-model expected margin, never a closing line"], miss, raw),
        FeatureSpec(S, "nfl.score_path_sequence_sim", "team", SPS, "PROXY",
                    "Kernel-weighted (as above) empirical expectation of the largest absolute margin, the number of lead changes, P(>= 2 lead changes), P(the eventual winner trailed by >= 24) and "
                    "P(the team leads by >= 14 at some point)", ["distribution summaries of max |margin|", "lead changes excluding the first score", "P(winner trailed by >= 24)",
                    "calibration against realised frequencies by own-rating expected margin and total"], miss + ["coin-toss possession order", "per-drive state multipliers"], raw),
    ]

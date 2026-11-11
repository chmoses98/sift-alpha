"""ten.tiebreak_sweep_joint_table (RESEARCH_ONLY): point-in-time 2x2 table of (any set tiebreak) x (winner won without losing a set), by pre-match mean hold x |hold gap| x best_of.

Deterministic counting and closed-form smoothing; NOTHING is fitted or outcome-optimised. Data and date-batching as tennis_ext3/ext4 (Sackmann ATP/WTA, CC BY-NC-SA 4.0: research use, attribution,
share-alike; NOT commercial-cleared). Pre-match holds are the verified tennis_ext4 columns gps_hold_pre / gps_opp_hold_pre.

Per match m (one row per player, both rows share the table because the bin is symmetric in the two players):
  bin(m)    = (floor(mean_hold/0.05), floor(|hold_gap|/0.05), best_of)
  table(m)  = counts n11 (tiebreak & sweep), n10 (tiebreak, not sweep), n01 (no tiebreak & sweep), n00 over matches with tourney_date STRICTLY EARLIER than m's, same bin, valid holds,
              completed matches only (RET/DEF/W-O/unfinished and match-tiebreak [..] scores excluded)
  p_ij      = (n_ij + 0.5) / (N + 2);   shrunk p*_ij = w p_ij + (1 - w) p_i. p_.j  with w = N / (N + 80);   odds ratio = p*11 p*00 / (p*10 p*01);
  CI        = exp(log OR +- 1.96 sqrt(sum 1/(n_ij + 0.5)))   (Woolf, on the add-0.5 counts)
Columns: tbs_n, tbs_p_tiebreak, tbs_p_sweep, tbs_p_both, tbs_odds_ratio, tbs_or_lo, tbs_or_hi.
Not implemented (so PARTIAL, not FULL): the catalog's regression-based opponent adjustment of the hold inputs (the verified additive adjustment is used).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .core import FeatureSpec
from . import tennis_ext4 as X4
from .tennis_ext4 import CONTENT, load_raw, perturb  # noqa: F401  (re-exported for the generic replay harness)

S = "TENNIS"
COLS = ["tbs_n", "tbs_p_tiebreak", "tbs_p_sweep", "tbs_p_both", "tbs_odds_ratio", "tbs_or_lo", "tbs_or_hi"]
W0, BIN = 80.0, 0.05
_SET = re.compile(r"^(\d+)-(\d+)(?:\((\d+)\))?$")


def parse_score(score) -> tuple[float, float]:
    """(any_tiebreak, straight_sets_win) as 1.0/0.0, or (nan, nan) when the score is not a clean completed set-scored match. Winner's games are listed first."""
    s = str(score)
    if any(t in s for t in ("RET", "W/O", "DEF", "ABD", "UNF", "Default", "[", "nan")): return np.nan, np.nan
    sets = s.split()
    if not sets: return np.nan, np.nan
    tb = sweep = 1.0; tb = 0.0
    for t in sets:
        m = _SET.match(t)
        if not m: return np.nan, np.nan
        a, b = int(m.group(1)), int(m.group(2))
        if m.group(3) is not None: tb = 1.0
        if a <= b: sweep = 0.0
    return tb, sweep


def compute(raw: dict) -> dict:
    base = X4.compute(raw)["team"]
    m = raw["matches"][["game_id", "best_of", "score", "date"]].copy()
    ts = m.score.map(parse_score); m["tb"] = [t[0] for t in ts]; m["sw"] = [t[1] for t in ts]
    h = base.groupby("game_id").agg(h1=("gps_hold_pre", "first"), h2=("gps_opp_hold_pre", "first")).reset_index()
    m = m.merge(h, on="game_id", how="left")
    m["mh"] = (m.h1 + m.h2) / 2; m["gap"] = (m.h1 - m.h2).abs()
    m["valid_bin"] = m.mh.notna() & m.best_of.notna()
    m["cell"] = np.where(m.valid_bin, np.floor(m.mh / BIN + 1e-9).fillna(-1).astype(int).astype(str) + "|" + np.floor(m.gap / BIN + 1e-9).fillna(-1).astype(int).astype(str) + "|" + m.best_of.fillna(0).astype(int).astype(str), None)
    cnt = m[m.valid_bin & m.tb.notna()].copy()
    cnt["k"] = (cnt.tb * 2 + cnt.sw).astype(int)             # 0: no tb & no sweep, 1: no tb & sweep, 2: tb & no sweep, 3: tb & sweep
    d = cnt.groupby(["cell", "date", "k"]).size().unstack("k", fill_value=0).reindex(columns=[0, 1, 2, 3], fill_value=0).reset_index().sort_values(["cell", "date"], kind="mergesort")
    for k in range(4): d[f"c{k}"] = d.groupby("cell")[k].cumsum()                          # inclusive cumulative counts as of each (cell, date)
    d = d[["cell", "date", "c0", "c1", "c2", "c3"]].sort_values("date", kind="mergesort")
    q = m[m.valid_bin][["game_id", "cell", "date"]].sort_values("date", kind="mergesort")
    q = pd.merge_asof(q, d, on="date", by="cell", direction="backward", allow_exact_matches=False)      # last state on a STRICTLY earlier date within the same cell
    n00, n01, n10, n11 = (q[f"c{k}"].fillna(0).to_numpy(float) for k in range(4))
    N = n00 + n01 + n10 + n11
    with np.errstate(all="ignore"):
        p = {ij: (n + 0.5) / (N + 2) for ij, n in (("00", n00), ("01", n01), ("10", n10), ("11", n11))}
        pt = p["10"] + p["11"]; ps = p["01"] + p["11"]; w = N / (N + W0)
        s11 = w * p["11"] + (1 - w) * pt * ps; s10 = w * p["10"] + (1 - w) * pt * (1 - ps); s01 = w * p["01"] + (1 - w) * (1 - pt) * ps; s00 = w * p["00"] + (1 - w) * (1 - pt) * (1 - ps)
        orr = s11 * s00 / (s10 * s01); se = np.sqrt(sum(1.0 / (n + 0.5) for n in (n00, n01, n10, n11)))
    res = pd.DataFrame({"game_id": q.game_id.to_numpy(), "tbs_n": N, "tbs_p_tiebreak": s10 + s11, "tbs_p_sweep": s01 + s11, "tbs_p_both": s11, "tbs_odds_ratio": orr, "tbs_or_lo": np.exp(np.log(orr) - 1.96 * se), "tbs_or_hi": np.exp(np.log(orr) + 1.96 * se)})
    out = base[["game_id", "team", "date", "season"]].merge(res, on="game_id", how="left")
    out.loc[out.tbs_n.isna() | (out.tbs_n < 1), COLS[1:]] = np.nan      # empty table: undefined, not zero
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "ten.tiebreak_sweep_joint_table", "team", COLS, "PARTIAL",
                        "point-in-time 2x2 table (any set tiebreak x straight-sets win) by mean hold (0.05 bins) x |hold gap| (0.05 bins) x best_of over strictly earlier completed matches, add-0.5 smoothing, shrinkage to the product of marginals with weight N/(N+80), odds ratio with Woolf CI",
                        ["pre-match hold probabilities (verified ext4 columns)", "0.05 x 0.05 x best_of bins", "2x2 counts over strictly earlier completed matches", "add-0.5 Laplace", "shrinkage N/(N+80) to the product of marginals", "odds ratio with CI", "retirements excluded"],
                        ["catalog's regression-based opponent adjustment of the hold inputs (additive adjustment used)", "Sackmann scores with match-tiebreak brackets and unfinished matches are excluded rather than modelled"], ["sackmann_atp_wta_matches"], "pregame_rolling")]

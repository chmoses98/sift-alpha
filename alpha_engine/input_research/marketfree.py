"""Market-free modelling guard and independent game-script inputs (RESEARCH_ONLY).

POLICY: primary prediction models must not use sportsbook lines, Kalshi prices or any feature derived from them. Prices are only used afterwards, to benchmark a finished
model and look for mispricing. ``assert_market_free`` is called by every model builder; a forbidden column is a hard error, not a warning.

``own_script`` replaces the market game-script inputs (spread, total, implied team total) with the model's OWN pregame expectation: a walk-forward ridge on opponent-adjusted
team ratings (no lines), trained only on seasons before the one being predicted.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# Superset of this lab's guard and PR #59's (alpha_engine/lab/guard.py): implied / closing / consensus / _mkt_ / bid$ / ask$ are rejected too.
FORBIDDEN = re.compile(r"(spread_line|total_line|moneyline|spread_odds|under_odds|over_odds|^mkt_|_mkt_|implied|closing|consensus|^spread_team$|^abs_spread$|odds|price|(^|_)ask($|_)|(^|_)bid($|_)|ask$|bid$|"
                       r"^ix_trailing_x_passrate$|^ix_total_x_pace$|^ix_spread_x|^ix_pace_x_total|kalshi|devig|vig$|close_line|market)", re.I)
# post-game quantities: valid only as TARGETS (from #59)
POSTGAME = re.compile(r"^(home_score|away_score|result|total|overtime)$")
SCRIPT_FEATURES = ["diff_exp_epa_pass", "diff_exp_epa_rush", "diff_exp_sr", "diff_exp_pressure", "diff_exp_sack_vs_prot", "diff_exp_expl_pass", "diff_score_drive", "diff_to_luck",
                   "sum_exp_epa_pass", "sum_exp_epa_rush", "sum_exp_sr", "sum_pace_sec", "sum_neutral_pass", "sum_pass_oe", "sum_to_luck", "sum_pen_rate", "sum_third_conv",
                   "sum_score_drive", "rest_diff", "short_week_any", "div_flag", "neutral_site", "late_season"]


def assert_market_free(cols, allow_targets=()) -> None:
    bad = [c for c in cols if FORBIDDEN.search(str(c)) or (POSTGAME.match(str(c)) and c not in allow_targets)]
    if bad:
        raise ValueError(f"market-derived or post-game columns are forbidden in primary models: {bad}")


def _ridge_fit(X, y, alpha):
    med = np.nanmedian(X, axis=0)
    X = np.where(np.isnan(X), med, X)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    ym = y.mean()
    w = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return lambda Q: ym + ((np.where(np.isnan(Q), med, Q) - mu) / sd) @ w


def own_script(gm: pd.DataFrame, first_train: int = 2012, alpha: float = 300.0) -> pd.DataFrame:
    """Per game: own_exp_margin (home minus away points) and own_exp_total, from team ratings only. Seasons < first_train+2 are NaN (no prior training data)."""
    assert_market_free(SCRIPT_FEATURES)
    d = gm[gm.game_type.eq("REG")].copy() if "game_type" in gm else gm.copy()
    cols = [c for c in SCRIPT_FEATURES if c in d.columns]
    out = pd.DataFrame({"game_id": d.game_id.to_numpy(), "season": d.season.to_numpy(), "own_exp_margin": np.nan, "own_exp_total": np.nan})
    X = d[cols].to_numpy(float)
    ok = d.result.notna().to_numpy()
    for s in sorted(d.season.unique()):
        tr = (d.season < s).to_numpy() & ok & (d.season >= first_train).to_numpy()
        if tr.sum() < 500:
            continue
        te = (d.season == s).to_numpy()
        fm = _ridge_fit(X[tr], d.result.to_numpy(float)[tr], alpha)
        ft = _ridge_fit(X[tr], d.total.to_numpy(float)[tr], alpha)
        out.loc[te, "own_exp_margin"] = fm(X[te]); out.loc[te, "own_exp_total"] = ft(X[te])
    return out


def qb_market_free(qb: pd.DataFrame, script: pd.DataFrame) -> pd.DataFrame:
    """Replace the market game-script columns of the QB table with the model's own expectation; drop everything derived from a line."""
    q = qb.merge(script[["game_id", "own_exp_margin", "own_exp_total"]], on="game_id", how="left")
    sign = np.where(q["side"] == "h", 1.0, -1.0)
    q["own_spread_team"] = sign * q["own_exp_margin"]
    q["own_abs_spread"] = q["own_spread_team"].abs()
    q["own_total"] = q["own_exp_total"]
    q["own_exp_team_pts"] = q["own_exp_total"] / 2 + q["own_spread_team"] / 2
    q["ix_own_trailing_x_passrate"] = (-q["own_spread_team"]).clip(lower=0) * q["team_neutral_pass"]
    q["ix_own_total_x_pace"] = q["own_exp_team_pts"] * q["team_sec_play"]
    drop = [c for c in q.columns if c in ("spread_team", "total_line", "implied_team_total", "abs_spread", "ix_trailing_x_passrate", "ix_total_x_pace")]
    return q.drop(columns=drop + ["own_exp_margin", "own_exp_total"])

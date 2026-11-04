"""Do football features add anything to the market-centred NFL game-total on chronological holdouts?

Question (P2): the production NFL total/team-total pricer centres on the market line and a residual bank and references NO football
input. For each candidate input group we fit, on PAST seasons only, a ridge model of the market residual  y = total - total_line  and
score it on the next season (expanding-window by season; test seasons 2020..2025). Baselines: B0 = the market line itself (residual 0) and
B1 = market + past mean residual. A group counts as an incremental improvement only if its squared-error gain over B0 is positive after
a calendar-week-cluster bootstrap, Bonferroni over every group tried, in both halves of the test period, and with each test season
dropped in turn. Nothing here is a betting claim: the line is a near-close consensus of undocumented timing (not point-in-time at a
horizon), there are no prices or fees, and `ctx.*_qb_change` uses the REALISED starter (a pregame-availability caveat, reported)."""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

import numpy as np

BOOT = 4000
SEED = 20261104
TEST_SEASONS = list(range(2020, 2026))
LAMBDAS = (10.0, 100.0, 1000.0)


def groups(df) -> dict[str, list[str]]:
    d = df
    d["pace_plays_sum"] = d["env.plays"]
    d["epa_off_sum"] = d["q_home_off.epa_play"] + d["q_away_off.epa_play"]
    d["epa_def_sum"] = d["q_home_def.epa_play"] + d["q_away_def.epa_play"]
    d["pts_sum"] = d["mx_home.points"] + d["mx_away.points"]
    d["td_drive_sum"] = d["q_home_off.td_per_drive"] + d["q_away_off.td_per_drive"]
    d["expl_sum"] = d["q_home_off.explosive_rate"] + d["q_away_off.explosive_rate"]
    d["sr_sum"] = d["q_home_off.success_rate"] + d["q_away_off.success_rate"]
    d["dome"] = d["roof"].isin(["dome", "closed"]).astype(float)
    d["qb_change_any"] = d["ctx.home_qb_change"].astype(float) + d["ctx.away_qb_change"].astype(float)
    return {
        "pace": ["pace_plays_sum", "env.sec_per_play"],
        "epa_efficiency": ["epa_off_sum", "epa_def_sum", "off_quality_sum.epa", "def_quality_sum.epa", "sr_sum"],
        "explosiveness_scoring": ["expl_sum", "td_drive_sum", "pts_sum"],
        "pass_rate_script": ["env.neutral_pass_rate"],
        "qb_change_REALISED_STARTER": ["qb_change_any"],
        "rest_context": ["home_rest", "away_rest", "dome", "neutral"],
        "all_features": ["pace_plays_sum", "env.sec_per_play", "epa_off_sum", "epa_def_sum", "off_quality_sum.epa", "def_quality_sum.epa", "sr_sum", "expl_sum", "td_drive_sum", "pts_sum",
                         "env.neutral_pass_rate", "qb_change_any", "home_rest", "away_rest", "dome", "neutral"],
    }


def _ridge(Xtr, ytr, lam):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    Z = (Xtr - mu) / sd
    ym = ytr.mean()
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    beta = np.linalg.solve(A, Z.T @ (ytr - ym))
    return lambda X: ym + ((X - mu) / sd) @ beta


def predict(df, feats: list[str]) -> np.ndarray:
    """Expanding-window by season; lambda picked on the last TRAIN season only."""
    out = np.full(len(df), np.nan)
    seasons = df["season"].to_numpy()
    X = df[feats].to_numpy(float)
    y = df["resid"].to_numpy(float)
    for s in TEST_SEASONS:
        tr, te = seasons < s, seasons == s
        last = seasons == s - 1
        fit_tr = tr & ~last
        best, best_l = None, LAMBDAS[0]
        for lam in LAMBDAS:
            f = _ridge(X[fit_tr], y[fit_tr], lam)
            e = float(np.mean((f(X[last]) - y[last]) ** 2))
            if best is None or e < best:
                best, best_l = e, lam
        out[te] = _ridge(X[tr], y[tr], best_l)(X[te])
    return out


def b1(df) -> np.ndarray:
    out = np.full(len(df), np.nan)
    seasons = df["season"].to_numpy()
    y = df["resid"].to_numpy(float)
    for s in TEST_SEASONS:
        out[seasons == s] = y[seasons < s].mean()
    return out


def _boot(d, keys, rng, alpha):
    g = defaultdict(list)
    for x, k in zip(d, keys):
        g[k].append(x)
    gl = [np.asarray(v) for v in g.values()]
    m = len(gl)
    means = []
    for _ in range(BOOT):
        idx = [rng.randrange(m) for _ in range(m)]
        tot = sum(gl[i].sum() for i in idx)
        cnt = sum(len(gl[i]) for i in idx)
        means.append(tot / cnt)
    means.sort()
    return means[int(alpha / 2 * BOOT)], means[min(BOOT - 1, int((1 - alpha / 2) * BOOT) - 1)]


def evaluate(df) -> dict[str, Any]:
    rng = random.Random(SEED)
    df = df.sort_values(["season", "week", "game_id"]).reset_index(drop=True)
    G = groups(df)
    test = df["season"].isin(TEST_SEASONS).to_numpy()
    y = df["resid"].to_numpy(float)
    keys = [f"{s}-{w}" for s, w in zip(df["season"], df["week"])]
    base1 = b1(df)
    n = int(test.sum())
    res: dict[str, Any] = {"n_test_games": n, "test_seasons": TEST_SEASONS, "n_groups_tried": len(G), "baselines": {
        "B0_market_line": {"rmse": round(float(np.sqrt(np.mean(y[test] ** 2))), 4), "mae": round(float(np.mean(np.abs(y[test]))), 4)},
        "B1_market_plus_past_mean_residual": {"rmse": round(float(np.sqrt(np.mean((y[test] - base1[test]) ** 2))), 4), "mae": round(float(np.mean(np.abs(y[test] - base1[test]))), 4)}}, "groups": {}}
    tk = [k for k, t in zip(keys, test) if t]
    seasons = df["season"].to_numpy()
    for name, feats in G.items():
        p = predict(df, feats)
        d_sq = ((y - 0.0) ** 2 - (y - p) ** 2)[test]               # >0: the model beats the market line itself
        d_sq1 = ((y - base1) ** 2 - (y - p) ** 2)[test]
        d_abs = (np.abs(y) - np.abs(y - p))[test]
        lo, hi = _boot(d_sq, tk, rng, 0.05)
        blo, bhi = _boot(d_sq, tk, rng, 0.05 / len(G))
        h = n // 2
        halves = [float(d_sq[:h].mean()), float(d_sq[h:].mean())]
        loso = {int(s): round(float(d_sq[seasons[test] != s].mean()), 4) for s in TEST_SEASONS}
        verdict = ("VALIDATED_INCREMENTAL" if blo > 0 and min(halves) > 0 and min(loso.values()) > 0 else
                   "SUGGESTIVE_UNCONFIRMED" if lo > 0 else "WORSE_THAN_MARKET" if bhi < 0 else "NOT_DEMONSTRATED")
        res["groups"][name] = {"features": feats, "mse_gain_vs_market_line": round(float(d_sq.mean()), 4), "ci95_week_cluster": [round(float(lo), 4), round(float(hi), 4)], "ci_bonferroni": [round(float(blo), 4), round(float(bhi), 4)],
                               "mse_gain_vs_B1": round(float(d_sq1.mean()), 4), "mae_gain_vs_market_line": round(float(d_abs.mean()), 4), "halves_mse_gain": [round(x, 4) for x in halves],
                               "leave_one_season_out_mse_gain": loso, "rmse": round(float(np.sqrt(np.mean(((y - p)[test]) ** 2))), 4), "verdict": verdict}
    res["n_week_clusters"] = len(set(tk))
    return res

"""NFL game-level market families (total, spread, moneyline) vs the closing market, with learned input importance.

Kalshi families covered (research/audit/input_registry.json blueprints game_total / game_side): NFL game total, NFL point spread, NFL game winner.
Benchmark: the nflverse closing consensus line / de-vigged closing price (a sportsbook CLOSE, not a Kalshi executable price at any horizon).
This answers "do pregame inputs add information beyond the closing market?" It is NOT an execution, fee or Kalshi-price test.

For every family and every candidate input the run produces:
  standalone  - out-of-sample R^2 gain of the input group on the RAW outcome vs a no-information baseline (importance without the market)
  incremental - MSE gain vs the market line (B0) and market+past-mean-residual (B1) on the RESIDUAL target (importance beyond the market)
  weight      - ridge coefficient (points per +1 SD of the input, with a season/week-cluster bootstrap CI) and GBM partial-dependence deciles
  significance- per-input cluster-bootstrap p, Benjamini-Hochberg q across all inputs; Holm across groups and interactions
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import stats as S

FIRST_MODEL_SEASON = 2013      # snap/injury coverage starts here; ratings burn in from 2010
TEST_FIRST = 2017
SIGMA_FLOOR = 1.0

COMMON_CONTEXT = ["dome", "wind_eff", "cold", "rest_diff", "short_week_any", "div_flag", "neutral_site", "late_season", "games_played_min"]

# group -> columns, per family orientation. 'sum' features for totals, 'diff' for margins.
def groups_for(kind: str) -> dict[str, list[str]]:
    s = kind == "total"
    p = "sum_" if s else "diff_"
    g = {
        "pass_efficiency_matchup": [f"{p}exp_epa_pass"],
        "rush_efficiency_matchup": [f"{p}exp_epa_rush"],
        "success_rate_matchup": [f"{p}exp_sr"],
        "pressure_and_protection": [f"{p}exp_pressure", f"{p}exp_sack_vs_prot"],
        "explosive_plays": [f"{p}exp_expl_pass"],
        "scoring_conversion": [f"{p}score_drive"] + (["sum_third_conv"] if s else []),
        "turnover_regression": ["sum_to_luck" if s else "diff_to_luck"],
        "penalties": ["sum_pen_rate"],
        "qb_quality_REALISED_STARTER": (["sum_qb_epa"] if s else ["diff_qb_epa"]),
        "qb_change_REALISED_STARTER": (["qb_change_any"] if s else ["diff_qb_change"]),
        "injuries_qb": [f"inj_{'sum' if s else 'diff'}_qb"],
        "injuries_ol": [f"inj_{'sum' if s else 'diff'}_ol"],
        "injuries_skill": [f"inj_{'sum' if s else 'diff'}_skill"],
        "injuries_defense": [f"inj_{'sum' if s else 'diff'}_{x}" for x in ("dl", "lb", "db")],
        "environment": ["dome", "wind_eff", "cold"],
        "rest_schedule": ["rest_diff", "short_week_any", "div_flag", "neutral_site", "late_season"],
        "sample_maturity": ["games_played_min"],
    }
    if s:
        g["pace"] = ["sum_pace_sec", "sum_plays_rating"]
        g["pass_rate_script"] = ["sum_neutral_pass", "sum_pass_oe"]
        g["market_level_structure"] = ["mkt_total_level", "mkt_abs_spread"]
    else:
        g["pass_rate_script"] = ["diff_neutral_pass"]
        g["market_level_structure"] = ["mkt_abs_spread", "mkt_total_level"]
    return g


INTERACTIONS = {
    "total": {
        "ix_spread_x_passrate": ("mkt_abs_spread", "sum_neutral_pass", "Larger spreads shift scripts toward the trailing team passing; clock-stopping passes add possessions only if both offences can sustain them."),
        "ix_wind_x_expl": ("wind_eff", "sum_exp_expl_pass", "Wind suppresses the deep/explosive pass, so explosiveness should matter less in high wind."),
        "ix_pace_x_total": ("sum_pace_sec", "mkt_total_level", "A slow-pace rating should matter more when the market already expects many possessions."),
        "ix_qbinj_x_epa": ("inj_sum_qb", "sum_qb_epa", "A QB injury designation matters more for offences that depend on a high-EPA quarterback."),
    },
    "margin": {
        "ix_pressure_x_qb": ("diff_exp_pressure", "diff_qb_epa", "Pass-rush edges hurt more against quarterbacks who are less able to escape/process pressure (proxied by past EPA)."),
        "ix_olinj_x_pressure": ("inj_diff_ol", "diff_exp_pressure", "Offensive-line injuries amplify a pass-rush mismatch."),
        "ix_qbinj_x_epa": ("inj_sum_qb", "diff_qb_epa", "QB injury status interacts with how much the QB matters."),
    },
}

LABELS = {
    "sum_exp_epa_pass": "Passing EPA/dropback matchup (both offences vs the opposing defences, opponent-adjusted)",
    "diff_exp_epa_pass": "Passing EPA/dropback matchup edge (home minus away, opponent-adjusted)",
    "sum_exp_epa_rush": "Rushing EPA/play matchup (sum)", "diff_exp_epa_rush": "Rushing EPA/play matchup edge",
    "sum_exp_sr": "Success-rate matchup (sum)", "diff_exp_sr": "Success-rate matchup edge",
    "sum_exp_pressure": "QB-hit/sack pressure matchup (sum)", "diff_exp_pressure": "QB-hit/sack pressure matchup edge",
    "sum_exp_sack_vs_prot": "Sack-rate vs protection matchup (sum)", "diff_exp_sack_vs_prot": "Sack-rate vs protection matchup edge",
    "sum_exp_expl_pass": "Explosive-pass (20+) rate matchup (sum)", "diff_exp_expl_pass": "Explosive-pass rate matchup edge",
    "sum_score_drive": "Drive scoring rate (sum)", "diff_score_drive": "Drive scoring rate edge", "sum_third_conv": "3rd-down conversion (sum)",
    "sum_to_luck": "Turnover rate (offence+defence, regression component)", "diff_to_luck": "Turnover-rate edge (regression component)",
    "sum_pen_rate": "Offensive/defensive penalty rate", "sum_qb_epa": "Starting QB EPA/dropback (shrunk; realised starter)", "diff_qb_epa": "QB EPA/dropback edge (shrunk; realised starter)",
    "qb_change_any": "QB change vs previous game (either team; realised starter)", "diff_qb_change": "QB change edge (realised starter)",
    "inj_sum_qb": "QB Out/Doubtful/Questionable snap-weighted impact (sum)", "inj_diff_qb": "QB injury impact (home minus away)",
    "inj_sum_ol": "OL injury impact (sum)", "inj_diff_ol": "OL injury impact (home minus away)",
    "inj_sum_skill": "WR/TE/RB injury impact (sum)", "inj_diff_skill": "WR/TE/RB injury impact (home minus away)",
    "inj_sum_dl": "DL injury impact (sum)", "inj_diff_dl": "DL injury impact (home minus away)",
    "inj_sum_lb": "LB injury impact (sum)", "inj_diff_lb": "LB injury impact (home minus away)",
    "inj_sum_db": "DB injury impact (sum)", "inj_diff_db": "DB injury impact (home minus away)",
    "dome": "Dome / closed roof", "wind_eff": "Wind (mph, 0 indoors)", "cold": "Cold (degrees below 65F, 0 indoors)",
    "rest_diff": "Rest-days difference (home minus away)", "short_week_any": "Either team on short rest", "div_flag": "Divisional game", "neutral_site": "Neutral site",
    "late_season": "Late season (week 14+)", "games_played_min": "Fewer games of evidence for the less-observed team",
    "sum_pace_sec": "Neutral-situation seconds per play (both teams; higher = slower)", "sum_plays_rating": "Plays-per-game ratings (offence+defence)",
    "sum_neutral_pass": "Neutral-situation pass rate (both teams)", "sum_pass_oe": "Pass rate over expected (both teams)", "diff_neutral_pass": "Neutral pass-rate edge",
    "mkt_total_level": "Market total level", "mkt_abs_spread": "Market absolute spread (expected game script)",
    "ix_spread_x_passrate": "Interaction: |spread| x neutral pass rate", "ix_wind_x_expl": "Interaction: wind x explosive-pass matchup", "ix_pace_x_total": "Interaction: pace x market total",
    "ix_qbinj_x_epa": "Interaction: QB injury x QB quality", "ix_pressure_x_qb": "Interaction: pressure matchup x QB quality", "ix_olinj_x_pressure": "Interaction: OL injury x pressure matchup",
}

# which catalog input ids each feature column operationalises (the dashboard joins evidence to the catalog on these ids)
FEATURE_CATALOG = {
    "exp_epa_pass": ["nfl.off_epa", "nfl.def_epa", "nfl.pass_efficiency"], "exp_epa_rush": ["nfl.rush_efficiency", "nfl.run_defense", "nfl.off_epa"],
    "exp_sr": ["nfl.success_rate"], "exp_pressure": ["nfl.pass_rush", "nfl.pressure_qb", "nfl.ol"], "exp_sack_vs_prot": ["nfl.pass_rush", "nfl.ol"],
    "exp_expl_pass": ["nfl.explosive"], "score_drive": ["nfl.drives", "nfl.redzone"], "third_conv": ["nfl.redzone"],
    "to_luck": ["nfl.turnovers", "nfl.fumble_luck"], "pen_rate": ["nfl.penalties"], "qb_epa": ["nfl.qb_efficiency", "nfl.qb"], "qb_change": ["nfl.qb"],
    "inj_sum_qb": ["nfl.injuries_pit", "nfl.qb"], "inj_diff_qb": ["nfl.injuries_pit", "nfl.qb"], "inj_sum_ol": ["nfl.injuries_pit", "nfl.ol"], "inj_diff_ol": ["nfl.injuries_pit", "nfl.ol"],
    "inj_sum_skill": ["nfl.injuries_pit", "nfl.skill_avail"], "inj_diff_skill": ["nfl.injuries_pit", "nfl.skill_avail"],
    "inj_sum_dl": ["nfl.injuries_pit", "nfl.def_personnel", "nfl.pass_rush"], "inj_diff_dl": ["nfl.injuries_pit", "nfl.def_personnel", "nfl.pass_rush"],
    "inj_sum_lb": ["nfl.injuries_pit", "nfl.def_personnel"], "inj_diff_lb": ["nfl.injuries_pit", "nfl.def_personnel"],
    "inj_sum_db": ["nfl.injuries_pit", "nfl.def_personnel"], "inj_diff_db": ["nfl.injuries_pit", "nfl.def_personnel"],
    "sum_pace_sec": ["nfl.pace"], "sum_plays_rating": ["nfl.pace", "nfl.drives"], "neutral_pass": ["nfl.proe", "nfl.script"], "pass_oe": ["nfl.proe"],
    "dome": ["nfl.weather_pit", "nfl.venue"], "wind_eff": ["nfl.weather_pit"], "cold": ["nfl.weather_pit"], "rest_diff": ["nfl.rest_travel"], "short_week_any": ["nfl.rest_travel"],
    "div_flag": ["nfl.divisional_familiarity"], "neutral_site": ["nfl.venue"], "late_season": ["nfl.motivation_seeding"], "games_played_min": ["nfl.ratings"],
    "mkt_total_level": ["m.external_lines", "nfl.script"], "mkt_abs_spread": ["m.external_lines", "nfl.script"],
    "ix_spread_x_passrate": ["nfl.script", "nfl.proe"], "ix_wind_x_expl": ["nfl.weather_pit", "nfl.explosive"], "ix_pace_x_total": ["nfl.pace", "m.external_lines"],
    "ix_qbinj_x_epa": ["nfl.injuries_pit", "nfl.qb_efficiency"], "ix_pressure_x_qb": ["nfl.pressure_qb", "nfl.qb_efficiency"], "ix_olinj_x_pressure": ["nfl.ol", "nfl.pass_rush"],
}


def links_for(col: str) -> list[str]:
    """Longest-matching-key lookup so 'sum_exp_epa_pass' and 'diff_exp_epa_pass' both resolve to the same catalog inputs."""
    if col in FEATURE_CATALOG:
        return FEATURE_CATALOG[col]
    best = None
    for k in FEATURE_CATALOG:
        if k in col and (best is None or len(k) > len(best)):
            best = k
    return FEATURE_CATALOG[best] if best else []


def label(col: str) -> str:
    return LABELS.get(col, col)


# ---------------------------------------------------------------------------------------------------------------------- core helpers
def _frame(d: pd.DataFrame) -> pd.DataFrame:
    d = d[(d["season"] >= FIRST_MODEL_SEASON) & d["result"].notna() & d["total_line"].notna() & d["spread_line"].notna()].copy()
    return d.sort_values(["season", "week", "gameday", "game_id"]).reset_index(drop=True)


def _test_seasons(d):
    return [int(s) for s in sorted(d["season"].unique()) if s >= TEST_FIRST]


def _single_feature_wf(d, cols, y, seasons, test_seasons, boot, test, b1, ridge_gain_cache=None):
    pass


def _gain_vs(boot, test, base_pred, model_pred, y, seasons, ts, alphas=(0.05,)):
    return S.gain_summary(boot, test, (y - base_pred) ** 2, (y - model_pred) ** 2, seasons, ts, alphas)


def _pearson(a, b):
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 30 or np.std(a[m]) == 0:
        return float("nan")
    return float(np.corrcoef(a[m], b[m])[0, 1])


def fit_logit_offset(X, y, offset, lam, iters=40):
    """Penalised logistic regression with an offset: P = sigmoid(a + b*offset + X beta); a, b unpenalised, beta ridge-penalised (on standardised X)."""
    mu, sd = S._prep(X)
    Z = np.nan_to_num((X - mu) / sd)
    n, k = Z.shape
    A = np.column_stack([np.ones(n), offset, Z])
    pen = np.diag([0.0, 0.0] + [lam] * k)
    w = np.array([0.0, 1.0] + [0.0] * k)
    for _ in range(iters):
        eta = A @ w
        p = 1 / (1 + np.exp(-np.clip(eta, -30, 30)))
        W = np.clip(p * (1 - p), 1e-6, None)
        g = A.T @ (y - p) - pen @ w
        H = A.T @ (A * W[:, None]) + pen + 1e-8 * np.eye(k + 2)
        step = np.linalg.solve(H, g)
        w = w + step
        if np.abs(step).max() < 1e-7:
            break
    def predict(Xn, off):
        return 1 / (1 + np.exp(-np.clip(w[0] + w[1] * off + np.nan_to_num((Xn - mu) / sd) @ w[2:], -30, 30)))
    return predict, w


LOGIT_LAMS = (10.0, 100.0, 1000.0, 10000.0)


def wf_logit(X, y, offset, seasons, test_seasons, min_train=300):
    out = np.full(len(y), np.nan)
    for s in test_seasons:
        tr, te, last = seasons < s, seasons == s, seasons == s - 1
        if tr.sum() < min_train or not te.any():
            continue
        fit_tr = tr & ~last
        best, bl = None, LOGIT_LAMS[0]
        for lam in LOGIT_LAMS:
            f, _ = fit_logit_offset(X[fit_tr], y[fit_tr], offset[fit_tr], lam)
            m = ~np.isnan(y[last])
            e = float(np.mean(S.logloss(f(X[last][m], offset[last][m]), y[last][m])))
            if best is None or e < best:
                best, bl = e, lam
        f, _ = fit_logit_offset(X[tr], y[tr], offset[tr], bl)
        out[te] = f(X[te], offset[te])
    return out


# ---------------------------------------------------------------------------------------------------------------------- continuous families
def run_continuous(df: pd.DataFrame, kind: str, n_boot: int = S.BOOT, quick: bool = False) -> dict:
    """kind='total' (target total-total_line) or 'margin' (margin-spread_line)."""
    d = _frame(df)
    ts = _test_seasons(d)
    resid = d["resid_total" if kind == "total" else "resid_margin"].to_numpy(float)
    raw = d["total" if kind == "total" else "margin"].to_numpy(float)
    mkt_pred = (d["total_line"] if kind == "total" else d["spread_line"]).to_numpy(float)       # B0 point forecast of the raw outcome
    res = study(d, ts, resid, raw, mkt_pred, groups_for(kind), INTERACTIONS[kind], n_boot, quick, prob_kind=kind)
    res["kind"] = kind
    return res


def study(d: pd.DataFrame, ts: list[int], resid: np.ndarray, raw: np.ndarray, mkt_pred: np.ndarray, G: dict, interactions: dict, n_boot: int, quick: bool,
          prob_kind: str | None = None, standalone_exclude_prefix=("mkt_", "ix_"), standalone_skip_groups=("market_level_structure",)) -> dict:
    """Generic incremental-value study. `mkt_pred` is the benchmark point forecast of `raw`; resid = raw - mkt_pred. Used by every continuous family."""
    seasons = d["season"].to_numpy()
    kind = prob_kind
    all_cols = [c for c in dict.fromkeys(c for v in G.values() for c in v) if c in d.columns and d[c].notna().mean() > 0.2]
    G = {k: [c for c in v if c in all_cols] for k, v in G.items()}
    G = {k: v for k, v in G.items() if v}
    X_all = d[all_cols].to_numpy(float)
    # ---- baselines on the residual target
    b1 = S.baseline_mean(resid, seasons, ts)
    # ---- walk-forward ridge for each group + all features
    pred = {}
    lams = {}
    for name, cols in G.items():
        idx = [all_cols.index(c) for c in cols]
        pred[name], lams[name] = S.walk_forward_ridge(X_all[:, idx], resid, seasons, ts)
    pred["ALL_FEATURES_RIDGE"], lams["ALL"] = S.walk_forward_ridge(X_all, resid, seasons, ts)
    test = ~np.isnan(pred["ALL_FEATURES_RIDGE"])
    keys = np.array([f"{s}-{w:02d}" for s, w in zip(seasons, d["week"])])
    boot = S.ClusterBoot(keys[test], n_boot=n_boot)
    base_mse = float(np.mean((resid - b1)[test] ** 2))
    # ---- group tests (confirmatory family; Holm)
    group_res = {}
    for name in pred:
        g = _gain_vs(boot, test, b1, pred[name], resid, seasons, ts)
        g0 = _gain_vs(boot, test, np.zeros_like(resid), pred[name], resid, seasons, ts)
        group_res[name] = {"gain_vs_B1": g, "mse_gain_vs_market_B0": g0["mean"], "pct_of_base_mse": 100 * g["mean"] / base_mse}
    holm_g = S.holm({k: v["gain_vs_B1"]["p"] for k, v in group_res.items()})
    for k, v in group_res.items():
        v["holm_p"] = holm_g[k]
        v["verdict"] = S.verdict(v["gain_vs_B1"], holm_g[k])
    # ---- GBM (nonlinear/interaction capable) on all features
    gbm_pred = S.walk_forward_gbm(X_all, resid, seasons, ts)
    gg = _gain_vs(boot, test, b1, gbm_pred, resid, seasons, ts)
    gbm_vs_ridge = _gain_vs(boot, test, pred["ALL_FEATURES_RIDGE"], gbm_pred, resid, seasons, ts)
    gbm = {"gain_vs_B1": gg, "gain_vs_ridge": gbm_vs_ridge, "n_features": len(all_cols)}
    gbm["holm_p"] = min(1.0, gg["p"] * 2)  # two model classes in the headline comparison (ridge, GBM)
    gbm["verdict"] = S.verdict(gg, gbm["holm_p"])
    # ---- per-input incremental tests (discovery family; BH)
    feat_res = {}
    pvals = {}
    for c in all_cols:
        i = all_cols.index(c)
        p1, _ = S.walk_forward_ridge(X_all[:, [i]], resid, seasons, ts)
        g = _gain_vs(boot, test, b1, p1, resid, seasons, ts)
        feat_res[c] = {"gain_vs_B1": g, "pct_of_base_mse": 100 * g["mean"] / base_mse}
        pvals[c] = g["p"]
    q = S.benjamini_hochberg(pvals)
    holm_f = S.holm(pvals)
    # ---- correlation with market residual + sign stability across seasons
    for c in all_cols:
        x = d[c].to_numpy(float)
        per = {int(s): _pearson(x[seasons == s], resid[seasons == s]) for s in ts}
        sgn = [np.sign(v) for v in per.values() if not np.isnan(v)]
        feat_res[c].update({"q_bh": q[c], "holm_p": holm_f[c], "corr_with_market_residual": _pearson(x[test], resid[test]),
                            "season_corrs": per, "sign_consistency": float(abs(np.mean(sgn))) if sgn else None,
                            "coverage": float(d[c].notna().mean()), "coverage_test": float(d.loc[test, c].notna().mean()),
                            "verdict": S.verdict(feat_res[c]["gain_vs_B1"], holm_f[c])})
    # ---- standalone predictive importance on the RAW outcome (market line excluded): how much of the outcome does each group explain?
    raw_b = S.baseline_mean(raw, seasons, ts)
    raw_idx = [i for i, c in enumerate(all_cols) if not c.startswith(standalone_exclude_prefix)]     # standalone = WITHOUT any market-derived input
    raw_all, _ = S.walk_forward_ridge(X_all[:, raw_idx], raw, seasons, ts)
    var_raw = float(np.mean((raw - raw_b)[test] ** 2))
    mkt_mse = float(np.mean((raw - mkt_pred)[test] ** 2))
    standalone = {"no_information_mse": var_raw, "market_line_mse": mkt_mse, "market_r2_vs_no_information": 1 - mkt_mse / var_raw,
                  "all_features_mse": float(np.mean((raw - raw_all)[test] ** 2)), "all_features_r2_vs_no_information": 1 - float(np.mean((raw - raw_all)[test] ** 2)) / var_raw,
                  "groups": {}}
    sp = {}
    for name, cols in G.items():
        if name in standalone_skip_groups:
            continue
        idx = [all_cols.index(c) for c in cols]
        p1, _ = S.walk_forward_ridge(X_all[:, idx], raw, seasons, ts)
        g = _gain_vs(boot, test, raw_b, p1, raw, seasons, ts)
        sp[name] = g["p"]
        standalone["groups"][name] = {"r2_gain_vs_no_information": g["mean"] / var_raw, "ci95_r2": [g["ci_0.05"][0] / var_raw, g["ci_0.05"][1] / var_raw], "seasons_positive": g["seasons_positive"], "seasons_total": g["seasons_total"]}
    qs = S.benjamini_hochberg(sp)
    for k in standalone["groups"]:
        standalone["groups"][k]["q_bh"] = qs[k]
    # ---- weights: ridge fit on all pre-test-end data, bootstrap by cluster; coefficient in outcome units per +1 SD
    train_mask = seasons >= FIRST_MODEL_SEASON
    wts = _weights(X_all, resid, keys, train_mask, all_cols, float(np.median(list(lams["ALL"].values()))), n_boot=200 if not quick else 40)
    for c in all_cols:
        feat_res[c]["weight"] = wts[c]
    # ---- drop-one-group (necessity) vs all-features ridge
    drop = {}
    for name, cols in G.items():
        keep = [i for i, c in enumerate(all_cols) if c not in cols]
        if not keep:
            continue
        pd_, _ = S.walk_forward_ridge(X_all[:, keep], resid, seasons, ts)
        dg = _gain_vs(boot, test, pd_, pred["ALL_FEATURES_RIDGE"], resid, seasons, ts)    # >0: dropping the group hurts
        drop[name] = {"mse_loss_if_removed": dg["mean"], "ci95": dg["ci_0.05"], "p": dg["p"]}
    hq = S.holm({k: v["p"] for k, v in drop.items()})
    for k in drop:
        drop[k]["holm_p"] = hq[k]
    # ---- interactions (pre-specified; Holm)
    ix_res = {}
    main_idx = list(range(len(all_cols)))
    p_main, _ = S.walk_forward_ridge(X_all, resid, seasons, ts)
    for iname, (a, b, hyp) in interactions.items():
        if iname not in d.columns or d[iname].notna().mean() < 0.5:
            continue
        Xi = np.column_stack([X_all, d[iname].to_numpy(float)])
        pi_, _ = S.walk_forward_ridge(Xi, resid, seasons, ts)
        g = _gain_vs(boot, test, p_main, pi_, resid, seasons, ts)
        ix_res[iname] = {"label": label(iname), "components": [a, b], "hypothesis": hyp, "gain_vs_main_effects": g}
    hi = S.holm({k: v["gain_vs_main_effects"]["p"] for k, v in ix_res.items()}) if ix_res else {}
    for k, v in ix_res.items():
        v["holm_p"] = hi[k]
        v["verdict"] = S.verdict(v["gain_vs_main_effects"], hi[k])
    # ---- permutation importance + partial dependence from the GBM (nonlinear functional effects), final model fit on all rows < last test season
    imp = _gbm_importance(X_all, resid, seasons, ts, all_cols)
    # ---- probability scoring vs the market's de-vigged price
    prob = _prob_scoring(d, kind, resid, pred["ALL_FEATURES_RIDGE"], gbm_pred, seasons, ts, test, keys, n_boot) if kind else None
    # ---- the market benchmark itself
    out = {
        "n_games_modeled": int(len(d)), "n_test_games": int(test.sum()), "test_seasons": ts, "n_week_clusters": int(boot.m), "lambdas_by_season_all_features": lams["ALL"],
        "baselines": {"B0_market_line": {"mse": float(np.mean(resid[test] ** 2)), "mae": float(np.mean(np.abs(resid[test])))},
                      "B1_market_plus_past_mean_residual": {"mse": base_mse, "mae": float(np.mean(np.abs((resid - b1)[test])))},
                      "ALL_FEATURES_RIDGE": {"mse": float(np.mean((resid - pred["ALL_FEATURES_RIDGE"])[test] ** 2)), "mae": float(np.mean(np.abs((resid - pred["ALL_FEATURES_RIDGE"])[test])))},
                      "GBM_ALL_FEATURES": {"mse": float(np.mean((resid - gbm_pred)[test] ** 2)), "mae": float(np.mean(np.abs((resid - gbm_pred)[test])))}},
        "groups": group_res, "gbm": gbm, "inputs": feat_res, "standalone": standalone, "drop_one_group": drop, "interactions": ix_res, "importance": imp, "probability": prob,
        "group_members": G,
    }
    # forward-only slice: the in-progress 2026 season (never used for fitting any 2026 prediction)
    last = ts[-1]
    m26 = (seasons == last) & test
    if m26.sum() >= 30:
        out["latest_season_holdout"] = {"season": last, "n": int(m26.sum()), "mse_B1": float(np.mean(((resid - b1)[m26]) ** 2)), "mse_ridge_all": float(np.mean(((resid - pred['ALL_FEATURES_RIDGE'])[m26]) ** 2)),
                                        "mse_gbm_all": float(np.mean(((resid - gbm_pred)[m26]) ** 2)), "mse_B0_market": float(np.mean(resid[m26] ** 2))}
    return out


def _weights(X, y, keys, mask, cols, lam, n_boot=200):
    Xm, ym, km = X[mask], y[mask], keys[mask]
    mu, sd = S._prep(Xm)
    f, beta, ym0 = S.ridge_fit(Xm, ym, lam)
    uniq, inv = np.unique(km, return_inverse=True)
    rng = np.random.default_rng(S.SEED)
    rows_by = [np.where(inv == i)[0] for i in range(len(uniq))]
    bs = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([rows_by[i] for i in pick])
        _, b, _ = S.ridge_fit(Xm[idx], ym[idx], lam)
        bs.append(b)
    bs = np.array(bs)
    out = {}
    for j, c in enumerate(cols):
        lo, hi = np.quantile(bs[:, j], [0.025, 0.975])
        out[c] = {"per_sd": float(beta[j]), "ci95": [float(lo), float(hi)], "sd": float(sd[j]), "per_unit": float(beta[j] / sd[j]),
                  "ci_excludes_zero": bool(lo > 0 or hi < 0), "unit": "outcome points per +1 SD of the input, conditional on all other inputs (ridge)"}
    return out


def _gbm_importance(X, y, seasons, ts, cols, repeats=3):
    rng = np.random.default_rng(S.SEED)
    deltas = {c: [] for c in cols}
    for s in ts:
        tr, te = seasons < s, seasons == s
        if tr.sum() < 300 or not te.any():
            continue
        m = S.make_gbm().fit(X[tr], y[tr])
        base = np.mean((y[te] - m.predict(X[te])) ** 2)
        for j, c in enumerate(cols):
            ds = []
            for _ in range(repeats):
                Xp = X[te].copy()
                Xp[:, j] = rng.permutation(Xp[:, j])
                ds.append(np.mean((y[te] - m.predict(Xp)) ** 2) - base)
            deltas[c].append(float(np.mean(ds)))
    # partial dependence from the model fit on all rows before the last test season
    last = ts[-1]
    tr = seasons < last
    m = S.make_gbm().fit(X[tr], y[tr])
    out = {}
    for j, c in enumerate(cols):
        v = np.array(deltas[c])
        entry = {"perm_mse_increase_mean": float(v.mean()) if len(v) else None, "seasons_positive": int((v > 0).sum()), "seasons_total": int(len(v))}
        x = X[tr][:, j]
        x = x[~np.isnan(x)]
        if len(np.unique(x)) >= 4:
            grid = np.unique(np.quantile(x, np.linspace(0.05, 0.95, 7)))
            pdp = []
            for gv in grid:
                Xg = X[tr].copy()
                Xg[:, j] = gv
                pdp.append(float(m.predict(Xg).mean()))
            entry["pdp"] = {"x": [float(g) for g in grid], "y": pdp, "range": float(max(pdp) - min(pdp))}
        out[c] = entry
    return out


def _prob_scoring(d, kind, resid, ridge_pred, gbm_pred, seasons, ts, test, keys, n_boot):
    pmkt = (d["p_over_mkt"] if kind == "total" else d["p_homecover_mkt"]).to_numpy(float)
    yb = (d["over"] if kind == "total" else d["home_cover"]).to_numpy(float)
    ok = test & ~np.isnan(pmkt) & ~np.isnan(yb)
    # sigma from the TRAIN residual spread (walk-forward)
    sig = np.full(len(resid), np.nan)
    for s in ts:
        tr = seasons < s
        sig[seasons == s] = max(SIGMA_FLOOR, float(np.std(resid[tr])))
    out = {"market_price_source": "nflverse closing two-way odds, vig removed; coarse (few distinct prices), so it is close to 0.5 by construction",
           "n_scored_non_push": int(ok.sum())}
    boot = S.ClusterBoot(keys[ok], n_boot=n_boot)
    for name, mu in (("ridge_all", ridge_pred), ("gbm_all", gbm_pred)):
        p = np.clip(S.norm_cdf(mu / sig), 0.02, 0.98)
        ll_m, ll_mod = S.logloss(pmkt, yb), S.logloss(p, yb)
        d_ll = (ll_m - ll_mod)[ok]
        d_br = (S.brier(pmkt, yb) - S.brier(p, yb))[ok]
        out[name] = {"logloss_market": float(ll_m[ok].mean()), "logloss_model": float(ll_mod[ok].mean()), "logloss_gain": boot.summarize(d_ll),
                     "brier_market": float(S.brier(pmkt, yb)[ok].mean()), "brier_model": float(S.brier(p, yb)[ok].mean()), "brier_gain": boot.summarize(d_br),
                     "logloss_no_information_0.5": float(np.log(2)), "calibration": S.calibration_slope(p[ok], yb[ok]), "calibration_table": S.calibration_table(p[ok], yb[ok], 8),
                     "hit_rate_model_side": float((((p > 0.5) == (yb == 1))[ok]).mean()), "mean_abs_p_minus_half": float(np.abs(p[ok] - 0.5).mean())}
    out["market_calibration"] = S.calibration_slope(pmkt[ok], yb[ok])
    return out


# ---------------------------------------------------------------------------------------------------------------------- moneyline
def run_moneyline(df: pd.DataFrame, n_boot: int = S.BOOT, quick: bool = False) -> dict:
    d = _frame(df)
    d = d[d["p_home_mkt"].notna() & d["home_win"].notna()].reset_index(drop=True)
    ts = _test_seasons(d)
    seasons = d["season"].to_numpy()
    y = d["home_win"].to_numpy(float)
    pm = np.clip(d["p_home_mkt"].to_numpy(float), 0.01, 0.99)
    off = np.log(pm / (1 - pm))
    G = groups_for("margin")
    all_cols = [c for c in dict.fromkeys(c for v in G.values() for c in v) if c in d.columns and d[c].notna().mean() > 0.2]
    G = {k: [c for c in v if c in all_cols] for k, v in G.items()}
    G = {k: v for k, v in G.items() if v}
    X_all = d[all_cols].to_numpy(float)
    keys = np.array([f"{s}-{w:02d}" for s, w in zip(seasons, d["week"])])
    p_all = wf_logit(X_all, y, off, seasons, ts)
    test = ~np.isnan(p_all)
    boot = S.ClusterBoot(keys[test], n_boot=n_boot)
    ll_mkt = S.logloss(pm, y)
    # recalibrated market (a + b*logit) is the fair competitor for "is the information in the inputs?"
    p_recal = wf_logit(np.zeros((len(y), 1)), y, off, seasons, ts)
    def gain(p):
        return S.gain_summary(boot, test, ll_mkt, S.logloss(np.clip(p, 1e-4, 1 - 1e-4), y), seasons, ts)
    res = {"kind": "moneyline", "n_games_modeled": int(len(d)), "n_test_games": int(test.sum()), "test_seasons": ts, "n_week_clusters": int(boot.m),
           "market_price_source": "nflverse closing moneylines, vig removed (two-way de-vig)",
           "baselines": {"market_devig": {"logloss": float(ll_mkt[test].mean()), "brier": float(S.brier(pm, y)[test].mean()), "calibration": S.calibration_slope(pm[test], y[test])},
                         "market_recalibrated": {"logloss": float(S.logloss(p_recal, y)[test].mean())},
                         "no_information_home_rate": {"logloss": float(np.mean(S.logloss(np.full(len(y), y.mean()), y)[test]))}}}
    g_all = gain(p_all)
    gm = {"logloss_model": float(S.logloss(p_all, y)[test].mean()), "brier_model": float(S.brier(p_all, y)[test].mean()), "logloss_gain_vs_market": g_all,
          "calibration": S.calibration_slope(p_all[test], y[test]), "calibration_table": S.calibration_table(p_all[test], y[test], 8),
          "n_features": len(all_cols)}
    res["all_features"] = gm
    # groups
    group_res, gp = {}, {}
    for name, cols in G.items():
        idx = [all_cols.index(c) for c in cols]
        pg = wf_logit(X_all[:, idx], y, off, seasons, ts)
        g = gain(pg)
        group_res[name] = {"logloss_gain_vs_market": g, "gain_vs_recalibrated_market": S.gain_summary(boot, test, S.logloss(np.clip(p_recal, 1e-4, 1 - 1e-4), y), S.logloss(np.clip(pg, 1e-4, 1 - 1e-4), y), seasons, ts)}
        gp[name] = group_res[name]["gain_vs_recalibrated_market"]["p"]
    hg = S.holm(gp)
    for k in group_res:
        gr = group_res[k]["gain_vs_recalibrated_market"]
        group_res[k]["holm_p"] = hg[k]
        group_res[k]["verdict"] = S.verdict(gr, hg[k])
    res["groups"] = group_res
    # features
    fres, fp = {}, {}
    for j, c in enumerate(all_cols):
        pf = wf_logit(X_all[:, [j]], y, off, seasons, ts)
        g = S.gain_summary(boot, test, S.logloss(np.clip(p_recal, 1e-4, 1 - 1e-4), y), S.logloss(np.clip(pf, 1e-4, 1 - 1e-4), y), seasons, ts)
        fres[c] = {"gain_vs_recalibrated_market": g, "coverage": float(d[c].notna().mean())}
        fp[c] = g["p"]
    q, hf = S.benjamini_hochberg(fp), S.holm(fp)
    for c in all_cols:
        x = d[c].to_numpy(float)
        r = y - pm                                           # outcome minus market probability = what the market missed
        fres[c].update({"q_bh": q[c], "holm_p": hf[c], "corr_with_market_miss": _pearson(x[test], r[test]), "verdict": S.verdict(fres[c]["gain_vs_recalibrated_market"], hf[c])})
    res["inputs"] = fres
    res["group_members"] = G
    # weights: final penalised logit fit
    train = seasons >= FIRST_MODEL_SEASON
    f, w = fit_logit_offset(X_all[train], y[train], off[train], 100.0)
    mu, sd = S._prep(X_all[train])
    res["weights_logit_per_sd"] = {c: float(w[2 + j]) for j, c in enumerate(all_cols)}
    res["offset_slope_and_intercept"] = {"market_logit_slope": float(w[1]), "intercept": float(w[0])}
    return res


def run_all(df: pd.DataFrame, n_boot: int = S.BOOT, quick: bool = False) -> dict:
    return {"total": run_continuous(df, "total", n_boot, quick), "spread": run_continuous(df, "margin", n_boot, quick), "moneyline": run_moneyline(df, n_boot, quick)}

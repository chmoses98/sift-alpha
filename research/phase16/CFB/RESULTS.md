# Phase 16 CFB: full-game TOTAL over-projection, a bounded experiment (research only)
Run against cfb-edge-finder research code at `7ebddfc6` (#308) on vault inputs (CFBD v1-292f3aac, ESPN summaries
collected-20261116). Code: `feats.py`, `total_exp.py`. Output: `results_total.json`. Integration branch head `c0be3ab9` (claude/fable-phase-16-production-9u2jw7).
Dev = 2016-2024 excl. 2020 (challenger totals from leave-one-season-out layer refits); holdout = 2025 + 2026 to
2026-11-15, the 1,413 FBS-vs-FBS games that have a production 0.5.0 forecast. Holdout scored once, after every choice was fixed on dev.
Ladder = 28 half-point strikes floor(mu_challenger) ± 13.5 per game, the same rows for every model. 95% CIs come from a game-clustered bootstrap.

## Diagnosis (residual = actual − challenger total; walk-forward, point-in-time features)
* Dev: mean +0.02, median −0.73, skew +0.37; P(actual > mean) 0.482. Season means range −0.69..+1.40 with no trend.
  By phase, pace tercile and predicted-total tercile the means stay within ±0.5. Dev therefore shows **no mean bias, only a right skew**.
* Holdout: mean **−0.89** (2025 −0.79, 2026 −1.01), median −2.08, P(over) 0.455. The bias grows later in the season
  (navg<3 −0.43, ≥7 games −1.40, postseason −2.35), in high predicted totals (−1.75) and in slow-pace games (−1.29).
  Blowouts (|margin| ≥ 28, defined by outcome, so diagnostic only) run +4.9 against −2.3 for other games.
* Reading: the over-probability bias combines (a) a symmetric normal on a right-skewed residual (median < mean), which
  is visible on dev, and (b) a 2025-26 scoring-environment drop of about 0.9 pts that dev cannot reveal. Dispersion is fine
  (holdout residual SD 15.8 vs σ 16.6). Garbage time and pace do not explain it.

## Fixes (each chosen on dev only)
| model | dev MAE | dev logloss | holdout MAE | holdout RMSE | holdout logloss | slope | bias |
|---|---|---|---|---|---|---|---|
| production 0.5.0 | 14.17 | 0.6627 | 13.62 | 16.96 | 0.6587 | 0.713 | +0.055 |
| challenger #307/#308 | 13.11 | 0.6214 | 12.81 | 15.82 | 0.6240 | 1.019 | +0.034 |
| F1 walk-forward in-season recentring (k0 chosen on dev = none) | 13.11 | 0.6214 | 12.81 | 15.82 | 0.6240 | 1.019 | +0.034 |
| F2 empirical dev residual shape | 13.11 | 0.6209 | 12.81 | 15.82 | **0.6222** | 0.988 | **+0.020** |
| F3 dev shrinkage (b = 0.995) + empirical | 13.11 | 0.6209 | 12.81 | 15.82 | 0.6222 | 0.989 | +0.021 |
Paired holdout deltas against the challenger: F2 logloss **−0.0017 [−0.0030, −0.0005]**, Brier −0.0008 [−0.0013, −0.0002], bias −0.0135,
total MAE 0 (the mean is unchanged). F3 MAE +0.002 [−0.000, +0.004]. On dev, F2 logloss −0.0005 [−0.0011, +0.0001] is not significant.
Against production 0.5.0: challenger MAE −0.81 [−1.08, −0.53], logloss −0.035 [−0.046, −0.024]; F2 logloss −0.037 [−0.048, −0.025].
F1 is a **null result**: in-season recentring worsened dev log loss at every finite k0 (0.6216-0.6229 vs 0.6213), so dev chose
none. For transparency only, the best finite value (k0 = 400, not selected) gives holdout MAE −0.018 [−0.036, +0.002] and logloss −0.0005 [−0.0012, +0.0002].

## Verdict
* F2 is a **calibration-only** improvement, not an accuracy gain: point MAE and RMSE are unchanged. It removes the
  skew part (bias +0.034 → +0.020) and leaves the 2025-26 environment drift, which no dev-fitted fix recovered.
* Full-game total and team totals therefore **stay PARTIAL and are not shipped** in the production integration. The challenger
  total mean is still far more accurate than production 0.5.0, so this is a calibration gap, not a ranking failure.
* Next lever: a prior-season-anchored league scoring intercept, validated once 2026 completes (one more drift season).

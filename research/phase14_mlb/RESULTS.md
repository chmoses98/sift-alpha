# Phase 14 MLB: plate-appearance simulation challenger

Data: vault `postgame_feed_compact` 2022-2026 (MLB Stats API). Regular season plus postseason, 12,359 games and 931k PAs.
Splits: 2022 burn-in, **dev 2023-24**, **validate 2025**, **holdout 2026** (scored once after `frozen_params.json` was
committed in b8be4cc). Reproduce: `python -m research.phase14_mlb.run_phase14 --stage freeze` and then `--stage holdout`.

## Model
- PA outcome rates (K, BB, HBP, 1B, 2B, 3B, HR, OUT) for batters and pitchers. Counts decay by game-day (tau=480), with
  a carry of 0.8 across seasons. Each outcome is shrunk to league using stabilisation constants. Handed splits are shrunk
  toward overall x league platoon. Rates are combined by a multinomial odds-ratio (log5) against the same stand/throws
  league cell, then multiplied by park (team home/road), home-field and team-defence factors.
  Hyper-parameters were chosen on dev PA log-loss (1.4947 for a static league model, 1.4707 here).
- Starter batters faced is the decayed per-pitcher mean, shrunk to league, with a Normal draw (sd 4.5). After that the
  team bullpen rates apply. Base-out transitions are an empirical table from 2022-24. The simulation runs 400 games per
  matchup and handles the home 9th and extras. Win probability gets a logistic recalibration fitted on dev.
- Lineups: **posted** is the actual starting nine (known at lineup posting). **typical** is pregame-safe: the 9 most
  frequent starters over the last 7 games. Both variants use the actual starter; the feed's probable matches it 99.8% of
  the time, but those probables come from a post-game snapshot.
- No-leakage test: changing outcomes on date D or later leaves every prediction for D unchanged (`tests/test_phase14_mlb.py`).

## Holdout 2026 (n = 2,469 games; 4,938 starter K lines; 44,442 posted batter-games)
Δ is challenger minus baseline, with a game-clustered bootstrap 95% CI. Negative means the challenger is better.

| Market (posted) | Baseline | Challenger | Δ [95% CI] |
|---|---|---|---|
| Win Brier (vs Elo, best baseline) | 0.2454 | 0.2442 | -0.0012 [-0.0031, +0.0008] |
| Win Brier, sim stacked with Elo | 0.2454 | 0.2443 | -0.0011 [-0.0021, -0.0002] |
| Win log-loss, stacked | | | -0.0024 [-0.0044, -0.0004] |
| Total runs MAE (vs ridge) | 3.526 | 3.495 | -0.031 [-0.066, +0.002] |
| Total runs CRPS | 2.480 | 2.469 | -0.012 [-0.031, +0.006] |
| Margin MAE | 3.487 | 3.445 | -0.042 [-0.079, -0.010] |
| Pitcher K CRPS (vs season average) | 1.311 | 1.261 | -0.050 [-0.064, -0.037] |
| Pitcher K MAE | 1.871 | 1.789 | -0.082 [-0.106, -0.057] |
| Pitcher K 5+ Brier | 0.2324 | 0.2192 | -0.013 [-0.017, -0.010] |
| Batter hits CRPS | 0.4622 | 0.4541 | -0.0081 [-0.0096, -0.0067] |
| Batter TB CRPS | 0.9249 | 0.8678 | -0.057 [-0.060, -0.054] |
| Batter HR 1+ Brier | 0.1024 | 0.1000 | -0.0023 [-0.0027, -0.0020] |

Calibration slopes: win 1.15 after calibration (0.86 raw). Totals 0.72-0.77. K 1.10-1.13. Batter markets 0.81-0.88. The typical-lineup variant gives nearly the same results (`results.json`).

Validation 2025 (posted, vs ridge):
- Win: Brier +0.0005 [-0.0015, +0.0024], not significant. Stacked: -0.0002 [-0.0012, +0.0007].
- Total CRPS: +0.002 [-0.017, +0.021].
- K CRPS: -0.059 [-0.072, -0.045].
- TB CRPS: -0.058 [-0.062, -0.055].

## Versus production (archived edge-finder-api outputs, 2026, identical games; prices ignored)
| Production output | n | Prod | Challenger | Δ [95% CI] |
|---|---|---|---|---|
| Team total MAE, all archived | 765 g | 3.316 | 3.406 | +0.089 [+0.014, +0.164] |
| Team total MAE, timestamp before first pitch | 313 g | 3.224 | 3.274 | +0.050 [-0.073, +0.168] |
| Margin MAE, timestamp before first pitch | 313 g | 3.408 | 3.376 | -0.031 [-0.113, +0.052] |
| Win Brier, all | 419 g | 0.2369 | 0.2376 | +0.0006 [-0.0092, +0.0107] |
| Win Brier, timestamp before first pitch | 203 g | 0.2417 | 0.2386 | -0.0031 [-0.0190, +0.0122] |
| Hitter hits P(X>=k) Brier | 2,169 (86 g) | 0.1437 | 0.1413 | -0.0024 [-0.0052, +0.0006] |
| Hitter TB P(X>=k) Brier | 2,601 (86 g) | 0.1393 | 0.1407 | +0.0014 [-0.0015, +0.0041] |
| Pitcher K mean MAE (postseason only) | 25 (13 g) | 1.73 | 2.08 | +0.35 [+0.11, +0.56] |

Production team files are overwritten during the day; meta.createdAt is the last write. As a result, the "all" rows can
include post-lineup or post-start information. Production win probability and team runs are not reproducible from
archived inputs, and archives only start on 2026-07-30.

## What failed / caveats
1. **Leak found and fixed:** the feed's `box.batting_order` lists the end-of-game occupant of each slot, including pinch
   hitters. Before the fix, the "posted" variant was overconfident: total slope was 0.35. Lineups now come from the
   starters with order "X00", and a test covers this.
2. Game level: the PA simulation alone is about equal to team run ratings. Dev and 2025 gains are not significant. On the
   2026 holdout, only the Elo-stacked win probability and margin MAE clear zero, and the gains are small.
3. Batter means are over-predicted by 6-8% (hits 0.937 predicted vs 0.872 actual) because starters are simulated as
   batting all game, with no substitution or PA-count model. Batter slopes are 0.8-0.88.
4. Raw simulation probabilities are over-dispersed: win slope 0.75-0.86 and totals about 0.7. The dev logistic
   calibration fixes win probability only.
5. Postseason starter K is worse than the production champion (n=25), because the simulation has no postseason
   quick-hook adjustment.
6. The transition table is structural but in-sample for the dev seasons. Validation and holdout are clean.

## Next lever
Add a participation and PA-count model: batter PA by slot including pinch-hit and rest removal, and a starter hook on
pitch count, times through the order and postseason. This should fix the player-market bias and the K tails.

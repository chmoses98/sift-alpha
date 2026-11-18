# NBA Phase 16: pbp possessions, starters, lineup stints (RESEARCH_ONLY, agent work, not human verified)

Inputs: nba-edge-finder `ef91cea` (#116). Vault `82b9a0f`: espn_pbp 2016-2024 snapshot-20261118 + espn_pbp_boxes_schedules snapshot-20261116.
Code: `build_pbp_lineup_features.py`, `run_experiments.py` (run from the nba-edge-finder worktree). Output: `data/*.csv.gz` (7.9 MB, hashes in `data/build_manifest.json`), `results.json`, entries appended to `readiness_delta.json`.

## Data built
2015-16..2026-27 (to 2026-11-16), regular season + playoffs: 14,330 games, 28,658 game-team rows, 305,377 player-game on-court rows.
Failures 4 (3 with no player box, 1 parse error). Per season (see manifest):
* final score from pbp = box score: 99.8-100%.
* event-counted possessions vs box formula (FGA-OREB+TOV+0.44FTA): r 0.86-0.93, mean abs diff 2.9-4.8; events count 3.0 fewer per team on average.
* box has 5 flagged starters: 99.3-100%. Period-1 starters inferred from pbp alone equal the box flags: 99.9-100%.
* seconds with a lineup that is not 5 players: 0.06-1.4% (worst 2017-18..2019-20).
Pregame features (EWM of earlier games only; team half-life 20, player 25, fixed before results): pace, ORtg, DRtg, starting-unit share
and net, bench net, starters' Q1/Q2 minutes, actual starters' prior on-court net, number of unexpected starters. Truncation leak test
on 6 random dates (same-day outcomes scrambled): max difference 0.

## Experiments (pre-stated in run_experiments.py docstring; dev <= 2023-24 walk-forward; holdout 2024-25, 2025-26, 2026-27 untouched)
**E1 full game, PAG + pbp residual ridge vs PAG** (deltas new - incumbent, game-clustered 95% CI, negative = better). Null.
| set | n | margin MAE | total MAE | winner log loss (accuracy, vs recalibrated PAG) | spread ladder LL |
|---|---|---|---|---|---|
| dev 2018-24 | 8,278 | +0.004 [-0.010, +0.018] | -0.006 [-0.023, +0.011] | +0.0000 [-0.0007, +0.0007] | +0.0003 (ns) |
| 2024-25 | 1,231 | -0.027 [-0.056, +0.003] | -0.025 [-0.054, +0.001] | -0.0004 (ns) | -0.0006 (ns) |
| 2025-26 | 1,230 | +0.014 [-0.010, +0.038] | +0.010 (ns) | +0.0006 (ns) | +0.0002 (ns) |
| 2026-27 | 197 | -0.020 [-0.075, +0.033] | +0.013 (ns) | -0.0016 [-0.0045, +0.0013] | -0.0019 [-0.0043, +0.0006] |
Recalibrating PAG's winner probability alone: +0.0001..+0.0010 log loss (no calibration gain either). vs pf-1.3 (2026-27 tip, 194 games):
PAG+pbp margin MAE 11.50 vs pf 11.93 (-0.42 [-0.85, -0.01]), log loss 0.556 vs 0.602; this is PAG's edge (PAG+pbp minus PAG: -0.03 [-0.08, +0.03]).

**E2 Q1/H1, #116 frozen chosen model (Q1 M3s, H1 M1) + A = pregame lineup features, B = A + actual starters (upper bound of lineup capture).**
| seg | set | total MAE B-chosen | team total MAE B-chosen | B-A total MAE (value of actual starters) |
|---|---|---|---|---|
| Q1 | dev 22/23/24 | -0.004 / -0.009 / **+0.021** worse | -0.002 / +0.001 / **+0.009** worse | -0.000 / **-0.008** / +0.007 |
| Q1 | 2024-25 / 2025-26 / 2026-27 | **-0.016** [-0.027,-0.006] / +0.008 / -0.013 | -0.002 / +0.005 / -0.006 (all ns) | **-0.006** / +0.001 / +0.006 |
| H1 | dev 22/23/24 | -0.002 / +0.017 / **+0.036** worse | all ns | -0.005 / +0.014 / **+0.029** worse |
| H1 | 2024-25 / 2025-26 / 2026-27 | -0.006 / +0.022 / -0.000 (ns) | -0.005 / +0.003 / -0.002 (ns) | +0.002 / +0.001 / -0.002 (ns) |
Ladder log loss (total, team total, spread) moves by <= 0.002 vs chosen with no consistent sign. Q1 total MAE is ~6.5, so even the
one significant gain is 0.25%. **Verdict: knowing the actual starters adds nothing robust to period forecasts beyond #116.** (Likely
because starters are mostly predictable from recent games; capture value for player minutes/props was not tested here.)

**E3 Q1/H1 spread reliability.** Spread-ladder calibration slope of `split` (the recommended spread source): Q1 0.98-1.01 and H1
0.96-1.02 in 2021-22..2025-26; 0.95 (Q1) / 0.94 (H1) on 2026-27 (194 games). There is no stable miscalibration to fix outside 2026-27.
split + starting-unit margin adjustment: slopes 0.94-1.02 (H1 2026-27 0.940 -> 0.955; Q1 2026-27 0.953 -> 0.939, worse): **calibration not
fixed**. It is a small mean (accuracy) gain on H1 spreads: ladder LL -0.0037 [-0.0065, -0.0009] and margin MAE -0.081 [-0.141, -0.016]
in 2025-26, margin MAE -0.19 [-0.36, -0.03] in 2026-27; ns in 2024-25 and Q1. The #116 chosen H1 model already gets a similar gain.

## Readiness
Ready: the reproducible builder and a validated historical table (possessions, starters, stints) for any later model. Not ready / not
recommended: adding these features to PAG or the period models (E1/E2 null). Confirmed-starter capture is not justified by period or
game markets on this evidence. Limits: PAG and period models are in-sample on dev seasons (dev deltas are residual fits on in-sample
incumbents); 2024-25/2025-26 use the active list as in #114/#116; 2026-27 n = 194; features are simple EWMs, not RAPM.

# Certified SIFT CBB inputs on top of the cbb-edge-finder incumbent: pre-registered prediction test

RESEARCH_ONLY. This tests **outcome prediction** (game margin and total). It makes **no betting claim**: no market
line, price, ROI or edge-versus-market was computed or used. A smaller squared error against final scores does not
mean the model beats a market.

## Files
- `protocol.json` was frozen before any TEST-season error was computed. Its sha256 is in `protocol.sha256`, and
  `run.py` refuses to analyse if the hash does not match. There were no amendments.
- `run.py` is the single entry point (`PYTHONDONTWRITEBYTECODE=1 python run.py`). It runs these stages:
  data → incumbent → features → analyse. `--no-test` is a dry run that stops before TEST.
- `report.json` holds every number. Key: `report["test"][target]["paired_delta_sq_err_95ci"]`.
- `feat/dataset.parquet` is the joined per-game table. `feat/data_audit.json` holds the input hash checks.

## Incumbent (pure-0.2.0 = arm B9)
- The incumbent was reproduced by running the **unmodified** `scripts/research/run_wave2.py` from a copy of
  cbb-edge-finder. It is a walk-forward, expanding-window projection: season s is predicted with ridge fits on
  seasons 2012..s-1, using engine states built only from results before tip-off.
- Incumbent SD: `arms.residual_sd`, which is the SD that `pure.finalize` uses.
- Fidelity is **exact**:
  - Every per-season B9 N, margin RMSE and total RMSE for 2015-2026 matches the committed
    `research/wave2/metrics.json` (max difference 1e-10).
  - The frozen `pure-0.2.0.json` refit matches the committed artefact. All 68 features are identical, the largest
    coefficient difference is 4e-8, and sigma matches to 1e-10. The sha256 differs only through those last-bit floats.
- Data:
  - ESPN schedules, team box and player box come from the vault. Their bytes equal the incumbent's pins for
    2015-2026. The 2006-2014 files were republished upstream, but the reproduced metrics are still identical.
  - **Deviation:** the vault holds no stats.ncaa.org lineup or possession files, which B9 needs for its RAPM and
    shot-zone blocks. The public SportsDataverse release files for 2010-2026 were downloaded and accepted only because
    all 34 match the sha256 pins in cbb-edge-finder `manifests/bronze`.

## Certified inputs
- Source: `alpha_engine.derived.basketball.build(vault CBB team_box+schedules, "CBB")`, run unmodified from
  sift-alpha-ops.
- Only the listed columns of cbb.four_factors, tempo, adj_off, adj_def, pace_elasticity_to_opponent and
  opp_foul_propensity_ft_points were used.
- Join: on (ESPN game_id, ESPN team id), taken from each team's own row.
  - Coverage: 59,719 of 59,795 incumbent games for 2016-2026 (99.87%); TEST 11,511 of 11,516.
  - Orientation: certified `home` flag 1.0 on incumbent home rows, 0.0 on away rows; neutral flag and dates agree
    100%; `home.opp_exp_pts_pre == away.exp_pts_pre` exactly; certified expected margin vs incumbent margin r = 0.88.

## Design
- Splits: fit on 2016-2022, select on validation 2023-2024, TEST on 2025 and 2026. Season = the year the season ends.
- Candidates (residual stacking with the incumbent as a feature):
  - C1: incumbent plus the expected-points difference or sum (plus expected possessions for total).
  - C2: C1 plus the mx_* four-factor matchups and expected FT points (differences for margin, sums for total).
  - C3: C2 with ridge, alpha chosen by forward-chaining CV inside the fit seasons.
- Selection: by validation RMSE, separately per target. **C2 was chosen for both margin and total.**
  - Validation margin RMSE: C1 11.2902, C2 11.2887, C3 11.2888, incumbent 11.2958.
  - Validation total RMSE: C1 16.547, C2 16.530, C3 16.557, incumbent **16.500**. Every total candidate was already
    worse than the incumbent on validation. The protocol still had to pick one, so C2 was scored on TEST.

## TEST results (2025 + 2026, n = 11,511, scored once)
Paired Δ = mean over games of (candidate squared error − incumbent squared error). Negative means the candidate is
better. The 95% CI is a date-clustered bootstrap (2,000 resamples, seed 11).

| target | incumbent RMSE / MAE | C2 RMSE / MAE | paired Δ sq err [95% CI] |
|---|---|---|---|
| margin | 11.483 / 9.021 | 11.471 / 9.016 | −0.283 [−0.505, −0.085] |
| total | 16.798 / 13.210 | 16.818 / 13.223 | +0.683 [+0.229, +1.138] |

- Winner accuracy (sign of margin): 72.63% for both, identical overall. By season: 2025 is 73.14 vs 73.10, and
  2026 is 72.13 vs 72.17.
- Margin by season: 2025 11.452 vs 11.445, Δ −0.18 [−0.51, +0.13]; 2026 11.514 vs 11.497, Δ −0.39 [−0.68, −0.11].
- Total by season: 2025 16.423 vs 16.454, Δ +1.01 [+0.33, +1.68]; 2026 17.166 vs 17.176, Δ +0.35 [−0.25, +0.96].
- Reading: the margin improvement is statistically clear but tiny, about −0.012 RMSE (0.1%). Adding the certified
  inputs makes totals **worse**.

## Situations (EXPLORATORY, TEST only, not corrected for multiplicity)
- Margin Δ is negative, with a CI excluding 0, in these situations:
  - slow pace tercile: −0.35
  - fast pace tercile: −0.63
  - |incumbent margin| 5-15: −0.31
  - |incumbent margin| >15: −1.23
  - first 30 days of the season: −1.02
  - strong offence vs weak defence: −0.29, CI upper bound −0.003
  - non-neutral sites: −0.28
- The margin CI includes 0 for: mid pace, |margin| <5, the rest of the season, and neutral sites (−0.33 [−0.80, +0.12]).
- The early-season and blowout gains fit the idea that the certified box-score inputs help most where the
  incumbent's ratings are least settled or most compressed.
- Total Δ is positive (worse) in almost every cell. The only exception is |incumbent margin| >15 (−0.46, CI includes 0).

## Calibration (TEST PIT coverage, nominal 50% / 80%)
- Margin: incumbent 50.5% / 80.1%; candidate (validation SD 11.29) 50.8% / 80.7%.
- Total: incumbent 52.2% / 81.6% (slightly wide); candidate (SD 16.47) 50.7% / 80.1%.
- Both are well calibrated. Per-season values are in `report.json`.

## Limitations
- Effect size: the margin gain is real but very small (about 0.28 points² per game). The total model got worse:
  stacking on 2016-2022 shrinks the incumbent total, and that does not transfer to later scoring levels.
- Overlapping inputs: the certified inputs are built from the same ESPN team box scores the incumbent already uses.
  Overlap is high (expected-margin correlation 0.88), so the room for gain is small by construction.
- Fit window: coefficients come from fit seasons only. They were not refit on validation or on TEST seasons, as the
  protocol requires. TEST 2025 is therefore 3 seasons beyond the fit window.
- Hindsight: the incumbent's 2025-26 numbers were already published in cbb-edge-finder (its "historical" split).
  Only the candidate-vs-incumbent comparison is new.
- Bias convention: bias in `report.json` is mean(actual − prediction).
- The fidelity threshold (0.02 RMSE) was set in `run.py`, not in the protocol. The observed difference was 1e-10.

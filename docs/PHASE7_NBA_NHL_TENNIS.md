# Phase 7 (2026-11-10): NBA, NHL and tennis builders from the owner's archives (RESEARCH_ONLY)

All figures are agent verification (Claude builders, replay gates, independent blind Claude re-implementations); **not human verified**, and nothing here authorises predictive experimentation, which stays PAUSED. No spending, orders, PRs, merges, permission/secret/environment/schedule changes. Continues from `74aab4e` on `claude/sift-alpha-free-data-coverage-wdmcaz`.

## What was built (34 builders, all PARTIAL in the matrix)
| Module | Sport | Inputs | Raw data (physically read) |
|---|---|---|---|
| `features/nba_ext.py` | NBA | four_factors_matchup, team_three_attempt_matchup, team_assisted_fgm_expectation, three_point_variance_load, bench_minutes_distribution, own_game_environment, team_stat_pair_difference_model | nba-edge-finder ESPN team/player box scores |
| `features/nba_player_ext.py` | NBA | heavy_minutes_tail_prob, single_game_ceiling_tail, points_upper_tail_rate, fga_per_minute_by_shot_type, teammate_absence_shift, first_basket_share, early_game_usage_first6 | ESPN player box scores + 927k shot events |
| `features/nhl_ext.py` | NHL | loser_point_rate, pair_attempt_volume, rating_posterior_uncertainty, series_ot_count_dependence, series_state_scoring_shift, series_game_dependence | NHL API results 2008-2025 + MoneyPuck team-games |
| `features/tennis_ext2.py` | Tennis | straight_set_share_curve, set_count_distribution_by_edge, game_margin_pmf_calibration, win_margin_conversion_curve, retirement_timing_profile, retirement_margin_state, tiebreak_base_rate_by_event, venue_speed_history, major_winner_concentration, slam_to_slam_carryover, home_slam_depth_prior, player_set_drop_propensity, round_upset_calibration | Sackmann ATP/WTA 2000-2026 (CC BY-NC-SA) |
| `features/tennis_ext3.py` | Tennis | second_serve_vulnerability (an earlier PARTIAL whose whole definition is now implemented) | same |

33 inputs came from the `DATA_IN_HAND` reservoir (so `verified_computable` stays 260: they moved from "data in hand, no builder" to "built, replayed, blind-matched"); built-and-verified (FULL+PARTIAL+PROXY) rose from 204 to 237. No input moved out of `REQUIRES_COLLECTION`: the remaining readable ones are simulation/model outputs, not data transformations.

## FULL candidates (not certified: capped by the extension gate)
`nhl.loser_point_rate`, `ten.major_winner_concentration` and `ten.second_serve_vulnerability` implement every data quantity in their catalog definition (model-side steps the catalog itself marks as placeholders or calibration checks are not part of the input) and pass every gate including the blind exact match. `tests/test_extension_gate.py` is an existing owner guard that never lets an extension-built input be FULL, so the matrix keeps them `VERIFIED_PARTIAL` with `evidence.full_candidate = true` (`verified_coverage.cap_extension_full`). Lifting the cap is an owner decision; the guard was not weakened.
`ten.home_slam_depth_prior` also implements its whole definition but exists only for matches at the four majors (column coverage 16 %), which the pipeline records as a limit (`min column coverage below 50%`), so it is **not** a full candidate.

## Gates and how they were run
1. **Replay gates** (`replay_generic.run`, full mode, 3 truncation cuts, 3 perturbations with new seeds, own-game, non-vacuity): determinism, truncation at 55/75/92 % of dates, future-content perturbation, one mid-history date's content scrambled, and a block perturbation that must move later rows of EVERY column.
2. **Blind exact match** (`compare_independent.py`): a fresh agent saw only the written brief (`verification/blind_briefs/`) and re-implemented every column; the comparison is computed here, exact to rtol = atol = 1e-9 over all (game_id, entity) rows, NaN pattern identical. 34 inputs, 143 columns.
3. Source rights recorded in `source_samples/rights_and_access_20261110b.json`.

## What the gates caught (real defects, fixed before promotion)
* **Tennis Elo ordering leak (blind comparison)**: the walk-forward Elo iterated pandas group indices, which are not guaranteed chronological, so some WTA pre-match ratings absorbed LATER results (about half of all cell-statistic values mismatched the blind implementation). Fixed by processing contiguous (tour, date) runs strictly in order; regression test `test_elo_pre_ratings_use_only_strictly_earlier_dates`. The earlier replay would have passed it by luck of ordering, which is why the blind gate matters.
* **NBA teammate absence**: first blind pass mismatched because the brief said "sorted game ids" (string order) while the builder uses chronological order; the brief was clarified and a fresh blind agent then matched exactly (round-1 evidence kept in `verification/independent/rounds/`).
* **Tennis tiebreak event rate**: the blind agent's cumulative-sum differencing lost ~1e-7 precision; the brief now fixes the numerical method and a fresh agent matched exactly.
* **Replay machinery**: permuting entity identity columns could change the row universe (a test artifact, not leakage). Tennis now uses a role-preserving perturbation (swap winner/loser of random matches), `played`-type row-universe flags are not permuted, and non-vacuity of key-driven inputs uses a separate stronger perturbation (`perturb_nv`) that is never used by the leak tests.
* **Non-informative columns dropped from a spec instead of weakening the gate**: `ser_game_no` (NHL) and `mwc_n_pre` (saturates at 12) cannot respond to any outcome perturbation, so they are not claimed.

## Limits stated plainly
Every PARTIAL spec lists what is missing (`FeatureSpec.missing`): fitted GPD/logit/copula models, lineup/active-set conditioning, simulation-based outputs, shrinkage targets that need a fitted curve. ESPN/NHL/MoneyPuck upstream rights are unresolved: those 20 inputs are internal research only. Soccer, MLB, CFB and CBB gained nothing (see `COVERAGE_ACCESS_AND_BLOCKERS.md`).

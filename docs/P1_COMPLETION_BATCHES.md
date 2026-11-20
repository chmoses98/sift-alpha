# P1 completion sprint (2026-11-20): builders, certification and evidence (RESEARCH_ONLY)

Every input below was built from data **already held** in sift-data-vault. No new data was collected or purchased. Nothing was deployed, scheduled or consumed by an operating model.
Certification used the unchanged foundation process:
1. **Replay** (`replay_ext_run <family>`): determinism, 3 truncation cuts, 3 future perturbations, own-game, non-vacuity, plus family-specific point-in-time checks.
2. **Blind exact match** (`compare_independent`, rtol = atol = 1e-9 over all keys, identical NaN pattern). The verifier was a separate agent that saw only the brief and the raw files.
   It was told not to open the repository. This is agent verification, not human.
3. **Ledger:** `regenerate --apply` and the dependent chain. Levels: FULL / PARTIAL / PROXY as declared by each spec, capped by the gates.

## Families

| Family | Builder | Inputs | Rows | Blind match (first comparison) |
|---|---|---|---|---|
| `cbb_player6` | `features/cbb_player_ext6.py` | cbb.player_usage, player_shooting_regression, stat_dist, player_three_volume, three_makes_compound_distribution, assist_creation, rebound_pool (all PARTIAL) | 2,166,971 player-games 2013-2027 | 36 / 36 |
| `mlb_team7` | `features/mlb_team_ext7.py` (+ `mlb_pa_core.py`) | mlb.lineup_k_platoon, team_wrc_vs_hand, run_dist (PARTIAL) | 19,778 team-games 2023-2026 | 17 / 17 |
| `mlb_pitcher7` | `features/mlb_pitcher_ext7.py` | mlb.tto, k_rates (PARTIAL) | 96,866 rotation-candidate rows | 17 / 17 |
| `nfl_team8` | `features/nfl_team_ext8.py` | nfl.heteroskedastic_margin_sd, total_plays_state_model (PARTIAL); model_team_points_mean, model_team_td_mean, quarter_total_order_statistics, paired_score_covariance_own, drive_result_lattice (PROXY) | 7,422 team-games 2013-2026 | 24 / 24 |
| `nfl_qb8` | `features/nfl_qb_ext8.py` | nfl.qb_expected_pass_td, td_luck, int_rate, qb_completion_count_model (PARTIAL) | 12,940 passer rows 2014-2026 | 15 / 15 |
| `nfl_skill8` | `features/nfl_skill_ext8.py` | nfl.skill_avail (PARTIAL) | 7,422 team-games | 5 / 5 |
| `nfl_path8` | `features/nfl_path_ext8.py` | nfl.market_free_score_state_blowout_mass, score_path_sequence_sim (PROXY) | 7,422 team-games | 14 / 14 |
| `cbb_team9` | `features/cbb_team_ext9.py` | cbb.first_half_pace_ratio, margin_regime_mixture (PROXY) | 167,106 team-games 2013-2027 | 11 / 11 |

Blind briefs: `verification/blind_briefs/briefs_<family>.md`. Blind implementations and notes: `verification/blind_briefs/<family>_blind_runs/`.

## Point-in-time rules that matter
- **MLB chronology (amendment 1 preserved).** A game is dated by first pitch. Its plays become history only after `avail_date`, the completion date of a suspended game.
  - The replay runs the required `pit_check_first_pitch_availability` for all five MLB inputs; it is now in `REQUIRED_PIT_CHECKS`.
  - One defect was found and fixed **before** the blind brief. The team run EWM was first ordered by first-pitch date, which could carry a suspended game into a regular game's state before the suspended game completed. It is now ordered by completion.
- **MLB starters are never assumed.** The archive has no pregame probable-pitcher vintages.
  - Pitcher inputs are keyed by **rotation candidate**: every pitcher who started for the club in its last 5 completed games. Nothing says which candidate starts.
  - A consumer must match the announced probable, which needs prospective capture. Lineup inputs use the recent-lineup PA share and output both pitcher hands.
- **NFL relocated teams (amendment 1 preserved):** OAK → LV, SD → LAC, STL → LA are mapped on the schedule, posteam, defteam and injury teams before every join. A unit test covers this.
- **NFL injuries** follow the rule of the certified `nfl.injuries_pit` builder:
  - A report is used only if its `date_modified` is at or before kickoff.
  - Two required checks: `pit_check_post_kickoff_injuries` (9,233 late rows rewritten, nothing moves) and `pit_check_future_injury_reports` (reports after each of 3 cuts permuted, earlier rows unchanged).
  - The 2025–2026 injury files have no timestamps, so those team-games are **missing, not assumed**.
- **History-only seasons** live in `*_warm` tables, which no replay cut truncates or permutes (precedent: `nfl_player_ext5`).
- **Role-preserving non-vacuity perturbations**, documented in each builder:
  - CBB appearances: permuted jointly.
  - NFL attempts: outcomes permuted jointly, passer kept.
  - MLB: PA outcomes permuted jointly; pitchers moved within a club's block games.
  - CBB line scores: the 2024 season is also permuted, because the default block season has no line scores.
- **Harness change (opt-in):** `replay_generic.run(truncate_by_date=True)` keeps every raw game dated before a cut, which is the documented semantics.
  - The default proxy dropped 2 CBB games of 2014 that have no output row. That shifted 2015 league priors, so every column failed truncation while every perturbation check passed.
  - Only `cbb_player6` and `cbb_team9` use the flag. Earlier evidence reproduces unchanged.

## What is NOT implemented (each spec's `missing` list is authoritative)
- Prospective components: confirmed lineups, probable starters, injury and availability vintages, weather forecasts. **No E-class (prospective) input was certified from history.** cbb.player_minutes and cbb.starters are deliberately not certified.
- Fitted models the catalog names, where simpler forms are used instead:
  - hierarchical, multilevel or copula models: fixed-strength shrinkage, binned or kernel frequencies, or moment estimates instead;
  - simulations: kernel-calibrated empirical frequencies instead (all PROXY).
- Park factors, weather, umpire and coach data.
- CBB: possession counts per half (the PROXY uses the points share); on-floor lineups.

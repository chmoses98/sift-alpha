# Readiness ledger: what to do about the missing PRIMARY slots (generated; RESEARCH_ONLY)

767 missing PRIMARY slots, reconciled with market_completeness.json (767): True. A slot is one input required by one market archetype; slots are not datasets.

| Class | Meaning | Slots | P1 slots | Distinct inputs |
|---|---|---|---|---|
| A_FREE_NOT_COLLECTED | free source known, not collected | 262 | 25 | 219 |
| A_NO_FREE_SOURCE | no permitted free source known | 49 | 7 | 41 |
| A_SOURCE_CONTESTED | blind rounds disagree a source exists | 10 | 6 | 7 |
| B_DATA_IN_HAND_NO_BUILDER | data already held; needs builder + certification | 90 | 8 | 83 |
| C_CALCULATED_NOT_CERTIFIED | built, certification failed/downgraded | 26 | 7 | 24 |
| E_PROSPECTIVE_CAPTURE | needs timestamped capture from now on | 300 | 61 | 219 |
| G_LEGAL_POLICY_BLOCKED | source blocked by provider policy/terms | 30 | 12 | 14 |

Priority tiers: {'F': 373, 'P1': 126, 'P2': 268}. Slots depending on a dataset whose rights are UNRESOLVED_INTERNAL_ONLY: 686.
Queue corrections (archived in sift-data-vault but still FREE_REACHABLE in the acquisition queue): cbb.box_player, cfb.box_player, mlb.pitch_pa_events, nfl.contracts_cap, nfl.depth_charts, nfl.ftn_charting, nfl.injuries_weekly, nfl.nextgen_stats, nfl.participation, nfl.pbp, nfl.player_stats_weekly, nfl.schedule_results, nfl.snap_counts, nhl.shifts_lines.

## Highest-value shared work (one dataset / one builder closes many P1 slots)

| Class | Datasets | P1 slots | All slots | Distinct inputs |
|---|---|---|---|---|
| E_PROSPECTIVE_CAPTURE | (no dataset listed) | 16 | 66 | 30 |
| G_LEGAL_POLICY_BLOCKED | soc.results_shots_cards | 10 | 17 | 6 |
| E_PROSPECTIVE_CAPTURE | nfl.depth_charts+nfl.pbp | 6 | 8 | 2 |
| E_PROSPECTIVE_CAPTURE | cfb.box_player | 6 | 7 | 1 |
| E_PROSPECTIVE_CAPTURE | mlb.pitch_pa_events | 5 | 11 | 8 |
| E_PROSPECTIVE_CAPTURE | cbb.box_player+cbb.games_espn | 5 | 9 | 4 |
| A_NO_FREE_SOURCE | soc.results_shots_cards | 4 | 25 | 20 |
| A_FREE_NOT_COLLECTED | mkt.kalshi_rules | 3 | 10 | 4 |
| A_FREE_NOT_COLLECTED | env.venue_geo+env.weather_forecast_pit+nfl.pbp | 3 | 5 | 4 |
| A_FREE_NOT_COLLECTED | cbb.box_player+cbb.coaching_staff_history+cbb.games_espn | 3 | 3 | 3 |
| A_NO_FREE_SOURCE | cbb.box_player | 3 | 3 | 3 |
| A_SOURCE_CONTESTED | cbb.box_player+cbb.games_espn | 3 | 3 | 1 |
| E_PROSPECTIVE_CAPTURE | mlb.pitch_pa_events+mlb.schedule_games | 2 | 5 | 4 |
| C_CALCULATED_NOT_CERTIFIED | nba.pbp+nba.player_games | 2 | 4 | 3 |
| E_PROSPECTIVE_CAPTURE | cbb.box_player | 2 | 4 | 2 |
| E_PROSPECTIVE_CAPTURE | nhl.player_games+nhl.shots_xy+nhl.team_states | 2 | 4 | 1 |
| A_SOURCE_CONTESTED | nba.pbp+nba.team_games | 2 | 2 | 2 |
| E_PROSPECTIVE_CAPTURE | mlb.pitch_pa_events+mlb.schedule_games+mlb.transactions | 2 | 2 | 2 |
| B_DATA_IN_HAND_NO_BUILDER | ten.matches | 1 | 7 | 6 |
| A_FREE_NOT_COLLECTED | cbb.box_player+cbb.ratings_barttorvik | 1 | 6 | 2 |
| A_FREE_NOT_COLLECTED | env.venue_geo+env.weather_forecast_pit+mlb.pitch_pa_events | 1 | 6 | 6 |
| B_DATA_IN_HAND_NO_BUILDER | cbb.box_player | 1 | 6 | 6 |
| B_DATA_IN_HAND_NO_BUILDER | mlb.pitch_pa_events+mlb.schedule_games | 1 | 6 | 6 |
| E_PROSPECTIVE_CAPTURE | nfl.pbp | 1 | 6 | 6 |
| E_PROSPECTIVE_CAPTURE | nba.injury_report_vintages | 1 | 5 | 1 |

## P1 operating-market readiness (certified share of PRIMARY inputs)

| Sport | Market | Certified / primary | Missing by class |
|---|---|---|---|
| CBB | first_half | 3/6 | A-free:2, E:1 |
| CBB | game_moneyline_spread | 6/11 | A-free:3, E:2 |
| CBB | game_total | 4/6 | A-none:1, E:1 |
| CBB | player_points | 3/8 | A-free:1, A-contested:1, B:1, E:2 |
| CBB | player_props | 3/9 | A-free:1, A-contested:1, E:4 |
| CBB | player_rebounds_assists | 3/8 | A-none:2, A-contested:1, E:2 |
| CBB | player_threes | 4/7 | A-contested:1, E:2 |
| CBB | team_total | 6/8 | B:1, E:1 |
| CFB | game_moneyline_spread | 2/5 | A-free:1, E:2 |
| CFB | game_total | 6/8 | A-free:1, E:1 |
| CFB | half_full_double_result | 7/8 | E:1 |
| CFB | quarter_and_half_sides | 6/7 | E:1 |
| CFB | quarter_and_half_totals | 8/9 | E:1 |
| CFB | team_total | 5/6 | E:1 |
| MLB | first5_markets | 3/7 | E:4 |
| MLB | first_inning_and_inning_markets | 2/6 | A-free:1, B:1, E:2 |
| MLB | game_moneyline | 3/8 | A-free:1, E:4 |
| MLB | game_total_and_team_total | 4/8 | A-free:2, E:2 |
| MLB | pitcher_outs | 3/7 | A-free:1, E:3 |
| MLB | pitcher_strikeouts | 8/9 | E:1 |
| NBA | combo_props | 8/9 | C:1 |
| NBA | game_moneyline_spread | 5/7 | B:2 |
| NBA | game_total | 5/7 | A-contested:1, E:1 |
| NBA | game_win_margin | 5/6 | A-free:1 |
| NBA | player_assists | 8/11 | C:1, E:1, G:1 |
| NBA | player_free_throws | 4/5 | C:1 |
| NBA | player_points | 7/9 | C:1, E:1 |
| NBA | player_rebounds | 8/10 | C:1, G:1 |
| NBA | player_threes | 7/7 | - |
| NBA | quarter_and_half_markets | 4/9 | A-free:2, C:1, E:2 |
| NBA | team_total | 8/9 | A-contested:1 |
| NFL | anytime_first_td_scorer | 7/7 | - |
| NFL | first_half_and_quarter_totals | 11/12 | E:1 |
| NFL | game_moneyline_spread | 6/9 | E:3 |
| NFL | game_total | 8/11 | A-free:2, E:1 |
| NFL | qb_passing_tds_and_ints | 6/6 | - |
| NFL | qb_passing_yards | 9/13 | A-free:1, E:3 |
| NFL | receiving_yards_and_receptions | 4/7 | B:1, E:2 |
| NFL | rushing_yards | 6/7 | B:1 |
| NFL | score_path_functionals | 4/4 | - |
| NFL | team_total | 5/6 | E:1 |
| NHL | game_moneyline_puckline | 5/8 | E:3 |
| NHL | game_total_and_team_total | 8/10 | E:2 |
| NHL | period_markets | 6/7 | C:1 |
| SOCCER | btts_and_clean_sheet | 1/6 | A-none:3, G:2 |
| SOCCER | first_half_and_period | 2/4 | A-free:1, G:1 |
| SOCCER | handicap_and_exact_score | 2/4 | A-free:1, G:1 |
| SOCCER | match_result_3way | 3/6 | E:1, G:2 |
| SOCCER | total_goals | 2/8 | A-none:1, E:1, G:4 |
| TENNIS | match_winner | 4/6 | A-free:1, B:1 |
| TENNIS | set_and_game_spreads | 5/6 | A-free:1 |
| TENNIS | total_games_and_sets | 6/7 | A-free:1 |

## P1 progress against the 2026-11-20 baseline (180 slots)

Missing now: **126** (closed 54: FULL 2, PARTIAL 35, PROXY 17). Reconciles with the ledger: True.

| Category | Value |
|---|---|
| A. P1 slots closed by FULL or PARTIAL certification | 37 |
| B. P1 slots covered only by a PROXY | 17 |
| C. Inputs replayed but not certified | 0 |
| D. Missing P1 slots whose data is held (needs a builder) | 8 |
| E. Missing P1 slots needing prospective capture | 61 |
| F. Missing P1 slots blocked by provider policy / with unresolved rights | 12 / 113 |
| G. Missing P1 slots needing an owner certification decision | 13 |

| Sport | Input | P1 slots (closed) | Certification | Remaining blocker |
|---|---|---|---|---|
| CBB | cbb.injuries | 7 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| CFB | cfb.qb_status_pit | 6 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.qb | 5 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| SOCCER | soc.xg_adjusted_ratings | 5 (0) | BLOCKED_BY_POLICY | only source is blocked by provider policy / terms: needs clearance |
| CBB | cbb.player_minutes | 4 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.lineup_pit | 4 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.sp_quality | 4 (0) | PIT_QUARANTINED | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| CBB | cbb.teammate_absence_shift | 3 (0) | BLOCKED_CONTESTED | blind rounds disagree that a permitted source exists: owner decision |
| SOCCER | soc.xi_strength_delta | 3 (0) | BLOCKED_BY_POLICY | only source is blocked by provider policy / terms: needs clearance |
| TENNIS | ten.retirement_settlement_rules | 3 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.starters | 2 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.weather_pit | 2 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| NHL | nhl.goalie_quality | 2 (0) | PIT_QUARANTINED | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NHL | nhl.injuries_pit | 2 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| SOCCER | soc.lineups_pit | 2 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| CBB | cbb.assist_conversion_chain | 1 (0) | REQUIRES_COLLECTION | no permitted free source is known for a required dataset |
| CBB | cbb.coach_blowout_substitution_rate | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.coach_early_foul_bench_rule | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.d3_team_rating | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.dnp_cause_taxonomy | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| CBB | cbb.lineup_adj_rating | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| CBB | cbb.minutes_scenario_mixture | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.possession_length_profile | 1 (0) | REQUIRES_COLLECTION | no permitted free source is known for a required dataset |
| CBB | cbb.race_early_scoring_profile | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| CBB | cbb.ratings | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.rebound_competition_on_floor | 1 (0) | REQUIRES_COLLECTION | no permitted free source is known for a required dataset |
| CBB | cbb.round_max_team_score | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| CBB | cbb.second_half_pregame_expectation | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CBB | cbb.three_shot_quality_xp | 1 (0) | BLOCKED_CONTESTED | blind rounds disagree that a permitted source exists: owner decision |
| CBB | cbb.transfer_role_cold_start_prior | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CFB | cfb.lower_division_game_margin_model | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| CFB | cfb.qb_replacement_value | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| CFB | cfb.weather_pit | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| MLB | mlb.f5_lineup_slot_exposure | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.f5_starter_change_risk | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.first_inning | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| MLB | mlb.injuries_pit | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.lineup_strength_delta | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.ninth_inning_entry_and_pitcher | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| MLB | mlb.opposing_lineup_out_rate_profile | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.outs_per_bf_dp_baserunning | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| MLB | mlb.pitch_count_limit | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.pitcher_k_talent_prior | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.series_length_distribution | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| MLB | mlb.sp_efficiency | 1 (0) | PIT_QUARANTINED | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| MLB | mlb.spring_training_playing_time_regime | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| MLB | mlb.weather_pit | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| NBA | nba.absence_pace_efficiency_decomposition | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NBA | nba.early_exit_hazard | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NBA | nba.frontcourt_competition | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| NBA | nba.ft_trip_structure_model | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| NBA | nba.game_pace_composition | 1 (0) | BLOCKED_CONTESTED | blind rounds disagree that a permitted source exists: owner decision |
| NBA | nba.joint_pace_interaction | 1 (0) | BLOCKED_CONTESTED | blind rounds disagree that a permitted source exists: owner decision |
| NBA | nba.live_period_state | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| NBA | nba.margin_decay_after_pull | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| NBA | nba.minutes_scenario_mixture | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| NBA | nba.nonadditive_absence_curve | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| NBA | nba.pot_ast | 1 (0) | BLOCKED_BY_POLICY | only source is blocked by provider policy / terms: needs clearance |
| NBA | nba.pts_exit_foulout_hazard | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NBA | nba.quarter_unit_projection | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NBA | nba.reb_chances | 1 (0) | BLOCKED_BY_POLICY | only source is blocked by provider policy / terms: needs clearance |
| NBA | nba.replacement_level_minutes_absorption | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| NBA | nba.rotation | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| NBA | nba.second_half_reg_ot_joint_margin | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| NBA | nba.starters_pit | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NBA | nba.teammate_conv | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| NBA | nba.usage_allocation_model | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| NFL | nfl.game_receiving_leader_field_sim | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.game_rushing_leader_field_sim | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| NFL | nfl.lineup_adjusted_team_rating | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.own_rating_game_state_prior | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.pro_bowl_flag_roster_strength | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.receiving_corps_route_weighted_quality | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NFL | nfl.routes | 1 (0) | REQUIRES_COLLECTION | data already held: needs a builder, replay and blind match |
| NFL | nfl.weather_total_response | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| NFL | nfl.with_without_target_redistribution | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NHL | nhl.lineup_impact_delta | 1 (0) | REQUIRES_COLLECTION | needs point-in-time vintages captured from now on (see docs/PROSPECTIVE_CAPTURE.md) |
| NHL | nhl.score_state | 1 (0) | DOWNGRADED_BY_VERIFIER | verifier downgraded the claim: owner decision (see c_class_reconsideration.json) |
| SOCCER | soc.cross_tier_strength_link | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| SOCCER | soc.gk | 1 (0) | BLOCKED_CONFIRMED | no permitted free source is known for a required dataset |
| SOCCER | soc.open_game_index | 1 (0) | REQUIRES_COLLECTION | no permitted free source is known for a required dataset |
| SOCCER | soc.pace_press | 1 (0) | BLOCKED_BY_POLICY | only source is blocked by provider policy / terms: needs clearance |
| SOCCER | soc.second_half_state_multiplier | 1 (0) | REQUIRES_COLLECTION | a free source is identified but not collected (check rights, collect, then build and certify) |
| SOCCER | soc.shared_openness_latent_factor | 1 (0) | REQUIRES_COLLECTION | no permitted free source is known for a required dataset |
| SOCCER | soc.team_fail_to_score_propensity | 1 (0) | REQUIRES_COLLECTION | no permitted free source is known for a required dataset |
| SOCCER | soc.xi_attack_defence_split | 1 (0) | BLOCKED_BY_POLICY | only source is blocked by provider policy / terms: needs clearance |
| TENNIS | ten.player_speed_slope | 1 (0) | DATA_IN_HAND_CONFIRMED | data already held: needs a builder, replay and blind match |
| CBB | cbb.stat_dist | 3 (3) | VERIFIED_PARTIAL | closed |
| MLB | mlb.team_wrc_vs_hand | 3 (3) | VERIFIED_PARTIAL | closed |
| NFL | nfl.model_team_points_mean | 3 (3) | VERIFIED_PROXY | closed |
| NFL | nfl.skill_avail | 3 (3) | VERIFIED_PARTIAL | closed |
| CBB | cbb.player_shooting_regression | 2 (2) | VERIFIED_PARTIAL | closed |
| CBB | cbb.player_usage | 2 (2) | VERIFIED_PARTIAL | closed |
| MLB | mlb.run_dist | 2 (2) | VERIFIED_PARTIAL | closed |
| NFL | nfl.heteroskedastic_margin_sd | 2 (2) | VERIFIED_PARTIAL | closed |
| NFL | nfl.model_team_td_mean | 2 (2) | VERIFIED_PROXY | closed |
| CBB | cbb.assist_creation | 1 (1) | VERIFIED_PARTIAL | closed |
| CBB | cbb.first_half_pace_ratio | 1 (1) | VERIFIED_PROXY | closed |
| CBB | cbb.margin_regime_mixture | 1 (1) | VERIFIED_PROXY | closed |
| CBB | cbb.player_three_volume | 1 (1) | VERIFIED_PARTIAL | closed |
| CBB | cbb.rebound_pool | 1 (1) | VERIFIED_PARTIAL | closed |
| CBB | cbb.three_makes_compound_distribution | 1 (1) | VERIFIED_PARTIAL | closed |
| CFB | cfb.expected_possessions | 1 (1) | VERIFIED_PARTIAL | closed |
| CFB | cfb.leader_scoring_persistence | 1 (1) | VERIFIED_PARTIAL | closed |
| CFB | cfb.period_drive_clock_budget | 1 (1) | VERIFIED_PARTIAL | closed |
| CFB | cfb.period_possession_allocation | 1 (1) | VERIFIED_PROXY | closed |
| MLB | mlb.first_inning_markov_run_prob | 1 (1) | VERIFIED_PROXY | closed |
| MLB | mlb.k_rates | 1 (1) | VERIFIED_PARTIAL | closed |
| MLB | mlb.lineup_k_platoon | 1 (1) | VERIFIED_PARTIAL | closed |
| MLB | mlb.tto | 1 (1) | VERIFIED_PARTIAL | closed |
| NBA | nba.assisted_three_passer_map | 1 (1) | VERIFIED_PROXY | closed |
| NBA | nba.creditable_rebound_pool | 1 (1) | VERIFIED_PARTIAL | closed |
| NBA | nba.lineup_conditional_component_rates | 1 (1) | VERIFIED_PROXY | closed |
| NBA | nba.margin_heteroscedasticity | 1 (1) | VERIFIED_FULL | closed |
| NBA | nba.on_court_assist_share | 1 (1) | VERIFIED_PARTIAL | closed |
| NBA | nba.pairing_adjusted_reb_share | 1 (1) | VERIFIED_PROXY | closed |
| NBA | nba.period_margin_pmf | 1 (1) | VERIFIED_FULL | closed |
| NFL | nfl.drive_result_lattice | 1 (1) | VERIFIED_PROXY | closed |
| NFL | nfl.int_rate | 1 (1) | VERIFIED_PARTIAL | closed |
| NFL | nfl.market_free_score_state_blowout_mass | 1 (1) | VERIFIED_PROXY | closed |
| NFL | nfl.paired_score_covariance_own | 1 (1) | VERIFIED_PROXY | closed |
| NFL | nfl.player_xtd | 1 (1) | VERIFIED_PARTIAL | closed |
| NFL | nfl.qb_completion_count_model | 1 (1) | VERIFIED_PARTIAL | closed |
| NFL | nfl.qb_expected_pass_td | 1 (1) | VERIFIED_PARTIAL | closed |
| NFL | nfl.quarter_total_order_statistics | 1 (1) | VERIFIED_PROXY | closed |
| NFL | nfl.score_path_sequence_sim | 1 (1) | VERIFIED_PROXY | closed |
| NFL | nfl.td_luck | 1 (1) | VERIFIED_PARTIAL | closed |
| NFL | nfl.total_plays_state_model | 1 (1) | VERIFIED_PARTIAL | closed |

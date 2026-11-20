# Readiness ledger: what to do about the missing PRIMARY slots (generated; RESEARCH_ONLY)

828 missing PRIMARY slots, reconciled with market_completeness.json (828): True. A slot is one input required by one market archetype; slots are not datasets.

| Class | Meaning | Slots | P1 slots | Distinct inputs |
|---|---|---|---|---|
| A_FREE_NOT_COLLECTED | free source known, not collected | 289 | 46 | 233 |
| A_NO_FREE_SOURCE | no permitted free source known | 50 | 8 | 42 |
| A_SOURCE_CONTESTED | blind rounds disagree a source exists | 10 | 6 | 7 |
| B_DATA_IN_HAND_NO_BUILDER | data already held; needs builder + certification | 121 | 38 | 107 |
| C_CALCULATED_NOT_CERTIFIED | built, certification failed/downgraded | 28 | 9 | 26 |
| E_PROSPECTIVE_CAPTURE | needs timestamped capture from now on | 300 | 61 | 219 |
| G_LEGAL_POLICY_BLOCKED | source blocked by provider policy/terms | 30 | 12 | 14 |

Priority tiers: {'F': 375, 'P1': 180, 'P2': 273}. Slots depending on a dataset whose rights are UNRESOLVED_INTERNAL_ONLY: 737.
Queue corrections (archived in sift-data-vault but still FREE_REACHABLE in the acquisition queue): cbb.box_player, cfb.box_player, mlb.pitch_pa_events, nfl.contracts_cap, nfl.depth_charts, nfl.ftn_charting, nfl.injuries_weekly, nfl.nextgen_stats, nfl.participation, nfl.pbp, nfl.player_stats_weekly, nfl.schedule_results, nfl.snap_counts, nhl.shifts_lines.

## Highest-value shared work (one dataset / one builder closes many P1 slots)

| Class | Datasets | P1 slots | All slots | Distinct inputs |
|---|---|---|---|---|
| E_PROSPECTIVE_CAPTURE | (no dataset listed) | 16 | 66 | 30 |
| G_LEGAL_POLICY_BLOCKED | soc.results_shots_cards | 10 | 17 | 6 |
| B_DATA_IN_HAND_NO_BUILDER | cbb.box_player | 8 | 14 | 9 |
| E_PROSPECTIVE_CAPTURE | nfl.depth_charts+nfl.pbp | 6 | 8 | 2 |
| E_PROSPECTIVE_CAPTURE | cfb.box_player | 6 | 7 | 1 |
| E_PROSPECTIVE_CAPTURE | mlb.pitch_pa_events | 5 | 11 | 8 |
| E_PROSPECTIVE_CAPTURE | cbb.box_player+cbb.games_espn | 5 | 9 | 4 |
| B_DATA_IN_HAND_NO_BUILDER | cbb.box_player+cbb.games_espn | 5 | 7 | 6 |
| A_NO_FREE_SOURCE | soc.results_shots_cards | 4 | 25 | 20 |
| A_FREE_NOT_COLLECTED | env.venue_geo+env.weather_forecast_pit+nfl.pbp | 4 | 6 | 5 |
| A_FREE_NOT_COLLECTED | env.venue_geo+mlb.pitch_pa_events+mlb.schedule_games | 4 | 6 | 3 |
| A_NO_FREE_SOURCE | cbb.box_player | 4 | 4 | 4 |
| B_DATA_IN_HAND_NO_BUILDER | nfl.pbp | 3 | 12 | 11 |
| A_FREE_NOT_COLLECTED | mkt.kalshi_rules | 3 | 10 | 4 |
| B_DATA_IN_HAND_NO_BUILDER | mlb.pitch_pa_events+mlb.schedule_games | 3 | 8 | 8 |
| C_CALCULATED_NOT_CERTIFIED | nba.pbp+nba.player_games+nba.team_games | 3 | 6 | 6 |
| A_FREE_NOT_COLLECTED | env.venue_geo+env.weather_forecast_pit+nfl.injuries_weekly+nfl.pbp+nfl.player_stats_weekly | 3 | 5 | 1 |
| A_FREE_NOT_COLLECTED | env.venue_geo+env.weather_forecast_pit+nfl.pbp+nfl.player_stats_weekly | 3 | 5 | 3 |
| B_DATA_IN_HAND_NO_BUILDER | nfl.injuries_weekly+nfl.participation+nfl.pbp+nfl.player_stats_weekly | 3 | 4 | 2 |
| A_FREE_NOT_COLLECTED | cbb.box_player+cbb.coaching_staff_history+cbb.games_espn | 3 | 3 | 3 |
| A_SOURCE_CONTESTED | cbb.box_player+cbb.games_espn | 3 | 3 | 1 |
| B_DATA_IN_HAND_NO_BUILDER | nfl.pbp+nfl.player_stats_weekly | 2 | 20 | 19 |
| E_PROSPECTIVE_CAPTURE | mlb.pitch_pa_events+mlb.schedule_games | 2 | 5 | 4 |
| A_FREE_NOT_COLLECTED | cfb.pbp_cfbd+cfb.rules_formats | 2 | 4 | 3 |
| A_FREE_NOT_COLLECTED | env.venue_geo+env.weather_forecast_pit+mlb.pitch_pa_events+mlb.schedule_games | 2 | 4 | 2 |

## P1 operating-market readiness (certified share of PRIMARY inputs)

| Sport | Market | Certified / primary | Missing by class |
|---|---|---|---|
| CBB | first_half | 2/6 | A-free:2, B:1, E:1 |
| CBB | game_moneyline_spread | 5/11 | A-free:3, B:1, E:2 |
| CBB | game_total | 4/6 | A-none:1, E:1 |
| CBB | player_points | 1/8 | A-free:1, A-contested:1, B:3, E:2 |
| CBB | player_props | 1/9 | A-free:1, A-contested:1, B:2, E:4 |
| CBB | player_rebounds_assists | 0/8 | A-none:2, A-contested:1, B:3, E:2 |
| CBB | player_threes | 0/7 | A-none:1, A-contested:1, B:3, E:2 |
| CBB | team_total | 6/8 | B:1, E:1 |
| CFB | game_moneyline_spread | 2/5 | A-free:1, E:2 |
| CFB | game_total | 5/8 | A-free:2, E:1 |
| CFB | half_full_double_result | 7/8 | E:1 |
| CFB | quarter_and_half_sides | 5/7 | A-free:1, E:1 |
| CFB | quarter_and_half_totals | 7/9 | A-free:1, E:1 |
| CFB | team_total | 4/6 | A-free:1, E:1 |
| MLB | first5_markets | 2/7 | A-free:1, E:4 |
| MLB | first_inning_and_inning_markets | 1/6 | A-free:1, B:2, E:2 |
| MLB | game_moneyline | 1/8 | A-free:3, E:4 |
| MLB | game_total_and_team_total | 2/8 | A-free:4, E:2 |
| MLB | pitcher_outs | 3/7 | A-free:1, E:3 |
| MLB | pitcher_strikeouts | 5/9 | A-free:1, B:2, E:1 |
| NBA | combo_props | 7/9 | B:1, C:1 |
| NBA | game_moneyline_spread | 5/7 | B:2 |
| NBA | game_total | 5/7 | A-contested:1, E:1 |
| NBA | game_win_margin | 4/6 | A-free:1, C:1 |
| NBA | player_assists | 7/11 | B:1, C:1, E:1, G:1 |
| NBA | player_free_throws | 4/5 | C:1 |
| NBA | player_points | 7/9 | C:1, E:1 |
| NBA | player_rebounds | 6/10 | B:2, C:1, G:1 |
| NBA | player_threes | 6/7 | B:1 |
| NBA | quarter_and_half_markets | 3/9 | A-free:2, C:2, E:2 |
| NBA | team_total | 8/9 | A-contested:1 |
| NFL | anytime_first_td_scorer | 4/7 | A-free:1, B:2 |
| NFL | first_half_and_quarter_totals | 9/12 | A-free:2, E:1 |
| NFL | game_moneyline_spread | 4/9 | A-free:2, E:3 |
| NFL | game_total | 5/11 | A-free:4, B:1, E:1 |
| NFL | qb_passing_tds_and_ints | 2/6 | A-free:2, B:2 |
| NFL | qb_passing_yards | 7/13 | A-free:2, B:1, E:3 |
| NFL | receiving_yards_and_receptions | 4/7 | B:1, E:2 |
| NFL | rushing_yards | 5/7 | B:2 |
| NFL | score_path_functionals | 1/4 | A-free:1, B:2 |
| NFL | team_total | 4/6 | B:1, E:1 |
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

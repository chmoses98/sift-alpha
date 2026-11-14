# Phase 15 (2026-11-14): NBA and NHL builders from the owner's archives (RESEARCH_ONLY)

Agent verification only (Claude builders, replay gates, independent blind Claude re-implementations); **not human verified**. Nothing here authorises predictive experimentation, orders, pushes, PRs,
workflow changes or new external data collection, and none was done. No rights tier was changed. No raw row is committed (aggregates, digests and evidence JSON only). The 1,649-input / 170-archetype
catalog is untouched (`baseline_lock` OK).

## 1. What the "492 P0 slots behind archived data" figure really is
`market_input_map.build` lists a missing PRIMARY slot under **every** dataset in `sat = {requirement.satisfied_by}`. An input has one requirement per distinct *need* (TEAM_BOX, PLAYER_BOX, EVENT, LINEUP,
AVAIL, ...); each need is resolved to its single best dataset (`satisfied_by`), and the any-of alternatives for that one need are the `candidates`, shown separately (`alternative_candidate_slots`) and never
queued. So a slot listed under several datasets needs **ALL** of them for its full definition (ANY applies only inside one requirement). Summing per-dataset rows therefore counts a slot once per dataset.
Recount from `map.json` (distinct slots, NBA + NHL + CBB):

| | before Phase 15 | after Phase 15 |
|---|---|---|
| distinct missing PRIMARY slots (NBA / NHL / CBB) | 358 (163 / 87 / 108) | 297 (138 / 51 / 108) |
| ... listing at least one COLLECTED_ARCHIVE dataset | 264 (133 / 67 / 64) | 203 (108 / 31 / 64) |
| ... listing ONLY archived datasets (the honest "archive is enough for the full definition" number) | 69 slots / 55 inputs (44 / 21 / 4) | 49 slots / 44 inputs (35 / 10 / 4) |

All-sport missing PRIMARY slots: **949 -> 888** (NBA 163 -> 138, NHL 87 -> 51; CBB, CFB, NFL, MLB, soccer, tennis unchanged). 61 slots in 28 archetypes; 20 of the 61 were archive-only slots, 41 are PARTIAL builds
of inputs whose full definition also names a dataset that is not archived (the non-archived part is in each spec's `missing`).

## 2. What was built (30 inputs: 29 PARTIAL, 1 PROXY, 0 FULL)
| Module | Sport / key | Inputs (missing PRIMARY slots unlocked) | Raw data physically read |
|---|---|---|---|
| `features/nba_ext3.py` | NBA team-game | rating_blowout_minutes_curve (7), lineup_adj_rating (7, **PROXY**), final_margin_pmf_empirical (2), own_model_team_totals (2), team_points_margin_curve (1), expectation_overperformance (1), team_win_streak_hazard (1) | nba-edge-finder `data/history/espn/{team_games,player_games}` (regular seasons 2023-24 .. 2026-27, 7,570 team-games) |
| `features/nba_player_ext3.py` | NBA player-game | stat_rate_posterior (1), avg_rounding_and_games_state (1), season_plus_minus_projection (1), rare_make_accrual_rate (1) | same player box scores (81,170 player-games) |
| `features/nhl_ext2.py` | NHL team-game 2008-2025 | settlement_goal_pmf (2), team_season_points_distribution (2), playoff_context (2), series_context (2), ratings_script_distribution (1), game_script_prob (1) | NHL-edge-finder `nhl/games` (23,227 final games) + MoneyPuck team-games, situation `all` |
| `features/nhl_ev_ext2.py` | NHL team-game 2021-2025 | goalie_start (6), early_window_goal_rate (2), goalie_minutes_in_net_dist (1), first_goal_hazard (1), period_split (1), ot_3v3_rate (1), opp_sog_for_rate (1) | NHL-edge-finder `players/{team_states,goals,shots,goalies}` (6,560 regular-season games) |
| `features/nhl_player_ext2.py` | NHL skater-game 2021-2025 | player_season_points_projection (5), ixg_player (2), games_played_hazard (2), joint_outcome_correlation (2), ipp_by_state (1), award_stats (1) | `players/{players,goals}` (236,101 skater-games) + MoneyPuck shot rows (xGoal) |

Every spec lists, in `FeatureSpec.missing`, the parts of the catalog definition that are **not** implemented (fitted models, simulations, injury-report vintages, confirmation timestamps, longer histories).
`nba.lineup_adj_rating` is labelled PROXY, not PARTIAL: both the impact metric (shrunk box plus-minus per 48 instead of ridge RAPM) and the expected-active set (the players who appeared in the team's
previous game instead of the latest injury-report vintage) are stand-ins. `nhl.goalie_start` implements only the pre-confirmation starter model from EARLIER games; the starter flag of the game itself is
never an input (the own-game replay test scrambles it), and timestamped confirmations still need prospective capture.

Not built:
* **CBB: 0 inputs.** The archived CBB raw rows are not on this machine: the owner's cbb-edge-finder repository (all 14 remote branches, main included) holds derived model tables, rosters and November 2026
  prospective snapshots only; the 5-season ESPN scoreboard cache and the sportsdataverse box files of Phase 8 live outside the repository. Re-downloading them is new collection, and the collector is
  frozen in `rights_registry.json` (`frozen_collectors`). Nothing was fetched.
* `DOWNGRADED_BY_VERIFIER` and `PIT_QUARANTINED` inputs (e.g. `nhl.goalie_quality`, `nba.minutes_scenario_mixture`, `nba.rotation`): not promotable by `verified_coverage.PROMOTABLE`; none was touched.
* Inputs needing the 2025-26-only injury-report vintages, stints/play-by-play (2 seasons) or a simulation as their whole content (standings, bracket, award-vote models): not attempted.

## 3. Gates (run for real, full mode)
1. **Replay** (`replay_ext_run.py` families `nba_team3`, `nba_player3`, `nhl2`, `nhl_ev2`, `nhl_player2` -> `verification/replay_ext/{NBA_nba_team3,NBA_nba_player3,NHL_nhl2,NHL_nhl_ev2,NHL_nhl_player2}.json`):
   determinism, truncation at 55 / 75 / 92 % of dates, future-content perturbation with 3 seeds, own-game scramble of one mid-history date, and the non-vacuity block perturbation that must move every
   column of every input. All 30 inputs pass every check; no constant column. `nhl.games_played_hazard` is participation-driven, so the non-vacuity test (only) uses `perturb_nv`, which also zeroes ice time on
   30 % of the block's rows. `nhl.series_context` exists on playoff rows only (column coverage 6.7 %), recorded by the pipeline as a limit.
2. **Blind exact match** (`compare_independent.py`, rtol = atol = 1e-9 over all keys, identical keys and NaN patterns): one fresh headless Claude Code session per sport, started in an empty directory holding
   only the brief (`verification/blind_briefs/briefs_p15_{nba,nhl}.md`) with a copy of the raw files outside any repository. 118 columns: NBA 49 (30 team + 19 player), NHL 69 (20 + 29 + 20).
   The sessions ran in `auto` permission mode with a reduced tool set; their transcripts were scanned for any reference to `/home/user`, a repository or the builder modules: none
   (`verification/blind_briefs/p15_blind_runs/audit.json`, which also holds the brief / implementation / CSV digests; the blind implementations are kept beside it as `.py.txt`).
3. Result: **30 of 30 inputs MATCH** (29 on the first comparison, 1 after a builder fix, below).

## 4. Defects found
* **`nhl.ixg_player` (blind comparison, round 1 MISMATCH)**: the three columns differed from the blind values by up to 2.7e-8 relative (NaN pattern identical). Cause: the archive stores MoneyPuck `xGoal`
  as float32 and the builder summed it in single precision; the blind implementation summed in double precision. The builder now casts to float64 before summing; the replay was re-run and the UNCHANGED
  round-1 blind CSV matches exactly. Round-1 evidence: `verification/independent/rounds/NHL_nhl_player2_round1_MISMATCH_float32_xg_sum.json`.
* **`nhl.ot_3v3_rate` (found while building, before the gates)**: `team_states.n_seconds` is the period grid (3600 or 4800), not time played; overtime length is now taken from the first overtime goal
  (300 s when the game went to a shootout).
* **NHL skater state columns** (`toi_ev_s`, `toi_pp_s`, `gf_ev`, `gf_pp`) are missing on about 2,050 rows; a rolling sum propagated the NaN over the next 60 games. Such a game is now skipped for that state
  (numerator and denominator), never imputed; the brief states the rule.
* `tests/test_extension_gate.py` listed the statuses an extension input may hold without `VERIFIED_PROXY`; it is added (PROXY is weaker than PARTIAL; the FULL-certification rule is unchanged).

## 5. Rights
ESPN (`espn_*`), NHL API (`nhl_*`) and MoneyPuck (`moneypuck_*`) raw sources resolve to `UNRESOLVED_INTERNAL_ONLY` in `rights_registry.json`: internal research only, not cleared for redistribution or
commercial use; `collection_allowed` is false, and nothing was collected (only parquet files already in the owner's repositories were read). The Phase 13 note that api-web.nhle.com carries an `ai-train=no`
reservation still applies to any downstream use. The map keeps showing these datasets under RIGHTS_APPROVAL_NEEDED; that is unchanged.

## 6. Matrix and regeneration
`verified_coverage`: PARTIAL 180 -> 209, PROXY 19 -> 20, FULL 58 (unchanged); `verified_computable` 277 -> 305; promoted from REQUIRES_COLLECTION 23, DATA_IN_HAND_SCHEMA_ONLY 5, DATA_IN_HAND_CONFIRMED 2.
Regenerated, in this order (a second full pass changes nothing):

    python -m alpha_engine.input_research.regenerate --apply
    for m in market_completeness full_promotion_audit rights_questions capture_plan prospective_plan source_mapping market_input_map; do python -m alpha_engine.input_research.data_foundation.$m; done
    python -m alpha_engine.input_research.data_foundation.phase12_coverage --write
    python research/provider_licensing/priority_recalc.py

Not regenerated here (owned by the ops layer): `python -m alpha_engine.foundation.ledger` (`research/data_foundation_ops/{pipeline_ledger,summary}.json`), `docs/DATA_FOUNDATION_OPS.md`, and the
hard-coded "949" in `src/market-input-map.jsx`.

Reproduce the gates (raw data stays outside the repository):

    python -m alpha_engine.input_research.data_foundation.replay_ext_run nba_team3 $SIFT_REPOS_DIR/nba-edge-finder/data/history OUT.json        # likewise nba_player3
    python -m alpha_engine.input_research.data_foundation.replay_ext_run nhl2 $SIFT_REPOS_DIR/NHL-edge-finder/data/history OUT.json             # likewise nhl_ev2, nhl_player2
    python -m alpha_engine.input_research.data_foundation.compare_independent features.nba_ext3 OUT.json BLIND.csv NOTES.json BRIEF.md -- $SIFT_REPOS_DIR/nba-edge-finder/data/history

## 7. Limits stated plainly
* PARTIAL means a stated subset: no fitted hierarchical / count / copula model, no simulation output, no injury-report or confirmed-lineup conditioning is implemented anywhere in this phase.
* NBA history is three seasons plus the start of a fourth; NHL event-based inputs start in 2021-22. Several catalog definitions ask for 5 to 20 seasons.
* `nhl.series_context` treats every playoff pairing as a best-of-seven (the 2020 qualifying round and round-robin games are not modelled).
* Whether any of these inputs improves a forecast is untested: this phase measures data readiness, not predictive value.

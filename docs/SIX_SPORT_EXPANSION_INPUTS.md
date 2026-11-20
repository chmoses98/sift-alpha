# Six-sport expansion, batch 1: 20 pre-game inputs for CFB, NHL and MLB from vault archives (RESEARCH_ONLY)

Shared core `alpha_engine/features/score_core.py` (walk-forward off/def ridge + season-walk-forward kernel). Builders: `cfb_espn_ext.py`, `nhl_period_ext.py`, `mlb_line_ext.py`
(definitions: the blind briefs under `research/input_research/data_foundation/verification/blind_briefs/`). No market price enters. Nothing is deployed, scheduled or consumed by a projection model.

| Sport | Input | Certified (ledger) | Consumed by a model | Coverage | Walk-forward vs naive baseline |
|---|---|---|---|---|---|
| CFB | `cfb.net_yards_per_play_model` | VERIFIED_PARTIAL | no | 99.8% | expectation +24.7% MSE, 12/12 seasons |
| CFB | `cfb.period_share_of_total` | VERIFIED_PARTIAL | no | 92.2% | not assessed |
| CFB | `cfb.own_drive_share` | VERIFIED_PARTIAL | no | 99.8% | drive count +16.9% (12/12); the share column is WORSE than a constant (-6.4%, 0/12) |
| CFB | `cfb.quarter_joint_scoring_pmf` | VERIFIED_PROXY | no | 92.2% | scoreless-quarter Brier +4.7% to +7.0%, all-four +10.6% (11/11); highest-quarter columns not assessed |
| CFB | `cfb.period_margin_lattice` | VERIFIED_PROXY | no | 92.2% | lead after Q1 +12.1%, at half +20.3%, second half +14.2% (11/11); tie columns +0.4% to +0.6% (no real gain) |
| CFB | `cfb.regulation_tie_curve` | VERIFIED_PROXY | no | 92.2% | +0.45% (10/11): negligible |
| CFB | `cfb.half_to_full_transition_matrix` | VERIFIED_PROXY | no | 92.2% | +11.3% (11/11) within state |
| CFB | `cfb.half_tie_conditional_win` | VERIFIED_PROXY | no | 84.4% | +11.2% (10/10), n = 1,044 |
| CFB | `cfb.td_count_dispersion` | VERIFIED_PROXY | no | 92.2% | mean +26.4%, tails +13.0% to +18.2% (11/11); variance not assessed |
| CFB | `cfb.first_td_race_rate` | VERIFIED_PROXY | no | 92.2% | first touchdown +12.2% (11/11); no-touchdown mass 0.0% (no gain) |
| CFB | `cfb.script_rush_attempts` | VERIFIED_PROXY | no | 92.2% | ridge expectation +27.0% (12/12), script kernel +4.1% (11/11) |
| NHL | `nhl.series_pair_scoring_rate_uncertainty` | VERIFIED_PARTIAL | no | 99.8% | expected total WORSE than a constant (-0.3%, 2/5); standard error not assessed |
| NHL | `nhl.period_entry_state_matrix` | VERIFIED_PROXY | no | 80.9% | lead entering P3 +1.9%, P2 +0.6% (4/4); tie and state-conditional rates +0.0% to +0.9% |
| NHL | `nhl.period_pair_count_model` | VERIFIED_PROXY | no | 80.9% | period means +0.8% to +1.1% (4/4); period-total tails +0.0% to +0.3%; covariance not assessed |
| MLB | `mlb.f5_split` | VERIFIED_PARTIAL | no | 80.0% | five-inning runs +0.9% (4/4), lead after five +0.9% (3/3); late runs -0.1%, tie 0.0% |
| MLB | `mlb.first_inning_splits` | VERIFIED_PROXY | no | 80.0% | expectation WORSE than a constant (-0.7%, 0/4); P(score) +0.2%, NRFI +0.1%: no usable signal |
| MLB | `mlb.playoff_walkoff_event_rate` | VERIFIED_PROXY | no | 80.0% | walk-off -0.1%, extras -0.2% (0/3): no signal |
| MLB | `mlb.sp_workload` | VERIFIED_PROXY | no | 99.9% | outs +2.9%, batters faced +3.8%, pitches +4.3% (4/4), team-level only |
| MLB | `mlb.sp_hook_hazard_curve` | VERIFIED_PROXY | no | 80.0% | +0.7% to +2.2% (3/3), team-level only |
| MLB | `mlb.exit_boundary_mass` | VERIFIED_PROXY | no | 80.0% | +1.1% to +1.9% (3/3), team-level only |

Walk-forward (`research/audit/six_sport_walkforward.json`, script alongside): skill = 1 - MSE(input) / MSE(league mean of earlier seasons), Brier for probabilities; every input value is already out of sample.
The foundations: CFB expected regulation points +29.8% and margin +40.5% (12/12 seasons); NHL goals +2.8%, margin +5.4% (5/5); MLB runs +1.7%, margin +2.4% (4/4).
These compare inputs against naive constants only. No closing-line benchmark was run for these sports and nothing here shows that any projection model would improve.
"Verified" means computed as specified without future information; several verified inputs carry no predictive gain (marked above) and should not be integrated.

## Certification (same foundation process and unchanged ledger rules)
1. Replay (`replay_ext_run cfb_espn | nhl_period | mlb_line` -> `verification/replay_ext/{CFB_cfb_espn,NHL_nhl_period,MLB_mlb_line}.json`): determinism, 3 truncation cuts, 3 future perturbations, own-game, non-vacuity. 20 of 20 inputs pass.
2. Blind exact match (`compare_independent` -> `verification/independent/`, rtol = atol = 1e-9 over all team-game keys): one fresh agent per sport that saw only the brief and the raw files.
   NHL 16/16 and MLB 20/20 columns MATCH on the first comparison. CFB 35/37 on the first comparison: the two `cfb.own_drive_share` columns differed because the brief did not say what to do with
   drive entries that have no team id (171 games). The brief was clarified (such entries are ignored), the agent re-ran, and all 37 match. The first comparison is kept in
   `blind_briefs/cfb_espn_blind_runs/first_comparison_before_brief_clarification.json`. Agent verification, not human.
3. `regenerate --apply` and the dependent reports: missing PRIMARY slots 873 -> 841 (CFB 74 -> 59, MLB 168 -> 154, NHL 51 -> 48); VERIFIED_PARTIAL 221 -> 226, VERIFIED_PROXY 22 -> 37, VERIFIED_FULL unchanged at 62.
   The 32 closed slots are in 18 market archetypes: CFB quarter/half sides and totals, half/full double result, overtime, game stat props, team total, touchdown scorer; NHL period markets and playoff series
   aggregate; MLB first-five, first-inning, pitcher outs / strikeouts / earned runs-hits-walks, game total and team total, counting specials.

## Limits that matter
* All MLB starter inputs are TEAM-level (the team's starters in earlier games, opponent-adjusted). The game's own starter is an as-played field and is not read. A starter-specific version needs pre-game probable-pitcher
  vintages (`mlb.lineup_il_vintages`, prospective capture only).
* MLB covers 2022-2026 and NHL 2021-2026 only, so the first season has no conditional frequencies (80% coverage).
* NHL uses team abbreviations as-is: ARI and UTA are separate teams.
* PROXY inputs use kernel empirical frequencies in place of the catalog's fitted distributions; each spec lists what is not implemented.

## Still missing (highest value)
* CFB: `cfb.qb_status_pit` (7 PRIMARY slots), player usage and participation: need timestamped availability capture. `cfb.fg_attempt_make_model`, `cfb.period_possession_allocation`, `cfb.leader_scoring_persistence`:
  buildable from the play lists already in the ESPN summary archive (not built here).
* MLB: `mlb.pa_sim`, `mlb.tto`, hitter contact and RBI inputs: buildable from the plate-appearance events in the same feed archive (not built here). Anything starter- or lineup-specific needs pre-game vintages.
* NHL: `nhl.playoff_round_goal_leader_sim` (player rates + series simulation); the rest needs shift/line data joins, injuries or pre-game goalie confirmations.

## Run
```
python sift-data-vault/tools/vault.py restore --path archives/CFB/espn_summary_postgame/2014-2025/espn_site_api/collected-20261116 --to RAW/CFB     # likewise 2026, NHL daily_scores_goals_periods, MLB postgame_feed_compact/<year>
OMP_NUM_THREADS=1 python -m alpha_engine.input_research.data_foundation.replay_ext_run cfb_espn RAW/CFB,RAW/CFB26 OUT.json      # about 4 min; nhl_period 1 min; mlb_line 6 min
```

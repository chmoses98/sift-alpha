# NFL batch 4: five pre-game inputs from the archived schedule and play-by-play (RESEARCH_ONLY)

Builder `alpha_engine/features/nfl_pbp_ext4.py` (definitions in its docstring). Raw data: `sift-data-vault` `archives/NFL/pbp/2010-2026` and
`archives/NFL/inseason_player_team/1999-2026` (schedule). No market price enters. Nothing is deployed, scheduled or consumed by a projection model.

| Input | Calculated | Certified (ledger) | Consumed by a model | Coverage |
|---|---|---|---|---|
| `nfl.own_team_rating_market_free` | yes | VERIFIED_PARTIAL | no | 99.6%, 1999-2026 |
| `nfl.team_points_for_against_rates` | yes | VERIFIED_PARTIAL | no | 99.6%, 1999-2026 |
| `nfl.proe` | yes | VERIFIED_PARTIAL | no | 60.6% (play-by-play archive starts 2010) |
| `nfl.team_score_pmf_own_mean` | yes | VERIFIED_PROXY | no | 93.0%, 2001-2026 |
| `nfl.model_margin_lattice` | yes | VERIFIED_PROXY | no | 93.0%, 2001-2026 |

The two PROXY inputs use kernel-weighted empirical frequencies on earlier seasons in place of the catalog's drive simulation / negative-binomial fit, and final scores in place of
regulation scores. Each spec lists what is not implemented.

## Certification (same foundation process as earlier batches; ledger rules unchanged)
1. Replay (`replay_ext_run nfl_pbp4` -> `verification/replay_ext/NFL_nfl_pbp4.json`): determinism, 3 truncation cuts, future perturbation, own-game, non-vacuity. 5 of 5 inputs pass.
2. Blind exact match (`compare_independent` -> `verification/independent/NFL_nfl_pbp4.json`): one fresh agent that saw only `blind_briefs/briefs_nfl_pbp4.md` and the raw files;
   24 of 24 columns MATCH on the first comparison (rtol = atol = 1e-9, all 14,850 team-game keys). Its code and notes: `blind_briefs/nfl_pbp4_blind_runs/`. Agent verification, not human.
3. `regenerate --apply`: missing PRIMARY slots 884 -> 873 (NFL 176 -> 165); VERIFIED_PARTIAL 218 -> 221, VERIFIED_PROXY 20 -> 22.
   The 11 closed slots are in 10 NFL market archetypes: game moneyline/spread, game total, team total, game events, score-path functionals, season win totals and futures,
   slate extremes, league tie and long-kick counts, QB passing yards, receiving yards and receptions.

## Walk-forward evidence (`research/audit/nfl_pbp4_walkforward.json`, seasons 2018-2026, baselines fitted on earlier seasons only)
* Expected margin vs a constant home edge: MAE 10.40 vs 11.04 (+5.9%), better in 9 of 9 seasons. The closing spread (benchmark, never an input) is 9.82 on the same games.
* Expected team points vs the prior-season mean by venue: MAE 7.53 vs 7.96 (+5.5%), 9 of 9 seasons.
* P(team points >= 17/21/24/28): Brier +5.4% to +7.0% vs base rate, 9 of 9 seasons. P(margin >= 1/4/8/15): +4.8% to +7.6%, 9 of 9 seasons.
* P(|margin| = 3), P(|margin| = 7) and P(overtime): no gain over the base rate (+0.0% to +0.1%). Verified as computed, not as useful.
* `nfl.proe`: not assessed.
This is evidence about inputs against naive baselines. It is not evidence that any projection model would improve.

## Integration recommendations (nothing activated)
1. NFL: test `omr_exp_margin_pre` and `pfa_exp_points_pre` as candidate features in the NFL operating model's walk-forward harness. They are worse than the closing line, so the question is
   only whether they add to the model's existing features.
2. NFL: test the `tsp_ge*` / `mml_ge*` rungs against the model's current ladder probabilities for team-total and spread rungs. Do not use the key-number or overtime columns.
3. CBB (PR #94 inputs): `cbb.adj_off`, `cbb.adj_def` (+10.0% RMSE vs naive), `cbb.tempo` (+6.7%), `cbb.opp_foul_propensity_ft_points` (+4.6%), `cbb.pace_elasticity_to_opponent` (+4.5%)
   have the strongest out-of-sample evidence among certified basketball inputs. NBA four-factors and three-attempt matchups are weaker (+0.6% to +2.5%).
4. Do not integrate the scale inputs (`nba.three_point_variance_load`, `nba.team_points_variance_by_style`, `nba.ot_prob_ratings_margin`, `cbb.total_variance_by_style`): no gain over a constant.

## Run
```
python sift-data-vault/tools/vault.py restore --path archives/NFL/pbp/2010-2026/nflverse/snapshot-20261116 --to RAW/NFL
python sift-data-vault/tools/vault.py restore --path archives/NFL/inseason_player_team/1999-2026/nflverse/snapshot-20261116 --to RAW/NFLp
python -m alpha_engine.input_research.data_foundation.replay_ext_run nfl_pbp4 RAW/NFL/pbp RAW/NFLp/schedules/games.csv OUT.json      # about 30 s
```

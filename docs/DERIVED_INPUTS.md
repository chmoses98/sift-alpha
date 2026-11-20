# Derived inputs: a shared feature foundation on data Alpha already holds (RESEARCH_ONLY)

`alpha_engine/derived/` turns archived raw data into verified pre-game inputs with explicit lineage:
raw vault dataset → derived columns → projection-model adoption → Kalshi market families.
Nothing here is consumed by a projection model, deployed, scheduled or traded.

## What exists
| Module | Purpose |
|---|---|
| `basketball.py` | One engine for NBA and CBB (identical ESPN team-box / schedule schemas): possessions, pace, per-possession ratings, four factors, shot-volume and opportunity rates, matchup compositions, market-free expected points / margin / total, variance, overtime and joint-structure parameters. |
| `registry.py` | One record per input: catalog id (or a proposed new input), level against the catalog definition, what is done, what is missing, raw datasets, Kalshi families, out-of-sample evidence triples. |
| `verify.py` | Leak replay, independent recomputation, coverage, out-of-sample evidence, adoption probe; writes `research/audit/derived_inputs.json` only. |

## Calculated, certified, consumed: three separate answers
* **Calculated** (28: NBA 13, CBB 15): this engine built the input and its own checks passed (leak replay, plain-Python recomputation of pace, FT rate and points per 100 possessions, coverage). Not certification.
* **Certified** (15 of the 18 catalog inputs): the data-foundation ledger `research/input_research/data_foundation/verified_coverage.json` holds VERIFIED_PARTIAL. It is written only by `verified_coverage.build` (via `regenerate --apply`); this engine reads it.
  * 9 promoted on this builder's evidence (REQUIRES_COLLECTION -> VERIFIED_PARTIAL): nba.ot_prob_ratings_margin, nba.team_points_variance_by_style, cbb.four_factors, cbb.pace_elasticity_to_opponent, cbb.opp_foul_propensity_ft_points,
    cbb.opp_three_defense_persistence_split, cbb.total_variance_by_style, cbb.margin_total_covariance, cbb.team_points_margin_coupling.
  * 6 were already VERIFIED_PARTIAL from earlier builders (features/nba_ext, features/cbb_ext): nba.four_factors_matchup, nba.team_three_attempt_matchup, nba.three_point_variance_load, cbb.tempo, cbb.adj_off, cbb.adj_def. This builder is not declared for them (the ledger rejects duplicate replay ids).
  * 3 are not promotable under the ledger's rules and were left alone: nba.joint_pace_interaction and nba.game_pace_composition (BLOCKED_CONTESTED) and nba.margin_heteroscedasticity (DOWNGRADED_BY_VERIFIER; the reason, "3 seasons vs 5", predates the 25-season vault archive). All three pass the replay and the blind match below; changing their status is an owner decision.
  * cbb.four_factors implements every clause of its catalog text but stays PARTIAL: the promotion audit stops it at S2 (the audit grades it PIT_COARSE), S4 (no measured catalog history) and there is no FULL certification record.
* **Consumed by an operating model**: 0. No promoted model in `sift_feed/operating_models.json` imports `alpha_engine.derived`. The adoption column is a keyword probe of projection code only.
* `research/input_research/computable_inputs.json` (the Milestone-2 catalog computability ledger) is not written by this engine; the panel shows it separately.

## Certification evidence (foundation process)
1. **Replay** (`replay_ext_run` families `nba_derived`, `cbb_derived` -> `verification/replay_ext/{NBA,CBB}_derived.json`; adapter `derived/foundation_ext.py`): determinism, truncation at 3 cuts, future perturbation with 3 seeds, own-game scramble, non-vacuity. 12 of 12 pass. The non-vacuity test uses `perturb_nv` (Phase 15 precedent): a within-season permutation cannot move a pooled seasonal overtime rate, so 30% of the block's games are also marked double-overtime.
2. **Blind exact match** (`compare_independent` -> `verification/independent/{NBA,CBB}_derived.json`): one fresh headless Claude Code session in an empty directory with only `blind_briefs/briefs_derived_bball.md` and a copy of the raw parquet; 38 of 38 columns MATCH (rtol = atol = 1e-9, all 308,514 keys, identical NaN patterns) on the first comparison. Isolation audit and the blind implementation: `blind_briefs/derived_bball_blind_runs/`.
3. **Promotion audit** (`full_promotion_audit`): every promoted input stays PARTIAL; first failed stage recorded per input.
Defect fixed while writing the brief: the early-season z-score switch counted rows in file order (order dependent at the 200-row boundary); it now counts rows dated strictly before the game.

## Run
```
python sift-data-vault/tools/vault.py restore --path archives/NBA/espn_pbp_boxes_schedules/2002-2027/sportsdataverse/snapshot-20261116 --to /tmp/vr/NBA
python sift-data-vault/tools/vault.py restore --path archives/CBB/espn_team_box_schedules/2006-2027/sportsdataverse/snapshot-20261116 --to /tmp/vr/CBB
python -m alpha_engine.derived.verify --nba /tmp/vr/NBA --cbb /tmp/vr/CBB --repos <dir holding the projection repos>
```
About 2.5 minutes for both sports (308,514 team-games).

## Point-in-time rules
* A team's value for a game uses only that team's strictly earlier games.
* Shrink targets are the team's previous-season mean (needs 10+ games), else the league mean over strictly earlier dates, else the previous season's league mean.
* Every fitted coefficient applied to season S is fitted on seasons before S (annual refit): pace models, home edge, variance regressions, overtime logistic, correlation and coupling tables.
* No market price or line enters anywhere.

## Four questions that are never merged
1. **Definition completeness** — FULL / PARTIAL / PROXY from the registry. FULL only when the whole definition is implemented; a PARTIAL input lists what is missing.
2. **Verification** — outcome-shuffle replay (rows on or before the cut must be unchanged within 1e-9; later rows must move), an independent plain-Python recomputation of the two-stage adjusted estimates from raw parquet rows, and measured coverage. A failed check withholds the status.
3. **Predictive evidence** — out-of-sample comparison with a stated naive baseline on the four latest seasons. This is evidence about the input, not a claim that any projection model improved.
4. **Model adoption** — a code-reference probe of the projection repo. `CONCEPT_REFERENCED_IN_PROJECTION_REPO` means the model has its own version of the idea; it does not import this engine. `NOT_ADOPTED` means no reference was found.

## What verification caught during the build
* An overtime miscount: one CBB game carried an empty trailing linescore period, so linescore length said two overtimes where ESPN's period count said one. The rule is now period count first, linescore length as fallback, in both the engine and the independent check.
* Exhibition sides in the NBA files (All-Star teams) produced impossible ratings; the engine keeps the 30 franchises only.
* Early-season z-scores divided by a near-zero spread; they now use the previous season's distribution until 200 rows exist, and are clipped to ±4.
* The first overtime logistic did not converge on unscaled columns; it now standardises internally.

## Known limits
* CBB opponents outside Division I are treated as league-average until they accumulate games.
* The scale forecasts (total sd by shot mix, team-points sd, NBA overtime probability) do not beat a constant on the latest seasons; they are verified as computed, not as useful.
* Team-level only. Player-level and lineup-conditional versions need the player box and play-by-play archives already in the vault.

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

## Relationship to the certified ledger
`research/input_research/computable_inputs.json` and the data-foundation matrix built on it are **not** written by this engine. That ledger has its own promotion process (foundation replay, two blind rechecks, rights tiering, promotion audit), and eleven governance tests fail if statuses are injected into it directly. Each catalog input here is therefore `PENDING_FOUNDATION_REPLAY`; the artifact reports the certified counts and the counts after promotion side by side. Promotion is the next step and needs the foundation replay to be pointed at this builder.

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

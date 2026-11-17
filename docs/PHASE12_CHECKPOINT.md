# Phase 12 checkpoint: data completion and predictive intelligence (resume here)

Written 2026-11-17. RESEARCH_ONLY. Agent-run, not human verified. Branch `claude/sift-alpha-phase-12-0x6vht` in
`sift-alpha` (code, evidence) and `sift-data-vault` (one new archive). No sport repository was changed.
Start state: `docs/PHASE12_HANDOFF.md` (main `21b2763`). Read this file first; nothing below needs re-investigation.

## 0. Phase 12 continued (2026-11-17, second session): resume here first

Branches `claude/nba-projections-phase-12-6ud22v` in `sift-alpha` (stacked on #88) and `nba-edge-finder` (PR #112, stacked on
#105 -> #104). No production, workflow, schedule, settlement or baseline change. Details: `docs/PHASE12_VERIFICATION.md`,
`nba-edge-finder/docs/research/NBA_PRODUCTION_POSTMORTEM.md`.

**Done**
* NBA production postmortem against what SIFT runs (pf-1.3 players, pf-nba-team_points games, V1 sim, 612k archived Kalshi
  quotes). Totals biased +3.8; win probability under-confident (slope 1.7); bench minutes +1.9; 775 phantom participants
  (562 COACH'S DECISION). pf-1.3 beats V1 on every player metric. The market beats production on every family.
* NBA player challenger QM (rotation-depth participation + team-coherent minutes): participation Brier 0.0825 -> 0.0751,
  minutes MAE 4.616 -> 4.543, unconditional points MAE 3.304 -> 3.184 (all CIs exclude 0; holds at tip - 4 h). No market edge.
  Frozen `frozen_pfc1.json` `c7bb2795` for games after 2026-11-17T12:00Z.
* NBA game challenger G1: equal to production on margins, fixes the totals bias and the slope; not significant on 197 games.
  Frozen `frozen_g1.json` `8fff6b5a`.
* Verification: NBA/CBB "2026-27" holdouts are 2025-26 + 2026-27-to-date (label error, no leakage); prereg ancestry and
  hashes verified for all six studies.
* Readiness: dataset certifications now feed `verified_coverage` (new status VERIFIED_DATASET_CERTIFIED, headline PARTIAL;
  never overrides a failure). 565 / 715 confirmed, not reduced: 11 of 12 certified inputs were already verified there; the
  12th (`mlb.wins_to_date_and_games_remaining`) has a verifier downgrade kept as a conflict for owner review.
* New certified dataset NBA player box `4a8449177781` (795,653 rows, blind 0 mismatches): +4 training-ready NBA inputs.
  Six core sports 37 -> **41** training-ready (NBA 6 -> 10); all eight sports 54 -> 58.
* CBB head-to-head vs production (`production_h2h_cbb.json`): the Alpha CBB model is much worse early-season (margin MAE
  12.69 vs 10.17, n = 638). Do not promote; it lacks a preseason prior.

**Next, in order**
1. `python scripts/nba_phase12_research.py prospective ...` (nba-edge-finder) once >= 100 post-freeze games settle; if QM holds,
   propose the `shadow_challenger` stream (owner approval).
2. Owner review: V1 (active pricing) is worse than pf-1.3 on identical player-games.
3. pf-nba-team_points stage-2 calibration (totals level, margin scale) as a preregistered challenger on history.
4. CFB head-to-head: production pf-cfb forecasts exist on `cfb-edge-finder` `projection-data` (from 2026-10-20); the CFB
   dataset must be extended through 2026-11-15 first. Re-run the CBB head-to-head after January, or add a prior.
5. NHL shift features; MLB probable-starter capture proposal (unchanged).

Reproduce (Alpha): `python -m alpha_engine.features.nba_player_box --root $B --out X --evidence E` (about 8 min with the leakage
suite); `python alpha_engine/certify/nba_player_box_independent.py --root $B --out Y`; `python -m alpha_engine.certify.compare
--a X --b Y --key key`; CBB: `training_sets_multi cbb`, then `discovery.run --prereg research/discovery/cbb_game_lines_v1/prereg.json
--dataset D --holdout --pred-out P`, then `discovery.production_h2h` with the projections-archive table (last projection
generated before start, from `cbb-edge-finder` branch `projections-archive`).

## 1. What changed, in one table

| Measure (six core sports, 1,241 predictive inputs) | End of Phase 11 | Now |
|---|---|---|
| Training-ready inputs, all eight sports | 48 | **54** |
| Training-ready, six core sports (MLB / CFB / CBB / NFL / NBA / NHL) | 31 (0 / 3 / 4 / 13 / 3 / 8) | **37 (2 / 4 / 4 / 13 / 6 / 8)** |
| Missing-primary inputs that have every raw data need archived | 105 | **178** |
| Inputs whose raw data is not archived | 357 | 287 |
| Inputs blocked only by provider rights for collection | 161 | 38 |
| Inputs with archived data and no feature built | 189 | 324 |
| Inputs built but not independently verified | 98 | 130 |
| Inputs with no historical pregame snapshot (cannot be reconstructed) | 382 | 382 |
| Missing primary inputs / slots (map definition: not replay-verified) | 565 / 715 | **565 / 715 (unchanged)** |
| Registered dataset versions | 7 | 12 (1 superseded) |
| Preregistered out-of-sample studies with a scored holdout | 0 | 6 (one per sport) |

Why 565 / 715 did not move: that count comes from the data-foundation replay ledger (`verified_coverage.json`),
which only changes when a feature is replayed and verified inside that system. Phase 12 certified inputs through
the dataset-certification route (blind re-implementation), which the planner honours for training readiness but
the replay ledger does not read. Wiring certification evidence into `verified_coverage` is next-session item 2.

Per sport (before -> now): certified · data-complete missing inputs · raw data not archived.
MLB 0->2 · 1->25 · 67->67. CFB 3->4 · 4->25 · 91->31. CBB 4->4 · 4->20 · 54->54. NFL 13->13 · 56->58 · 63->62.
NBA 3->6 · 33->41 · 51->51. NHL 8->8 · 7->9 · 31->22.

## 2. Data: what the vault holds, measured

`python -m alpha_engine.foundation.vault_ledger` counts restored archives into
`research/input_research/data_collection/vault_ledger.json` (24 entries; counts, dates, hashes only). 16 dataset
definitions now point at those entries (`datasets.py: VAULT_EVIDENCE`), so "raw data archived" is separate from
"feature verified". Holding data is not permission; rights stay in the registry and the vault `POLICY.md`.

| Sport | Archive (measured) | Period | Complete / partial |
|---|---|---|---|
| MLB | 12,148 regular-season games, 3,560,564 pitches, 357,172 player box rows | 2022-04-07..2026-09-27 | complete for 2022-2026; nothing before 2022; probables and weather are postgame values (12,137 games), not pregame vintages |
| NFL | play-by-play 1999-2026 (1999-2009 hash-pinned upstream), weekly player/team, rosters 2002-2026, officials 2015-2026 (3,045 games), contracts; **new: schedule + closing lines `games.csv`** | 1999..2026-11-15 | complete; injury and inactive vintages not held |
| NBA | 32,395 team boxes, 853,395 player box rows, 33,496 schedule rows; play-by-play 2,846 games | boxes 2001-10-30..2026-11-15; pbp 2024-10..2026-11 | boxes complete; play-by-play only three seasons; no lineup or injury history |
| NHL | 20,919 games of shift events (7.78M rows), 20,920 team/player boxes; play-by-play 1,725 games | shifts/boxes 2010-10-07..2026-11-15; pbp 2025-26 and 2026-27 only | shifts and boxes complete; full play-by-play two seasons only; expected goals exist only in the NHL-edge-finder MoneyPuck history (not manufactured here) |
| CFB | CFBD cache (drives, team games, advanced, SP+, rankings, recruiting, portal, coaches, lines), 11,124 ESPN summaries with player boxes; 10,953 with drives and plays (1,985,080 plays) | 2014..2026 | 171 summaries have no play-by-play at the source; CFBD is internal-only |
| CBB | 126,264 team-box games, 125,066 player-box games (3.70M rows), 147,805 schedule rows | 2003..2026-11-15 | team/player boxes complete where ESPN has a box (803 games have none upstream); play-by-play only 2026-27; half scores still missing (74,944) |

Measured but not linked to a catalog dataset (no matching definition): `cbb_sdv_schedule`, `cbb_sdv_team_box`,
`cfb_cfbd_lines`, `nba_sdv_pbp`, `nhl_sdv_player_box`, `nhl_sdv_team_box`.

## 3. Datasets and certifications (append-only registry)

| Sport | sha256 (first 12) | Rows | Builder / spec | Status |
|---|---|---|---|---|
| NFL | `9c1893bd06d8` | 7,548 | `training_sets nfl`, Phase 7 inputs | **new**; same builder as `d0616511`, which is now superseded: it used an unarchived `games.csv` and cannot be rebuilt bit-exact |
| MLB v1.1 | `2e4c89b37f3c` (first pitch), `ccd908f235d1` (24 h before) | 12,148 | `certify.mlb_game_v11`, `MLB_FEATURE_SPEC_V11.md` | **new, certified**: blind match 0 of 12,148 x 59 cells on both leads; truncation, future-scramble, own-outcome identical |
| NBA team box | `f2a75ff0d647` | 30,257 | `features.nba_team_box`, `NBA_TEAM_BOX_SPEC.md` | **new, certified**: blind match 0 of 30,257 x 74 cells; four cut dates identical |
| CBB (vault) | `17c5da58603e` | 121,884 | `features.cbb_box`, spec v1.1 | **new, certified** on the vault snapshot (blind 0 mismatches, 3 leakage dates, 1 truncation date, outcomes 121,883 / 121,884) |
| NHL `71f08bf06a78`, NBA `f079a9ffa007`, CFB v1/v2, CBB `3e73d70d`, MLB v1 | | | | unchanged; NHL and NBA rebuilt bit-exact this session |

New certified inputs: `mlb.pythag_luck`, `mlb.wins_to_date_and_games_remaining`, `nba.four_factors_matchup`,
`nba.pythag_residual`, `nba.rebound_pool`. Promoted by archived data alone (already built and verified, only the raw
data check was open): `cfb.pythag_luck`. Evidence: `research/certification/certification_{mlb_v11,nba_team_box,cbb_vault}.json`.

The MLB blind build found a real defect in the primary builder (a feed whose last play is stamped before first pitch
made the game its own prior; 37 cells in one game). Fixed before registration.

Held back, with reasons in the certification files: MLB starter quality / workload / probable-starter vintage (starter
identity is the box-score starter; timestamped captures cover 28% of 2026 and nothing earlier), `mlb.opp_strength`,
`nba.pace`, `nba.off_rtg`, `nba.def_rtg` (need opponent / lineup adjustment), `nba.rest_travel`, `nba.venue` (need
venue coordinates, `env.venue_geo` not archived).

MLB forecast-time availability: with a first-pitch cutoff, features are final 90 minutes before on 99.4% of rows, 6 h
before on 98.4%, 24 h before on 25.9%. The 24 h dataset is final by construction on 100%.

## 4. Research: six preregistered studies (`docs/DISCOVERY_REPORT.md`)

Engine `alpha_engine/discovery/` (`engine`, `run`, `kalshi_labels`, `adapters`, `joint`, `report`). A study is a JSON
preregistration committed before scoring. The engine refuses an unregistered dataset hash and any market or postgame
feature column, fits season S on seasons before S only, blanks holdout outcomes unless `--holdout`, and ties
`holdout.json` to the preregistration hash. Accuracy evidence only: no price, liquidity or fee data is used.

| Study (prereg) | Test n | Margin RMSE: climatology / reference / full | Winner picked | Versus closing line | Inputs surviving Holm | Holdout (scored once) |
|---|---|---|---|---|---|---|
| NFL `d627830789b2`, test 2022-25 | 1,139 | 13.87 / 12.91 / 12.87 | 64.4% | spread MAE 9.85 vs line 9.54; side vs spread 50.9% (95% CI 47.7-54.1); totals 49.7%; win Brier 0.2208 vs market 0.2100 | 0 of 22 | 2026, n=149: MAE 10.15 vs 9.58; side 42.0% (33.6-52.8) |
| CFB `9fd26b882bcc`, test 2022-24 | 2,725 | 21.86 / 18.02 / 16.69 | 73.7% | spread MAE 13.16 vs 12.07; side 50.3% (48.6-52.3); totals 52.1% (50.6-53.7) | 6 of 14 | 2025, n=934: MAE 12.71 vs 11.90; side 52.3% (48.8-55.6); totals 50.5% |
| NBA `f7ac9d8d7911`, test 2020-25 | 7,061 | 15.04 / 14.06 / 13.91 | 64.1% | no line history in the vault | 10 of 10 (totals reference is weak, see below) | 2026-27, n=1,428: 14.84 vs 15.05; winner 67.2% |
| NHL `5e59c903abb7`, test 2022-24 | 3,936 | 2.632 / 2.549 / 2.548 | 60.2% | none | 0 of 10 | 2025-26, n=1,312: 2.542 vs 2.547; winner 53.8% |
| CBB `2c26cbe6b8c9`, test 2021-25 | 28,994 | 17.29 / 14.69 / 13.61 | 72.0% | none | 6 of 8 | 2026-27, n=7,159: 14.56 vs 16.25; winner 74.0% |
| MLB `47d76899f603`, test 2025 | 2,430 | 4.589 / 4.539 / 4.540 | 53.1% | none | 0 of 4 | 2026, n=2,429: 4.536 vs 4.534; winner 53.4% |

What the evidence supports:
* **No study shows value against a market.** Where closing lines exist (NFL, CFB) the sports-only model is less
  accurate than the line and its side selection is not distinguishable from 50%. The CFB totals result on test seasons
  (52.1%) did not repeat on the holdout (50.5%): not a finding.
* **Inputs that improve forecasts over the reference, out of sample:** CFB drive scoring, success rate, pass/rush split
  and roster priors (margin), drive scoring and success rate (total); CBB four factors, tempo, conference strength;
  NBA four-factors matchup, rebound pool, efficiency, pace, rest. NBA totals gains are measured against a reference with
  no scoring-level information across eras, so they show that pace/efficiency inputs are needed, not how much they add
  to a competent totals model.
* **No incremental value found:** every NFL input beyond season record (0 of 22; penalties, turnovers and red zone
  made totals or margin worse), every NHL input beyond standings rates, MLB Pythagorean / run form beyond season state.
* **Calibration:** win-probability slope 1.00-1.12 on test seasons in every sport (NFL 1.12, NBA 1.11: slightly
  under-confident). NHL holdout winner accuracy fell to 53.8% from 60.2%.
* **Official labels:** NFL 2026 holdout, 7,396 Kalshi contracts: official result equals the score-derived outcome on all;
  model Brier 0.175 / 0.178 / 0.224 (spread / total / winner) vs a closing-line-derived benchmark 0.167 / 0.168 / 0.213.
  NFL 2025: 11,037 of 11,040 agree; the three exceptions are listed in `nfl_game_lines_v1/results.json` for settlement
  review. NBA 2025-26 and 2026-27: 43,280 of 43,280 agree.
* **Dependence between legs** (`joint_dependence_{NFL,CFB}.json`): favourite-wins x over is independent in both sports
  (joint / product 1.00, NFL CI 0.99-1.02; CFB 1.01, CI 1.00-1.02). CFB favourite-covers x over is not: joint 0.259 vs
  product 0.244, ratio 1.06 (CI 1.04-1.08). NFL cover x over 1.00 (0.98-1.03). Multiplying leg probabilities is wrong
  for same-margin legs by construction (favourite wins x covers: 1.52 NFL, 1.32 CFB).

Limits: closing lines carry no quote timestamp; no Kalshi quote history is in the vault, so no closing-line value or
fee-inclusive result exists; CFB and CBB official labels are not joined (team identity, ladder semantics); NHL dataset
ends before the Kalshi NHL snapshot starts; MLB has one test season; no comparison with existing SIFT production
projections was run (they live on the sport repositories' data branches, not fetched this session).

## 5. Model recommendations (research-only; nothing promoted)

| Sport | Recommendation | Evidence | Status |
|---|---|---|---|
| CFB | Evaluate drive-scoring (v2), success-rate and roster-prior inputs as challengers to the current spread model | 6 hypotheses pass Holm; margin RMSE 18.02 -> 16.69 on test, 17.46 -> 16.24 on holdout | candidate; needs a head-to-head with the production projection |
| CBB | Same for four factors, tempo and conference strength | margin RMSE 14.69 -> 13.61 test, 16.25 -> 14.56 holdout | candidate |
| NBA | Team-level four-factor and rest inputs help; the binding gap is availability | holdout margin RMSE 14.84 with no injury input | candidate; player props stay blocked |
| NFL | Do not add the 11 certified efficiency inputs to a line model expecting gains | 0 of 22, three worse | negative finding |
| NHL, MLB | No change supported | 0 of 10 and 0 of 4 | negative finding |
| All | Price same-margin and (in CFB) cover x total combinations with a joint model, not a product | section 4 | research only |

## 6. Dashboard

Data foundation -> **Coverage** tab (`src/market-coverage.jsx`, data from
`python -m alpha_engine.foundation.market_coverage`): before/after cards, sport tabs, class table, market cards with
a coverage bar and next action, input drill-down (checks, sources with archived flag, gap, next action), research
studies. Checked in a browser at 1280 px and 390 px: no horizontal overflow, no page errors.
`tests/market-coverage.spec.mjs` needs the project's own Playwright browsers (CI); it was not run here.

## 7. Engineering state

* Tests: `python -m pytest -q tests` -> 1,667 passed, 8 skipped. `npm test` -> 89 passed. `regenerate --check` -> ok.
  New: `tests/test_phase12.py` (15 tests). Seven older tests pinned Phase 11 counts; each pin was updated with its
  reason in a comment (certified inputs 7 -> 12, training-ready 48 -> 54, data-in-hand rows 132 -> 263, NFL manifest hash).
* Rule changes (all stricter or evidence-preserving): history must hold for every data need (was: any need);
  a vault-held dataset reports the held date range; an input whose data became held keeps an earlier extension-replay
  verification; a certification that names its columns counts as the built feature.
* Production: unchanged. `NFL_SETTLE_PHASE11_RULES` and `NBA_SETTLE_1_1` appear in no workflow (unset = off);
  NBA `ACTIVE_BASELINE_ID` = V1. No schedule, weight, trading or visibility change. No paid service used.
  Downloads this session: nflverse `games.csv` and hash-verified play-by-play 2000-2009 (public release assets).

## 8. Reproduce

    S=<scratch>; cd sift-data-vault                      # restore what a step needs: tools/vault.py restore --path <archive> --to $S/v/<SPORT>/<dataset>/<season>
    cd ../sift-alpha
    python -m alpha_engine.foundation.vault_ledger --restored $S/v --catalog ../sift-data-vault/CATALOG.json   # about 2.5 min
    bash scripts/research/regen_coverage_chain.sh                                                              # catalog -> map -> plan -> coverage, about 70 s
    python -m alpha_engine.certify.mlb_game_v11 --feed-root $S/v/MLB/postgame_feed_compact --out $S/mlb/L0.parquet --lead-hours 0 --evidence $S/mlb/ev0.json
    python alpha_engine/certify/mlb_independent_v11.py --feed-root $S/v/MLB/postgame_feed_compact --out $S/mlb/blind0.parquet
    python -m alpha_engine.certify.compare --a $S/mlb/L0.parquet --b $S/mlb/blind0.parquet
    python -m alpha_engine.features.nba_team_box --root $S/v/NBA/espn_pbp_boxes_schedules --out $S/nba/tb.parquet --evidence $S/nba/ev.json
    python -m alpha_engine.foundation.training_sets nfl --raw $S/raw_nfl --out $S/ds/nfl     # raw_nfl: pbp/pbp_<season>.parquet, games.csv, players.parquet
    python -m alpha_engine.foundation.training_sets_multi cbb --cbb $S/v/CBB/espn_team_box_schedules/2006-2027 --out $S/ds/cbb   # 7 min
    python -m alpha_engine.discovery.run --prereg research/discovery/nfl_game_lines_v1/prereg.json --dataset $S/ds/nfl/nfl_game_training.parquet \
        --market $S/raw_nfl/games.csv --official $S/v/NFL/kalshi_official_settlements/all-to-20261116/NFL [--holdout]
    python -m alpha_engine.discovery.joint --sport NFL --dataset ... --market ... --first-season 1999 --last-season 2025 --out research/discovery/joint_dependence_NFL.json
    python -m alpha_engine.discovery.report

Re-running a study with an unchanged preregistration reproduces its files. A changed question needs a new study
directory; a holdout season already scored (NFL 2026, CFB 2025, NBA/CBB 2026-27, NHL 2025, MLB 2026) is no longer
untouched for that sport and family.

## 9. Not done

* NHL shift-based ice-time, line-usage and matchup features: archive measured and linked (20,919 games); no builder.
* NFL opponent-adjusted usage, weather and lineup-context inputs: not started (96 inputs have data and no feature).
* CFB missing play-by-play (171 summaries) and alias table (346 events); CBB half scores (74,944) and join (1,047).
* NBA player-level inputs (minutes, rotation, usage) from the 853k archived player rows; injury vintages do not exist before 2025-10.
* MLB probable-starter capture: proposal only (below). Second NFL overlay snapshot (after 2026-11-30). NBA V1-vs-V2 2H evaluation.
* Comparison of study predictions with production SIFT projections.

Inactive proposal (needs approval, no schedule changed): capture MLB probable starters and posted lineups with a
retrieval timestamp at fixed leads (24 h, 6 h, 90 min) into the existing `data/slates` path from the 2027 season
opener; without it MLB starter inputs can never be certified historically.

## 10. Owner decisions

1. Review and merge the Phase 12 pull requests (`sift-alpha`, `sift-data-vault`). Research and evidence only.
2. Approve (or decline) the MLB probable-starter capture proposal for 2027.
3. Carried over, unchanged: activate NFL #288 rules; NBA settle-1.1; adopt the MLB #319 and NFL #286 overlays; CFBD
   raw responses on public cfb-edge-finder branches.

## 11. Next, in order of expected value

1. Head-to-head of the CFB and CBB challengers against production projections and against Kalshi quotes (fetch the
   quote history from the sport repositories' data branches); only then discuss promotion.
2. Feed dataset-certification evidence into `verified_coverage` so the 715-slot count reflects certified inputs.
3. NHL shift features and NBA player-minutes features on the archived data, each with a blind re-implementation.
4. CFB and CBB team-identity joins so official Kalshi labels can score those studies.
5. Extend the NHL dataset through 2026-11-15 so its study can use official labels.

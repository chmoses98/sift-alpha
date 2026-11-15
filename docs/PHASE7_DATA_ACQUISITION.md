# Phase 7 (2026-11-15): data acquisition and training-dataset construction (RESEARCH_ONLY)

Agent verification only (Claude builders, replay gates, one blind Claude re-implementation). **Not human verified.** No model was retrained or promoted, no schedule was created or activated, no paid service, credential or account was used, and **no rights tier was changed**. No raw or dataset row is committed: aggregates, digests and evidence JSON only.
Dashboard: Data foundation → **Phase 7** tab (rendered from `research/data_foundation_ops/phase7_acquisition.json`, built by `python -m alpha_engine.foundation.phase7`).
Builds on draft PR #77 (Phase 6). At the start of this phase the recomputed baseline was 1,649 candidate inputs, 888 missing PRIMARY slots (683 distinct inputs), 39 training-ready inputs and 60 VERIFIED_FULL.

## 1. Counts before and after (recomputed by the regeneration chain, not typed)
| | Before (PR #77) | After |
|---|---|---|
| Training-ready predictive inputs | 39 | **41** (NFL 11 → 13) |
| VERIFIED_FULL (certified) | 60 | 62 |
| Missing PRIMARY slots / distinct inputs | 888 / 683 | **886 / 681**: `NFL:team_total` closed by `nfl.pass_run_split_epa_both_sides`, `NFL:game_events` closed by `nfl.rush_yardage_tail` |
| Sport training datasets assembled | 0 | 1 (NFL, 7,548 games, 1999-2026) |

## 2. Data collected
* **nflverse play-by-play 1999-2025:** 27 season files, 0 failures, about 466 MB; 1,279,628 plays.
* **nflverse 2026 current season:** 24,002 plays through week 10 (last game 2026-11-12, 137 of 272 games), plus the schedule and the players file.
* Also reachable and profiled (HTTP 200), not otherwise used: the 2026 injuries, depth-chart, snap-count, weekly-roster, weekly player/team stats, FTN charting, PFR passing and officials files.
* The 2026 NGS passing and pbp participation files are not published (HTTP 404).
* Rights: `nflverse` is WRAPPER_LICENCE_UPSTREAM_CAVEAT with collection allowed.
* Raw files are held outside the repository (session scratch). Regenerate them with `refresh.py` or with the release URLs in `features/nfl_pbp_ext3.py`.

## 3. New inputs and how they were verified
| Input | Builder | Replay gates | Blind match | Status |
|---|---|---|---|---|
| `nfl.pass_run_split_epa_both_sides` (opponent-adjusted offence/defence EPA per dropback and per rush, neutral pass rate, blended expected EPA vs the opponent) | `features/nfl_pbp_ext3.py` | determinism, 3 truncation cuts, 3 perturbation seeds, own-game, non-vacuity: all pass; 14,826 team-games, 1999-09-19 .. 2026-11-12 | 6/6 columns, round 1 | VERIFIED_FULL, PIT_SAFE, training-ready |
| `nfl.rush_yardage_tail` (P(yards ≥ 7/10/15/20/30/40) per carry, QB/RB prior, opponent explosive and stuff factors) | `features/nfl_rush_ext3.py` (rusher view of `nfl_pbp_ext3`) | all pass; 57,548 rusher-games, 1999-09-13 .. 2026-11-12 | 7/7 columns, round 1 | VERIFIED_FULL, PIT_SAFE, training-ready |

* **Blind brief and evidence.** The brief is `verification/blind_briefs/briefs_p7_nfl.md`. A fresh subagent, given only the brief and a copy of the raw files, wrote its own implementation (`p7_blind_runs/blind_impl_nfl.py.txt`, 0 references to the repository).
* **Comparison.** `compare_independent.py` matched every value exactly (rtol = atol = 1e-9, identical keys and NaN pattern).
* **Certification.** `verification/full_certification/phase7_round1.json` maps every catalog clause to columns.
* **Two interpretation choices,** recorded in the certification:
  * The catalog's blended-EPA formula subtracts the defence term. It is applied with defence expressed as EPA prevented (league minus allowed), so a weak defence raises the opponent's expected EPA.
  * The catalog says "nfl.proe model". That is the published nflfastR `xpass` model, which only exists from 2006, so the pass-rate and blend columns are NaN for 1999-2005. Coverage is still 75%.
* **Harness note.** The rusher table uses a role-preserving perturbation, the same precedent as tennis. Per-carry yardage is permuted while rusher and team identities stay fixed. The generic scramble permuted identities, which changed the row universe and failed the own-game gate for a reason unrelated to leakage.

## 4. NFL training dataset (`alpha_engine/foundation/training_sets.py`, manifest `research/data_foundation_ops/training_sets/NFL.json`)
* **Unit and admission.** One row per game, home perspective, with `home_`/`away_` pre-game columns. Only inputs whose readiness state is TRAINING_READY are admitted: 12 game-level inputs, 70 columns. `nfl.rush_yardage_tail` is player-level and stays in its own table.
* **Prediction cutoff.** The scheduled kickoff. Each feature uses only games dated strictly before the game date.
* **Splits** (chronological, by season): train 1999-2018 (5,316 games), validate 2019-2021 (821), test 2022-2025 (1,139), prospective 2026 (272 rows, 137 with outcomes).
* **Checks.**
  * Keys are unique.
  * Regeneration is deterministic: the build runs twice and the canonical hashes agree (`ced4bf83…`).
  * Outcomes reconcile with the play-by-play final score for 7,393 of 7,410 games. The 17 mismatches are 16 Jacksonville home games in 2001-02 plus 2011_13_DET_NO, all play-by-play score-tracking errors; the schedule result is kept.
* **Legacy builder range.** The legacy builder (`features/nfl.py`) is fed only 2010-2026, the range it was certified on. Pre-2010 play-by-play contains empty `posteam` codes it does not handle, which had produced duplicate rows; the assembler now fails closed on duplicates.
* **Walk-forward check.** Market-free ridge, refitted for each test season on all earlier seasons; no betting line used. Home-margin MAE and winner accuracy:

| Test season | Games | MAE, all 12 inputs | MAE, legacy 11 only | MAE, constant | Winner accuracy, all | Winner accuracy, legacy |
|---|---|---|---|---|---|---|
| 2022 | 284 | 9.063 | 9.137 | 9.579 | 64.9% | 63.5% |
| 2023 | 285 | 10.553 | 10.522 | 11.083 | 63.5% | 63.5% |
| 2024 | 285 | 10.121 | 9.995 | 11.142 | 69.1% | 67.7% |
| 2025 | 285 | 10.104 | 10.231 | 11.002 | 64.8% | 61.6% |
| 2026 (wk 1-10) | 137 | 9.899 | 10.134 | 10.649 | 63.2% | 61.0% |
| **Mean** | | **9.948** | 10.004 | 10.691 | 65.1% | 63.5% |

  The gain is small and not uniform: 2023 and 2024 are slightly worse on MAE. This is a diagnostic, not a validated improvement and not a promotion.
* **Limitation.** Unplayed 2026 games carry no features yet, because the builders emit rows for completed games only. Scoring upcoming games needs the scheduled-row extension (next step).

## 5. Capture and current-season findings
* **The NFL weather-forecast capture has stalled.** nfl-edge-finder `context-capture.yml` published 224 forecast snapshots to `market-data` between 2026-09-04 and 2026-10-28 and has published none since. Its latest scheduled runs failed (2026-11-14) or were cancelled (2026-11-15), and the job logs have expired. Forecasts are point-in-time, so the missed weeks cannot be backfilled. **Owner action:** re-run it once and read the fresh log. No new workflow is needed.
* **NFL injuries and depth charts are running.** `pit-availability-nfl.yml` holds 3,292 nflverse injury vintages. Keep it. nflverse play-by-play needs no schedule.
* **The CFB current season is preserved.** The cfb-edge-finder `script-engine` workflow holds 751 completed 2026 games (1,502 team-game rows with play logs, box scores and drives) and availability for 143 teams, fetched 2026-11-15T14:45Z. Nothing to add.
* **NBA starters/transactions, NHL goalie confirmations and CBB availability:** the Phase 6 proposal stands unchanged.

## 6. Per-sport status
| Sport | New records acquired | Coverage | Datasets / features | Training-ready | Highest-value next acquisition |
|---|---|---|---|---|---|
| NFL | 1,303,630 plays (1999-2026), 7,548 games | 28 seasons, 2026 through week 10 | game training set; 2 inputs certified | 11 → 13 | repair the weather capture; ffopportunity rights reading (td_luck, first-TD attribution) |
| CFB | none new (owner archive current: 751 games, 2026) | 2026 only held | none (0 training-ready, 9 proxy-ready) | 0 | owner approval for the CFBD 10-call probe, then a CFBD backfill (`cfb.pbp_cfbd`) |
| NBA | none (rights) | owner archive 2023-24 .. 2026-27 | none new | 3 | NBA game dataset from the 3 ready inputs (next session); transactions capture |
| CBB | none (rights freeze) | no multi-season history | none | 0 | owner rights decision on `sportsdataverse_espn_mbb_cfb` (box scores 2005-2026 verified reachable in Phase 6) |
| NHL | none new | owner archive 2021-22 .. 2026-27 | none new | 8 | NHL game dataset from the 8 ready inputs; shift charts (rights + host) |

## 7. Owner decisions
1. Re-run nfl-edge-finder `context-capture.yml` and check why it fails. NFL weather vintages are being lost each week.
2. CFBD: add the approval file and dispatch the 10-call `college-direct-probe` (docs/COLLEGE_DIRECT_PROBE.md).
3. CBB/CFB history: record a rights decision for `sportsdataverse_espn_mbb_cfb`, or keep the freeze. This is unchanged from Phase 6.
4. ffopportunity: record a rights reading before it is collected.
5. Review and merge order: PR #77 (Phase 6) first, then this PR, which is stacked on it.

## 8. Regeneration
    python -m alpha_engine.input_research.data_foundation.replay_ext_run nfl_pbp3 RAW/pbp RAW/games.csv RAW/players.parquet OUT.json      # about 25 min
    python -m alpha_engine.input_research.data_foundation.replay_ext_run nfl_rush3 RAW/pbp RAW/games.csv RAW/players.parquet OUT.json     # about 1 min
    python -m alpha_engine.input_research.regenerate --apply && python -m alpha_engine.input_research.data_foundation.verified_coverage
    (then the Phase 6 §6 chain), python -m alpha_engine.foundation.training_sets nfl --raw RAW --out OUT --write-manifest && python -m alpha_engine.foundation.phase7

Tests: `pytest tests` 1,584 passed / 8 skipped. `npm test` 89/89. Pinned counts were updated with reasons: 888 → 886 slots, 796 → 794 provider slots, FULL 60 → 62.
Playwright could not launch here because the project's pinned browser build is not installed. A Chromium smoke test of the Phase 7 tab at 1280 px and 390 px rendered with no page errors and no horizontal overflow. The CI `e2e` job runs the full specs, including the new Phase 7 test.

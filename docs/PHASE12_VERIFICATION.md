# Phase 12 verification review (time safety, labels, preregistration, readiness accounting)

RESEARCH_ONLY. Written 2026-11-17 on top of PR #88 (`claude/sift-alpha-phase-12-0x6vht` @ `8825d9e`). Agent review, not
human verified. No preregistered file, holdout result or dataset was rewritten; corrections are stated here.

## 1. Holdout season labels: NBA and CBB "2026-27" are mislabelled (no leakage)

The engine labels seasons with ESPN's **end-year** convention for NBA and CBB (season 2027 = 2026-27). Both
preregistrations hold out `[2026, 2027]`, which is **two seasons**, not one:

| Study | Holdout as reported | What it actually contains (checked against the vault archive) |
|---|---|---|
| NBA `f7ac9d8d7911` | "2026-27, n=1,428" | 2025-26 regular season (ESPN season 2026, ~1,231 games) **plus** 2026-27 to 2026-11-15 (season 2027, 197 games) |
| CBB `2c26cbe6b8c9` | "2026-27, n=7,159" | 2025-26 (6,299 games) **plus** 2026-27 to 2026-11-15 (860 games); the two climatology probability bins in `holdout.json` are exactly these two seasons |
| NHL `5e59c903abb7` | "2025-26, n=1,312" | correct: NHL uses the start-year label, 2025 = 2025-26 (complete season, 1,312 games) |
| NFL, CFB, MLB | 2026 / 2025 / 2026 | correct (single-year seasons) |

Time safety: the last scored game in every holdout is dated on or before 2026-11-15; the archives were retrieved
2026-11-16. No scored game is later than its snapshot. Features use strictly earlier dates (certified leakage suites).
**Correction:** wherever `DISCOVERY_REPORT.md` and `PHASE12_CHECKPOINT.md` say "2026-27 holdout" for NBA or CBB,
read "2025-26 season plus 2026-27 to 2026-11-15". The numbers themselves are unaffected. Consequence for future work:
the 2025-26 NBA and CBB seasons are **no longer untouched** for those families.

## 2. Preregistration ancestry and hash linkage

| Study | prereg first committed | results + holdout committed | `holdout.json.prereg_sha256` = canonical hash of `prereg.json` |
|---|---|---|---|
| NFL | `8ec0570` 01:06:26Z | `e376ced` 01:15:47Z | yes |
| CFB | `7ab387d` 01:13:32Z | `e376ced` 01:15:47Z | yes |
| NHL | `e376ced` 01:15:47Z | `be08b39` 01:18:32Z | yes |
| MLB | `deeea33` 01:18:33Z | `46febb7` 01:33:33Z | yes |
| NBA | `46febb7` 01:33:33Z | `0314656` 01:36:35Z | yes |
| CBB | `0314656` 01:36:35Z | `3aedacf` 01:41:26Z | yes |

Every preregistration is an ancestor of its results. The file bytes hash differently from `prereg_sha256` because
the engine hashes canonical JSON (sorted keys, compact separators); recomputed and matched for all six.
Caveat: development, test and holdout were all scored minutes apart by the same agent session. The engine blocks
holdout labels until `results.json` exists, but nothing prevents a re-specification between the two; none occurred
(each `holdout.json` carries the hash of the committed prereg).

## 3. Reference competitiveness, now measured against production

The studies compared new inputs with weak references only. This session compared with what SIFT actually runs:

* **NBA game lines** (`nba-edge-finder` PR, `docs/research/NBA_PRODUCTION_POSTMORTEM.md`): production `pf-nba-team_points`
  on 197-205 games of 2026-27 has margin RMSE 15.36, total RMSE 18.66, total bias +3.8 to +4.0 points (CI excludes 0),
  win-probability calibration slope 1.70-1.84 (under-confident). An independent ratings model tuned only on 2016-2025
  (G1) is within noise of production on margins (RMSE 15.34), removes the totals bias (+0.53) and has slope 1.14. The
  market's two-sided T-60 mid beats production on every game family (spread, total, team total, winner; CIs exclude 0).
* **CBB**: see section 5.

## 4. Readiness accounting: the 565 / 715 count was not stale

`PHASE12_CHECKPOINT.md` said dataset certifications were not read by the replay ledger (`verified_coverage.json`).
Checked input by input: of the 12 inputs any certification file lists as eligible, **11 were already VERIFIED_PARTIAL or
VERIFIED_PROXY in the replay ledger** through extension replays, so they were already counted as covered in the
missing-primary count. The twelfth, `mlb.wins_to_date_and_games_remaining`, carries a blind-verifier downgrade (no game-status
column in the 2015-2025 schedule ledger) that the MLB v1.1 certification (built on the 2022-2026 postgame feed, which has
status) does not automatically override; it is recorded as a conflict for owner review.

Change made: `verified_coverage.py` now reads dataset certifications directly (`load_dataset_certifications`) under gates
equal to the replay gates (verdict CERTIFIED, blind re-implementation identical with 0 mismatched cells, truncation, and
every leakage entry future-scramble- and own-game-identical). A passing certification promotes only an input that is not
already verified and has no recorded failure, to `VERIFIED_DATASET_CERTIFIED` (headline PARTIAL, never FULL). Effect on
the current catalog: 0 promotions, 1 conflict recorded; missing primary 565 inputs / 715 slots (six core sports) is
**confirmed, not reduced**. The certification evidence is now attached to the 12 rows, so a future certification that
covers a not-yet-verified input will move the count automatically.

Two different denominators explain the apparent disconnect: "training-ready" (37 core inputs) requires every readiness
check (data, history, built, verified FULL, PIT, evaluated), while "missing primary" counts any slot whose input is not
FULL/PARTIAL/PROXY. Both are shown per input in the Coverage tab (`chk`).

## 5. CBB: the Phase 12 challenger against production (`research/discovery/production_h2h_cbb.json`)

The study's full model (four factors, tempo, conference strength, adjusted efficiency; walk-forward, 2026-27 fitted on seasons
through 2025-26) against the `cbb-edge-finder` projections-archive incumbent `pure-0.2.0` (last projection archived before tip),
on the 638 identical games of 2026-11-01..15 with a certified outcome (date-clustered CIs):

| | production | Alpha challenger | challenger - production |
|---|---|---|---|
| margin MAE / RMSE | **10.17 / 13.02** | 12.69 / 16.23 | +2.52 [+2.00, +3.14] |
| total MAE / RMSE | 13.71 / 17.14 | 13.75 / 17.09 | +0.05 [-0.50, +0.66] |
| winner Brier | **0.143** | 0.170 | +0.027 [+0.015, +0.040] |

**The CBB challenger is much worse than production on margins and winners early in the season** and ties on totals. Its
features are season-to-date only (no preseason prior, no carry-over), so in the first two weeks it knows almost nothing;
production carries priors. The Phase 12 recommendation "evaluate four factors / tempo / conference strength as a CBB
challenger" therefore stands only as *feature* evidence; as a model it must not be promoted. Re-test after January with
the same script, or add a prior (preseason ratings) first. Reproduction was exact: re-running the study with `--holdout`
rewrote `holdout.json` byte-identically.

## 6. New certified inputs this session

NBA player-box dataset `4a8449177781` (`NBA_PLAYER_BOX_SPEC.md` v1.1, 795,653 rows): blind re-implementation identical
(0 of 795,653 x 31 cells); truncation, future-scramble and own-game identical on 4 cut dates including 2026-11-10. The v1
draft's league-team rule (>= 20 games) silently excluded the season in progress; the leakage report exposed it, the spec was
revised before registration and both implementations were updated. Training-ready: `nba.heavy_minutes_tail_prob`,
`nba.points_upper_tail_rate`, `nba.combo_covariance`, `nba.bench_minutes_distribution` (six core sports 37 -> 41; NBA 6 -> 10).
They were already VERIFIED_PARTIAL in the replay ledger, so missing primary stays 565 / 715.

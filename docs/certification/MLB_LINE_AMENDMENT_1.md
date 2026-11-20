# MLB linescore inputs, amendment 1: first-pitch chronology for suspended games (2026-11-20)

Affects the six `alpha_engine/features/mlb_line_ext.py` inputs certified in PR #96: `mlb.first_inning_splits`, `mlb.f5_split`,
`mlb.playoff_walkoff_event_rate`, `mlb.sp_workload`, `mlb.sp_hook_hazard_curve`, `mlb.exit_boundary_mass`. RESEARCH_ONLY; nothing consumes them.

## Defect
Version 1 dated every game by `datetime.resumeDate` when present, else `officialDate`. A game suspended on day D1 and finished on day D2
was therefore dated D2. Its "pre-game" row was computed from every game played before D2, including games played after its own first
pitch. That is look-ahead. The archive (2022–2026, 12,359 kept games) holds 16 such games. Most resumed the next day. Two did not:
716404 (2023-09-28 → 10-02) and 746942 (2024-06-26 → **2024-08-26**, two months of later games in its pre-game row).

The certification harness could not see it. Truncation, perturbation and own-game all key on the builder's own date column, which was the
resumption date, so they stayed self-consistent. The blind brief prescribed the same rule, so the blind re-implementation matched exactly.

## Correction
* A game is dated by its **first pitch**: `date = datetime.officialDate`, which equals `resumedFromDate` for every suspended game in the archive.
* Its result becomes available on `avail = resumeDate` when the game was suspended, else `officialDate`.
* `score_core.fit` takes an optional `avail` column. A pool game for date d must be dated before d **and** have `avail` before d. A
  suspended game's own row therefore uses only pre-first-pitch information. Its result enters other games' pools only once it is
  complete; dating it by first pitch alone would leak its result into the games played in between.
* Without the column (CFB, NHL, every other builder), the output is unchanged byte for byte. A test pins this, and the re-run CFB/NHL
  walk-forward sections are identical.
* The season-walk-forward kernel uses earlier seasons only. The builder raises if any game completes outside its season (none do).

## Re-certification (fresh evidence; v1 evidence preserved)
| Step | Result | File |
|---|---|---|
| Spec (blind brief v2) | Two sentences changed: `date`/`avail` and the Method R pool condition | `verification/blind_briefs/briefs_mlb_line.md` (sha256 `cadc1694…`) |
| Blind re-implementation | New agent, brief and raw files only, no repository access: **20/20 columns MATCH on the first comparison** (rtol = atol = 1e-9, all 24,718 keys) | `verification/independent/MLB_mlb_line.json`, `verification/blind_briefs/mlb_line_blind_runs/` |
| Replay | determinism, 3 truncation cuts, 3 perturbation seeds, own-game, non-vacuity, plus the new `pit_check_first_pitch_availability` | `verification/replay_ext/MLB_mlb_line.json` |
| New PIT check, version 1 | **fails** for all 6 inputs (q0.55 cut and three straddle cuts) | `verification/superseded/mlb_line_v1_resume_date/v1_under_new_check.json` |
| Ledger | `pit_check_first_pitch_availability` is REQUIRED for the six inputs (fail-closed if absent) | `verified_coverage.REQUIRED_PIT_CHECKS` |

The new check works as follows. At each cut c, the content of every game whose result became known on or after c is permuted. Every row
whose game's first pitch (taken from the raw table, never from the builder) is before c must not change. Cuts are the three standard
quantile cuts plus first-pitch + 1 day for the four longest straddling games.

## Size of the change
* Pre-game values of the 16 suspended games change materially, e.g. by up to 0.87 expected starter outs and 4.1 expected pitches.
* Almost every other row also moves, because the 16 games enter pools at different times and shift recency weights. The median
  change is about 1e-4 (starter outs). See `superseded/mlb_line_v1_resume_date/v1_vs_v2_diff.json`.
* Walk-forward skill against the naive baseline is unchanged at the reported precision. Every input moved by at most 0.01 percentage
  points (`research/audit/six_sport_walkforward.json`, MLB section; v1 copy in the superseded folder). The conclusions of PR #96 stand:
  starter workload +2.9% to +4.3%, first-inning and walk-off inputs carry no usable signal.
* Ledger levels and missing-PRIMARY counts are unchanged: 6 inputs, still 1 PARTIAL and 5 PROXY.

## Preserved v1 evidence
`research/input_research/data_foundation/verification/superseded/mlb_line_v1_resume_date/` holds the v1 brief, the v1 blind
implementation and notes, the v1 independent comparison and the v1 replay, all byte-identical to PR #96's commits, plus the v1-vs-v2 diff
and the v1 result under the new check.

# SIFT overnight operation — CEO report (2026-11-20)

> DRAFT — sections marked ⏳ are filled when the remaining CI runs and studies complete.

Research-only throughout: no live model change, no bets, no bankroll, staking or exposure change, no deployment, no schedule change, no data purchase.
Protected surfaces were diffed against pre-session main `5813eaa8`. The only change is one additive CI test step (from #99).

## 1. Completed (PRs, SHAs, verification)
| Repo | PR | Result | Verification |
|---|---|---|---|
| sift-alpha | [#94](https://github.com/chmoses98/sift-alpha/pull/94) (+#95 inside) | merged → `4d46c27a` | Final-head CI 4/4 green (research-desk, e2e, dashboard, test). Locally, 10 test modules that errored only on missing deps pass once scipy/sklearn are installed. Main tree == #94 head tree. |
| cfb-edge-finder | [#312](https://github.com/chmoses98/cfb-edge-finder/pull/312) | merged → `95f9c4b2` | CI green. Independent re-run of `research_home_effect.py`: `report.json` byte-identical, 8,652 records identical. `ENABLED = False`; no production import (test-enforced). |
| sift-alpha | [#96](https://github.com/chmoses98/sift-alpha/pull/96) | ⏳ | MLB amendment 1 commit `bff96c7f`. CI research-desk, test and dashboard green; e2e ⏳. Local: 1,766 passed / 8 skipped; JS 89/89; e2e 110/110 (Chromium desktop + phone) on the integrated tree. |
| sift-alpha | #97, #98, #99 | ⏳ | 26/26 count-checked CFB probability/contract tests pass locally on the integrated tree. |

## 2. Input foundation
- **MLB look-ahead fixed and re-certified.** Suspended games had been dated by resumption: 16 games, one resumed two months later.
  - Builds now use first-pitch chronology.
  - Brief v2 was re-run by a fresh blind agent: 20/20 columns MATCH on the first comparison.
  - The full replay passes, including a new required `pit_check_first_pitch_availability`. That check fails the old dating for all 6 inputs.
  - v1 evidence is preserved under `verification/superseded/`. Details: `docs/certification/MLB_LINE_AMENDMENT_1.md`.
- **Counts are unchanged and reconciled.**
  - VERIFIED_FULL 62, VERIFIED_PARTIAL 226, VERIFIED_PROXY 37: 325 certified.
  - 841 missing PRIMARY slots.
  - `regenerate --check` is clean.
- **What the 841 slots need** (`research/input_research/readiness/`; reconciles exactly):

  | Class | Slots | In P1 markets |
  |---|---|---|
  | A: free source known, not collected | 289 | 46 |
  | A: no permitted free source | 50 | 8 |
  | A: source contested | 10 | 6 |
  | B: data already held, no builder | 134 | 47 |
  | C: calculated, certification failed | 28 | 9 |
  | E: needs timestamped capture from now on | 300 | 61 |
  | G: blocked by provider policy/terms | 30 | 12 |

  - Priority tiers: P1 189 · P2 277 · optional/low value 375.
  - 737 slots depend on data whose licence is unresolved: free to access ≠ cleared.
  - 14 datasets already archived in sift-data-vault were still listed as merely "reachable". NFL weekly stats, snaps, injuries, depth charts and participation, MLB pitch/PA events, CBB/CFB player box and NHL shifts are all **in hand**.
- **Adoption ladder** (`research/pipeline/ladder_summary.json`; levels above certified need evidence-checked claims, never keyword matches):

  | Exists | Calculated | Certified | Used by a frozen experiment | Prediction verified | Price-aware verified | Production |
  |---|---|---|---|---|---|---|
  | 1,649 | 387 | 325 | ⏳ | ⏳ | 0 | 0 |
- **Finding:** the CFB studies #97–#99 consumed `cfbx_mar_pre` / `cfbx_tot_pre`. These are intermediate builder columns, not certified catalog inputs. Their point-in-time replay now passes all checks (`verification/auxiliary/`), but they are not blind-certified.

## 3. Models (outcome prediction) ⏳
## 4. Betting selection ⏳
## 5. CFB ⏳
## 6. SIFT readiness ⏳
## 7. Remaining blockers ⏳
## 8. Tomorrow's priorities ⏳

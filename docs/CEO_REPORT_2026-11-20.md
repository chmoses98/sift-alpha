# SIFT overnight operation: CEO report (2026-11-20)

Research only throughout. No live model or published probability was changed. No bets, bankroll, staking or exposure change,
deployment, schedule change or data purchase. Protected surfaces (workflows, `sift_feed`, `feed/`, deploy config, promotion keys)
were diffed against pre-session main `5813eaa8`; the only change is one additive CI test step that came with #99.

## 1. Completed
| Repo | PR | Merge SHA | Verification |
|---|---|---|---|
| sift-alpha | [#94](https://github.com/chmoses98/sift-alpha/pull/94) (contains #95) | `4d46c27a` | Final-head CI 4/4 green. Main tree == PR head tree after merge. |
| cfb-edge-finder | [#312](https://github.com/chmoses98/cfb-edge-finder/pull/312) | `95f9c4b2` | CI green. The study was reproduced from the research-data cache: `report.json` byte-identical, 8,652 records identical. `ENABLED = False`; no production import (test-enforced). |
| sift-alpha | [#96](https://github.com/chmoses98/sift-alpha/pull/96) + MLB amendment 1 | `857df836` | Final head `bff96c7f`: CI 4/4 green incl. e2e (WebKit). Local 1,766 passed / 8 skipped. Main tree == head tree. |
| sift-alpha | [#97](https://github.com/chmoses98/sift-alpha/pull/97) | `059ac65b` | Retargeted to main, branch updated; final-head CI green (research-desk, test). Main tree == head tree. |
| sift-alpha | [#98](https://github.com/chmoses98/sift-alpha/pull/98) | `2ac2e8ca` | CI 3/3 green on `9838b018`. GitHub picked a stale criss-cross merge base after #97 and reported a false add/add conflict on `evaluate.py`. Resolved by merging main locally with the correct base. The final head `c9698210` has the **identical tree** (`9176c651`) to the tested head. Main tree == that tree. |
| sift-alpha | [#99](https://github.com/chmoses98/sift-alpha/pull/99) | `e6af2f9b` | CI 3/3 green (research-desk, test, e2e). Main tree == head tree. 26/26 count-checked CFB tests pass. |
| sift-alpha | overnight branch `claude/sift-overnight-execution-juf0pr` → PR | see PR | Local: Python 1,806 passed / 8 skipped / 0 failed; JS 91/91; e2e 110/110 (Chromium desktop + phone); `regenerate --check`, ladder and readiness `--check` clean. |

## 2. Input foundation
- **MLB suspended-game look-ahead: fixed and re-certified.**
  - 16 suspended games (2022–26) were dated by their resumption, so each one's pre-game row saw later games. One resumed two months later.
  - Builds now use first-pitch dating, and a game's result is withheld until it completes.
  - Brief v2 was re-run by a fresh blind agent: **20/20 MATCH on the first comparison**.
  - A new required replay check (`pit_check_first_pitch_availability`) passes for the fixed builder and **fails for the old dating**.
  - The v1 evidence is preserved. Walk-forward skill is unchanged (≤ 0.01 pt). `docs/certification/MLB_LINE_AMENDMENT_1.md`.
- **NFL legacy builder defect: fixed** (found by the NFL research agent).
  - The schedule codes relocated teams' home games as STL/SD/OAK, while play-by-play uses LA/LAC/LV. In 184 games (2010–19) neither row was marked home, so the home team took the away score.
  - 13 of 33 legacy inputs change values.
  - The replay was re-run; no certification status changed. `docs/certification/NFL_LEGACY_AMENDMENT_1.md`.
- **New: NFL player-prop batch 5, certified.**
  - Six inputs: carry, target, red-zone share, TD rates, target competition, stat variance.
  - Built from play-by-play we already held.
  - Replay passes, and the blind agent matched **19/19 columns** exactly on the first comparison.
- **Counts (ledger, reconciled):**

  | | Before | After |
  |---|---|---|
  | VERIFIED FULL / PARTIAL / PROXY | 62 / 226 / 37 = 325 | **62 / 230 / 39 = 331** |
  | Missing PRIMARY slots | 841 | **828** |
- **What the 828 slots need** (`research/input_research/readiness/`; reconciles exactly):

  | Class | Meaning | Slots | In P1 markets |
  |---|---|---|---|
  | A | data missing, free source known | 289 | 46 |
  | A | no permitted free source | 50 | 8 |
  | A | source contested | 10 | 6 |
  | B | data already held, no builder | 121 | 38 |
  | C | calculated, certification failed or downgraded | 28 | 9 |
  | E | needs timestamped capture from now on | 300 | 61 |
  | G | blocked by provider policy | 30 | 12 |

  - Priority tiers: P1 180 · P2 273 · optional/low value 375.
  - **737 slots depend on data whose licence is unresolved**: free to access is not cleared for every use.
  - 14 datasets the acquisition queue listed as merely "reachable" are already archived in sift-data-vault: NFL weekly stats, snaps, injuries, depth charts and participation; MLB pitch/plate-appearance events; CBB/CFB player box; NHL shifts.
- **Adoption ladder** (`research/pipeline/ladder_summary.json`). Levels above "certified" require evidence-checked claims, never keyword matches:

  | In catalog | Calculated | Certified | Used by a frozen experiment | Prediction gain verified | Price-aware gain verified | Production |
  |---|---|---|---|---|---|---|
  | 1,649 | 393 | 331 | 4 | **3** (CBB) | **0** | **0** |

## 3. Models: outcome prediction (unseen data)
| Sport | Test | Result |
|---|---|---|
| **CBB** | Certified four-factor matchups, adjusted-offence expected points and FT points stacked on the operating model (pure-0.2.0, reproduced exactly); fit 2016–22, chosen on 2023–24, TEST 2025–26 (11,511 games) | **Margin better**: ΔMSE −0.283 [−0.505, −0.085]. **Replicated forward** on 2026-27 (517 games): −2.17 [−3.61, −0.73]. The gain is tiny (RMSE 11.483 → 11.471) and concentrated early-season and in lopsided games. Winner accuracy is unchanged. **Totals worse** (+0.68 [+0.23, +1.14]). |
| NFL | Certified inputs stacked on the operating model's market-free baseline (rebuilt to 7e-15); TEST 2024–25 | **No improvement** for team points, total, margin or 1H total (all CIs include 0), before and after the builder fix. |
| NBA | Frozen projection-foundation prop challenger (reproduced exactly) vs Kalshi mid, 2025-26, 7,181 contracts | **Close to the market**: Brier 0.1764 vs 0.1782 (CI includes 0). Threes and Oct–Jan slightly better (exploratory). |
| MLB | Operating model vs mid, 2026 (8,762 contracts) | **Market better**: Brier 0.209 vs 0.193; model overconfident (slope 0.57–0.65). |
| CFB | Prior-season shrinkage of total projections (new hypothesis) | Held-out 2024–25 ΔMSE −7.9 [−11.1, −5.0]; 2025 −8.3 [−14.0, −3.5]; flat on 2026 (not independent). **Frozen as `cfb_total_shrink_v1`** for week 13+ only. |

## 4. Betting selection (real executable prices, fees included)
**No validated profitable selection rule exists in any sport.**

| Study | Best frozen rule | Result | Status |
|---|---|---|---|
| **MLB** (2026, bid/ask, no sizes) | R3: net edge ≥ 5¢ and \|model − mid\| ≤ 0.10 | EXPLORE +4.9% [−0.9, +11.5] (682 bets); CONFIRM **+12.2% [−1.9, +24.7]** (187 bets, win 0.642 vs break-even 0.572; calibrated inside the selection) | **Survived one forward split, not validated.** CIs include 0; 4 rules tested (Bonferroni p ≈ 0.11). Frozen as `mlb_r3_agreement_v1` for 2027. |
| R3 idea in other sports | — | NBA −1.9%; CFB model side loses even against mid; CBB forward −14% | **Not a general property**; MLB-specific or noise. |
| NBA props 2025-26 | R1 | −1.1% [−12%, +10%], 441 bets | no edge |
| NFL 2025 | R1 / R2 | +3.7% [−10, +17] / +5.0% [−9, +19] | not supported (CIs include 0; model Brier worse than mid) |
| CBB 2026-27 forward | R3 | C2 −14.3% [−23.6, −3.8]; incumbent −19.5% | **negative** |
| CFB weeks 6–12 (#99) | existing process | −5.1% [−18, +7]; all-family −13% to −15% | negative |

Consistent pattern: when the model disagrees strongly with the price, the price is right. Claimed win probability on chosen sides
was 0.51–0.70 against 0.31–0.56 realised. CLV is measured as market movement only (`sift-clv-canonical/1`); the ~1.7¢ fee and
half-spread are reported separately and never counted as CLV.

## 5. CFB
- **Home-effect fix** (#312): merged disabled, deterministic and reproduced. Margin RMSE 17.75 → 16.13 on 2026. It does not beat prices.
- **Settlement disagreements:** #99's 5 disagreements are one game, WKU at MTU on Nov 7. MTU scored a 0:00 fumble-return TD after the winning FG: ESPN 51–42, Kalshi settled every market on 45–42. P&L uses the official settlement; outcome models use the game result.
- **Superseded numbers labelled:** `research/cfb_bet_selection/REPORT_STATUS.md`.
- **Leakage check on studied columns:** the studies used builder base columns (`cfbx_mar_pre/tot_pre`), not certified catalog inputs. Those columns now pass a full point-in-time replay.
- **Remaining weakness:** totals. Projections are overdispersed, and the model–market disagreement on totals points the wrong way. The frozen shrink candidate addresses the first problem.

## 6. SIFT readiness
- **Integrated (research):**
  - the certified inputs (331);
  - the pipeline machinery: shared selection evaluator, adoption ladder, readiness ledger, operating-readiness dashboard panel;
  - every study above, with frozen protocols and independent recomputation.
- **Experimental (disabled or frozen):** CFB home effect, `cfb_total_shrink_v1`, `mlb_r3_agreement_v1`, CBB C2 margin model.
- **Production changes warranted:** none for betting. One candidate for an owner decision is the CBB margin model as a **shadow** projection. It is a small, real, forward-replicated accuracy gain, but has no price value.
- **Operating-model defects to fix** (reported, not changed):
  - MLB totals adapter off-by-one (fixed around 08-28);
  - MLB YRFI biased +9–13 pts and margins −6 pts;
  - MLB recommendation archive keeps only the post-first-pitch run.

## 7. Remaining blockers
1. **Kalshi depth/fill data.** NBA props and MLB have no sizes; NBA 2025-26 has hourly candles only. A prospective sized-quote collector needs owner authorization.
2. **Licensing.** 737 missing slots depend on UNRESOLVED_INTERNAL_ONLY sources (ESPN, MLB Stats API, NHL API). Owner or legal clearance is needed before any commercial use.
3. **NFL training-set manifest.** Its walk-forward diagnostic predates the NFL builder fix. A rebuild needs 1999–2009 play-by-play, which the vault pins but doesn't hold.
4. **Legacy inputs never blind-verified.** Legacy NFL inputs were certified by replay only. A blind brief for the 13 affected inputs is recommended.

## 8. Tomorrow's priorities
1. **CBB:** run the frozen C2 margin model as a disabled shadow projection in cbb-edge-finder, needs owner approval. Re-score it forward at season end with the same freeze.
2. **CFB:** score `cfb_total_shrink_v1` on week 13+ and bowls once final, outcomes plus price.
3. **NFL props:** a frozen experiment using the new batch-5 inputs for rushing, receiving and anytime-TD props against 2026 sized books (`market-data` branch).
4. **MLB:** fix the reported operating-model biases (YRFI, margins, recommendation archive timing), then run `mlb_r3_agreement_v1` forward in 2027.
5. **Data:** next class-B builders: CBB player box (14 slots) and MLB pitch/PA events; authorize a sized-quote capture for NBA/MLB.

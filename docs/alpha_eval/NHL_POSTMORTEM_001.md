# Alpha postmortem NHL-001: NHL frozen forecasts, all archived game-bound market families (`sift-alpha-eval/1`)

RESEARCH_ONLY. Read-only. No orders, no authority, no promotion, no production change. Aggregates only; no per-row data is committed.

**Reproduce** (local copies only; the run itself makes no network call):
1. Sparse, blobless checkout of `chmoses98/NHL-edge-finder@data-archive` @ `114470818f2c` (dirs: `predictions*`, `contracts`, `settlements`, `results`, `player_events/{goals,players,goalies}`, `context/schedule`, `kalshi/markets`, `kalshi/markets_delta`; about 450 MB, no full clone).
2. `git log --no-renames --format='C %H %cI %aI %s' --name-status origin/data-archive -- predictions predictions_v2 predictions_player predictions_oa > predlog.txt`.
3. `python3 -I scripts/fetch_nhl_api_outcomes.py --game-ids ids.txt --out <cache>`: official NHL public API (`api-web.nhle.com`, free, no key) boxscore + play-by-play for the 309 forecast games, fetched 2026-11-13 ~03:50Z (618 files, 0 failures).
4. `python -m alpha_eval nhl-archive --root <checkout> --api-cache <cache> --git-log predlog.txt --out-dir reports/alpha_eval/nhl`.

Input digests (sha256 roll-up of `relpath sha256` lines): predictions `69ed0bfb…`, predictions_v2 `20381f6a…`, predictions_player `e0abd2c2…`, predictions_oa `bdb7faba…`, contracts `f1435bba…`, settlements `e4f03398…`, results `0e3c47fc…`, player_events `d50a2b0d…`, kalshi/markets `7299114b…`, kalshi/markets_delta `c45a389b…`, NHL API cache `a72b8de5…`, git log `8869808f…`.

## 1. What was evaluated

| model (producer-declared sports-only) | what | markets |
|---|---|---|
| `DATA_ONLY_V1` (`nhl-sim-1.1`) | game simulator, "never sees a price" | moneyline, spread, total, team total |
| `DATA_ONLY_V2` (`nhl-sim-2.0`, shadow) | game + period simulator | the above + period winner / spread / total |
| `PLAYER_SIM_V1` (shadow) | joint player simulator | goals, assists, points, first goal, goalie saves |
| `OA_RIDGE_V1` arms `OA_SVA`, `OA_SVA_C1` (shadow) | opponent-adjusted game probabilities | moneyline; totals 5.5 / 6.5 |

Not evaluated: the `MARKET_ANCHORED_*` columns (market-informed by construction) and `p_overtime` (frozen, not yet mapped to `KXNHLOT`; counted below).

**Selection (prespecified, applied before looking at any outcome):** per (model, ticker) the **last attested pregame capture** is graded. The producer captures hourly; of 2.87 M capture rows (1.68 M with a null probability, i.e. unpriced by the producer) the 75,901 selected forecasts are graded and the rest are counted, not graded, because repeated captures of one market are not independent evidence. Consequence: nearly every graded forecast is a T-10 to T-60 minute capture, so these results describe the models near puck drop, not at T-6h or T-12h.

## 2. Freeze evidence (why these are PROSPECTIVE)

The NHL archive has no producer hash chain (the sealed ledger was retired 2026-10-22). Alpha therefore attests freezes from the **git commit chain** of `data-archive`:
* every one of the 3,471 forecast files was **added exactly once and never modified or deleted** (linear history, 5,519 commits);
* each file's adding commit names the same GitHub Actions run id as the file name;
* the adding commit is **before the official NHL start time** of the game. 2,766 of 1.19 M priced pregame capture rows fail that check (committed at or after start) and are never preferred; only 8 selected forecasts had no attested capture and are classed BACKTEST (none graded).

Like the NBA chain, the commit chain is tamper-evident but its clock is the producer's runner clock. **Independent clock check:** for 6 capture runs spread over the window (`36637445489`, `38648579687`, `40156398978`, `41022093907`, `41827955477`, `43351958977`) the GitHub API's own `created_at`/`updated_at` (GitHub's clock) brackets every commit time of that run. This is a sample, not a per-file proof.

## 3. Outcomes, independently verified

* **Source:** official NHL API, fetched by Alpha after the games, through Alpha's existing derivation (`research/outcome_intel/nhl_audit.derive_outcome`).
* **Identity (independent):** all 67,024 forecast tickers were checked against the official game record (ET date, away and home codes). Player tickers were **resolved independently** from the ticker (team code, sweater, surname) against the official box score; the producer's player id agreed in **50,234 / 50,234** resolvable cases. 1,649 player markets name a player absent from the box (no mismatch, unverifiable). **0 mismatches.**
* **Cross-check 1, same derivation on the producer's archived results / player events:** 63,763 agree, **40 disagree**.
* **Cross-check 2, the producer's separately implemented settle engine:** 63,548 agree, **36 disagree**, 243 unsettleable, 1,679 no row.
* **What the disagreements are:**
  * **39 shootout totals / team totals:** the producer counts the shootout goal, but Kalshi's rule text is silent on it. Alpha emits both outcomes, so the standard blocks them.
  * **41 player / period markets:** official stat corrections. Today's NHL API differs from what was archived right after the game, e.g. an assist removed, saves 24 vs 23.
  * All 80 conflicting markets (124 forecast rows) are **BLOCKED (`CONFLICTING_OUTCOME_ROWS_FOR_MARKET`)**, never resolved by choosing a side.
* **Not exchange settlement:** Kalshi's own `result` is not in the archive. 1,047 forecasts are on players who did not play: `void`.

## 4. Quotes

Replay of the archived board: 225 full checkpoints + 4,730 hash-chained deltas, **0 chain breaks, 0 count mismatches, 0 non-monotonic boards**.
* **Pricing a forecast:** the quote on the latest board at or before its freeze; the closing quote is the last pregame board.
* **Cross-check:** the quotes embedded in the producer's own forecast rows equal the replayed board at the same instant in **46,901 / 46,901** comparable rows.
* **Unusable quotes:** 12,218 forecast rows had a one-sided, crossed or inactive book at freeze (mostly thin player props). They are `PIT_QUOTE_ONE_SIDED_OR_CROSSED`, not dropped.

## 5. Coverage: every archived NHL board ticker in exactly one category

Universe: union of every ticker on any checkpoint or added by any delta. **77,572 tickers**:
* 74,327 in-window game-bound (game dates 2026-09-29 to the 2026-11-12 horizon, 307 games final in the official record);
* 1,331 for games not final at the horizon;
* 1,914 season-long (not game bound).

| family | in-window | graded | fc, not graded | game fc, mkt not fc | game not fc | frozen, not eval. | no frozen source |
|---|---:|---:|---:|---:|---:|---:|---:|
| game_winner | 614 | 614 | 0 | 0 | 0 | 0 | 0 |
| game_spread | 2,333 | 1,228 | 0 | 1,105 | 0 | 0 | 0 |
| game_total | 3,088 | 2,744 | 19 | 325 | 0 | 0 | 0 |
| team_total | 3,070 | 3,050 | 20 | 0 | 0 | 0 | 0 |
| period_winner | 2,763 | 2,763 | 0 | 0 | 0 | 0 | 0 |
| period_spread | 2,368 | 1,841 | 1 | 526 | 0 | 0 | 0 |
| period_total | 4,566 | 2,762 | 1 | 1,803 | 0 | 0 | 0 |
| player_goals | 18,372 | 16,955 | 453 | 666 | 298 | 0 | 0 |
| player_assists | 10,767 | 9,860 | 119 | 631 | 157 | 0 | 0 |
| player_points | 13,967 | 13,120 | 151 | 487 | 209 | 0 | 0 |
| first_goal | 11,113 | 10,040 | 355 | 553 | 165 | 0 | 0 |
| goalie_saves | 692 | 489 | 7 | 85 | 111 | 0 | 0 |
| game_overtime | 307 | 0 | 0 | 0 | 0 | 307 | 0 |
| game_early_goal | 307 | 0 | 0 | 0 | 0 | 0 | 307 |
| **all in-window** | **74,327** | **65,466 (88.1%)** | **1,126** | **6,181** | **940** | **307** | **307** |

**Complete eligible-market coverage: INCOMPLETE (88.1% graded).** The gaps, measured:
The 7,121 unforecast markets in evaluated families (6,181 in games the model forecast for that family, plus 940 in games where it did not) split into exactly two measured reasons:
* **4,925 never appear in any forecast file:** mostly alternate spread / total / period strikes (3,759) that Kalshi listed but the producer never captured as contracts.
* **2,196 were listed by the producer but never priced** (null probability: unsupported player or strike).
* **614 have no evaluated source:** overtime (frozen OA input, not mapped) and first-10-minute goal (none).
* **1,126 forecast but not graded:** the void / DNP and blocked-conflict cases above.

The earlier outcome-intelligence audit (`reports/outcome_intel/nba_nhl_SUMMARY.md`) counted 55,407 contracts from the producer's own listing; the board universe is larger and is the honest denominator.

## 6. Results (PROSPECTIVE; event-clustered 95% CIs; the primary grid is Holm-adjusted)

| model | graded | Brier | calib. slope | Δ Brier mkt−model (all fams) [95% CI] | hyp. ROI, full priced pop. [95% CI] | selection CLV |
|---|---:|---:|---:|---|---|---|
| DATA_ONLY_V1 | 7,636 | 0.1628 | 1.06 | −0.0055 [−0.0094, −0.0014] | −11.5% [−15.5%, −7.2%] | +0.00015 |
| DATA_ONLY_V2 | 15,002 | 0.1722 | 1.06 | −0.0053 [−0.0082, −0.0023] | −8.3% [−11.5%, −5.0%] | +0.00001 |
| OA_SVA | 565 | 0.2406 | 1.00 | −0.0091 [−0.0141, −0.0036] | −20.5% [−30.6%, −10.6%] | +0.00017 |
| OA_SVA_C1 | 565 | 0.2386 | 1.16 | −0.0071 [−0.0118, −0.0024] | −16.9% [−26.7%, −7.2%] | −0.00013 |
| PLAYER_SIM_V1 | 50,456 | 0.1093 | 0.99 | −0.0008 [−0.0013, −0.0004] | −5.9% [−7.1%, −4.8%] | +0.00084 |

**Primary grid (Holm across 11 cells, 307 games):**
* **MARKET_BETTER (p ≤ 0.05):**
  * V1 ladders (−0.0035)
  * V2 ladders (−0.0032)
  * V2 moneyline (−0.0116)
  * OA_SVA moneyline (−0.0128)
  * PLAYER_SIM_V1 player props (−0.0020)
* **Market better on the point estimate and CI, Holm p 0.05–0.09:**
  * V1 moneyline (p 0.092)
  * OA_SVA_C1 moneyline (p 0.051)
  * V2 period (p 0.052)
* **NOT_DISTINGUISHABLE:**
  * OA ladders (totals, 142 games)
  * PLAYER_SIM_V1 first goal (+0.0004 [−0.0001, +0.0011])
* **No cell shows the model better than the market.**

**Calibration:** all five models are roughly calibrated (slopes 0.99–1.16; signed bias −0.008 overall). This differs from NBA, where the models were miscalibrated. The NHL models are calibrated but less sharp than the market.

**Leads, not findings:**
* **goalie_saves:** Δ Brier +0.0009 [−0.0064, +0.0084] (not distinguishable). It has the largest selection CLV, +0.0070 [+0.0036, +0.0104] on 288 games, and is the only family whose hypothetical ROI interval includes zero (−0.7% [−9.4%, +7.9%]). The earlier audit also flagged goalie saves as PROMISING_INSUFFICIENT. That is two analyses of overlapping data, not replication.
* **Player assists / points:** selection CLV is +0.0013 / +0.0015 (prices moved toward the model after freeze), while their Brier is worse than the market's.

**Economics:** QUOTED_HYPOTHETICAL, top-of-book taker size 1:
* full population: −7.4% [−8.9%, −5.8%] on 62,006 priced rows;
* positive-edge subset (selection-biased): −8.5%;
* quoted-execution CLV: −0.011;
* **no verified fills: NO_PROFITABILITY_CLAIM.**

**Consistency:** the earlier, separately built incremental-information audit (train/holdout, calibrated mid) found no demonstrated improvement over the market for V1, PLAYER_SIM_V1 or OA. This run agrees. Agreement is evidence about the data, not a claim of edge.

## 7. Limits and defects

1. **Not exchange settlement.**
   * Outcomes are official NHL API data, re-fetched 2026-11-13 after the games. Post-game stat corrections therefore surface as conflicts (41 blocked).
   * Shootout handling for totals is unresolved (39 blocked).
   * Kalshi's `result` is unavailable.
2. **Freeze clock is the producer's runner clock.** It is verified for tamper-evidence by the commit chain, and against GitHub's clock only on a 6-run sample.
3. **Near-close horizon only.** Graded forecasts are the last pregame capture. Earlier horizons (T-6h, T-12h) are not graded here, so a model that is useful early but not late would be missed.
4. **Producer-declared independence.** `sports_only` is declared in producer docs, not verified by Alpha.
5. **Board universe is a union of snapshots.** A market listed and delisted between two boards is invisible.
6. **Correlation handling.** Ladder rungs, both moneyline sides and repeated models share games; inference collapses to one unit per event × model × family and clusters by game.
7. **Shared code.** The universe reconciliation reuses the NBA category names (`ADAPTER_FAMILY_GAME_HAS_NO_SHADOW_FORECAST`, …). Here "shadow" means "this adapter's forecast source". The only change to shared code is an optional `frozen_not_evaluated` argument; NBA behaviour is unchanged (tested).

## 8. Next

* Grade a fixed earlier horizon (T-6h) as a separate, pre-declared cell.
* Map `p_overtime` to `KXNHLOT`.
* Obtain Kalshi-official results to replace the shootout and stat-correction blocks with exchange truth.
* Keep accumulating goalie_saves prospectively as a pre-registered single cell before reading anything into it.

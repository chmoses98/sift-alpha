# Alpha postmortem NHL-001: NHL frozen forecasts, all archived game-bound market families (`sift-alpha-eval/1`)

RESEARCH_ONLY. Read-only. No orders, no authority, no promotion, no production change. Aggregates only; no per-row data is committed.

**Reproduce** (local copies only; the run itself makes no network call):
1. Sparse, blobless checkout of `chmoses98/NHL-edge-finder@data-archive` @ `114470818f2c` (dirs: `predictions*`, `contracts`, `settlements`, `results`, `player_events/{goals,players,goalies}`, `context/schedule`, `kalshi/markets`, `kalshi/markets_delta`; about 450 MB, no full clone).
2. `git log --no-renames --format='C %H %cI %aI %s' --name-status origin/data-archive -- predictions predictions_v2 predictions_player predictions_oa > predlog.txt`.
3. `python3 -I scripts/fetch_nhl_api_outcomes.py --game-ids ids.txt --out <cache>`: official NHL public API (`api-web.nhle.com`, free, no key) boxscore + play-by-play for the 309 forecast games (618 files, 0 failures). Revision 1 cache fetched 2026-11-13 ~05:25Z; revision 0 cache ~03:50Z.
4. `python -m alpha_eval nhl-archive --root <checkout> --api-cache <cache> --git-log predlog.txt --out-dir reports/alpha_eval/nhl`.

Input digests (`nba_nhl_common.file_digests` roll-up): predictions `69ed0bfb…`, predictions_v2 `20381f6a…`, predictions_player `e0abd2c2…`, predictions_oa `bdb7faba…`, contracts `f1435bba…`, settlements `e4f03398…`, results `0e3c47fc…`, player_events `d50a2b0d…`, kalshi/markets `7299114b…`, kalshi/markets_delta `c45a389b…`, git log `8869808f…` (all re-verified identical for revision 1); NHL API cache `f1d3db50…` (revision 1; revision 0 was `a72b8de5…`).

## Revision 1 (2026-11-13): baseline of record

All numbers in §§3–6 are **revision 1** and match `reports/alpha_eval/nhl/`. Revision 0 (PR head `ef6c90d`) is preserved in git history. Revision 1 differs from it for two separately measured reasons. Each reason was isolated by running the old and new code on the same inputs.

**(a) Defect fixed: player identity now fails closed.** When a player ticker did not resolve independently to an official box-score player, the adapter fell back to the producer's player id. If that player had played, the outcome was graded on the producer's identity alone, and the market was labelled `PLAYER_NOT_IN_OFFICIAL_BOX` ("no mismatch").
* **Measured:** 620 player markets. In every inspected case the ticker's sweater number differs from the official box: `NYRJMILLER8` against J. Miller #10, and `CBJMKNIES23` against M. Knies #89.
* **Fix:** these markets are now `MISMATCH_PLAYER_TICKER_NOT_RESOLVED`. Their outcome event id is stamped, so the standard blocks them (`OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST`). Regression test: `test_unresolved_ticker_with_producer_player_in_box_is_blocked`.
* **Effect, same cache:** 610 forecast-level accuracy grades become BLOCKED, all in PLAYER_SIM_V1 families. PLAYER_SIM_V1 cell verdicts and Holm p-values are unchanged. Revision 0's "0 identity mismatches" and "players resolved independently" claims were overstated for these 620 markets.

**(b) Outcome-cache vintage: one more game final.** The cache was re-fetched about 95 minutes later, and one 2026-11-12 game had become final. The horizon is still 2026-11-12. Effect, with the old code on the new cache:
* 307 → 308 games;
* +237 eligible markets;
* Holm p for OA_SVA_C1 moneyline 0.051 → 0.050 and for V2 period 0.052 → 0.036;
* `game_total` calibration reading UNDERCONFIDENT → ROUGHLY_CALIBRATED (slope near the 1.1 boundary).

The pinned producer archive predates this game's result, so its 180 markets have the official-API outcome only, with no producer cross-check (`ARCHIVE_NOT_DERIVABLE` / `SETTLE_ENGINE_NO_ROW` +180).

| headline | revision 0 | revision 1 |
|---|---:|---|
| games final / eligible markets | 307 / 74,327 | 308 / 74,564 |
| graded markets (coverage) | 65,466 (88.1%) | 65,037 (87.2%) |
| graded forecasts | 74,224 | 73,828 |
| Holm cells favouring the model | 0 / 11 | 0 / 11 |
| cell verdict labels | — | identical in all 11 cells |

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

Like the NBA chain, the commit chain is tamper-evident but its clock is the producer's runner clock. **Independent clock check:** for 6 capture runs spread over the window (`36637445489`, `38648579687`, `40156398978`, `41022093907`, `41827955477`, `43351958977`) the GitHub API's own `created_at`/`updated_at` (GitHub's clock) brackets every commit time of that run. This is a sample, not a per-file proof: the archive history names **371** capture runs, so **365 remain unchecked** against GitHub's clock. Checking them needs read access to the producer repository's Actions API, which the evaluation session did not have. No evidence is substituted.

## 3. Outcomes, independently verified

* **Source:** official NHL API, fetched by Alpha after the games, through Alpha's existing derivation (`research/outcome_intel/nhl_audit.derive_outcome`).
* **Identity (independent):** all 67,024 forecast tickers were checked against the official game record (ET date, away and home codes); 0 game-level mismatches. Player tickers are **resolved independently** from the ticker (team code, sweater, surname) against the official box score:
  * the producer's player id agrees in **50,234 / 50,234** resolvable cases;
  * **620** player markets do not resolve, although the producer's player played. They are blocked as `MISMATCH_PLAYER_TICKER_NOT_RESOLVED` (revision 1 fix); the sweater number differs in every inspected case;
  * 1,029 name a player absent from the box. These are `void` (unverifiable, never graded).
* **Cross-check 1, same derivation on the producer's archived results / player events:** 63,763 agree, **40 disagree**.
* **Cross-check 2, the producer's separately implemented settle engine:** 63,548 agree, **36 disagree**, 243 unsettleable, 1,859 no row. The 180-row increase from revision 0 is the newly final game, whose result is not in the pinned archive.
* **What the disagreements are:**
  * **39 shootout totals / team totals:** the producer counts the shootout goal, but Kalshi's rule text is silent on it. Alpha emits both outcomes, so the standard blocks them.
  * **41 player / period markets:** official stat corrections. Today's NHL API differs from what was archived right after the game, e.g. an assist removed, saves 24 vs 23.
  * All 80 conflicting markets (124 forecast rows) are **BLOCKED (`CONFLICTING_OUTCOME_ROWS_FOR_MARKET`)**, never resolved by choosing a side.
* **Not exchange settlement:** Kalshi's own `result` is not in the archive. 1,085 forecasts are on players who did not play: `void`.

## 4. Quotes

Replay of the archived board: 225 full checkpoints + 4,730 hash-chained deltas, **0 chain breaks, 0 count mismatches, 0 non-monotonic boards**.
* **Pricing a forecast:** the quote on the latest board at or before its freeze; the closing quote is the last pregame board.
* **Cross-check:** the quotes embedded in the producer's own forecast rows equal the replayed board at the same instant in **46,901 / 46,901** comparable rows.
* **Unusable quotes:** 12,069 forecast rows had a one-sided, crossed or inactive book at freeze (mostly thin player props). They are `PIT_QUOTE_ONE_SIDED_OR_CROSSED`, not dropped.

## 5. Coverage: every archived NHL board ticker in exactly one category

Universe: union of every ticker on any checkpoint or added by any delta. **77,572 tickers**:
* 74,564 in-window game-bound (game dates 2026-09-29 to the 2026-11-12 horizon, 308 games final in the official record);
* 1,094 for games not final at the horizon;
* 1,914 season-long (not game bound).

| family | in-window | graded | fc, not graded | game fc, mkt not fc | game not fc | frozen, not eval. | no frozen source |
|---|---:|---:|---:|---:|---:|---:|---:|
| game_winner | 616 | 616 | 0 | 0 | 0 | 0 | 0 |
| game_spread | 2,339 | 1,232 | 0 | 1,107 | 0 | 0 | 0 |
| game_total | 3,097 | 2,753 | 19 | 325 | 0 | 0 | 0 |
| team_total | 3,080 | 3,060 | 20 | 0 | 0 | 0 | 0 |
| period_winner | 2,772 | 2,772 | 0 | 0 | 0 | 0 | 0 |
| period_spread | 2,374 | 1,847 | 1 | 526 | 0 | 0 | 0 |
| period_total | 4,580 | 2,771 | 1 | 1,808 | 0 | 0 | 0 |
| player_goals | 18,440 | 16,791 | 679 | 672 | 298 | 0 | 0 |
| player_assists | 10,797 | 9,783 | 226 | 631 | 157 | 0 | 0 |
| player_points | 14,008 | 13,011 | 301 | 487 | 209 | 0 | 0 |
| first_goal | 11,151 | 9,910 | 519 | 557 | 165 | 0 | 0 |
| goalie_saves | 694 | 491 | 7 | 85 | 111 | 0 | 0 |
| game_overtime | 308 | 0 | 0 | 0 | 0 | 308 | 0 |
| game_early_goal | 308 | 0 | 0 | 0 | 0 | 0 | 308 |
| **all in-window** | **74,564** | **65,037 (87.2%)** | **1,773** | **6,198** | **940** | **308** | **308** |

**Complete eligible-market coverage: INCOMPLETE (87.2% graded).** The gaps, measured:
The 7,138 unforecast markets in evaluated families (6,198 in games the model forecast for that family, plus 940 in games where it did not) split into exactly two measured reasons:
* **4,935 never appear in any forecast file:** mostly alternate spread / total / period strikes (3,766) that Kalshi listed but the producer never captured as contracts.
* **2,203 were listed by the producer but never priced** (null probability: unsupported player or strike).
* **616 have no evaluated source:** overtime (frozen OA input, not mapped) and first-10-minute goal (none).
* **1,773 forecast but not graded:** the void / DNP cases, the blocked conflicts, and the 620 identity-unresolved player markets above.
* **Unsupported market families** (no evaluated source): `game_overtime` (frozen `p_overtime`, not mapped to `KXNHLOT`) and `game_early_goal` (no producer source). Season-long futures (1,914 tickers) are outside the game-bound standard.

The earlier outcome-intelligence audit (`reports/outcome_intel/nba_nhl_SUMMARY.md`) counted 55,407 contracts from the producer's own listing; the board universe is larger and is the honest denominator.

## 6. Results (PROSPECTIVE; event-clustered 95% CIs; the primary grid is Holm-adjusted)

| model | graded | Brier | calib. slope | Δ Brier mkt−model (all fams) [95% CI] | hyp. ROI, full priced pop. [95% CI] | selection CLV |
|---|---:|---:|---:|---|---|---|
| DATA_ONLY_V1 | 7,661 | 0.1631 | 1.05 | −0.0056 [−0.0097, −0.0018] | −11.5% [−15.6%, −7.2%] | +0.00015 |
| DATA_ONLY_V2 | 15,051 | 0.1725 | 1.05 | −0.0054 [−0.0082, −0.0023] | −8.4% [−11.6%, −5.1%] | +0.00002 |
| OA_SVA | 569 | 0.2408 | 0.99 | −0.0094 [−0.0147, −0.0037] | −21.1% [−30.7%, −10.7%] | +0.00019 |
| OA_SVA_C1 | 569 | 0.2388 | 1.15 | −0.0074 [−0.0124, −0.0021] | −17.5% [−27.5%, −7.6%] | −0.00012 |
| PLAYER_SIM_V1 | 49,978 | 0.1093 | 0.99 | −0.0009 [−0.0013, −0.0004] | −6.0% [−7.2%, −4.9%] | +0.00083 |

**Primary grid (Holm across 11 cells, 308 games):**
* **MARKET_BETTER (Holm p ≤ 0.05):**
  * V1 ladders (−0.0035)
  * V2 ladders (−0.0032)
  * V2 moneyline (−0.0118)
  * OA_SVA moneyline (−0.0133)
  * OA_SVA_C1 moneyline (−0.0117, p 0.04998, borderline; 0.051 in revision 0)
  * V2 period (−0.0010, p 0.036; 0.052 in revision 0)
  * PLAYER_SIM_V1 player props (−0.0021)
* **Market better on the point estimate and CI, Holm p 0.05–0.09:**
  * V1 moneyline (p 0.082)
* **NOT_DISTINGUISHABLE:**
  * OA ladders (totals, 143 games)
  * PLAYER_SIM_V1 first goal (+0.0005 [−0.0001, +0.0011])
* The two cells that moved below 0.05 did so because of the one additional final game (§ Revision 1 (b)), not the identity fix. Read them as borderline.
* **No cell shows the model better than the market.**

**Calibration:** all five models are roughly calibrated (slopes 0.99–1.15; signed bias −0.008 overall). This differs from NBA, where the models were miscalibrated. The NHL models are calibrated but less sharp than the market.

**Leads, not findings:**
* **goalie_saves:** Δ Brier +0.0008 [−0.0069, +0.0079] (not distinguishable). It has the largest selection CLV, +0.0070 [+0.0037, +0.0103] on 289 games, and is the only family whose hypothetical ROI interval includes zero (−0.6% [−9.5%, +7.7%]). The earlier audit also flagged goalie saves as PROMISING_INSUFFICIENT. That is two analyses of overlapping data, not replication.
* **Player assists / points:** selection CLV is +0.0013 / +0.0014 (prices moved toward the model after freeze), while their Brier is worse than the market's.

**Economics:** QUOTED_HYPOTHETICAL, top-of-book taker size 1:
* full population: −7.5% [−9.0%, −6.0%] on 61,761 priced rows;
* positive-edge subset (selection-biased): −8.8%;
* quoted-execution CLV: −0.011;
* **no verified fills: NO_PROFITABILITY_CLAIM.**

**Measures kept apart:** predictive accuracy (Brier, log loss vs outcomes), calibration (slope, reliability buckets), model versus market (paired Δ Brier on identical outcomes, Holm-adjusted), hypothetical economics (quoted, taker, size 1; never a profitability claim), and CLV (selection and quoted-execution, signed; no actual-fill CLV because there are 0 verified fills) are reported as separate sections. No measure is used as a proxy for another.

**Consistency:** the earlier, separately built incremental-information audit (train/holdout, calibrated mid) found no demonstrated improvement over the market for V1, PLAYER_SIM_V1 or OA. This run agrees. Agreement is evidence about the data, not a claim of edge.

## 7. Limits and defects

1. **Not exchange settlement.**
   * Outcomes are official NHL API data, re-fetched 2026-11-13 after the games. Post-game stat corrections therefore surface as conflicts (41 blocked).
   * Shootout handling for totals is unresolved (39 blocked).
   * Kalshi's `result` is unavailable.
2. **Freeze clock is the producer's runner clock.** It is verified for tamper-evidence by the commit chain, and against GitHub's clock only on a 6-run sample; 365 of 371 capture runs are unchecked (§2).
3. **Near-close horizon only.** Graded forecasts are the last pregame capture. Earlier horizons (T-6h, T-12h) are not graded here, so a model that is useful early but not late would be missed.
4. **Producer-declared independence.** `sports_only` is declared in producer docs, not verified by Alpha.
5. **Board universe is a union of snapshots.** A market listed and delisted between two boards is invisible.
6. **Correlation handling.** Ladder rungs, both moneyline sides and repeated models share games; inference collapses to one unit per event × model × family and clusters by game.
7. **Player identity is ticker-based.** 620 markets whose ticker sweater number disagrees with the official box are blocked rather than graded (revision 1). The producer's own match is not accepted as independent evidence.
8. **Outcome-cache vintage.** One game's result postdates the pinned producer archive and has no producer cross-check. The baseline should be refreshed only by re-pinning the archive and cache together.
9. **Kalshi data rights unresolved.** Quotes come from an archived Kalshi board. Whether this evaluation, its storage, and public aggregate reports are permitted under Kalshi's Developer Agreement and Data Terms is an open question. No authorization is claimed; future commercial use is not assumed. See the adoption tracker.
10. **Shared code.** The universe reconciliation reuses the NBA category names (`ADAPTER_FAMILY_GAME_HAS_NO_SHADOW_FORECAST`, …). Here "shadow" means "this adapter's forecast source". The only change to shared code is an optional `frozen_not_evaluated` argument; NBA behaviour is unchanged (tested).

## 8. Next

* Grade a fixed earlier horizon (T-6h) as a separate, pre-declared cell. The archive supports it (hourly captures), but it is roadmap work after the Kalshi data-rights question, not part of this baseline.
* Map `p_overtime` to `KXNHLOT`.
* Obtain Kalshi-official results to replace the shootout and stat-correction blocks with exchange truth.
* Keep accumulating goalie_saves prospectively as a pre-registered single cell before reading anything into it.

## Addendum: second outcome source (reconciliation of PRs #66 and #68)

PR #68 graded the same archive against **Kalshi's own settlement** instead of the official NHL API. On the reconciled branch this adapter
is unchanged and the settlement is added as a second outcome source by `alpha_eval/nhl_kalshi_settlement.py`
(`python -m alpha_eval nhl-archive ... --kalshi-dir <pages from scripts/alpha_eval/fetch_kalshi_settled.py>`). Each market's official-API
outcome is compared with Kalshi's result; an agreeing settlement row collapses, a disagreeing one (value, void-vs-final or event identity)
is a conflicting outcome row and the standard blocks the market. A market is never graded on the settlement alone. #68's postmortem is kept
as `NHL_POSTMORTEM_002_KALSHI_SETTLEMENTS.md` and its report under `reports/alpha_eval/nhl/kalshi_settlement_pr68/`.

Status of the direct cross-check: implemented and unit-tested on synthetic fixtures; **not yet run on real data**, because neither raw
input is committed (the API cache and the settled pages both live outside the repository) and no new collection was made for the
reconciliation. What the two committed reports already show against the one artefact they share, the producer's settle engine:

| compared with the producer settle engine | agree | disagree | note |
|---|---:|---:|---|
| official NHL API derivation (this postmortem, as of 2026-11-13T05:32Z) | 63,548 | 36 | plus 39 shootout-ambiguous markets blocked |
| Kalshi settlement (#68, as of 2026-11-13T04:23Z) | 64,930 | 44 | 28 goalie saves, 16 assist/point credits; plus 4 Kalshi `scalar` vs producer NO |

Both sources disagree with the producer on a few dozen player-stat markets, consistent with official stat revisions; whether they agree with
each other on those markets is exactly what the per-market cross-check will report on its first real run.

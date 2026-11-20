# MLB operating model: when is SIFT right? (RESEARCH_ONLY)

No bets were placed, no pushes, no PRs. The source repos were only read.
How to run: `python run.py build` (reads no outcomes), then `python run.py evaluate` (checks `protocol.sha256` and
`protocol_amendments.sha256` before it reads any settlement).
Files: `protocol.json` (frozen, sha256 52dbb34e...), `protocol_amendments.json` (A1), `report.json` (all numbers), `coverage.json`,
`selection.py` (a copy of the sift-alpha-ops evaluator, with `fee_order` reimplemented to give identical results).

## Data used (edge-finder-api working tree, read-only)
- Model P(YES) with timestamps. Four sources:
  1. `data/edgelab/snapshots/*/pre_game_decision/*/frozen/recommendation_output.json.gz`: pipeline ledger `modelProb`, 285 intraday runs, timed by the manifest `capturedAt`.
  2. `data/pipeline/<date>/recommendations.json`: the final daily ledger, timed by `meta.createdAt`.
  3. `data/edgelab/model_evaluations` rows from `pipeline_recommendations` and `prospective_snapshot`, timed by `provenance.capturedAt`.
  4. `data/kalshi/discovery/<date>.json`: the repo adapter's fair probability for every supported rung, timed by `generatedAt`. Only the last run per date survives.
  - The `kalshi_discovery_extension` and `market_universe_extension` rows in model_evaluations are not timed by their own field, because their `provenance.capturedAt` is a quote time, not the time the model ran.
  - `projections.json` holds only run projections, not per-contract probabilities. It was inspected but not used.
- Quotes: `data/edgelab/observations` (232k in-scope rows) plus 26k extra quotes from raw `data/kalshi_registry_snapshots/*.json`.
  `clv_quotes` and the snapshot `market_observations` are subsets of these and added nothing.
  **No displayed sizes exist anywhere.** All P&L assumes a fill at top-of-book bid/ask with unknown depth.
- Schedule: the earliest of three starts: `data/edgelab/games` `scheduledStartTime` (713 games), the Kalshi ticker ET time (137), and the observation `scheduledStart` (2).
  Taking the earliest is conservative: it guards against postponed games and TBD postseason times. 14 games disagree by more than 2 minutes.
- Truth: Kalshi official results (vault `archives/MLB/kalshi_official_settlements/all-to-20261116`, restored to `settle_raw/`).
  11,584 of 11,593 contracts are settled yes/no. The repo's own `data/edgelab/settlements` covers 10,565 of them and **disagrees on 278**: game_total 105, F5_margin 87, F5_total 83 (for example, it marks over 2.5 runs as NO).
  The official results were used.
- R0: `data/edgelab/recommendations` (source pipeline_recommendations, status RECOMMENDED / BET_PLACED / RECOMMENDED_NOT_BET; 660 rows).
- Real wagers were found but not scored, as they are out of protocol scope: bets.json has 59 in the window, and data/research/wagers.jsonl has 6,498 mixed ledger rows.

## Point-in-time construction
- Entry quote: the latest two-sided quote with 0 < bid < ask < 1, taken at least 10 minutes before first pitch. Post-start rows are excluded.
- Model value: the latest model value at or before the entry quote.
- Close: the last two-sided quote strictly before first pitch. It counts for CLV only if it came after the entry quote; otherwise CLV is missing, not zero.
- Assertions in `build` check every one of these rules.
- Families: F5_result, F5_total, F5_margin, game_total, team_total, game_result, RFI (YES = YRFI, NO = NRFI).
  winning_margin and pitcher strikeouts (105 EXPLORE games) are scored in a separate block. Pitcher outs failed the coverage rule.
- Coverage after settlement:
  - EXPLORE (to 09-14): 7,096 core contracts, 373 games.
  - CONFIRM (09-15 to 10-28): 1,666 core contracts, 147 games.
- Median gaps: entry quote to first pitch 43 minutes; model to quote 42 minutes.
- 39.5k quoted tickers were dropped for having no model value at or before the entry quote (17.9k had no model value at all).

## Amendment A1 (recorded separately; the original protocol is kept)
- Observation prices switch from cents to dollars partway through 2026-09-10. The first evaluate run divided every row by 100, which made the CONFIRM mid Brier score 0.47.
- Fix: the unit is now decided per ingest run. No rule, threshold or split changed.
- When this was found, no R0–R3 or reliability-map result had been computed.
- Also corrected: the last price bucket was not treated as closed at 0.95 as the protocol says. This affected labels only; no candidate either way.

## Diagnostics (all quoted core contracts; model vs mid)
| split | n | Brier model / mid | log loss model / mid | calib. slope model / mid | joint b_model (se) / b_mid |
|---|---|---|---|---|---|
| EXPLORE | 7,096 | 0.209 / 0.193 | 0.619 / 0.566 | 0.65 / 1.05 | 0.07 (0.04) / 0.96 |
| CONFIRM | 1,666 | 0.231 / 0.224 | 0.659 / 0.637 | 0.57 / 0.89 | 0.18 (0.11) / 0.64 |

- The mid beats the model on Brier and log loss in every family, in both splits.
- The model is overconfident (slope about 0.6).
- Given the mid, it adds little or no information.
- The pipeline-ledger model (the incumbent's own probabilities) is the weakest source, with an EXPLORE calibration slope of 0.11.
- Systematic biases visible without any outcomes (mean of model minus mid):
  - Totals adapter, before about 2026-08-28 to 09-01: −0.10 to −0.19 on game/F5 totals. This matches the off-by-one documented in `docs/EDGELAB_KALSHI_TOTAL_LADDER_SEMANTICS.md`.
  - Winning margin and F5 margin: about −0.06.
  - YRFI: about +0.09 to +0.13.
  - Pitcher props: about −0.10.
  - So EXPLORE and CONFIRM partly measure different model versions.

## Pre-declared rules
All values are net of the unrounded fee. ROI is a game-clustered bootstrap with 95% CI (2,000 resamples, seed 7).

| rule | split | bets / games | win rate (Wilson) | break-even | model E[win] | ROI [95% CI] |
|---|---|---|---|---|---|---|
| R0 incumbent | EXPLORE | 304 / 163 | 0.480 [0.425, 0.536] | 0.501 | 0.556 | −4.2% [−16.0, +6.9] |
| R0 incumbent | CONFIRM | 48 / 32 | 0.583 [0.443, 0.712] | 0.530 | 0.614 | +10.1% [−19.0, +38.5] |
| R1 edge≥5c | EXPLORE | 1461 / 365 | 0.558 [0.532, 0.583] | 0.567 | 0.704 | −1.7% [−7.1, +3.7] |
| R1 | CONFIRM | 483 / 144 | 0.571 [0.527, 0.615] | 0.557 | 0.669 | +2.6% [−7.7, +12.8] |
| R2 price 0.30–0.70 | EXPLORE | 1383 / 365 | 0.530 | 0.544 | 0.681 | −2.5% [−8.3, +3.3] |
| R2 | CONFIRM | 468 / 144 | 0.562 | 0.540 | 0.651 | +4.2% [−6.2, +14.5] |
| R3 abs(model−mid)≤0.10 | EXPLORE | 682 / 268 | 0.546 [0.508, 0.583] | 0.520 | 0.587 | +4.9% [−0.9, +11.5] |
| R3 | CONFIRM | 187 / 108 | 0.642 [0.571, 0.707] | 0.572 | 0.638 | +12.2% [−1.9, +24.7] |

- Regular season only, CONFIRM: R1 +0.6%, R2 +2.4%, R3 +13.8% [−1.3, +27.9] (152 bets), R0 +19.0% [−9.6, +46.8] (40 bets).
- R0 drops 267 of 660 archived recommendations because the archive holds only the day's last pipeline run, which often came after first pitch.
- Supplementary R0b scores every intraday "Accepted" ledger decision instead: EXPLORE −3.5% (745 bets), CONFIRM +2.3% (225 bets). Both CIs span 0.
- R0 at its own archived price (sensitivity): −4.4% and +11.6%.
- The rounded 1-contract fee changes P&L by about 0.1–0.4 contracts per 100 bets.
- **CLV is essentially unmeasurable.** Only about 2.5% of contracts have a quote between entry and first pitch, so selection CLV has n = 9 to 45 per rule, with means from +0.001 to +0.007. R0 has more (n = 186, mean −0.002), because its quote is taken at the recommendation time. The entry fee (about 1.6c) is reported separately and is not counted as CLV.
- **R3 filter on R0:**
  - R3 would have avoided 263 of 352 R0 bets: 162 for disagreement > 0.10 and 119 for net edge < 0.05.
  - The avoided bets returned −3.0% [−14.8, +8.5]; the kept bets returned +0.5% [−20.4, +20.5].
  - In CONFIRM the avoided bets did better (+11.5%, n = 37). There is no reliable benefit either way.
- Other block (winning margin and strikeouts): R1–R3 are near zero in EXPLORE; R3 CONFIRM is −15.3% on 29 bets.

## Reliability map (EXPLORE; family × price bucket × side; 43 cells)
- **No cell met the pre-declared candidate rule** (n ≥ 60, win rate − break-even ≥ +0.04, and model within 0.05 of the observed rate). So nothing was scored on CONFIRM.
- The largest excesses were:
  - game_result favorites at [0.5, 0.75): NO +0.038 and YES +0.028. The model was not calibrated there (0.55 against an observed 0.63).
  - RFI YES at [0.25, 0.5): +0.025. The model was off by 0.08.
- Most cells sit 0.01–0.09 below break-even. All cells are listed in `report.json` under reliability_map.cells.

## Honest reading
- No subset has been validated. R3 (model and market agree, net edge ≥ 5c) is the only pre-declared rule that was positive in both splits:
  - EXPLORE +4.9%, CONFIRM +12.2%.
  - Both CIs include 0. The CONFIRM sample is 187 bets across 108 games, several bets per game, in correlated families.
  - Its CONFIRM win rate (0.642) matches the model's expectation (0.638), which is consistent with "reliable when it agrees with the market".
  - This is survived one forward split, not validated. A further untouched forward sample is required.
- The incumbent's actual recommendations (R0/R0b) show no edge over break-even, and the model is generally worse than the mid.

## Limitations
- No order-book depth.
- Quotes are sparse (about 3 snapshots per ticker), so the entry quote is a median of 43 minutes before first pitch.
- Most probabilities come from the discovery adapter, which has only one surviving run per date and so covers mostly late games. The pipeline ledger covers 9 market types (RL excluded because its side orientation is ambiguous).
- The model changed during the sample: the totals off-by-one fix.
- CONFIRM coverage for F5_margin, F5_total and winning_margin is thin (about 19 games).
- The postseason is small (32 R1 games).
- Repo settlements are unreliable for totals.
- The bootstrap clusters by game but not by date.

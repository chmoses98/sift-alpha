# Alpha postmortem 001: NBA PURE shadow store (first real `sift-alpha-eval/1` run)

RESEARCH_ONLY. Read-only. No orders, no authority, no promotion, no production change. Aggregates only; no per-row data is committed.

**Reproduce** (local checkout of the store, no network): `python -m alpha_eval nba-shadow --root <checkout of nba-edge-finder@nba-shadow-pure> --out-dir reports/alpha_eval/nba`
Source: `chmoses98/nba-edge-finder`, branch `nba-shadow-pure`, commit `465d3c76…` (2026-11-12T06:51Z). Outputs: `reports/alpha_eval/nba/nba_shadow_cumulative.{md,json}`. Code: `alpha_eval/nba_shadow.py` (adapter), existing grader/report.

## 1. Freeze evidence (what is and is not attested)
* The store's append-only hash chain was recomputed here: **918 / 918 links verified, 0 failures, 0 unchained files** (link = sha256(prev|path|sha256) and every file's bytes re-hashed).
* Every projection file's `written_at_utc` is ≤ the game's kickoff, and every row's `source_max_observed_at` ≤ `as_of` < `kickoff`. One `model_frozen_hash` per model version (no silent model drift). All lineage is `sports_only`; no market inputs declared. Hence all 81,350 projection rows are classed **PROSPECTIVE** (live capture + chain-verified + archived before kickoff).
* Limits: the chain proves the archive was not altered after `written_at_utc`, but `written_at_utc` is the producer's own clock (no external timestamping). 2 model versions only: `sim-rotation-pure` and the `EWM5` statistical baseline.

## 2. Coverage accounting (three separate denominators; nothing silently excluded)
| layer | count |
|---|---|
| Projection rows (conditional on playing), 2 arms | 81,350 (40,675 per arm), 29 dates, 2026-10-12 to 11-12 |
| → Alpha forecast rows | 520,640 = 81,350 CONTINUOUS (mean) + 439,290 BINARY ladder rungs |
| of the rungs: matched to an archived Kalshi listing (**priced**) | 45,298 |
| of the rungs: no archived listing at that `as_of` (accuracy only) | 393,992 |
| **Eligible-market universe** = distinct archived Kalshi listing tickers (4 player-prop series: PTS, REB, AST, 3PT) | **18,519** |
| eligible, forecast **and** graded | 16,537 (89.3%) |
| eligible, forecast but not graded (void / no outcome / overdue) | 779 |
| eligible, **never forecast** | 1,203 (6.5%): 1,116 no projection for that player-game-stat; 87 rung not on the forecast grid or not listed at the `as_of` |

**Complete eligible-market coverage: INCOMPLETE (93.5% forecast, 89.3% graded).** Forecast-only coverage would have read ~100% of 520,640 rows and hidden the 1,203 unforecast markets.

**Not established:** coverage of *all* Kalshi NBA markets (moneyline, spread, total, other props, futures). The eligible universe here is limited to the four player-prop series the shadow store lists. The wider `data-archive` catalog was not ingested in this run; the store's `listings_status` board counts are a sum over repeated snapshots (653,739), not a distinct-market denominator, and are not used. 443 listing rows had no resolved player identity.

Outcome accounting for the 520,640 forecast rows (accuracy): GRADED 324,992; BLOCKED void/DNP 42,432 (conditional-on-playing forecasts; Kalshi voids DNP); BLOCKED `NO_OUTCOME_ROW_EVENT_OVERDUE` 142,912; PENDING (games inside 24h of the data horizon) 10,304. The overdue rows are projected players **absent from the box score** of games with otherwise complete outcomes (1,626 of 5,850 player-games; mean participation probability 0.44 vs 0.73 for present players). They are not scored; if they are really non-appearances this is consistent with the conditional forecasts, but that is **not verified** (see §5).

## 3. Results (PROSPECTIVE class; descriptive, event-clustered 95% CIs)
**Accuracy** (324,992 graded across 197 games). Binary rung Brier 0.0917; **calibration slope 0.83, OVERCONFIDENT** (forecast exceeds observed by +0.02 to +0.08 across the 0.1-1.0 buckets; 0.0-0.1 bucket is well calibrated). Mean-forecast MAE: points 5.24 (bias +1.18), rebounds 2.08 (+0.38), assists 1.47 (+0.21), threes 0.96 (+0.11), minutes 6.25 (+1.27); positive bias = over-forecast, so the model over-forecasts every stat. By arm (binary Brier, same outcomes): EWM5 0.0881 vs sim-rotation 0.0953 (descriptive, not a formal paired arm test).

**Model vs market** (priced, point-in-time quote ≤ `as_of`, raw mid, not de-vigged): 37,764 paired rows (18,882 per arm) over 14,296 distinct tickers, two forecast slots (morning, pretip), 103 games, all regular season. Brier Δ (market − model; positive favours model): EWM5 +0.0037 [−0.0013, +0.0091]; sim-rotation −0.0055 [−0.0116, +0.0009]; Holm p 0.18 for both. **Verdict: NOT_DISTINGUISHABLE from the market for both.** Per series the sign is mixed (points −0.0059, 3PT −0.0046, assists +0.0027, rebounds +0.0005; pooled arms, all CIs include 0).

**Hypothetical economics** (QUOTED_HYPOTHETICAL: top-of-book taker, size 1, fee estimated): model-side ROI on the full priced population **−9.3% [−10.7%, −7.8%]**; positive-edge subset −7.5% [−10.0%, −4.9%] (selection-biased). **No verified fills exist → NO_PROFITABILITY_CLAIM.** Quoted-execution CLV −0.036.

**Selection CLV** +0.0056 [+0.003, +0.008] is computed on only **18 events** (the listing archive rarely holds a distinct pre-start close), below the standard's 30-cluster floor. Not a finding.

## 4. Reading
Alpha's NBA player-stat forecasts are usable accuracy evidence and are **not** shown to beat Kalshi prices; the data are consistent with no edge and with systematic over-forecasting that costs ~9% hypothetically at the ask. The calibration finding (over-forecasting every stat, overconfident mid-range) is the actionable one, and it is about the model, not about the market. No promotion, sizing or execution inference follows.

## 5. Defects and caveats found while running it
1. **Shared taxonomy substring bug** (`alpha_engine/taxonomy.py`, `season_award` regex contains unanchored `hart`): the ticker `…NYKJHART3…` (Josh Hart) classified as a *season award future*. 478 rows were mis-routed into a spurious FUTURE cell until `alpha_eval.families` was changed to trust a declared `native_family`. The shared engine file was **not** modified; the defect should be fixed or anchored there under review.
2. Missing outcomes for finished events were reported PENDING; the standard now distinguishes `NO_OUTCOME_ROW_EVENT_OVERDUE` when a data horizon is supplied.
3. Outcome event-identity checks and conflict detection ran but could not fire: the adapter builds outcome rows from the same `(game, player, stat)` key, so mismatches are impossible by construction here. This run validates join *coverage*, not independent identity.
4. Outcomes are the ESPN-derived sports source; **Kalshi settlements were not cross-checked** against them. Quotes are archived listing snapshots (median age 12.5 min, max 54 min before `as_of`), not a continuous tape; only top-of-book, no depth.
5. Repeated grading of the same ticker (2 slots × 2 arms) is handled by game-level clustering and the collapse step for CIs, but point estimates weight repeats equally.
6. 103 priced games (2026-10-20 to 11-11). Enough for the 30-cluster floor, far from enough to resolve a ±0.005 Brier difference.

## 6. Next (needs no new infrastructure)
Ingest the `data-archive` catalog for a universe covering **all** NBA Kalshi markets; cross-check ESPN outcomes against Kalshi settlements; investigate the over-forecast bias in `sim_rotation` and EWM5 (minutes bias +1.27 is the likeliest driver); resolve the absent-from-box player-games.

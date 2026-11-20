# SIFT CBB forward test: frozen C2 vs incumbent pure-0.2.0 on 2026-27 games (RESEARCH_ONLY)

This is a forward test only. No orders were placed and nothing was pushed. All entries are hypothetical taker fills at the archived ask.

## Files
- `protocol.json` was frozen before any 2026-27 outcome was joined. Its sha256 is in `protocol.sha256` (76874f70…).
  `run.py --stage score` refuses to run if the hash does not match. There were no amendments.
- `run.py` stages: `extract` (Kalshi snapshots → `out/quotes.parquet`), `build` (mapping, quotes, projections, features;
  reads no outcomes), `score` (settlements, ESPN finals, evaluation).
- `report.json` holds every number. `out/` holds the intermediate tables (contracts, games, selections).
- `sift/` holds unmodified copies of sift-alpha-ops `selection.py` and `canonical.py`. `cbb_code/` is a copy of the
  cbb-edge-finder code at 5ba7daa, used for the Kalshi mapping and contract semantics.

## Inputs
- **Candidate C2.** Coefficients and sigma = 11.2856 come from `cbb_pred/report.json`. They were fit on 2016-22, and the
  sigma is the validation 2023-24 residual SD. Nothing was refit.
- **Incumbent.** Archived prospective pure-0.2.0 records (`projections-archive` @1929f14) using `projection.margin` and
  `margin_sd`.
  - The record used is the latest one with as_of ≤ the game's Kalshi entry snapshot. The median as_of is 3.6 h before tip.
  - Orientation was checked against ESPN: 512 records match, 5 neutral-site records were flipped.
  - **The walk-forward reproduction was not possible.** `run_wave2.py` hard-codes seasons ≤ 2026 and needs stats.ncaa.org
    files that do not exist for 2027, so no agreement check was run.
- **Certified features.** `alpha_engine.derived.basketball.build` was rerun unmodified on the vault ESPN snapshot-20261116.
  Its season-2027 rows are identical to the previous study's parquet.
- **Quotes.** `kalshi-archive` @ecb674d (836 November snapshots, gaps up to about 9 h).
  - Families: KXNCAAMBGAME (winner) and KXNCAAMBSPREAD (rungs "X wins by over k").
  - Entry is the last snapshot whose `captured_at` (UTC) is ≤ ESPN listed tip − 30 min. It is asserted to precede tip for
    every contract. Entry was 31-232 min before tip, median 61 min.
  - Only active, two-sided quotes were used. Size is the top-of-book `yes_*_size_fp`.
- **Settlement.** Kalshi official results come from the vault `kalshi_official_settlements` snapshot-20261116. They cover all
  7,055 contracts, so the kalshi-archive fallback was not needed; it agrees on 7,055 of 7,055.
  Ticker semantics (incumbent `parse_contract`/`settle` vs ESPN finals) agree on 7,055 of 7,055.

## Coverage
- Window: games listed on ET dates 2026-11-03 to 2026-11-15 (13 dates). That is the last date in the vault ESPN snapshot,
  the only source of certified 2026-27 features. **Games after 11-15 are out of scope** because they have no certified
  features.
- There were 676 final ESPN games in the window. 517 had an incumbent record (the others involve non-D-I teams), and all 517
  have complete C2 inputs.
- Price-aware set: 515 games and 7,055 contracts (909 winner, 6,146 spread rungs). 4,104 contracts have a later pre-tip
  quote for CLV.

## Outcome-only (517 games)
| | RMSE | MAE | bias (actual − pred) | winner acc. | 50% / 80% coverage |
|---|---|---|---|---|---|
| incumbent | 12.566 | 9.908 | +0.26 | 77.4% | 47.4% / 78.3% (sd 12.06) |
| C2 | 12.480 | 9.839 | −0.03 | 77.4% | 45.5% / 76.0% (sd 11.29) |

- Paired Δ squared error (C2 − incumbent) is −2.17. The game-bootstrap 95% CI is [−3.28, −0.97] and the date-clustered CI is
  [−3.61, −0.73].
- C2 is better on 54.6% of games; RMSE improves by 0.087. This fits the previous study's exploratory "first 30 days" gain (−1.02). It is one early-season window of 13 dates, so
  it is not a season-level estimate.
- Both sigmas are too narrow for November (realised residual SD about 12.5); C2's 11.29 is the more overconfident.

## Price-aware (same 7,055 contracts; selection.evaluate, 2000 bootstraps, seed 7)
Diagnostics (Brier / log loss): entry mid 0.1368 / 0.4224, C2 0.1527 / 0.4674, incumbent 0.1533 / 0.4680. Both models
are clearly worse than the market mid, for both winner and spread contracts.

| rule | model | bets (games) | win rate vs break-even | net ROI [95% CI] | size-capped P&L (contracts) | sel. CLV |
|---|---|---|---|---|---|---|
| R1 | C2 | 505 (344) | 0.374 vs 0.477 | −21.5% [−30.9, −11.6] | −$518.9 (5,019) | +0.19c (n 295) |
| R1 | inc | 530 (356) | 0.311 vs 0.413 | −24.6% [−35.3, −14.0] | −$541.6 (5,274) | +0.11c (n 304) |
| R2 | C2 | 424 (335) | 0.380 vs 0.490 | −22.6% [−32.5, −11.8] | −$469.2 (4,225) | +0.13c |
| R2 | inc | 432 (346) | 0.359 vs 0.463 | −22.5% [−33.7, −11.9] | −$452.5 (4,302) | +0.08c |
| R3 | C2 | 333 (282) | 0.429 vs 0.501 | −14.3% [−23.6, −3.8] | −$239.1 (3,255) | +0.04c |
| R3 | inc | 370 (307) | 0.368 vs 0.457 | −19.5% [−29.9, −9.9] | −$330.8 (3,614) | +0.03c |

- Under every rule and for both models, the ROI CI excludes zero on the losing side.
- The models are badly overconfident on their own selections. The expected win rate is 0.54-0.63, but the observed rate is
  0.31-0.43.
- The losses hold in every price bucket and for both families. The YES side is worst.
- Selection CLV is about zero (0.0-0.2c), so the market did not move toward either model before tip.
- Overlap: under R1 and R2 most bets are shared (363 of about 520, and 331 of about 430). Under R3 only 96 are shared.
- POST HOC, not pre-registered: ROI(C2) − ROI(incumbent) by joint game bootstrap is R1 +3.1 pp [−1.6, +8.1],
  R2 −0.1 pp [−4.7, +4.3], R3 +5.2 pp [−3.7, +14.6]. None is distinguishable from zero.

## Reading
C2 has a better margin than the incumbent on these games (CI excludes 0). At Kalshi prices neither model has an edge:
both lose about 14-25% net under every frozen rule, and C2's smaller margin error does not become a detectable
price-aware improvement.

## Limitations
- **Small, early-season sample.** There are 13 dates, 517 games and about 300-530 bets per rule. Bets within a game and
  date are correlated. The game bootstrap handles the first but not the date-level correlation.
- Early season is where both models' preseason priors are weakest. The result says nothing about later months.
- Snapshot gaps mean some entries are stale (up to 3.9 h). Displayed size is top-of-book only, and there is no fill
  simulation.
- Fee = taker schedule 0.07·P·(1−P); size-capped P&L uses per-order rounded fees.
- The incumbent's published `home_win_prob` (a separate win-probability model) was not used. The protocol uses
  Normal(margin, margin_sd) for both models.

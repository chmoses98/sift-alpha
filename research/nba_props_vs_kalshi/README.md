# Frozen NBA Projection Foundation vs Kalshi player props, 2025-26 regular season (RESEARCH ONLY)

No betting, no deployment. Pre-registered in `protocol.json` (sha256 `53d7fd30...a9458`, hashed at 05:14:32Z and made
read-only before any model probability was joined to a price or a settlement). Every number is in `report.json`.
Reproduce with `venv/bin/python run.py` (the model stage takes about 25 min the first time and is cached in `out/`).

## What was done
* **Model.** `research/projection_foundation` was copied to `repo/` and run there. Box data is the vault hoopR snapshot-20261116, with no network.
  * Frozen holdout winners: points E LightGBM + empirical; rebounds F stack + minutes mixture; assists E + mixture; threes F + mixture. Minutes model E. **No injury report**, because the frozen holdout config does not use it (E_inj is a separate track).
  * Faithfulness check, pooled 2024-25 + 2025-26 holdout CRPS, recomputed vs published:
    * points 3.1656 vs 3.1655;
    * rebounds 1.2954 vs 1.2954;
    * assists 0.8995 vs 0.8995;
    * threes 0.5812 vs 0.5812.
  * The best model and distribution are the same as published for all four families.
  * Amendment A1 (made before any outcome join): the primary pmfs use the frozen stack weights and distribution parameters verbatim, because the refit F weights differed slightly (LightGBM 4.7.0; the original version is not pinned).
  * Results with the fully refit pmfs are in `sensitivity_refit_pmfs`; they are essentially identical.
* **Frame.** Conditional on playing. Contracts settled `scalar` (DNP or inactive, settled at fair price) are void.
* **Truth.** The official Kalshi `result` from the vault settlements snapshot. Rung semantics: floor_strike s means YES iff stat >= s+0.5. ESPN box agrees with the official result on 9,552 of 9,557 played contracts; the 5 disagreements are all rebounds and look like stat corrections.
* **Entry.** The last hourly candle that ends in [tip−24h, tip−60min], with tip from the ESPN game time. YES pays yes_ask close, NO pays 1 − yes_bid close.
  * The quote must be TWO_SIDED (the `classify_quote` rule). Candles have no sizes, so the size test cannot be applied.
  * Median entry candle is 1.0 h before tip. Median spread is 5c; 90th percentile is 18c.

## Coverage (`coverage_funnel`)
Candles exist for only about 15% of the listed prop markets: 11,778 of 80,582. They cover a subset of games spread across the season.

| | points | rebounds | assists | threes |
|---|---:|---:|---:|---:|
| markets with candles | 3,519 | 3,284 | 2,599 | 2,376 |
| regular-season & player matched | 2,929 | 2,736 | 2,144 | 1,951 |
| void (scalar) incl. players absent from box | 153 | 143 | 105 | 110 |
| yes/no with model row | 2,869 | 2,673 | 2,099 | 1,916 |
| executable two-sided entry quote | 2,338 | 2,095 | 1,495 | 1,253 |

* Excluded: 1,710 playoff/play-in contracts, 308 contracts on players absent from the box (all settled scalar) and 203 other scalar voids.
* Final quoted set: **7,181 contracts**, 673 player-games, 1,880 player-game-families, 148 games, 151 players.
* Dates run 2025-11-18 to 2026-04-12, split 2,507 contracts in Oct-Jan and 4,674 in Feb-Apr.

## Diagnostics on all 7,181 quoted contracts (`diagnostics`)
| | n | Brier model | Brier mid | diff (95% CI, game-clustered) | LogLoss model / mid | joint logit: b_model / b_mid (cluster SE) |
|---|---:|---:|---:|---|---|---|
| all | 7181 | 0.1764 | 0.1782 | −0.0018 [−0.0046, +0.0007] | 0.527 / 0.531 | 0.56 (0.09) / 0.48 (0.09) |
| points | 2338 | 0.1753 | 0.1735 | +0.0018 [−0.0027, +0.0063] | 0.526 / 0.521 | 0.39 (0.16) / 0.71 (0.16) |
| rebounds | 2095 | 0.1771 | 0.1803 | −0.0032 [−0.0071, +0.0010] | 0.528 / 0.536 | 0.71 (0.18) / 0.31 (0.19) |
| assists | 1495 | 0.1759 | 0.1773 | −0.0014 [−0.0079, +0.0048] | 0.524 / 0.528 | 0.47 (0.17) / 0.58 (0.17) |
| threes | 1253 | 0.1779 | 0.1846 | −0.0067 [−0.0126, −0.0013] | 0.531 / 0.549 | 0.81 (0.19) / 0.16 (0.19) |
| Oct-Jan | 2507 | 0.1855 | 0.1919 | −0.0063 [−0.0121, −0.0015] | 0.550 / 0.565 | 0.65 / 0.38 |
| Feb-Apr | 4674 | 0.1715 | 0.1709 | +0.0005 [−0.0025, +0.0035] | 0.514 / 0.514 | 0.45 / 0.61 |

* Both forecasts are well calibrated on the logit scale: slope 1.01 (SE 0.03) for the model and 1.01 for the mid.
* The mid sits about 2.8 points below the base rate: mean mid 0.430, model 0.450, realised 0.458. Its reliability bins under-predict at the high end (0.8-1.0).
* In the joint regression both terms carry independent information. The model term is significant overall, while the market dominates for points.
* **Prediction quality on quoted player-games** (CRPS of the full pmf): points 3.96, rebounds 1.60, assists 1.40, threes 0.82. These are higher than the season-wide values (3.16 / 1.28 / 0.90 / 0.58) because Kalshi lists high-usage players.
  * Mean rung Brier, model vs mid: points 0.1753 vs 0.1735, rebounds 0.1771 vs 0.1803, assists 0.1759 vs 0.1773, threes 0.1779 vs 0.1846.

## Pre-declared rules, evaluated once (unrounded fee; rounded C=1 fee in brackets)
| rule | bets | wins | win rate | avg price | avg fee | break-even | net P&L | ROI | ROI 95% CI (game bootstrap) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| R1 edge>=5c | 441 | 183 | 0.415 | 0.404 | 0.0152 [0.0192] | 0.420 [0.424] | −2.06 [−3.84] | −1.1% [−2.1%] | [−12.0%, +10.1%] ([−12.8%, +9.0%]) |
| R2 + price 0.25-0.75 | 399 | 178 | 0.446 | 0.446 | 0.0164 [0.0200] | 0.463 [0.466] | −6.61 [−8.03] | −3.6% [−4.3%] | [−14.2%, +7.7%] ([−14.8%, +6.9%]) |
| R3 + abs(model−mid)<=0.15 | 390 | 162 | 0.415 | 0.409 | 0.0144 [0.0185] | 0.423 [0.427] | −3.07 [−4.68] | −1.9% [−2.8%] | [−12.8%, +8.6%] ([−13.6%, +7.5%]) |

The average model probability on the chosen side was 0.51 for R1, against a realised win rate of 0.415. The model's claimed edge of about 9c disappeared.

R1 splits (ROI, unrounded fee):
* By family:
  * points −5.0% (n 227);
  * rebounds −9.6% (73);
  * assists +8.8% (106);
  * threes +14.6% (35).
* By side: YES +2.2% (235), NO −4.1% (206).
* By price bucket:
  * [0.05,0.25) +18% (80);
  * [0.25,0.5) −4.4% (238);
  * [0.5,0.75) −2.8% (116);
  * [0.75,0.95] +22% (7, degenerate CI).
* By half: Oct-Jan −11.5% (129), Feb-Apr +2.8% (312).

Every split CI includes 0, except the n = 7 bucket, whose CI is degenerate. R2 and R3 show the same pattern (`rules.*.by_*`). The R3 halves are Oct-Jan −20% and Feb-Apr +4.5%.

## Exploratory → forward split
* The pre-declared grid had 18 subgroups of the R1 bets: family, side, price bucket, and family x side. They were selected on games before 2026-02-01, with n >= 30 required.
* **No subgroup qualified**, under either the strict rule (ROI > 0 and CI lower bound > 0) or the lenient rule (ROI >= 5%).
  * The only first-half subgroups with n >= 30 were points (−39%), YES (−9%), NO (−14%), the [0.05,0.25) bucket (−19%) and the [0.25,0.5) bucket (−4%).
  * Assists (+46%, n 24) failed the size requirement.
* Nothing was scored as a confirmation, and **no subgroup survived a forward split**. Any subgroup number above is EXPLORATORY.

## Honest conclusion
* As a forecaster, the frozen model is about as good as the Kalshi mid on these contracts.
  * It is slightly better on aggregate Brier and log loss, but the CI includes 0.
  * It is clearly better on threes and in Oct-Jan, and slightly worse on points.
  * It adds information beyond the mid: the joint-logit model coefficient is 0.56 (SE 0.09).
* That information **does not survive the spread and fees.** All three pre-declared selection rules lose a little: −1% to −4% ROI. Their 95% CIs run from about −14% to +10%.
* The pattern resembles an edge that went away rather than a stable one. Oct-Jan bets lost heavily even though the model's Brier was better than the mid then, and Feb-Apr bets were roughly break-even.
* There is no evidence of a frozen, pre-declared subset that wins more often than fee-adjusted break-even. The sample (441 bets over 125 games) also cannot rule out a modest edge of +5-10% or a loss of similar size.

## Limitations
* Hourly candle closes are not fills. There are no sizes, so depth and slippage are unknown and the size condition of `executable_quote` could not be applied. The quote at close may have lasted seconds.
* Only about 15% of markets have candles, covering 148 of 1,231 games. Candle markets were chosen by the archive job's priority and budget, not by us, but they may not be representative.
* The model uses no injury report or lineup information. The market at T−60 does. This plausibly explains why points, the family most sensitive to minutes, is the market's strongest family.
* Tip-off comes from ESPN. For the 1% of games where Kalshi's expected expiration minus tip was not 3 h, the timing may be slightly off.
* The original LightGBM version is unknown, so 4.7.0 was used. The published holdout CRPS reproduces to 4 decimals.
* Settlement truth is Kalshi's official result. The 5 box disagreements and 11 `scalar` contracts on players who did play are counted in `settlement_checks`.

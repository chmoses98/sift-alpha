# SIFT Alpha evaluation report (cumulative)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | SYNTHETIC FIXTURE - exercises code paths; NOT evidence about any real model or market

Forecast rows in input: 908; in window: 908; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **FORECAST_ONLY**; complete eligible-market coverage: **NOT_ESTABLISHED**
- forecast rows 908 over 747 markets. no eligible-market universe supplied: this accounts for forecasts only and says nothing about how many eligible markets were never forecast

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | BLOCKED | FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 1 |
| accuracy | BLOCKED | SPORTS_ONLY_MODEL_DECLARES_MARKET_INPUT | 1 |
| accuracy | BLOCKED | FORECAST_PAYLOAD_INVALID | 1 |
| accuracy | BLOCKED | DUPLICATE_FORECAST_ID | 1 |
| accuracy | GRADED | OK | 902 |
| accuracy | PENDING | EVENT_NOT_FINAL | 1 |
| accuracy | UNSUPPORTED | COMBO_REQUIRES_JOINT_DISTRIBUTION | 1 |
| market | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 22 |
| market | BLOCKED | ACCURACY_FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 1 |
| market | BLOCKED | ACCURACY_SPORTS_ONLY_MODEL_DECLARES_MARKET_INPUT | 1 |
| market | BLOCKED | ACCURACY_COMBO_REQUIRES_JOINT_DISTRIBUTION | 1 |
| market | BLOCKED | ACCURACY_FORECAST_PAYLOAD_INVALID | 1 |
| market | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 2 |
| market | BLOCKED | ACCURACY_DUPLICATE_FORECAST_ID | 1 |
| market | GRADED | OK | 698 |
| market | PENDING | ACCURACY_EVENT_NOT_FINAL | 1 |
| market | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 180 |
| economics | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 22 |
| economics | BLOCKED | ACCURACY_FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 1 |
| economics | BLOCKED | ACCURACY_SPORTS_ONLY_MODEL_DECLARES_MARKET_INPUT | 1 |
| economics | BLOCKED | ACCURACY_COMBO_REQUIRES_JOINT_DISTRIBUTION | 1 |
| economics | BLOCKED | ACCURACY_FORECAST_PAYLOAD_INVALID | 1 |
| economics | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 2 |
| economics | BLOCKED | ACCURACY_DUPLICATE_FORECAST_ID | 1 |
| economics | GRADED | OK | 698 |
| economics | PENDING | ACCURACY_EVENT_NOT_FINAL | 1 |
| economics | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 180 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 378 |
| clv | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 22 |
| clv | BLOCKED | ACCURACY_FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 1 |
| clv | BLOCKED | ACCURACY_SPORTS_ONLY_MODEL_DECLARES_MARKET_INPUT | 1 |
| clv | BLOCKED | ACCURACY_COMBO_REQUIRES_JOINT_DISTRIBUTION | 1 |
| clv | BLOCKED | ACCURACY_FORECAST_PAYLOAD_INVALID | 1 |
| clv | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 2 |
| clv | BLOCKED | ACCURACY_DUPLICATE_FORECAST_ID | 1 |
| clv | GRADED | OK | 320 |
| clv | PENDING | ACCURACY_EVENT_NOT_FINAL | 1 |
| clv | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 180 |

## Evidence class: BACKTEST

Graded 902 of 908 forecasts across 181 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 722 | Brier 0.146258 [0.133446, 0.159871] | -0.019416343490304744 |
| CONTINUOUS | 80 | MAE 4.4625 [3.737187, 5.3125] | 1.1625 |
| ORDINAL_PMF | 80 | CRPS 3.20165 [2.705344, 3.757424] | 1.182819 |
| CATEGORICAL | 20 | multiclass Brier 0.5918 [0.5228, 0.6628] | – |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| CBB | ALT_TOTAL | syn-v1 | 150 | 40 | -0.01072 [-0.017434, -0.004685] | 0.010493 | MARKET_BETTER |
| CBB | MONEYLINE | syn-v1 | 80 | 40 | -0.008376 [-0.030067, 0.013337] | 1.0 | NOT_DISTINGUISHABLE |
| CBB | TOTAL | syn-v1 | 39 | 39 | -0.000134 [-0.011887, 0.012018] | 1.0 | NOT_DISTINGUISHABLE |
| NBA | ALT_TOTAL | syn-v1 | 152 | 40 | -0.006876 [-0.012895, -0.000585] | 0.18291 | MARKET_BETTER |
| NBA | MONEYLINE | syn-v1 | 80 | 40 | -0.015006 [-0.038698, 0.007468] | 1.0 | NOT_DISTINGUISHABLE |
| NBA | TOTAL | syn-v1 | 37 | 37 | -0.024326 [-0.036636, -0.01193] | 0.004 | MARKET_BETTER |
| NFL | MONEYLINE | syn-v1 | 80 | 40 | 0.004561 [-0.021827, 0.030262] | 1.0 | NOT_DISTINGUISHABLE |
| NHL | MONEYLINE | syn-v1 | 80 | 40 | 0.010875 [-0.008207, 0.031471] | 1.0 | NOT_DISTINGUISHABLE |

### Economics (hypothetical unless stated)

- full priced population: n=698, ROI -0.067842 [-0.139357, -0.000691]
- positive-edge subset (selection-biased): n=433, ROI -0.082481 [-0.178795, 0.01047]
- verified fills: n=16
- **NO_PROFITABILITY_CLAIM: verified fills n=16 < 200 or CI includes 0; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.014144 (n=320)
- quoted-execution CLV: 0.004144 (n=320)
- actual-fill CLV: -0.00825 (n=16)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| CBB | 360 | 360 | 0.125573 | -0.03828857142857134 | UNDERCONFIDENT |
| NBA | 367 | 362 | 0.128742 | -0.0026858156028368163 | UNDERCONFIDENT |
| NFL | 80 | 80 | 0.202207 | 0.048534999999999995 | UNDERCONFIDENT |
| NHL | 80 | 80 | 0.224446 | -0.08029000000000008 | OVERCONFIDENT |
| SOCCER | 21 | 20 | – | – | – |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| ALT_TOTAL | 320 | 320 | 0.078448 | -0.013410937500000109 | UNDERCONFIDENT |
| COMBO | 1 | 0 | – | – | – |
| MONEYLINE | 347 | 342 | 0.229824 | -0.028795652173913 | OVERCONFIDENT |
| PLAYER_PROP | 160 | 160 | – | – | – |
| TOTAL | 80 | 80 | 0.081143 | -0.005686250000000004 | UNDERCONFIDENT |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| GAME | 80 | 80 | 0.202207 | 0.048534999999999995 | UNDERCONFIDENT |
| game_winner | 246 | 242 | 0.238954 | -0.05435950413223134 | OVERCONFIDENT |
| match_result_3way | 21 | 20 | – | – | – |
| parlay | 1 | 0 | – | – | – |
| player_points | 160 | 160 | – | – | – |
| total | 400 | 400 | 0.078987 | -0.011865999999999932 | UNDERCONFIDENT |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| syn-v1 | 908 | 902 | 0.146258 | -0.019416343490304744 | UNDERCONFIDENT |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 720 | 720 | 0.122208 | -0.016040178571428587 | UNDERCONFIDENT |
| 6h_24h | 181 | 180 | 0.23026 | -0.026475625000000003 | OVERCONFIDENT |
| le_2h | 7 | 2 | 0.16 | -0.4 | INSUFFICIENT_DATA |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 64 | 0.046 | 0.000 | 0.046 |
| 0.1-0.2 | 41 | 0.147 | 0.049 | 0.098 |
| 0.2-0.3 | 53 | 0.257 | 0.151 | 0.106 |
| 0.3-0.4 | 60 | 0.350 | 0.317 | 0.034 |
| 0.4-0.5 | 103 | 0.450 | 0.388 | 0.061 |
| 0.5-0.6 | 102 | 0.550 | 0.588 | -0.038 |
| 0.6-0.7 | 80 | 0.645 | 0.863 | -0.218 |
| 0.7-0.8 | 99 | 0.751 | 0.798 | -0.047 |
| 0.8-0.9 | 70 | 0.847 | 0.943 | -0.096 |
| 0.9-1.0 | 50 | 0.954 | 1.000 | -0.046 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

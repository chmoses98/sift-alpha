# SIFT Alpha evaluation report (cumulative)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | NHL data-archive frozen forecasts postmortem

Forecast rows in input: 75901; in window: 75901; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **ELIGIBLE_UNIVERSE**; complete eligible-market coverage: **INCOMPLETE**
- eligible markets 74327; forecast coverage 0.895933; graded coverage 0.880784
- status: {'FORECAST_AND_GRADED': 65466, 'NO_FORECAST_FOR_ELIGIBLE_MARKET': 7735, 'FORECAST_NOT_GRADED': 1126}
- forecast markets outside the eligible universe: 432

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | BLOCKED | CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| accuracy | BLOCKED | OUTCOME_VOID_OR_POSTPONED | 1047 |
| accuracy | GRADED | OK | 74232 |
| accuracy | PENDING | NO_OUTCOME_ROW | 498 |
| market | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| market | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 12220 |
| market | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1047 |
| market | GRADED | OK | 62012 |
| market | PENDING | ACCURACY_NO_OUTCOME_ROW | 498 |
| economics | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| economics | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 12220 |
| economics | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1047 |
| economics | GRADED | OK | 62012 |
| economics | PENDING | ACCURACY_NO_OUTCOME_ROW | 498 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 336 |
| clv | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| clv | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 12220 |
| clv | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1047 |
| clv | GRADED | OK | 61676 |
| clv | PENDING | ACCURACY_NO_OUTCOME_ROW | 498 |

## Evidence class: BACKTEST

Graded 8 of 8 forecasts across 4 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 8 | Brier 0.127948 [0.005596, 0.331868] | -0.1298 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NHL | OTHER_EVENT | PLAYER_SIM_V1 | 2 | 2 | 9e-05 [4.9e-05, 0.000131] | 0.001 | INSUFFICIENT_SAMPLE |
| NHL | PLAYER_PROP | PLAYER_SIM_V1 | 4 | 4 | 0.061159 [-0.004758, 0.162458] | 0.148926 | INSUFFICIENT_SAMPLE |

### Economics (hypothetical unless stated)

- full priced population: n=6, ROI 0.351351 [-0.122807, 1.941176]
- positive-edge subset (selection-biased): n=1, ROI 0.754386 [0.754386, 0.754386]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.0 (n=6)
- quoted-execution CLV: -0.049167 (n=6)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NHL | 8 | 8 | 0.127948 | -0.1298 | INSUFFICIENT_DATA |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| OTHER_EVENT | 3 | 3 | 0.000267 | 0.015033333333333334 | INSUFFICIENT_DATA |
| PLAYER_PROP | 5 | 5 | 0.204557 | -0.21670000000000003 | INSUFFICIENT_DATA |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| first_goal | 3 | 3 | 0.000267 | 0.015033333333333334 | INSUFFICIENT_DATA |
| goalie_saves | 1 | 1 | 0.149073 | -0.3861 | INSUFFICIENT_DATA |
| player_goals | 4 | 4 | 0.218428 | -0.17435 | INSUFFICIENT_DATA |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| PLAYER_SIM_V1 | 8 | 8 | 0.127948 | -0.1298 | INSUFFICIENT_DATA |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| le_2h | 8 | 8 | 0.127948 | -0.1298 | INSUFFICIENT_DATA |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 6 | 0.032 | 0.167 | -0.135 |
| 0.1-0.2 | 1 | 0.155 | 0.000 | 0.155 |
| 0.2-0.3 | 0 | – | – | – |
| 0.3-0.4 | 0 | – | – | – |
| 0.4-0.5 | 0 | – | – | – |
| 0.5-0.6 | 0 | – | – | – |
| 0.6-0.7 | 1 | 0.614 | 1.000 | -0.386 |
| 0.7-0.8 | 0 | – | – | – |
| 0.8-0.9 | 0 | – | – | – |
| 0.9-1.0 | 0 | – | – | – |

## Evidence class: PROSPECTIVE

Graded 74224 of 75893 forecasts across 307 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 74224 | Brier 0.129478 [0.12659, 0.132513] | -0.008317146744988152 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NHL | LADDER | DATA_ONLY_V1 | 6981 | 307 | -0.003495 [-0.005304, -0.001547] | 0.009 | MARKET_BETTER |
| NHL | LADDER | DATA_ONLY_V2 | 6981 | 307 | -0.003163 [-0.004895, -0.001422] | 0.0055 | MARKET_BETTER |
| NHL | LADDER | OA_RIDGE_V1:OA_SVA | 281 | 142 | -0.005349 [-0.012153, 0.001243] | 0.376311 | NOT_DISTINGUISHABLE |
| NHL | LADDER | OA_RIDGE_V1:OA_SVA_C1 | 281 | 142 | -0.002994 [-0.008632, 0.002104] | 0.376311 | NOT_DISTINGUISHABLE |
| NHL | MONEYLINE | DATA_ONLY_V1 | 614 | 307 | -0.007573 [-0.013746, -0.000776] | 0.091956 | MARKET_BETTER |
| NHL | MONEYLINE | DATA_ONLY_V2 | 614 | 307 | -0.011577 [-0.018839, -0.004434] | 0.011992 | MARKET_BETTER |
| NHL | MONEYLINE | OA_RIDGE_V1:OA_SVA | 284 | 142 | -0.012793 [-0.020293, -0.004767] | 0.020993 | MARKET_BETTER |
| NHL | MONEYLINE | OA_RIDGE_V1:OA_SVA_C1 | 284 | 142 | -0.011187 [-0.019361, -0.002875] | 0.050976 | MARKET_BETTER |
| NHL | OTHER_EVENT | PLAYER_SIM_V1 | 3183 | 278 | 0.000445 [-9.6e-05, 0.001065] | 0.376311 | NOT_DISTINGUISHABLE |
| NHL | PERIOD | DATA_ONLY_V2 | 7366 | 307 | -0.001033 [-0.001812, -0.000269] | 0.052475 | MARKET_BETTER |
| NHL | PLAYER_PROP | PLAYER_SIM_V1 | 35137 | 302 | -0.002026 [-0.002781, -0.001276] | 0.0055 | MARKET_BETTER |

### Economics (hypothetical unless stated)

- full priced population: n=62006, ROI -0.073503 [-0.088992, -0.057991]
- positive-edge subset (selection-biased): n=26008, ROI -0.085224 [-0.115045, -0.055867]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.000542 (n=61670)
- quoted-execution CLV: -0.010914 (n=61670)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NHL | 75893 | 74224 | 0.129478 | -0.008317146744988152 | ROUGHLY_CALIBRATED |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| LADDER | 14790 | 14606 | 0.160056 | -0.010872939203067256 | ROUGHLY_CALIBRATED |
| MONEYLINE | 1812 | 1796 | 0.233068 | 0.0 | UNDERCONFIDENT |
| OTHER_EVENT | 10462 | 10037 | 0.027322 | 0.00028234532230746526 | UNDERCONFIDENT |
| PERIOD | 7416 | 7366 | 0.181987 | -0.014618904425739876 | ROUGHLY_CALIBRATED |
| PLAYER_PROP | 41413 | 40419 | 0.129623 | -0.008750162052500066 | ROUGHLY_CALIBRATED |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| first_goal | 10462 | 10037 | 0.027322 | 0.00028234532230746526 | UNDERCONFIDENT |
| game_spread | 2472 | 2456 | 0.177731 | -0.015586848534201947 | ROUGHLY_CALIBRATED |
| game_total | 6138 | 6050 | 0.140567 | -0.013649966942148706 | UNDERCONFIDENT |
| game_winner | 1812 | 1796 | 0.233068 | 0.0 | UNDERCONFIDENT |
| goalie_saves | 499 | 488 | 0.241689 | -0.0023182377049180136 | ROUGHLY_CALIBRATED |
| period_spread | 1854 | 1841 | 0.131239 | -0.023269717544812607 | UNDERCONFIDENT |
| period_total | 2781 | 2762 | 0.179436 | -0.02347693700217235 | UNDERCONFIDENT |
| period_winner | 2781 | 2763 | 0.21835 | 0.0 | UNDERCONFIDENT |
| player_assists | 10035 | 9860 | 0.15581 | -0.015495983772819438 | ROUGHLY_CALIBRATED |
| player_goals | 17532 | 16951 | 0.085165 | -0.0008178337561205867 | ROUGHLY_CALIBRATED |
| player_points | 13347 | 13120 | 0.163216 | -0.014168292682926797 | ROUGHLY_CALIBRATED |
| team_total | 6180 | 6100 | 0.172269 | -0.006220745901639346 | ROUGHLY_CALIBRATED |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| DATA_ONLY_V1 | 7725 | 7636 | 0.162758 | -0.01264689628077531 | ROUGHLY_CALIBRATED |
| DATA_ONLY_V2 | 15141 | 15002 | 0.172199 | -0.009939951339821396 | ROUGHLY_CALIBRATED |
| OA_RIDGE_V1:OA_SVA | 576 | 565 | 0.240603 | -0.01710884955752201 | ROUGHLY_CALIBRATED |
| OA_RIDGE_V1:OA_SVA_C1 | 576 | 565 | 0.238555 | -0.01970911504424777 | UNDERCONFIDENT |
| PLAYER_SIM_V1 | 51875 | 50456 | 0.109273 | -0.006953363326462653 | ROUGHLY_CALIBRATED |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 439 | 355 | 0.109644 | 0.060528309859154944 | OVERCONFIDENT |
| 6h_24h | 403 | 31 | 0.024263 | 0.03901290322580646 | INSUFFICIENT_DATA |
| le_2h | 75051 | 73838 | 0.129617 | -0.008668014437010763 | ROUGHLY_CALIBRATED |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 28481 | 0.042 | 0.046 | -0.004 |
| 0.1-0.2 | 11754 | 0.146 | 0.157 | -0.010 |
| 0.2-0.3 | 9447 | 0.251 | 0.245 | 0.006 |
| 0.3-0.4 | 8714 | 0.347 | 0.354 | -0.006 |
| 0.4-0.5 | 4946 | 0.446 | 0.463 | -0.017 |
| 0.5-0.6 | 3987 | 0.548 | 0.579 | -0.032 |
| 0.6-0.7 | 2165 | 0.638 | 0.657 | -0.020 |
| 0.7-0.8 | 1028 | 0.761 | 0.802 | -0.040 |
| 0.8-0.9 | 2389 | 0.851 | 0.881 | -0.030 |
| 0.9-1.0 | 1313 | 0.971 | 0.983 | -0.012 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

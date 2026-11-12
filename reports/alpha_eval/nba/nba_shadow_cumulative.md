# SIFT Alpha evaluation report (cumulative)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | NBA PURE shadow store postmortem

Forecast rows in input: 668035; in window: 668035; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **ELIGIBLE_UNIVERSE**; complete eligible-market coverage: **INCOMPLETE**
- eligible markets 145981; forecast coverage 0.240408; graded coverage 0.232256
- status: {'NO_FORECAST_FOR_ELIGIBLE_MARKET': 110886, 'FORECAST_AND_GRADED': 33905, 'FORECAST_NOT_GRADED': 1190}
- forecast markets outside the eligible universe: 178600

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | BLOCKED | NO_OUTCOME_ROW_EVENT_OVERDUE | 108224 |
| accuracy | BLOCKED | OUTCOME_VOID_OR_POSTPONED | 79424 |
| accuracy | BLOCKED | CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 10 |
| accuracy | GRADED | OK | 469623 |
| accuracy | PENDING | NO_OUTCOME_ROW | 10754 |
| market | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 287923 |
| market | BLOCKED | ACCURACY_NO_OUTCOME_ROW_EVENT_OVERDUE | 108224 |
| market | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 79424 |
| market | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 5077 |
| market | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 10 |
| market | BLOCKED | PIT_QUOTE_TOO_OLD | 4529 |
| market | GRADED | OK | 121314 |
| market | PENDING | ACCURACY_NO_OUTCOME_ROW | 10754 |
| market | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 50780 |
| economics | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 287923 |
| economics | BLOCKED | ACCURACY_NO_OUTCOME_ROW_EVENT_OVERDUE | 108224 |
| economics | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 79424 |
| economics | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 5077 |
| economics | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 10 |
| economics | BLOCKED | PIT_QUOTE_TOO_OLD | 4529 |
| economics | GRADED | OK | 121314 |
| economics | PENDING | ACCURACY_NO_OUTCOME_ROW | 10754 |
| economics | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 50780 |
| clv | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 287923 |
| clv | BLOCKED | ACCURACY_NO_OUTCOME_ROW_EVENT_OVERDUE | 108224 |
| clv | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 79424 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 33560 |
| clv | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 5077 |
| clv | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 10 |
| clv | BLOCKED | PIT_QUOTE_TOO_OLD | 4529 |
| clv | GRADED | OK | 87754 |
| clv | PENDING | ACCURACY_NO_OUTCOME_ROW | 10754 |
| clv | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 50780 |

## Evidence class: BACKTEST

Graded 144641 of 147395 forecasts across 170 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 144641 | Brier 0.166599 [0.157077, 0.175536] | 0.03353476773438474 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NBA | LADDER | pf-1.2.1|alpha-derive:gauss-copula-notie-v1 | 11399 | 15 | -0.003724 [-0.01416, 0.006065] | 0.902548 | INSUFFICIENT_SAMPLE |
| NBA | LADDER | pf-1.3.0|alpha-derive:gauss-copula-notie-v1 | 70017 | 129 | -0.008311 [-0.01353, -0.003241] | 0.005997 | MARKET_BETTER |
| NBA | MONEYLINE | pf-1.2.1|alpha-derive:gauss-copula-notie-v1 | 228 | 15 | -0.016831 [-0.05921, 0.025159] | 0.902548 | INSUFFICIENT_SAMPLE |
| NBA | MONEYLINE | pf-1.3.0|alpha-derive:gauss-copula-notie-v1 | 1916 | 133 | -0.025441 [-0.038907, -0.010601] | 0.004 | MARKET_BETTER |

### Economics (hypothetical unless stated)

- full priced population: n=83560, ROI -0.079229 [-0.136473, -0.024197]
- positive-edge subset (selection-biased): n=45720, ROI -0.091377 [-0.184719, -0.004846]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.007093 (n=78376)
- quoted-execution CLV: -0.022362 (n=78376)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NBA | 147395 | 144641 | 0.166599 | 0.03353476773438474 | ROUGHLY_CALIBRATED |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| LADDER | 144513 | 141813 | 0.165732 | 0.03420350983244935 | ROUGHLY_CALIBRATED |
| MONEYLINE | 2882 | 2828 | 0.210056 | 0.0 | UNDERCONFIDENT |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| game_spread | 47567 | 46676 | 0.16454 | -0.027550480294389168 | ROUGHLY_CALIBRATED |
| game_total | 41951 | 41168 | 0.166691 | 0.07604337886993706 | ROUGHLY_CALIBRATED |
| game_winner | 2882 | 2828 | 0.210056 | 0.0 | UNDERCONFIDENT |
| team_total | 54995 | 53969 | 0.166031 | 0.055696691374168106 | ROUGHLY_CALIBRATED |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| pf-1.2.1|alpha-derive:gauss-copula-notie-v1 | 11628 | 11628 | 0.165526 | 0.026703487607943832 | ROUGHLY_CALIBRATED |
| pf-1.3.0|alpha-derive:gauss-copula-notie-v1 | 135767 | 133013 | 0.166692 | 0.034131958424845454 | ROUGHLY_CALIBRATED |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 24h_72h | 44652 | 43734 | 0.165904 | 0.02723753872259249 | ROUGHLY_CALIBRATED |
| 2h_6h | 23250 | 22842 | 0.165477 | 0.03034596229543396 | ROUGHLY_CALIBRATED |
| 6h_24h | 58253 | 56825 | 0.166316 | 0.03776364592444742 | ROUGHLY_CALIBRATED |
| le_2h | 21240 | 21240 | 0.169992 | 0.03861648639200804 | OVERCONFIDENT |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 18363 | 0.064 | 0.060 | 0.003 |
| 0.1-0.2 | 21637 | 0.147 | 0.119 | 0.028 |
| 0.2-0.3 | 17224 | 0.249 | 0.219 | 0.030 |
| 0.3-0.4 | 16268 | 0.350 | 0.333 | 0.016 |
| 0.4-0.5 | 14163 | 0.449 | 0.421 | 0.028 |
| 0.5-0.6 | 11634 | 0.548 | 0.507 | 0.041 |
| 0.6-0.7 | 9668 | 0.649 | 0.571 | 0.078 |
| 0.7-0.8 | 9935 | 0.751 | 0.690 | 0.061 |
| 0.8-0.9 | 13131 | 0.854 | 0.794 | 0.059 |
| 0.9-1.0 | 12618 | 0.937 | 0.905 | 0.032 |

## Evidence class: PROSPECTIVE

Graded 324982 of 520640 forecasts across 197 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 274202 | Brier 0.091705 [0.089618, 0.093893] | 0.02240671111078693 |
| CONTINUOUS | 50780 | MAE 3.200132 [3.090839, 3.314153] | 0.630722 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NBA | PLAYER_PROP | EWM5_BASELINE_W1 | 18877 | 103 | 0.003715 [-0.001253, 0.009145] | 0.173914 | NOT_DISTINGUISHABLE |
| NBA | PLAYER_PROP | NBA_BASELINE_2026_PRESEASON_V1:sim-rotation-pure | 18877 | 103 | -0.005551 [-0.011653, 0.000932] | 0.173914 | NOT_DISTINGUISHABLE |

### Economics (hypothetical unless stated)

- full priced population: n=37754, ROI -0.092564 [-0.107373, -0.077596]
- positive-edge subset (selection-biased): n=19633, ROI -0.074759 [-0.100489, -0.049646]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.005573 (n=9378)
- quoted-execution CLV: -0.035901 (n=9378)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NBA | 520640 | 324982 | 0.091705 | 0.02240671111078693 | OVERCONFIDENT |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| PLAYER_PROP | 520640 | 324982 | 0.091705 | 0.02240671111078693 | OVERCONFIDENT |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| player_assists | 113890 | 71086 | 0.077257 | 0.016609753815854278 | OVERCONFIDENT |
| player_minutes | 16270 | 10156 | – | – | – |
| player_points | 146430 | 91404 | 0.086819 | 0.02856153997636865 | OVERCONFIDENT |
| player_rebounds | 130160 | 81244 | 0.099665 | 0.02514201271663291 | OVERCONFIDENT |
| player_threes | 113890 | 71092 | 0.103378 | 0.016805653472495713 | OVERCONFIDENT |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| EWM5_BASELINE_W1 | 260320 | 162491 | 0.088107 | 0.01551678251799768 | OVERCONFIDENT |
| NBA_BASELINE_2026_PRESEASON_V1:sim-rotation-pure | 260320 | 162491 | 0.095302 | 0.029296639703576183 | OVERCONFIDENT |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 52480 | 26492 | 0.106842 | 0.0685999776306371 | OVERCONFIDENT |
| 6h_24h | 329280 | 212990 | 0.089172 | 0.014013903511212511 | OVERCONFIDENT |
| le_2h | 138880 | 85500 | 0.093324 | 0.0290016592736346 | OVERCONFIDENT |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 150488 | 0.018 | 0.020 | -0.002 |
| 0.1-0.2 | 24559 | 0.146 | 0.123 | 0.023 |
| 0.2-0.3 | 16839 | 0.248 | 0.212 | 0.035 |
| 0.3-0.4 | 13262 | 0.348 | 0.295 | 0.054 |
| 0.4-0.5 | 11728 | 0.449 | 0.395 | 0.054 |
| 0.5-0.6 | 11292 | 0.549 | 0.477 | 0.072 |
| 0.6-0.7 | 10477 | 0.650 | 0.567 | 0.083 |
| 0.7-0.8 | 10545 | 0.750 | 0.675 | 0.075 |
| 0.8-0.9 | 11613 | 0.851 | 0.786 | 0.065 |
| 0.9-1.0 | 13399 | 0.953 | 0.894 | 0.059 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

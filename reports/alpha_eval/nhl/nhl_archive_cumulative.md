# SIFT Alpha evaluation report (cumulative)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | NHL data-archive frozen forecasts postmortem

Forecast rows in input: 75901; in window: 75901; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **ELIGIBLE_UNIVERSE**; complete eligible-market coverage: **INCOMPLETE**
- eligible markets 74564; forecast coverage 0.896009; graded coverage 0.872231
- status: {'FORECAST_AND_GRADED': 65037, 'NO_FORECAST_FOR_ELIGIBLE_MARKET': 7754, 'FORECAST_NOT_GRADED': 1773}
- forecast markets outside the eligible universe: 214

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | BLOCKED | CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| accuracy | BLOCKED | OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST | 610 |
| accuracy | BLOCKED | OUTCOME_VOID_OR_POSTPONED | 1084 |
| accuracy | GRADED | OK | 73836 |
| accuracy | PENDING | NO_OUTCOME_ROW | 247 |
| market | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| market | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 12069 |
| market | BLOCKED | ACCURACY_OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST | 610 |
| market | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1084 |
| market | GRADED | OK | 61767 |
| market | PENDING | ACCURACY_NO_OUTCOME_ROW | 247 |
| economics | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| economics | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 12069 |
| economics | BLOCKED | ACCURACY_OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST | 610 |
| economics | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1084 |
| economics | GRADED | OK | 61767 |
| economics | PENDING | ACCURACY_NO_OUTCOME_ROW | 247 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 334 |
| clv | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 124 |
| clv | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 12069 |
| clv | BLOCKED | ACCURACY_OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST | 610 |
| clv | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1084 |
| clv | GRADED | OK | 61433 |
| clv | PENDING | ACCURACY_NO_OUTCOME_ROW | 247 |

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

Graded 73828 of 75893 forecasts across 308 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 73828 | Brier 0.129823 [0.12696, 0.132733] | -0.007730163352657499 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NHL | LADDER | DATA_ONLY_V1 | 7004 | 308 | -0.003487 [-0.005387, -0.001572] | 0.0055 | MARKET_BETTER |
| NHL | LADDER | DATA_ONLY_V2 | 7004 | 308 | -0.003216 [-0.004896, -0.001533] | 0.0055 | MARKET_BETTER |
| NHL | LADDER | OA_RIDGE_V1:OA_SVA | 283 | 143 | -0.005456 [-0.012328, 0.001266] | 0.36132 | NOT_DISTINGUISHABLE |
| NHL | LADDER | OA_RIDGE_V1:OA_SVA_C1 | 283 | 143 | -0.003095 [-0.008581, 0.002268] | 0.36132 | NOT_DISTINGUISHABLE |
| NHL | MONEYLINE | DATA_ONLY_V1 | 616 | 308 | -0.007739 [-0.014423, -0.001353] | 0.08196 | MARKET_BETTER |
| NHL | MONEYLINE | DATA_ONLY_V2 | 616 | 308 | -0.011802 [-0.018679, -0.004673] | 0.015992 | MARKET_BETTER |
| NHL | MONEYLINE | OA_RIDGE_V1:OA_SVA | 286 | 143 | -0.013279 [-0.021127, -0.00448] | 0.015992 | MARKET_BETTER |
| NHL | MONEYLINE | OA_RIDGE_V1:OA_SVA_C1 | 286 | 143 | -0.011698 [-0.01981, -0.002636] | 0.049975 | MARKET_BETTER |
| NHL | OTHER_EVENT | PLAYER_SIM_V1 | 3148 | 278 | 0.000452 [-9e-05, 0.001071] | 0.36132 | NOT_DISTINGUISHABLE |
| NHL | PERIOD | DATA_ONLY_V2 | 7390 | 308 | -0.001048 [-0.001749, -0.000252] | 0.035982 | MARKET_BETTER |
| NHL | PLAYER_PROP | PLAYER_SIM_V1 | 34845 | 303 | -0.002055 [-0.002836, -0.00133] | 0.0055 | MARKET_BETTER |

### Economics (hypothetical unless stated)

- full priced population: n=61761, ROI -0.074879 [-0.090223, -0.059857]
- positive-edge subset (selection-biased): n=25911, ROI -0.087621 [-0.116553, -0.058736]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.000534 (n=61427)
- quoted-execution CLV: -0.010905 (n=61427)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NHL | 75893 | 73828 | 0.129823 | -0.007730163352657499 | ROUGHLY_CALIBRATED |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| LADDER | 14790 | 14656 | 0.160491 | -0.009282942139738015 | ROUGHLY_CALIBRATED |
| MONEYLINE | 1812 | 1804 | 0.233272 | 0.0 | UNDERCONFIDENT |
| OTHER_EVENT | 10462 | 9907 | 0.027379 | 0.00021340466336933553 | UNDERCONFIDENT |
| PERIOD | 7416 | 7390 | 0.182214 | -0.01372227334235454 | ROUGHLY_CALIBRATED |
| PLAYER_PROP | 41413 | 40071 | 0.129614 | -0.008369102343340568 | ROUGHLY_CALIBRATED |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| first_goal | 10462 | 9907 | 0.027379 | 0.00021340466336933553 | UNDERCONFIDENT |
| game_spread | 2472 | 2464 | 0.177334 | -0.014795860389610394 | ROUGHLY_CALIBRATED |
| game_total | 6138 | 6072 | 0.141523 | -0.01155962615283268 | ROUGHLY_CALIBRATED |
| game_winner | 1812 | 1804 | 0.233272 | 0.0 | UNDERCONFIDENT |
| goalie_saves | 499 | 490 | 0.241659 | -0.0023691836734693883 | ROUGHLY_CALIBRATED |
| period_spread | 1854 | 1847 | 0.130872 | -0.02275625338386572 | UNDERCONFIDENT |
| period_total | 2781 | 2771 | 0.180208 | -0.02142793215445693 | UNDERCONFIDENT |
| period_winner | 2781 | 2772 | 0.218427 | 0.0 | UNDERCONFIDENT |
| player_assists | 10035 | 9783 | 0.15588 | -0.015130072574874753 | ROUGHLY_CALIBRATED |
| player_goals | 17532 | 16787 | 0.084799 | -0.0002903615893250777 | ROUGHLY_CALIBRATED |
| player_points | 13347 | 13011 | 0.163468 | -0.01393479363615402 | ROUGHLY_CALIBRATED |
| team_total | 6180 | 6120 | 0.172528 | -0.004804534313725517 | ROUGHLY_CALIBRATED |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| DATA_ONLY_V1 | 7725 | 7661 | 0.163138 | -0.011280981595092054 | ROUGHLY_CALIBRATED |
| DATA_ONLY_V2 | 15141 | 15051 | 0.172535 | -0.008786877948309069 | ROUGHLY_CALIBRATED |
| OA_RIDGE_V1:OA_SVA | 576 | 569 | 0.240825 | -0.015209841827768078 | ROUGHLY_CALIBRATED |
| OA_RIDGE_V1:OA_SVA_C1 | 576 | 569 | 0.238787 | -0.017801581722319826 | UNDERCONFIDENT |
| PLAYER_SIM_V1 | 51875 | 49978 | 0.109349 | -0.006667815838969138 | ROUGHLY_CALIBRATED |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 439 | 353 | 0.110262 | 0.060764164305949 | OVERCONFIDENT |
| 6h_24h | 403 | 31 | 0.024263 | 0.03901290322580646 | INSUFFICIENT_DATA |
| le_2h | 75051 | 73444 | 0.129961 | -0.008079103126191367 | ROUGHLY_CALIBRATED |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 28195 | 0.042 | 0.046 | -0.004 |
| 0.1-0.2 | 11690 | 0.146 | 0.156 | -0.010 |
| 0.2-0.3 | 9397 | 0.251 | 0.245 | 0.006 |
| 0.3-0.4 | 8701 | 0.347 | 0.353 | -0.005 |
| 0.4-0.5 | 4948 | 0.446 | 0.462 | -0.016 |
| 0.5-0.6 | 3981 | 0.548 | 0.578 | -0.030 |
| 0.6-0.7 | 2171 | 0.638 | 0.655 | -0.018 |
| 0.7-0.8 | 1030 | 0.761 | 0.800 | -0.039 |
| 0.8-0.9 | 2398 | 0.851 | 0.877 | -0.027 |
| 0.9-1.0 | 1317 | 0.971 | 0.980 | -0.009 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

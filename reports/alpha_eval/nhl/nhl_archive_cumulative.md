# SIFT Alpha evaluation report (cumulative)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | NHL archive postmortem

Forecast rows in input: 74749; in window: 74749; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **ELIGIBLE_UNIVERSE**; complete eligible-market coverage: **INCOMPLETE**
- eligible markets 75466; forecast coverage 0.888135; graded coverage 0.868974
- status: {'FORECAST_AND_GRADED': 65578, 'NO_FORECAST_FOR_ELIGIBLE_MARKET': 8442, 'FORECAST_NOT_GRADED': 1446}
- forecast markets outside the eligible universe: 0

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | BLOCKED | CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 18 |
| accuracy | BLOCKED | OUTCOME_VOID_OR_POSTPONED | 1032 |
| accuracy | BLOCKED | FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 8 |
| accuracy | GRADED | OK | 73256 |
| accuracy | PENDING | NO_OUTCOME_ROW | 435 |
| market | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 82 |
| market | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 18 |
| market | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1032 |
| market | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 7661 |
| market | BLOCKED | PIT_QUOTE_TOO_OLD | 3417 |
| market | BLOCKED | ACCURACY_FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 8 |
| market | GRADED | OK | 62096 |
| market | PENDING | ACCURACY_NO_OUTCOME_ROW | 435 |
| economics | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 82 |
| economics | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 18 |
| economics | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1032 |
| economics | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 7661 |
| economics | BLOCKED | PIT_QUOTE_TOO_OLD | 3417 |
| economics | BLOCKED | ACCURACY_FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 8 |
| economics | GRADED | OK | 62096 |
| economics | PENDING | ACCURACY_NO_OUTCOME_ROW | 435 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 830 |
| clv | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 82 |
| clv | BLOCKED | ACCURACY_CONFLICTING_OUTCOME_ROWS_FOR_MARKET | 18 |
| clv | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 1032 |
| clv | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 7661 |
| clv | BLOCKED | PIT_QUOTE_TOO_OLD | 3417 |
| clv | BLOCKED | ACCURACY_FORECAST_NOT_FROZEN_BEFORE_EVENT_START | 8 |
| clv | GRADED | OK | 61266 |
| clv | PENDING | ACCURACY_NO_OUTCOME_ROW | 435 |

## Evidence class: BACKTEST

Graded 0 of 8 forecasts across 0 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| – | – | – | 0 | 0 | no paired priced rows | – | NO_PAIRED_DATA |

### Economics (hypothetical unless stated)

- full priced population: n=0, ROI n/a
- positive-edge subset (selection-biased): n=0, ROI n/a
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: None (n=0)
- quoted-execution CLV: None (n=0)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NHL | 8 | 0 | – | – | – |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| OTHER_EVENT | 3 | 0 | – | – | – |
| PLAYER_PROP | 5 | 0 | – | – | – |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| first_goal | 3 | 0 | – | – | – |
| goalie_saves | 1 | 0 | – | – | – |
| player_goals | 4 | 0 | – | – | – |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| PLAYER_SIM_V1|player-sim-1.0|player-features-1.0 | 8 | 0 | – | – | – |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| le_2h | 8 | 0 | – | – | – |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 0 | – | – | – |
| 0.1-0.2 | 0 | – | – | – |
| 0.2-0.3 | 0 | – | – | – |
| 0.3-0.4 | 0 | – | – | – |
| 0.4-0.5 | 0 | – | – | – |
| 0.5-0.6 | 0 | – | – | – |
| 0.6-0.7 | 0 | – | – | – |
| 0.7-0.8 | 0 | – | – | – |
| 0.8-0.9 | 0 | – | – | – |
| 0.9-1.0 | 0 | – | – | – |

## Evidence class: PROSPECTIVE

Graded 73256 of 74741 forecasts across 309 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 73256 | Brier 0.127816 [0.124902, 0.130705] | -0.008459033389756482 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NHL | LADDER | DATA_ONLY_V1|nhl-sim-1.1|nhl-features-1.0 | 7023 | 308 | -0.003567 [-0.005435, -0.001652] | 0.0035 | MARKET_BETTER |
| NHL | LADDER | DATA_ONLY_V2|nhl-sim-2.0|nhl-features-2.0 | 7023 | 308 | -0.003162 [-0.004804, -0.001454] | 0.0035 | MARKET_BETTER |
| NHL | MONEYLINE | DATA_ONLY_V1|nhl-sim-1.1|nhl-features-1.0 | 614 | 307 | -0.007573 [-0.013746, -0.000776] | 0.045978 | MARKET_BETTER |
| NHL | MONEYLINE | DATA_ONLY_V2|nhl-sim-2.0|nhl-features-2.0 | 614 | 307 | -0.011577 [-0.018839, -0.004434] | 0.005996 | MARKET_BETTER |
| NHL | OTHER_EVENT | PLAYER_SIM_V1|player-sim-1.0|player-features-1.0 | 3772 | 279 | 0.000403 [-0.000138, 0.00102] | 0.164418 | NOT_DISTINGUISHABLE |
| NHL | PERIOD | DATA_ONLY_V2|nhl-sim-2.0|nhl-features-2.0 | 7394 | 309 | -0.001084 [-0.001863, -0.000329] | 0.014994 | MARKET_BETTER |
| NHL | PLAYER_PROP | PLAYER_SIM_V1|player-sim-1.0|player-features-1.0 | 35656 | 302 | -0.001995 [-0.00274, -0.001266] | 0.0035 | MARKET_BETTER |

### Economics (hypothetical unless stated)

- full priced population: n=62096, ROI -0.07074 [-0.086184, -0.054853]
- positive-edge subset (selection-biased): n=25478, ROI -0.080648 [-0.108995, -0.050353]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 4.4e-05 (n=61266)
- quoted-execution CLV: -0.011482 (n=61266)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NHL | 74741 | 73256 | 0.127816 | -0.008459033389756482 | ROUGHLY_CALIBRATED |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| LADDER | 14214 | 14128 | 0.156758 | -0.012113045016987567 | ROUGHLY_CALIBRATED |
| MONEYLINE | 1236 | 1228 | 0.234381 | 0.0 | UNDERCONFIDENT |
| OTHER_EVENT | 10462 | 10067 | 0.027245 | 0.00037590146021654683 | UNDERCONFIDENT |
| PERIOD | 7416 | 7394 | 0.182079 | -0.014184818771977248 | ROUGHLY_CALIBRATED |
| PLAYER_PROP | 41413 | 40439 | 0.129584 | -0.008591792576473217 | ROUGHLY_CALIBRATED |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| first_goal | 10462 | 10067 | 0.027245 | 0.00037590146021654683 | UNDERCONFIDENT |
| game_spread | 2472 | 2456 | 0.177731 | -0.015586848534201947 | ROUGHLY_CALIBRATED |
| game_total | 5562 | 5526 | 0.129666 | -0.013474619978284585 | UNDERCONFIDENT |
| game_winner | 1236 | 1228 | 0.234381 | 0.0 | UNDERCONFIDENT |
| goalie_saves | 499 | 487 | 0.241469 | -0.00104188911704306 | ROUGHLY_CALIBRATED |
| period_spread | 1854 | 1848 | 0.130796 | -0.022730600649350646 | UNDERCONFIDENT |
| period_total | 2781 | 2774 | 0.179943 | -0.022666330209084373 | UNDERCONFIDENT |
| period_winner | 2781 | 2772 | 0.218406 | 0.0 | UNDERCONFIDENT |
| player_assists | 10035 | 9869 | 0.155666 | -0.015138301752963795 | ROUGHLY_CALIBRATED |
| player_goals | 17532 | 16955 | 0.085231 | -0.0009010793276319762 | ROUGHLY_CALIBRATED |
| player_points | 13347 | 13128 | 0.163109 | -0.013883180987202925 | ROUGHLY_CALIBRATED |
| team_total | 6180 | 6146 | 0.172737 | -0.009500658965180597 | ROUGHLY_CALIBRATED |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| DATA_ONLY_V1|nhl-sim-1.1|nhl-features-1.0 | 7725 | 7678 | 0.163 | -0.01477272727272727 | ROUGHLY_CALIBRATED |
| DATA_ONLY_V2|nhl-sim-2.0|nhl-features-2.0 | 15141 | 15072 | 0.172325 | -0.010787596204883232 | ROUGHLY_CALIBRATED |
| PLAYER_SIM_V1|player-sim-1.0|player-features-1.0 | 51875 | 50506 | 0.109185 | -0.006804326218667084 | ROUGHLY_CALIBRATED |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 431 | 347 | 0.103201 | 0.055487896253602315 | OVERCONFIDENT |
| 6h_24h | 403 | 32 | 0.023507 | 0.03805625 | INSUFFICIENT_DATA |
| le_2h | 73907 | 72877 | 0.127979 | -0.008783938005131942 | ROUGHLY_CALIBRATED |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 28511 | 0.042 | 0.046 | -0.004 |
| 0.1-0.2 | 11772 | 0.146 | 0.157 | -0.011 |
| 0.2-0.3 | 9442 | 0.251 | 0.245 | 0.005 |
| 0.3-0.4 | 8620 | 0.347 | 0.353 | -0.006 |
| 0.4-0.5 | 4571 | 0.445 | 0.465 | -0.019 |
| 0.5-0.6 | 3574 | 0.547 | 0.580 | -0.033 |
| 0.6-0.7 | 2024 | 0.638 | 0.663 | -0.025 |
| 0.7-0.8 | 1017 | 0.762 | 0.800 | -0.039 |
| 0.8-0.9 | 2406 | 0.851 | 0.881 | -0.030 |
| 0.9-1.0 | 1319 | 0.971 | 0.983 | -0.013 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

## Secondary: model vs market by native family (separate Holm family; not a promotion input)

Split at the prior NHL audit's data pin (2026-11-04T19:38:30Z). Δ = market − model (positive favours the model).

| model | native family | window | rows | events | Δ Brier [95% CI] | Δ log-loss [95% CI] | p_holm (secondary) | verdict |
|---|---|---|---|---|---|---|---|---|
| DATA_ONLY_V1 | game_spread | AFTER_PRIOR_AUDIT_PIN | 244 | 61 | -0.0058 [-0.0126, +0.0004] | -0.0143 [-0.0320, +0.0015] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V1 | game_spread | ALL | 1228 | 307 | -0.0051 [-0.0085, -0.0015] | -0.0141 [-0.0233, -0.0042] | 0.184926 | MARKET_BETTER |
| DATA_ONLY_V1 | game_spread | UP_TO_PRIOR_AUDIT_PIN | 984 | 246 | -0.0050 [-0.0091, -0.0010] | -0.0140 [-0.0254, -0.0031] | 0.489748 | MARKET_BETTER |
| DATA_ONLY_V1 | game_total | AFTER_PRIOR_AUDIT_PIN | 536 | 61 | -0.0018 [-0.0058, +0.0024] | -0.0057 [-0.0159, +0.0048] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V1 | game_total | ALL | 2722 | 307 | -0.0024 [-0.0043, -0.0005] | -0.0071 [-0.0124, -0.0016] | 0.47976 | MARKET_BETTER |
| DATA_ONLY_V1 | game_total | UP_TO_PRIOR_AUDIT_PIN | 2186 | 246 | -0.0026 [-0.0048, -0.0003] | -0.0074 [-0.0135, -0.0011] | 0.671664 | MARKET_BETTER |
| DATA_ONLY_V1 | game_winner | AFTER_PRIOR_AUDIT_PIN | 122 | 61 | -0.0148 [-0.0261, -0.0021] | -0.0317 [-0.0551, -0.0057] | 0.464783 | MARKET_BETTER |
| DATA_ONLY_V1 | game_winner | ALL | 614 | 307 | -0.0076 [-0.0137, -0.0008] | -0.0164 [-0.0293, -0.0024] | 0.574725 | MARKET_BETTER |
| DATA_ONLY_V1 | game_winner | UP_TO_PRIOR_AUDIT_PIN | 492 | 246 | -0.0058 [-0.0132, +0.0022] | -0.0127 [-0.0278, +0.0039] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V1 | team_total | AFTER_PRIOR_AUDIT_PIN | 613 | 62 | -0.0047 [-0.0084, -0.0011] | -0.0137 [-0.0229, -0.0048] | 0.415808 | MARKET_BETTER |
| DATA_ONLY_V1 | team_total | ALL | 3073 | 308 | -0.0039 [-0.0060, -0.0018] | -0.0102 [-0.0159, -0.0045] | 0.024 | MARKET_BETTER |
| DATA_ONLY_V1 | team_total | UP_TO_PRIOR_AUDIT_PIN | 2460 | 246 | -0.0037 [-0.0063, -0.0011] | -0.0093 [-0.0161, -0.0024] | 0.233892 | MARKET_BETTER |
| DATA_ONLY_V2 | game_spread | AFTER_PRIOR_AUDIT_PIN | 244 | 61 | -0.0106 [-0.0196, -0.0023] | -0.0285 [-0.0513, -0.0075] | 0.558714 | MARKET_BETTER |
| DATA_ONLY_V2 | game_spread | ALL | 1228 | 307 | -0.0059 [-0.0100, -0.0020] | -0.0157 [-0.0266, -0.0053] | 0.11996 | MARKET_BETTER |
| DATA_ONLY_V2 | game_spread | UP_TO_PRIOR_AUDIT_PIN | 984 | 246 | -0.0048 [-0.0092, -0.0002] | -0.0125 [-0.0243, -0.0005] | 0.83958 | MARKET_BETTER |
| DATA_ONLY_V2 | game_total | AFTER_PRIOR_AUDIT_PIN | 536 | 61 | +0.0001 [-0.0029, +0.0029] | +0.0001 [-0.0075, +0.0075] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | game_total | ALL | 2722 | 307 | -0.0011 [-0.0024, +0.0002] | -0.0031 [-0.0065, +0.0004] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | game_total | UP_TO_PRIOR_AUDIT_PIN | 2186 | 246 | -0.0014 [-0.0027, -0.0001] | -0.0039 [-0.0076, -0.0001] | 0.83958 | MARKET_BETTER |
| DATA_ONLY_V2 | game_winner | AFTER_PRIOR_AUDIT_PIN | 122 | 61 | -0.0211 [-0.0358, -0.0063] | -0.0458 [-0.0761, -0.0147] | 0.27986 | MARKET_BETTER |
| DATA_ONLY_V2 | game_winner | ALL | 614 | 307 | -0.0116 [-0.0188, -0.0044] | -0.0249 [-0.0398, -0.0103] | 0.062958 | MARKET_BETTER |
| DATA_ONLY_V2 | game_winner | UP_TO_PRIOR_AUDIT_PIN | 492 | 246 | -0.0092 [-0.0171, -0.0004] | -0.0197 [-0.0360, -0.0014] | 0.827586 | MARKET_BETTER |
| DATA_ONLY_V2 | period_spread | AFTER_PRIOR_AUDIT_PIN | 372 | 63 | -0.0012 [-0.0030, +0.0008] | -0.0046 [-0.0128, +0.0042] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | period_spread | ALL | 1848 | 309 | -0.0004 [-0.0014, +0.0005] | -0.0012 [-0.0054, +0.0031] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | period_spread | UP_TO_PRIOR_AUDIT_PIN | 1476 | 246 | -0.0002 [-0.0013, +0.0009] | -0.0004 [-0.0053, +0.0047] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | period_total | AFTER_PRIOR_AUDIT_PIN | 560 | 63 | -0.0024 [-0.0048, -0.0003] | -0.0049 [-0.0110, +0.0005] | 0.827586 | MARKET_BETTER |
| DATA_ONLY_V2 | period_total | ALL | 2774 | 309 | -0.0007 [-0.0017, +0.0002] | -0.0023 [-0.0049, +0.0001] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | period_total | UP_TO_PRIOR_AUDIT_PIN | 2214 | 246 | -0.0003 [-0.0014, +0.0008] | -0.0017 [-0.0045, +0.0012] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | period_winner | AFTER_PRIOR_AUDIT_PIN | 558 | 63 | -0.0035 [-0.0059, -0.0009] | -0.0080 [-0.0136, -0.0023] | 0.32283 | MARKET_BETTER |
| DATA_ONLY_V2 | period_winner | ALL | 2772 | 309 | -0.0019 [-0.0032, -0.0005] | -0.0044 [-0.0074, -0.0013] | 0.379302 | MARKET_BETTER |
| DATA_ONLY_V2 | period_winner | UP_TO_PRIOR_AUDIT_PIN | 2214 | 246 | -0.0015 [-0.0031, +0.0002] | -0.0034 [-0.0072, +0.0003] | 1.0 | NOT_DISTINGUISHABLE |
| DATA_ONLY_V2 | team_total | AFTER_PRIOR_AUDIT_PIN | 613 | 62 | -0.0067 [-0.0110, -0.0026] | -0.0182 [-0.0289, -0.0079] | 0.11996 | MARKET_BETTER |
| DATA_ONLY_V2 | team_total | ALL | 3073 | 308 | -0.0038 [-0.0059, -0.0017] | -0.0096 [-0.0148, -0.0039] | 0.024 | MARKET_BETTER |
| DATA_ONLY_V2 | team_total | UP_TO_PRIOR_AUDIT_PIN | 2460 | 246 | -0.0031 [-0.0056, -0.0004] | -0.0074 [-0.0138, -0.0006] | 0.47976 | MARKET_BETTER |
| PLAYER_SIM_V1 | first_goal | AFTER_PRIOR_AUDIT_PIN | 1203 | 60 | -0.0003 [-0.0006, -0.0000] | -0.0037 [-0.0091, -0.0000] | 1.0 | MARKET_BETTER |
| PLAYER_SIM_V1 | first_goal | ALL | 3772 | 279 | +0.0004 [-0.0001, +0.0010] | +0.0035 [-0.0012, +0.0091] | 1.0 | NOT_DISTINGUISHABLE |
| PLAYER_SIM_V1 | first_goal | UP_TO_PRIOR_AUDIT_PIN | 2569 | 219 | +0.0006 [-0.0001, +0.0014] | +0.0055 [-0.0008, +0.0126] | 1.0 | NOT_DISTINGUISHABLE |
| PLAYER_SIM_V1 | goalie_saves | AFTER_PRIOR_AUDIT_PIN | 104 | 60 | -0.0047 [-0.0123, +0.0034] | -0.0095 [-0.0249, +0.0071] | 1.0 | NOT_DISTINGUISHABLE |
| PLAYER_SIM_V1 | goalie_saves | ALL | 478 | 290 | +0.0010 [-0.0071, +0.0083] | +0.0023 [-0.0150, +0.0179] | 1.0 | NOT_DISTINGUISHABLE |
| PLAYER_SIM_V1 | goalie_saves | UP_TO_PRIOR_AUDIT_PIN | 374 | 230 | +0.0025 [-0.0068, +0.0109] | +0.0053 [-0.0142, +0.0230] | 1.0 | NOT_DISTINGUISHABLE |
| PLAYER_SIM_V1 | player_assists | AFTER_PRIOR_AUDIT_PIN | 1897 | 61 | -0.0024 [-0.0046, -0.0002] | -0.0076 [-0.0146, -0.0008] | 0.83958 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_assists | ALL | 9639 | 301 | -0.0027 [-0.0039, -0.0015] | -0.0082 [-0.0119, -0.0043] | 0.024 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_assists | UP_TO_PRIOR_AUDIT_PIN | 7742 | 240 | -0.0028 [-0.0042, -0.0015] | -0.0083 [-0.0125, -0.0039] | 0.043 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_goals | AFTER_PRIOR_AUDIT_PIN | 2760 | 61 | -0.0007 [-0.0014, -0.0000] | -0.0026 [-0.0056, +0.0004] | 0.83958 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_goals | ALL | 12621 | 302 | -0.0007 [-0.0010, -0.0003] | -0.0025 [-0.0045, -0.0008] | 0.081959 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_goals | UP_TO_PRIOR_AUDIT_PIN | 9861 | 241 | -0.0006 [-0.0010, -0.0002] | -0.0025 [-0.0046, -0.0005] | 0.11996 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_points | AFTER_PRIOR_AUDIT_PIN | 2633 | 61 | -0.0027 [-0.0050, -0.0004] | -0.0085 [-0.0153, -0.0017] | 0.55323 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_points | ALL | 12918 | 301 | -0.0031 [-0.0043, -0.0019] | -0.0092 [-0.0129, -0.0057] | 0.024 | MARKET_BETTER |
| PLAYER_SIM_V1 | player_points | UP_TO_PRIOR_AUDIT_PIN | 10285 | 240 | -0.0032 [-0.0045, -0.0019] | -0.0094 [-0.0132, -0.0054] | 0.024 | MARKET_BETTER |

### Pre-specified confirmation test

`PLAYER_SIM_V1` / `goalie_saves`, games starting after 2026-11-04T19:38:30Z; paired Brier delta (market - model), event-clustered bootstrap, sift-alpha-eval/1 market_cell; two-sided, alpha 0.05.

- result: **NOT_CONFIRMED**; rows 104, events 60, Δ Brier -0.0047 [-0.0123, +0.0034] (p 0.248876), Δ log-loss -0.0095 [-0.0249, +0.0071]

# SIFT Alpha evaluation report (cumulative)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | NBA PURE shadow store postmortem

Forecast rows in input: 520640; in window: 520640; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **ELIGIBLE_UNIVERSE**; complete eligible-market coverage: **INCOMPLETE**
- eligible markets 18519; forecast coverage 0.93504; graded coverage 0.892975
- status: {'FORECAST_AND_GRADED': 16537, 'NO_FORECAST_FOR_ELIGIBLE_MARKET': 1203, 'FORECAST_NOT_GRADED': 779}
- forecast markets outside the eligible universe: 178575

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | BLOCKED | NO_OUTCOME_ROW_EVENT_OVERDUE | 142912 |
| accuracy | BLOCKED | OUTCOME_VOID_OR_POSTPONED | 42432 |
| accuracy | GRADED | OK | 324992 |
| accuracy | PENDING | NO_OUTCOME_ROW | 10304 |
| market | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 230630 |
| market | BLOCKED | ACCURACY_NO_OUTCOME_ROW_EVENT_OVERDUE | 142912 |
| market | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 42432 |
| market | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 4076 |
| market | BLOCKED | PIT_QUOTE_TOO_OLD | 1742 |
| market | GRADED | OK | 37764 |
| market | PENDING | ACCURACY_NO_OUTCOME_ROW | 10304 |
| market | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 50780 |
| economics | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 230630 |
| economics | BLOCKED | ACCURACY_NO_OUTCOME_ROW_EVENT_OVERDUE | 142912 |
| economics | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 42432 |
| economics | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 4076 |
| economics | BLOCKED | PIT_QUOTE_TOO_OLD | 1742 |
| economics | GRADED | OK | 37764 |
| economics | PENDING | ACCURACY_NO_OUTCOME_ROW | 10304 |
| economics | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 50780 |
| clv | BLOCKED | NO_PIT_QUOTE_AT_FORECAST_TIME | 230630 |
| clv | BLOCKED | ACCURACY_NO_OUTCOME_ROW_EVENT_OVERDUE | 142912 |
| clv | BLOCKED | ACCURACY_OUTCOME_VOID_OR_POSTPONED | 42432 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 28382 |
| clv | BLOCKED | PIT_QUOTE_ONE_SIDED_OR_CROSSED | 4076 |
| clv | BLOCKED | PIT_QUOTE_TOO_OLD | 1742 |
| clv | GRADED | OK | 9382 |
| clv | PENDING | ACCURACY_NO_OUTCOME_ROW | 10304 |
| clv | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 50780 |

## Evidence class: PROSPECTIVE

Graded 324992 of 520640 forecasts across 197 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 274212 | Brier 0.091714 [0.089617, 0.093897] | 0.022401075809957233 |
| CONTINUOUS | 50780 | MAE 3.200132 [3.090839, 3.314153] | 0.630722 |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| NBA | PLAYER_PROP | EWM5_BASELINE_W1 | 18882 | 103 | 0.003701 [-0.001268, 0.009143] | 0.175912 | NOT_DISTINGUISHABLE |
| NBA | PLAYER_PROP | NBA_BASELINE_2026_PRESEASON_V1:sim-rotation-pure | 18882 | 103 | -0.005547 [-0.011649, 0.000932] | 0.175912 | NOT_DISTINGUISHABLE |

### Economics (hypothetical unless stated)

- full priced population: n=37764, ROI -0.092624 [-0.107434, -0.077695]
- positive-edge subset (selection-biased): n=19635, ROI -0.07474 [-0.100391, -0.049469]
- verified fills: n=0
- **NO_PROFITABILITY_CLAIM: no verified fills; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.00557 (n=9382)
- quoted-execution CLV: -0.035896 (n=9382)
- actual-fill CLV: None (n=0)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| NBA | 520640 | 324992 | 0.091714 | 0.022401075809957233 | OVERCONFIDENT |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| PLAYER_PROP | 520640 | 324992 | 0.091714 | 0.022401075809957233 | OVERCONFIDENT |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| player_assists | 113890 | 71092 | 0.077307 | 0.01657900584219507 | OVERCONFIDENT |
| player_minutes | 16270 | 10156 | – | – | – |
| player_points | 146430 | 91404 | 0.086819 | 0.02856153997636865 | OVERCONFIDENT |
| player_rebounds | 130160 | 81248 | 0.09966 | 0.025146967309964574 | OVERCONFIDENT |
| player_threes | 113890 | 71092 | 0.103378 | 0.016805653472495713 | OVERCONFIDENT |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| EWM5_BASELINE_W1 | 260320 | 162496 | 0.088118 | 0.015510713608448912 | OVERCONFIDENT |
| NBA_BASELINE_2026_PRESEASON_V1:sim-rotation-pure | 260320 | 162496 | 0.09531 | 0.02929143801146558 | OVERCONFIDENT |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 52480 | 26496 | 0.106868 | 0.06866002415458938 | OVERCONFIDENT |
| 6h_24h | 329280 | 212992 | 0.089178 | 0.0140049434650997 | OVERCONFIDENT |
| le_2h | 138880 | 85504 | 0.093336 | 0.028981258316699926 | OVERCONFIDENT |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 150490 | 0.018 | 0.020 | -0.002 |
| 0.1-0.2 | 24563 | 0.146 | 0.123 | 0.023 |
| 0.2-0.3 | 16841 | 0.248 | 0.212 | 0.035 |
| 0.3-0.4 | 13262 | 0.348 | 0.295 | 0.054 |
| 0.4-0.5 | 11728 | 0.449 | 0.395 | 0.054 |
| 0.5-0.6 | 11292 | 0.549 | 0.477 | 0.072 |
| 0.6-0.7 | 10478 | 0.650 | 0.567 | 0.083 |
| 0.7-0.8 | 10546 | 0.750 | 0.675 | 0.075 |
| 0.8-0.9 | 11613 | 0.851 | 0.786 | 0.065 |
| 0.9-1.0 | 13399 | 0.953 | 0.894 | 0.059 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

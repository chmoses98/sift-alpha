# SIFT Alpha evaluation report (daily 2026-11-03)

`sift-alpha-eval/1` | status **RESEARCH_ONLY** | SYNTHETIC FIXTURE - exercises code paths; NOT evidence about any real model or market

Forecast rows in input: 908; in window: 48; schema rejects: 0; auxiliary (outcome/quote/fill) rows rejected: 0

## Coverage

- basis: **FORECAST_ONLY**; complete eligible-market coverage: **NOT_ESTABLISHED**
- forecast rows 48 over 40 markets. no eligible-market universe supplied: this accounts for forecasts only and says nothing about how many eligible markets were never forecast

## Accounting (nothing silently excluded)

| evaluation | status | reason | n |
|---|---|---|---|
| accuracy | GRADED | OK | 48 |
| market | GRADED | OK | 36 |
| market | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 12 |
| economics | GRADED | OK | 36 |
| economics | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 12 |
| clv | BLOCKED | NO_VALID_CLOSING_QUOTE | 20 |
| clv | GRADED | OK | 16 |
| clv | UNSUPPORTED | NOT_APPLICABLE_NONBINARY | 12 |

## Evidence class: BACKTEST

Graded 48 of 48 forecasts across 12 events.

| scoring type | n | primary metric | signed bias |
|---|---|---|---|
| BINARY | 36 | Brier 0.139742 [0.101016, 0.187795] | -0.05297777777777768 |
| CONTINUOUS | 4 | MAE 5.0 [0.5, 12.5] | 4.0 |
| ORDINAL_PMF | 4 | CRPS 4.34149 [1.459594, 9.908497] | 4.020319 |
| CATEGORICAL | 4 | multiclass Brier 0.7188 [0.5388, 0.8138] | – |

### Model vs market (primary grid; Holm / BH adjusted across cells)

| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |
|---|---|---|---|---|---|---|---|
| CBB | ALT_TOTAL | syn-v1 | 8 | 2 | -0.009094 [-0.021369, 0.00318] | 1.0 | INSUFFICIENT_SAMPLE |
| CBB | MONEYLINE | syn-v1 | 4 | 2 | 0.107913 [0.100368, 0.115458] | 0.004 | INSUFFICIENT_SAMPLE |
| CBB | TOTAL | syn-v1 | 2 | 2 | -0.00274 [-0.004651, -0.000828] | 0.004 | INSUFFICIENT_SAMPLE |
| NBA | ALT_TOTAL | syn-v1 | 8 | 2 | -0.011906 [-0.02817, 0.004358] | 1.0 | INSUFFICIENT_SAMPLE |
| NBA | MONEYLINE | syn-v1 | 4 | 2 | 0.043305 [-0.01242, 0.099029] | 1.0 | INSUFFICIENT_SAMPLE |
| NBA | TOTAL | syn-v1 | 2 | 2 | -0.051392 [-0.072894, -0.029891] | 0.004 | INSUFFICIENT_SAMPLE |
| NFL | MONEYLINE | syn-v1 | 4 | 2 | 0.101569 [0.081171, 0.121968] | 0.004 | INSUFFICIENT_SAMPLE |
| NHL | MONEYLINE | syn-v1 | 4 | 2 | -0.027461 [-0.101812, 0.046891] | 1.0 | INSUFFICIENT_SAMPLE |

### Economics (hypothetical unless stated)

- full priced population: n=36, ROI 0.092896 [-0.196365, 0.490811]
- positive-edge subset (selection-biased): n=25, ROI 0.312336 [0.027749, 0.649811]
- verified fills: n=1
- **NO_PROFITABILITY_CLAIM: verified fills n=1 < 200 or CI includes 0; hypothetical quoted returns are not evidence of realisable profit**

### CLV (signed; quoted vs actual-fill kept apart)

- selection CLV: 0.03 (n=16)
- quoted-execution CLV: 0.02 (n=16)
- actual-fill CLV: 0.011 (n=1)

### Accuracy by sport

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| CBB | 18 | 18 | 0.093514 | -0.14692142857142854 | INSUFFICIENT_DATA |
| NBA | 18 | 18 | 0.164763 | -0.04610714285714285 | INSUFFICIENT_DATA |
| NFL | 4 | 4 | 0.259001 | 0.07965 | INSUFFICIENT_DATA |
| NHL | 4 | 4 | 0.094711 | 0.11914999999999998 | INSUFFICIENT_DATA |
| SOCCER | 4 | 4 | – | – | – |

### Accuracy by family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| ALT_TOTAL | 16 | 16 | 0.092152 | 0.026437500000000003 | INSUFFICIENT_DATA |
| MONEYLINE | 20 | 20 | 0.191011 | -0.16795000000000004 | INSUFFICIENT_DATA |
| PLAYER_PROP | 8 | 8 | – | – | – |
| TOTAL | 4 | 4 | 0.125028 | 0.08925000000000005 | INSUFFICIENT_DATA |

### Accuracy by native family

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| GAME | 4 | 4 | 0.259001 | 0.07965 | INSUFFICIENT_DATA |
| game_winner | 12 | 12 | 0.168348 | -0.2504833333333334 | INSUFFICIENT_DATA |
| match_result_3way | 4 | 4 | – | – | – |
| player_points | 8 | 8 | – | – | – |
| total | 20 | 20 | 0.098727 | 0.038999999999999924 | UNDERCONFIDENT |

### Accuracy by model version

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| syn-v1 | 48 | 48 | 0.139742 | -0.05297777777777768 | UNDERCONFIDENT |

### Accuracy by horizon

| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |
|---|---|---|---|---|---|
| 2h_6h | 36 | 36 | 0.125094 | -0.020128571428571385 | UNDERCONFIDENT |
| 6h_24h | 12 | 12 | 0.191011 | -0.16795000000000004 | INSUFFICIENT_DATA |

### Calibration by probability bucket (binary)

| bucket | n | mean forecast | observed | signed gap (fcst − obs) |
|---|---|---|---|---|
| 0.0-0.1 | 0 | – | – | – |
| 0.1-0.2 | 1 | 0.146 | 0.000 | 0.146 |
| 0.2-0.3 | 3 | 0.267 | 0.000 | 0.267 |
| 0.3-0.4 | 3 | 0.350 | 0.667 | -0.317 |
| 0.4-0.5 | 4 | 0.410 | 0.000 | 0.410 |
| 0.5-0.6 | 9 | 0.560 | 0.556 | 0.004 |
| 0.6-0.7 | 6 | 0.669 | 1.000 | -0.331 |
| 0.7-0.8 | 2 | 0.724 | 1.000 | -0.276 |
| 0.8-0.9 | 5 | 0.841 | 1.000 | -0.159 |
| 0.9-1.0 | 3 | 0.918 | 1.000 | -0.082 |

_Descriptive only. No model promotion, order, or authority change follows from this report._

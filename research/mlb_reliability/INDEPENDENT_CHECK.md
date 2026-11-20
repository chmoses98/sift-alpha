# Independent recomputation (2026-11-20)

The orchestrating session recomputed R1 and R3 per split from `contracts_with_y.parquet` with `alpha_engine/pipeline/selection.py`. Every number matches the agent's report:
- R1: EXPLORE 1,461 bets, −1.66% [−7.1, +3.7]; CONFIRM 483 bets, +2.58% [−7.7, +12.8].
- R3: EXPLORE 682 bets, win 0.546 vs break-even 0.520, +4.89% [−0.9, +11.5]; CONFIRM 187 bets / 108 games, win 0.642 vs break-even 0.572, model 0.638, +12.15% [−1.9, +24.7].

R3 by family is positive in 6 of 7 families in both splits; game total is −0.9% and −1.6%. This is exploratory and was **not** used to modify the frozen rule.

Diagnostics: the mid beats the model on Brier in both splits (0.209 vs 0.193; 0.231 vs 0.224).

Reading: the operating model is overconfident overall (calibration slope 0.57–0.65). Where it disagrees only mildly with the market while still clearing fees, it has been calibrated and ahead of break-even. Large disagreements are mostly model error, as in NBA and CFB. Status: hypothesis frozen as `frozen_candidate_mlb_r3_agreement_v1.json` for the 2027 season. **Not validated.**

Operating-model defects found (reported, NOT changed; production changes need owner approval):
1. The totals adapter had an off-by-one until about 2026-08-28/09-01. EXPLORE totals are 10–19 points too low.
2. YRFI probabilities run 9–13 points too high.
3. Margin probabilities run about 6 points too low.
4. The recommendation archive keeps only the day's last pipeline run, often after first pitch: 267 of 660 recommendations are unscorable point-in-time.

## Cross-sport replication of the R3 idea (recorded after freezing; the frozen MLB candidate is unchanged)
| Sport / sample | What was measured | Result |
|---|---|---|
| NBA props 2025-26 (`research/nba_props_vs_kalshi`, frozen pf model, hourly candles) | R3 as a pre-declared rule (net edge ≥ 0.05, \|model − mid\| ≤ 0.15) | 390 bets, ROI −1.9% [−12.8%, +8.6%]: no edge |
| CFB 2026 weeks 6–12 (PR #99 forward report, 3 frozen candidates) | contracts with \|model − mid\| in (0.05, 0.10], before fees | on the model's side: model 0.51–0.53, market 0.44–0.46, observed 0.41–0.43; the model side loses even against mid |
| MLB 2026 (this study) | R3 | +4.9% / +12.2% on two splits, CIs include 0 |

"Moderate disagreement plus edge" is therefore not a general SIFT property. It held, without significance, only for the MLB
operating model, the one model here built on a Poisson run engine. Treat the MLB result as sport- and model-specific until the
2027 forward test.

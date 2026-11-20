# Independent recomputation (2026-11-20)

The study was run by a delegated agent under the frozen protocol (`protocol.json`, sha256 `53d7fd30…9458`, hashed
before any price or outcome join). The orchestrating session recomputed the headline from the committed contract
table using the shared evaluator `alpha_engine/pipeline/selection.py`, with the same exclusions: two-sided quotes,
official yes/no result, player played.

| Quantity | Agent | Recomputed |
|---|---|---|
| Quoted contracts | 7,181 | 7,181 |
| Brier model / mid | 0.1764 / 0.1782 | 0.17639 / 0.17821 |
| R1 bets / win rate / break-even | 441 / 0.415 / 0.420 | 441 / 0.415 / 0.4196 |
| R1 ROI (unrounded fee) | −1.1%, CI [−12.0%, +10.1%] | −1.11%, CI [−12.5%, +10.0%] (different bootstrap code, same seed) |
| R1 mean model probability on chosen side | 0.51 | 0.513 |

The model chose sides it rated 0.51 to win, and they won 0.415. Selecting the largest model–market disagreements
selects the model's errors. This is the same failure mode as CFB (PR #99).

Status: **PRICE-AWARE NOT VERIFIED** for NBA props. Prediction quality is close to the market mid. Threes (−0.0067 Brier,
CI excludes 0) and Oct–Jan are slightly better than mid, but both are exploratory diagnostics, not a selection edge.

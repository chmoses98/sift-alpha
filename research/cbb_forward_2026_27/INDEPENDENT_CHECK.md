# Checks by the orchestrating session (2026-11-20)

- `protocol.json` sha256 matches `protocol.sha256` (`76874f70…`). It was written before any 2026-27 outcome was joined.
- Recomputing `c2_margin` from the frozen 2016–2022 coefficients (`research/cbb_certified_inputs/report.json`) and the forward
  feature columns gives a maximum absolute difference of **0.0**. No refit on forward data.

Reading of the results:
- **Prediction:** the backtest margin gain replicates forward. The effect is larger in November, as the backtest's
  early-season situation suggested.
- **Betting:** neither model has an edge at Kalshi prices. Both are worse than the market mid on Brier and lose 14–25% under
  every frozen rule. This is the same pattern as CFB, NBA props and NFL: the market already prices what our margin models know,
  and the largest disagreements are model error.
- **Sample:** 13 dates, early season. Re-score at season end with the same frozen spec.

# Independent recomputation (2026-11-20)

From the agent's joined dataset (59,719 games; not committed, 39 MB, rebuildable with `run.py`), the orchestrating session
refit candidate C2 for margin on the fit seasons 2016–2022. Coefficients are identical to `report.json` to 4 decimals. It then
recomputed the TEST (2025 + 2026) paired squared-error difference with a 2,000-resample bootstrap over game dates, seed 11:
**−0.2828 [−0.5051, −0.0850]** on 11,511 games. That is identical to the report.

What this does and does not show:
- It is a real out-of-sample improvement to the CBB operating model's margin projection from certified SIFT inputs: four-factor
  matchups, adjusted-offence expected points and free-throw points. The incumbent was reproduced exactly from its own pipeline.
- The gain is very small: RMSE 11.483 → 11.471. Winner accuracy is unchanged at 72.63%. It is concentrated in the first 30 days
  of the season and in lopsided games (exploratory).
- For totals, the same approach is **worse**. The total candidates were already worse on validation.
- There is no price evidence, so this says nothing yet about betting. The next step is a frozen forward test on 2026-27 games
  against the timestamped, sized quotes in cbb-edge-finder `kalshi-archive` (2026-10-05 →).

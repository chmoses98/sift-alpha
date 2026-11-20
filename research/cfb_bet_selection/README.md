# CFB bet selection — audit and calibration of PR #97 (RESEARCH_ONLY)

Nothing here is activated, deployed or scheduled. 2026 sample = weeks 1–5 only (244 games with projections, 207 with bets).

## Reproduce
```
python sift-data-vault/tools/vault.py restore --path archives/CFB/espn_summary_postgame/2014-2025/espn_site_api/collected-20261116 --to RAW/a   # likewise 2026 -> RAW/b
python sift-data-vault/tools/vault.py restore --path archives/CFB/kalshi_official_settlements/all-to-20261116/kalshi_public_api/snapshot-20261116 --to RAW/kalshi
python research/cfb_bet_selection/evaluate.py          --espn RAW/a,RAW/b --cfb ../cfb-edge-finder --cache team.pkl --out research/cfb_bet_selection/report_2026_corrected.json
python research/cfb_bet_selection/audit_calibration.py --espn RAW/a,RAW/b --cfb ../cfb-edge-finder --cache team.pkl --kalshi RAW/kalshi --out research/cfb_bet_selection/audit_report_2026.json
python -m unittest tests.test_cfb_bet_selection -v
```
`report_2026.json` is PR #97's original (uncorrected) output, kept for comparison. `report_2026_corrected.json` and `audit_report_2026.json` are this PR's.

## 1. Was PR #97 right? (verified)
| Check | Result |
|---|---|
| Ticker → game, home/away (key = AWAY then HOME) | correct; 0 undecidable |
| YES/NO direction, strict "wins by over N−0.5" | 5,674 / 5,674 quoted tickers match Kalshi's official `result` |
| Spread strike | 5,202 / 5,202 equal official `floor_strike` and ticker suffix − 0.5 |
| Quote timing | all ≥ 15 min before kickoff, none after official close; median lead 87 min; ask+ask overround ≤ 0.05 |
| Fee, P&L, ROI arithmetic | correct for the unrounded formula; a true 1-contract order pays the next whole cent (about 1.5 contracts worse over the sample, reported separately) |
| Future information | none found: blend and sigma fit on 2024–25 only; inputs are pre-game walk-forward; no market price enters the model |
| **WIN probability** | **defect, fixed**: threshold −0.5 was used for both teams in a continuous normal, so P(home)+P(away)=1.024 and every WIN edge was inflated ~1.2 points |

Blend, all bets: **previously −5.03 contracts / −4.2% ROI on 326 bets → corrected −6.52 / −5.6% on 317 bets.** The 5–10-point edge bucket: +28.2% (73 bets) → +16.5% (70 bets), under one standard error from zero in every corrected variant; still exploratory.

## 2. Why the probabilities are untrustworthy (verified on all 5,674 quoted contracts, not just selected bets)
1. **Home-margin bias inherited from the incumbent.** cfb-edge-finder adds its in-season home effect `h` to the home score and subtracts it from the away score (margin +2h). Mean 2h was 4.4 (2024), 6.1 (2025) and **11.9 points in 2026 weeks 1–5** (9.3×2 in week 2). 2026 home margin is over-projected by 6.4 (incumbent) and 4.5 (blend); 256 of 317 selected bets back the home team.
2. **The market carries all the information the model has, and more.** Market-implied margin MAE 11.25 vs blend 14.40; winner accuracy 78.6% vs 71.4% (same 192 games). Regressing outcomes on both: market coefficient ≈ 1.2–1.4, model coefficient ≈ −0.1 to −0.15. Brier: market 0.133 (WIN) / 0.167 (SPREAD) vs blend 0.173 / 0.213.
3. **So "edge" measures model error.** Where model − market > 0.20, the model says 58–64%, the market 29–33%, and the outcome is 20–31%. Selecting the largest edge across a ~27-rung ladder picks the worst of those errors.
4. **The normal assumption is a minor factor.** 2024–25 standardized residuals are normal (sd 1.00, kurtosis ≈ 0–0.2). In 2026 sd is 1.05 and |z|>2 is 6.6% vs 4.6%: sigma is ~5% too small early in the season, far too little to explain a 40-point calibration gap.

## 3. Corrections tested (walk-forward, EDGE left at 0.05, one pass each; none tuned on 2026)
| Variant | Bets | Win | Net contracts | Net ROI |
|---|---|---|---|---|
| PR #97 blend, WIN fix | 317 | 34.7% | −6.52 | −5.6% |
| A. home effect decoupled (coefficients from 2024–25) | 309 | 31.1% | −8.67 | −8.3% |
| B. walk-forward 2026 bias (earlier weeks only) | 307 | 31.3% | −7.68 | −7.4% |
| A+B | 306 | 29.4% | −12.76 | −12.4% |
| A, main line only | 273 | 39.2% | −16.61 | −13.4% |
| C. walk-forward recalibration against market mid (weeks 4–5) | 118 | 61.0% | −1.04 | −1.4% |

A and B improve contract Brier (SPREAD 0.213 → 0.201, WIN 0.173 → 0.164) and cut the ≥20-point-edge loss from −11.0 to −2.5 contracts, but **no variant is profitable** and none is statistically different from zero (game-clustered SE ≈ 9 contracts). C is the only calibrated one (win rate ≈ ask) and shows no edge left after fees. Fees are 4.4 contracts and half-spread 1.8 of the baseline's −6.5; at mid with no fee the baseline is −0.4, i.e. there is no pre-cost edge either.

## 4. Remaining weaknesses
- Five weeks, one season, early-season only; ladder contracts within a game are highly correlated (effective n ≈ 200 games).
- Correction C trains on 2026 quotes because no earlier executable quotes exist; it has two scored weeks.
- Asks have no size; 1-contract fills assumed.
- `frozen_forward_candidate` in the audit report (variant A, sha256-stamped) is a research freeze for weeks ≥ 6, not a betting rule.

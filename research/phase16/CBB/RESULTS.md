# Phase 16 CBB: preseason roster prior and early-season uncertainty (research only)

**Provenance.** cbb-edge-finder `d47ea8ccd00aaaea717296b611cafe3a73b18448`; engine `cbb_p15_model.py` copied verbatim from #53; roster-archive `fdf31992`, projections-archive `69bb4774`, vault snapshot-20261116. Nothing is wired into production.

**Files.** `cbb_p16_exp.py`, `cbb_p16_results.json`, `tables/preseason_roster_features.csv.gz` (0.59 MB, 12,797 team-seasons, 2006-2027), `tables/coverage_report.json`.

## Arms
Layers were fitted on DEV seasons 2010-25 only. Holdouts were scored once.
* **A, #53 `full`.** Reproduces #53: 2026 margin MAE 9.305; 2027 margin MAE 10.43 against production 10.07.
* **B, (i) roster known from day 1.** Non-members add nothing to continuity; transfers count before their first game. Membership: 2027 = official ESPN roster snapshot before each team's first tip (point-in-time); 2026 and DEV = box appearances (hindsight, not point-in-time).
* **C, (iii) = B + variance term:** 1/(1+games) x roster turnover in the margin and total variance regressions (calibration only).
* **(ii), prior-weight decay: not run.**

## Early slice: either team has played fewer than 10 games
Deltas are row minus column, with 95% game-bootstrap CIs.

| set | n | A mMAE | B mMAE | B-A mMAE | B-A tMAE | B-A logloss | C-B logloss | slope A/B/C |
|---|---|---|---|---|---|---|---|---|
| DEV 10-25 | 27,267 | 9.347 | 9.342 | -0.005 [-0.009,-0.000] | -0.001 [-0.004,+0.002] | -0.0003 [-0.0005,-0.0001] | -0.0000 [-0.0002,+0.0001] | 1.05/1.05/1.05 |
| 2026 | 1,708 | 10.066 | 10.032 | -0.034 [-0.070,+0.002] | -0.010 [-0.028,+0.007] | -0.0006 [-0.0018,+0.0005] | +0.0025 [+0.0011,+0.0037] | 1.07/1.06/1.12 |
| 2027 PIT | 638 | 10.425 | 10.316 | -0.110 [-0.213,-0.017] | +0.032 [-0.018,+0.083] | -0.0029 [-0.0071,+0.0012] | +0.0047 [+0.0015,+0.0077] | 0.95/0.97/1.04 |

**Production `pure-0.2.0`, 2027, same 638 games** (last record before tip): margin MAE 10.070, total MAE 13.706, logloss 0.4237, Brier 0.1407, slope 0.89. B minus production: margin MAE +0.245 [-0.004,+0.521], total MAE +0.216 [-0.117,+0.544], logloss +0.0053 [-0.0059,+0.0176]. A minus production: margin MAE +0.355 [+0.090,+0.634].

**Brier, B minus A:** 2027 -0.0012 [-0.0027,+0.0002]; 2026 -0.0002 [-0.0007,+0.0003].

## Verdict
* **(i) is a small accuracy gain over #53.** Point-in-time 2027: margin MAE -0.11 (CI excludes 0), about 30% of #53's gap to production. 2026: -0.03 (CI touches 0); DEV tiny. No significant change in totals or winner logloss/Brier; B is still not better than production.
* **(iii) is rejected. It is a calibration change, not an accuracy change, and it made calibration worse.** It is
  neutral in DEV. In both holdouts it widens the distributions too much (2027 z-SD 0.96) and logloss gets worse.
* **Caveats.** 2027 covers 2 weeks; 2026 and DEV membership uses hindsight; #53's prior coefficients were fitted on proxy membership but applied to the official roster in 2027; 18% of rostered non-freshmen have no D-I box history, so they carry zero production.

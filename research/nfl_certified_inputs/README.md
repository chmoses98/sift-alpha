# SIFT NFL study: certified inputs vs the operating model's market-free projection (RESEARCH_ONLY)

No betting, no orders, no pushes. Reproduce with `PYTHONDONTWRITEBYTECODE=1 venv/bin/python run.py all` (stages `prep`,
`dev`, `test`, `diag`). The protocol was frozen in `protocol.json` (sha256 in `protocol.sha256`) before any test-season
error was computed. Amendments are in `protocol_amendments.json`. The tables below are the pre-fix record (`report.json`);
the A4 rerun with the fixed builder (`VARIANT=fixed_builder ... run.py all`) is in `report_fixed_builder.json`.

## Bottom line
- **Prediction:** the certified SIFT inputs did **not** improve the market-free baseline on unseen 2024-2025. No target's
  95% CI excludes zero. Game total comes closest, and it points the wrong way (worse).
- **Betting:** real archived bid/ask quotes exist, so the test was run. It shows **no evidence of profitability**. Pooled
  Brier is worse than the market mid, and every R1-R3 ROI CI straddles zero. Nothing here is a betting claim.

## Baseline (fidelity)
- **Model:** nfl-edge-finder's DATA_ONLY / Milestone-E football-only game projection (`nfl_edge/arms/data_only.py`,
  `scripts/research/game_model_study.py`). It uses point-in-time opponent-adjusted ridge ratings on 11 pbp metrics, then
  ridge (lambda 30) margin and total models refit each season on the 8 prior seasons.
- **Why this one:** it is the repo's documented market-free game projection. The sim layer takes its game centre from the
  closing line, and `projection_foundation` team_points is the closing implied total.
- **Reproduction:** rebuilt from the committed point-in-time feature table. It matches the committed walk-forward
  predictions to 7e-15 on all 3,151 games (2014-2025). Playoff ratings rebuilt from vault pbp with the repo's code match
  the committed snapshots to 2e-15.
- **Caveats:** 2012 and 2013 train on only 2 and 3 seasons (features start in 2010). Team points = (total ± margin)/2.
  **The 1H total is not an operating-model output**: its baseline is an OLS map fitted on 2012-2021 (4.88 + 0.402 x
  total). PROE (nflfastR xpass) is indirectly market-informed according to the repo's own audit.

## Certified inputs used (sift-alpha-ops `alpha_engine/features/nfl.py`, all ledger VERIFIED_*)
- **C1:** nfl.off_epa (epa/pass_epa/rush_epa_pre); nfl.def_epa, PIT_COARSE (def_epa/def_pass_epa/def_rush_epa_pre);
  nfl.success_rate (success_pre, def_success_pre); nfl.explosive (expl_pre, def_expl_pre); nfl.redzone (rz_epa_pre,
  def_rz_epa_pre, rz_td_pre); nfl.turnovers (to_rate_pre, def_to_rate_pre); nfl.q_scoring, PROXY (pts_pre, pts_a_pre);
  nfl.points_vs_expected (pts_vs_exp_pre); nfl.ratings (margin_pre).
- **C2 adds:** nfl.pace (plays_pre, nohud_pre); nfl.drives (drives_pre); nfl.rest_travel (rest_gap, short_rest, bye);
  nfl.venue (outdoors, home); nfl.divisional_familiarity (div_game).
- **C3** is C2 with ridge (alpha by forward-chaining season CV on 2012-2021).
- Offence features are paired with the opponent's defence.
- **Defect A1:** the builder flags no home team in 184 STL/SD/OAK home games (2010-2019), because pbp uses LA/LAC/LV.
  `home`, `rest` and `rest_gap` are therefore wrong for those home teams. Rows were joined by normalised team code and the
  values used as built. The defect was fixed upstream and re-run as A4 (see below).

## A4: fixed builder rerun (same protocol, candidates, splits and seeds)
The fix changes `pts_pre` and `margin_pre` on 107-113 team-game rows in 2024-2025 and `home`/`rest` pre-2020 only. The
same candidates were selected. Conclusions are unchanged: no CI excludes zero, and profitability is still not supported.

| TEST delta [95% CI] | team_points C2 | total C3 | margin C2 | 1H total C2 | R1 ROI | R2 ROI | R3 ROI |
|---|---|---|---|---|---|---|---|
| pre-fix | -0.04 [-1.18,1.03] | +2.87 [-1.71,7.70] | +0.06 [-3.06,2.90] | +0.20 [-1.92,2.51] | +2.4% [-11.8,16.7] | +5.1% [-9.0,19.3] | -5.4% [-19.4,9.4] |
| fixed | +0.09 [-1.11,1.24] | +2.88 [-1.70,7.61] | +1.40 [-2.20,4.60] | +0.14 [-1.99,2.43] | +3.7% [-10.1,17.0] | +5.0% [-9.2,18.9] | -5.9% [-19.3,7.1] |

## Validation RMSE (fit 2012-2021, validate 2022-2023): baseline vs selected
team_points 9.224 vs C2 9.174 · total 13.458 vs C3 13.350 · margin 12.617 vs C2 12.609 · 1H 8.599 vs C2 8.527

## TEST 2024-2025, regular season weeks 1-18 (selected candidate refit on 2012-2023, scored once)
Delta = mean(candidate sq. error − baseline sq. error); negative = better. CI is a 95% week-clustered bootstrap
(36 clusters, 2,000 draws, seed 13).

| target | n | RMSE base | RMSE cand | MAE base | MAE cand | delta | 95% CI |
|---|---|---|---|---|---|---|---|
| team_points (C2) | 1088 | 9.205 | 9.203 | 7.377 | 7.350 | -0.04 | [-1.18, +1.03] |
| game_total (C3) | 544 | 13.044 | 13.154 | 10.210 | 10.301 | +2.87 | [-1.71, +7.70] |
| margin (C2) | 544 | 12.993 | 12.995 | 10.165 | 10.081 | +0.06 | [-3.06, +2.90] |
| first_half_total (C2) | 544 | 8.896 | 8.907 | 7.148 | 7.081 | +0.20 | [-1.92, +2.51] |

- **Per season:** worst cell 2024 total, +5.25 [-0.09, +11.28]; all others span 0. **Secondary (not selected):** best is
  C3 on 1H total, -0.88 [-1.71, +0.02], then C3 margin -0.26 [-3.02, +2.32]; none excludes zero.
- **Playoffs (26 games):** every CI is very wide and spans 0.

## Situations (EXPLORATORY; selected candidate vs baseline; no multiplicity correction)
The splits are projected-total tercile (cuts 43.4 and 46.7, set on fit seasons), divisional, |rest diff| >= 3, dome,
and weeks 1-4. No cell's CI excludes zero. The closest are 1H total with |rest diff| >= 3, -4.75 [-10.06, +0.77], and
team_points outdoors, -0.83 [-2.33, +0.65]. Treat both as noise.

## Price-aware, 2025 (copied `selection.py` + `sift_clv/canonical.py`)
- **Quotes:** moneyline = last KXNFLGAME candle ending >= 60 min before kickoff (median age 60 min); spread, total, team
  total = backfill T-90m snapshot of the same candle bid/ask; two-sided only; no trades or post-kickoff prices.
  Settlement = vault Kalshi official results (100% agreement with box scores).
- **Coverage, regular season** (8,217 contracts): 538 moneyline (278 games), 4,144 spread, 3,287 total, 248 team total.
  Spread and total cover 264 games, because the horizons file lacks Rams games. 1H total exists only for 5 playoff games.
- **Probability:** a normal on the selected projection. Sigma is the validation residual SD: margin 12.60, total 13.29,
  team points 9.15, 1H 8.53.
- **Diagnostics:** Brier 0.1997 model vs 0.1953 mid (log loss 0.584 vs 0.573). Worse on moneyline (0.2224 vs 0.2137)
  and spread (0.1898 vs 0.1793); slightly better on total (0.2095 vs 0.2131) and team total (0.1849 vs 0.1856), no CI.

| rule | bets | win rate | fee-adj break-even | net ROI | ROI 95% CI (game bootstrap) |
|---|---|---|---|---|---|
| R1 edge>=0.05 | 428 | 0.383 | 0.374 | +2.4% | [-11.8%, +16.7%] |
| R2 + entry 0.30-0.70 | 353 | 0.456 | 0.434 | +5.1% | [-9.0%, +19.3%] |
| R3 + abs(model-mid)<=0.10 | 314 | 0.369 | 0.390 | -5.4% | [-19.4%, +9.4%] |

- **R1 breakdowns:** entries below 0.25 return -36% on 81 bets; NO side +10%, YES side -8%. The baseline's own
  probabilities give similar results: R1 +2.9% [-10.5%, +15.8%].
- **Playoffs:** 25 bets in 10 games (uninformative). **Profitability: NOT SUPPORTED.**

## Limitations
- **Power:** a single frozen pass with 36 week-clusters cannot detect deltas of about ±1-3 squared points.
- **Redundancy:** the certified columns mostly re-express the pbp signal the baseline already holds in its
  opponent-adjusted ratings. That is the likely reason for the null result.
- **Data and modelling choices:** pre-fix, A1 contaminates the C2 rest/home columns in 7% of fit games (fixed in A4).
  The 1H baseline is a mapping I added. The normal ignores key numbers and ties.
- **Price data:** a single Kalshi season; the horizons file misses the Rams; the spread/total entry is at T-90m;
  staleness reaches 240 min in rare cases; displayed depth was not used.

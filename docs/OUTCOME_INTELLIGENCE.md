# Outcome Intelligence (Project A) — market-first evidence audit and incremental-gain study — RESEARCH_ONLY

Tracking: issue #27 · PR #29 (continues PR #25 head `aa263fc`). No execution module, betting authority or Project B file is touched. Nothing here is merged, deployed or production-verified.

**Question:** does any time-valid pregame input (or the existing SIFT model) improve prediction of settled Kalshi outcomes *beyond the contemporaneous market price*? Accurate prediction ≠ profitable execution; no EV/profit claim is made here.

## Headline
* **No cell in any sport is VALIDATED_IMPROVEMENT.** Of 803 reported sport/family/horizon/challenger cells (355 with a gain estimate): 2 PROMISING_INSUFFICIENT (both multiplicity-adjusted p ≥ 0.24), 149 NO_DEMONSTRATED_IMPROVEMENT, 505 INCONCLUSIVE_UNDERPOWERED, 146 MISSING_DATA, 1 INVALID_EVIDENCE. Counts per sport: `reports/outcome_intel/dashboard.json → sport_status_counts`.
* INCONCLUSIVE and MISSING_DATA are **coverage/power gaps, not negative findings.** Most holdouts are 12–80 games.
* The market is the benchmark to beat and, where tested, the SIFT models do not beat it; several are reliably worse (NBA moneyline, NHL V2 win probability, MLB season-to-date-runs proxy vs Pinnacle).

## Status definitions (`research/outcome_intel/status.py`; enforced centrally in `build_dashboard.py`)
VALIDATED_IMPROVEMENT: holdout CI lower bound > 0 **and** Holm p ≤ 0.05 **and** clean negative control **and** ≥ 30 holdout games · PROMISING_INSUFFICIENT: CI lower bound > 0 but multiplicity-adjusted p > 0.05 · NO_DEMONSTRATED_IMPROVEMENT: ≥ 30 holdout games and CI excludes a meaningful (≥ 0.005 logloss) gain · INCONCLUSIVE_UNDERPOWERED: too few games / CI too wide (**not** evidence of no effect) · MISSING_DATA: no usable pregame price/outcome/input (reason + repair given) · INVALID_EVIDENCE: integrity/negative-control failure. Each sport's own classifier is re-checked centrally; 22 cells were downgraded to INCONCLUSIVE (`status_note` in the dashboard).

Protocol (all sports, `research/outcome_intel/incremental.py`): rows are time-valid (quote/model at or before decision time); train = earliest 2/3 of games by start time, untouched holdout = latest 1/3, one pass, fixed ridge; metric = logloss gain of (calibrated market + challenger) over calibrated market-only; game-cluster bootstrap (independent games are the unit); Holm over every tested cell; shuffled-challenger negative control and look-ahead positive control per cell. Settlement is re-derived independently from final scores wherever possible.

## 1. NFL — independent reproduction (`audit_nfl.py`, separate code, 100-lot fees)
Inputs: `nfl-edge-finder@market-data` `0b47f43bc88e854552e77c03696450328d3968f8` (`data/kalshi/backfill`), nflverse `games.csv` sha256 `53577f42…`, PBP 2023–25 (hashes in the command log). Per-file hashes: `nfl_audit.json → inputs`.
* PR #25's `nfl_outcome.py` re-run → committed report identical (0 differing fields).
* Universe: 381 series, 61,068 settled yes/no markets; **pregame price history exists only for KXNFLGAME (658 tickers) and KXNFLSPREAD (349)**.
* Settlement: Kalshi's official `result` is present for NFL. Re-derived from nflverse scores: moneyline **566/566 agree** (+2 ties = Kalshi `scalar`; 98 preseason markets unmapped), team total 809/809, spread 5,849 agree / 1 DISAGREE / 2 underivable (1,568 non-2025 unmapped), total 4,620 agree / 2 DISAGREE (1,296 unmapped). The 3 disagreements are Kalshi anomalies (all settled 2025‑12‑22, "originally scheduled" games, e.g. `KXNFLTOTAL-25NOV02ATLNE-ABOVE` strike 0.5 settled NO) → treated as INVALID_EVIDENCE and excluded.
* Headline recomputation, 2025 moneyline, 24h, 562 tickers / 281 games: buy‑YES at ask **−2.108¢** (CI −2.157…−2.063), buy‑NO **−1.964¢** (−2.016…−1.912); mid Brier 0.21246; closing-mid Brier 0.21183 (PR: 0.21165 — closing-definition difference). Matches PR #25 (−2.108/−1.964/0.21246).
* **Correction to PR #25:** spread pregame candles cover 22 games of which 9 are regular-season (PR said playoff only).
* Incremental (home-contract row per game, 281 games, 94 holdout games): independent opponent-adjusted ridge ratings — 24h gain **+0.0006 [−0.0145, +0.0160]**, 6h +0.0017 [−0.011, +0.014], 90m +0.0020 [−0.011, +0.015]; PR #25 matchup model — 24h +0.0002 [−0.0245, +0.0231]. All INCONCLUSIVE (CI ±0.015–0.024 > the 0.01 power bar); negative controls clean.
* Not testable (MISSING_DATA, repair = extend the backfill collector to candles+trades): totals, team totals, 1H/2H/quarter, player props (outcomes only: e.g. 10,170 receiving-yard and 7,358 receptions markets settled, no pregame prices).

## 2. MLB 2022–2026 (`mlb_*.py`; `edge-finder-api@main` `5b1ba79253ecf69c849f2c75fc61fdc953be401d`)
* Kalshi MLB prices **exist for 2026-08-01…10-29 only** (812,650 observations, 262,520 contracts; 255,097 settled tickers). **2022–2025 Kalshi: MISSING_DATA** (repair: Kalshi candle backfill + official results). Only multi-season market: sampled Pinnacle (178 dates; moneyline games with a valid pregame snapshot per season 2022–26: 162/180/179/150/144).
* Settlement derived from MLB data; Kalshi official result archived on 0 rows. Re-derivation: moneyline 648/648, run line 2,234/2,234, team total 4,536/4,536. Stored game-total settlements before 2026‑09‑01 use `>N` while Kalshi pays `>=N`: 306 boundary rungs disagree; re-derived where possible, 3,226 contracts dropped. 38,575 rows captured after scheduled start excluded (not provably leaks; actual first pitch not archived).
* SIFT model vs Kalshi mid (NEAR): moneyline −0.011 [−0.026, +0.004] (34 holdout games), F5 ML −0.031 [−0.064, 0.000] (38), YRFI ≈0 (39), team total ≈0 (49): all INCONCLUSIVE. Game total, run line, F3/F7, F5 total, props have no timestamped SIFT probabilities → MISSING_DATA.
* Pinnacle season split (fit 2022‑24, validate 2025, holdout 2026) with a season-to-date-runs proxy (not production): moneyline −0.0065 [−0.0113, −0.0014] (Holm 0.025, proxy worse than Pinnacle); total −0.0003 [−0.0019, +0.0012].
* Weak "own older quote" challenger across 17 families: 34 cells, none > 0 after Holm. Starters/lineups/weather/injuries/bullpen challengers **not run**: per-input availability times are not archived (repair: archive `captured_at` for each input).
* 71 cells: 34 INCONCLUSIVE, 10 NO_DEMONSTRATED (weak challenger only), 27 MISSING_DATA.

## 3. NBA / NHL (`nba_*.py`, `nhl_audit.py`; `nba-edge-finder@data-archive` `ea34ea59…`, `nba-shadow-pure@7beeb96c…`, `NHL-edge-finder@data-archive` `eacc3b9d…`)
* NBA: 158 final games, 75,898 settled tickers (54,622 YES/NO), 116 cells (61 tested). NHL: 246 games, 55,407 tickers (53,153 YES/NO), 114 cells (97 tested). Board replay: 0 broken delta chains.
* No Kalshi official result in either archive; re-derived from box/goal events: NBA 54,622/54,622, NHL 52,110/52,110 agree; owner wagers confirmed 44/44 (NBA), 30/30 (NHL).
* SIFT NBA sim is worse than the market (moneyline logloss ≈0.70 vs 0.56 at T‑6h); NBA shadow player forecasts: nothing; NHL SIFT V1/V2 and sportsbook consensus: gains −0.003…−0.015 (V2 T‑6h reliably negative).
* Only recurring candidate: NHL `PLAYER_SIM_V1` goalie saves — T‑1h +0.0157 (CI lower +0.0055, 63 games, Holm p 0.24), closing +0.0185 (52 games, Holm p 0.82): **PROMISING_INSUFFICIENT**; at T‑6h its own negative control also "gains" → INVALID_EVIDENCE. Needs prospective confirmation.
* Excluded: 33 NHL shootout-ambiguous contracts; period/first-goal contracts for game 2026020155. Illiquid strikes (spread >10¢) not covered (≈29k NBA / 44k NHL rows dropped).
* Not done: structured standalone inputs (rest, injuries, lineups, goalie status), fee/CLV economics, `projection-data` branches.

## 4. CBB / Soccer / Tennis
* **CBB** (301 games with pre-tip quotes, 140 with settled binary game contract, 6,153 settled contracts): game winner H24 −0.040 [−0.097, +0.006] (109 games, NO_DEMONSTRATED); most cells underpowered (45), 17 MISSING_DATA (halves, team totals, OT have no model probability). 2 games (26 tickers) have home/away opposite to ESPN → excluded. Kalshi result cross-checked vs ESPN.
* **Soccer** (441 settled fixtures, 24,161 settled tickers, 13 families; 0 disagreements vs ESPN): 329 cells, 45 NO_DEMONSTRATED, 284 INCONCLUSIVE. Best raw (uncorrected) team_total T‑6h +0.0037 [+0.0008, +0.0067] → not significant after Holm. Lineups are `unknown` on every record; 31% of settled records lack a usable two-sided quote.
* **Tennis**: only 3,340 of 108,727 settled observations (3.1%) are strict pre-game by first-ball truth (299 POST_START, 104,941 START_UNKNOWN — **the repo's headline scorecard rests on START_UNKNOWN rows and is not usable as evidence**). Match winner (322 matches) and set winner (208) NO_DEMONSTRATED; game spread +0.03 on 14 holdout matches INCONCLUSIVE; totals have no strict rows. Prediction-ledger hash chain verified (0 violations).

## 5. CFB (`audit_cfb.py`, `cfb_repairs.py`, `cfb_incremental.py`; `cfb-edge-finder@research-data` `292f3aacafe4b892d56ed7c1446225ce85afbc81`)
* PR #25's CFB script reproduces its committed report exactly; independent recomputation matches the Brier gap (+0.01266, n=31,043, 96 games) and buy-every-side baseline (−3.0864¢ at 1-lot fee, n=9,104).
* **Official settlement (unresolved, documented):** `official_kalshi_settlement` is null on all 11,509 rows and all 4,552 settled tickers use the ESPN fallback (CFBD HTTP 429). Kalshi's API is not reachable from this environment (proxy-blocked; not bypassed). Independent re-derivation 4,552/4,552; exchange-reported wager settlements (`kalshi-router/settle-CFB`) confirm 14/14 overlapping tickers (0.3% of universe); 93 settlement amendments change economics only, never outcomes.
* **Overtime:** 97 tickers in 2 OT games; scores equal ESPN period-score finals (4,454/4,454 checked); no wager overlaps OT, so Kalshi's OT rule is *unconfirmed* (scores include OT).
* **Rescheduled kickoff:** one game (Southern Miss at Auburn) 23:30→23:45; 41 rows were captured after the earlier kickoff. Fix: all PIT filters and the chronological order now use the **earliest** recorded kickoff (conservative).
* **Fees normalised:** canonical 100-lot per-contract fee. Buy-every-side: −2.66¢ (CI −2.78…−2.54) at 100 lots vs −3.09¢ at 1 lot; signs unchanged.
* **Incremental (12 cells, ~26–31 holdout games each):** 11 INCONCLUSIVE_UNDERPOWERED, 1 NO_DEMONSTRATED (spread T‑3D); best Holm p 0.88; none validated.
* Team total / 1H / quarter / props: no Kalshi price capture exists (searched `cfb-edge-finder`); ESPN period scores exist for 573 games (outcome side only) → MISSING_DATA; repair: add series discovery for those families to the research capture.

## 6. Ranked signals (top by CI lower bound; full list incl. negatives in `dashboard.json → ranked_signals_top25_by_ci_lower_bound`, `worst5_by_mean_gain`)
| # | Sport / family / horizon | Challenger | Holdout games | Gain (logloss) lower bound | Holm p | Status |
|---|---|---|---|---|---|---|
| 1 | NHL goalie_saves T‑1h | PLAYER_SIM_V1 | 63 | +0.0157 (+0.0055) | 0.24 | PROMISING_INSUFFICIENT |
| 2 | NHL goalie_saves closing | PLAYER_SIM_V1 | 52 | +0.0185 (+0.0044) | 0.82 | PROMISING_INSUFFICIENT |
| 3 | NBA period_team_total T‑6h | SIFT sim | 24 | +0.048 (+0.008) | 0.88 | INCONCLUSIVE (<30 games) |
| 4 | Tennis game_spread | ELO_DP_FAIR | 14 | +0.03 | 1.0 | INCONCLUSIVE |
| 5 | Soccer team_total T‑6h | world_sim_v2 | — | +0.0037 (+0.0008) | 1.0 | INCONCLUSIVE |
| — | NFL moneyline 24h | independent ratings / PR #25 model | 94 | +0.0006 / +0.0002 | — | INCONCLUSIVE |
| — | CFB all 12 cells | SIFT CFB model | ~30 | −0.027 … +0.007 | ≥0.88 | INCONCLUSIVE / NO_DEMONSTRATED |
| — | MLB moneyline (Pinnacle proxy) | season-to-date runs | 2026 | −0.0065 | 0.025 | worse than market |
Multiple testing: ranking by lower bound is a descriptive sort over hundreds of cells; only Holm-adjusted p counts as evidence, and none reaches 0.05 with a positive gain.

## 7. Data gaps and repairs (priority order)
1. Kalshi official settlement/result archived per contract (CFB, MLB, NBA, NHL, soccer lack it). 2. NFL: candles+trades for totals/team totals/periods/props. 3. MLB 2022–2025 Kalshi history; per-input availability timestamps (starters, lineups, weather, injuries); timestamped model probabilities for all families; actual first-pitch time. 4. Soccer pre-kickoff lineups; two-sided quotes at every horizon. 5. Tennis: first-ball truth before the entry quote; join frozen-producer rows. 6. CBB 15-minute capture. 7. CFB: price capture for team totals/halves/quarters/props. 8. Prospective, pre-registered holdout windows (a 2¢ edge needs ≈4,700 independent contracts at 80% power).

## 8. Reproduce
```
# data (read-only, anonymous git): nfl-edge-finder@market-data (data/kalshi/backfill), cfb-edge-finder@research-data,
# kalshi-router/settle-CFB, period-scores, edge-finder-api@main (sparse), nba/NHL/cbb/soccer/tennis data-archive branches; nflverse games.csv + pbp from github.com/nflverse
python3 -I research/outcome_intel/audit_nfl.py --backfill $NFL/data/kalshi/backfill --games games.csv --pr-model nfl_model_probs.jsonl --out reports/outcome_intel/nfl_audit.json
python3 -I research/outcome_intel/audit_cfb.py --root $CFB --out reports/outcome_intel/cfb_audit.json
python3 -I research/outcome_intel/cfb_incremental.py --root $CFB
python3 -I research/outcome_intel/cfb_repairs.py --root $CFB --settle $CFB_SETTLE --periods $CFB_PERIODS
# MLB / NBA / NHL / CBB / soccer / tennis: commands in reports/outcome_intel/{mlb,nba_nhl,cbb_soccer_tennis}_SUMMARY.md
python3 -I research/outcome_intel/build_dashboard.py          # dashboard.json + coverage_ledger.json
python3 -m unittest discover -s tests -p 'test_*.py'
```
Input digests/commit SHAs: each `*_audit.json` (`inputs`/`provenance`).

## 9. What is implemented / tested / merged / production-verified
Implemented and unit-tested (leakage, settlement derivation, split ordering, controls, status rules); research outputs committed. **Not merged, not deployed, not production-verified.** PR #25 is still open, so #29 is based on its branch. No betting authority changed.

# CBB / Soccer / Tennis: market-first evidence audit and incremental-prediction test (RESEARCH_ONLY)

Scope: does any time-valid pregame input (the SIFT model) improve outcome prediction beyond the contemporaneous Kalshi price?
Nothing here trades, deploys or touches execution code. All three archives are weeks old, so most cells are underpowered.
A cell that was not testable is MISSING_DATA or INCONCLUSIVE_UNDERPOWERED, never a negative result.

Result: **0 VALIDATED_IMPROVEMENT cells in any sport.** Best cells are PROMISING_INSUFFICIENT with Holm p = 1.0 over every cell tried.

## Method (identical across sports, `research/outcome_intel/cbb_common.py` wraps `incremental.py` unchanged)
* One row per (contract, horizon). Market = mid of the stored two-sided yes bid/ask (spread <= 0.10), taken from a capture strictly before tip/kickoff/first-ball.
* Chronological split by game start: earliest 2/3 of games fit the logistic calibration (market-only) and the challenger term; latest 1/3 is the holdout, never used for fitting. Ridge fixed at 1. One pass.
* Statistic = holdout logloss gain over the train-calibrated market (positive = model adds information). CI = game-cluster bootstrap (2000). Holm over EVERY cell tried; cells that could not be tested enter with p = 1.
* Controls per cell: game-shuffled challenger (negative) and an outcome-informed planted challenger (positive; proves the pipeline can see a real signal at that n). Positive control detected in 140 of 140 testable cells. Shuffled control nominally significant in 2 of 140 (expected about 3.5): chance level, no leakage signal.
* Status rule (`cbb_common.classify`): VALIDATED needs CI > 0 and Holm p <= 0.05 with a clean negative control; PROMISING = positive mean, raw p < 0.10; NO_DEMONSTRATED = at least 30 holdout games and not promising; INCONCLUSIVE_UNDERPOWERED otherwise; a significant negative control voids any claimed gain (INVALID_EVIDENCE).

## CBB (chmoses98/cbb-edge-finder; panel archive 2026-10-05 to 2026-11-04, tips from 2026-11-01)
Heads: kalshi-panel-archive b57c6c2, kalshi-archive 2943394, projections-archive 18fe9f2, schedule-archive e2e03cd, period-scores-archive 1d6fed0 (full SHAs and file-set digests in `cbb_audit.json`).
* Independent events: 301 games with pre-tip game-market quotes; 140 games with a settled binary game contract. Settled binary contracts: 6,153 (GAME_WINNER 308, SPREAD 2,318, TOTAL 2,870, HALF 576, TEAM_TOTAL 94, OVERTIME/RACE 15); 2 Kalshi `scalar` (void) GAME_WINNER contracts excluded.
* Settlement: Kalshi `result` is official; independently re-derived from ESPN final and period scores via parsed contract semantics. 0 conflicting Kalshi results, 0 conflicting ESPN finals. Disagreements: 26 tickers, all in 2 games (ESPN 401909694 FAMU/FSU, 401921704 PUR/GONZ) where the panel's home/away mapping is opposite to ESPN's. A swapped mapping would also invert the model probability, so these are a panel mapping risk. They are excluded everywhere.
* Prices: 538,011 panel rows in game families. Raw snapshot vs panel quotes: 9,905 checked, 0 mismatches. 0 phase/tip mismatches. Top of book only (orderbooks null). Coverage by horizon is thin because capture cadence was sparse before Nov 1: H6 has only 3 games. 242 GAME_WINNER tickers are UNMAPPED (no game id).
* Model: frozen projections (pure-0.2.0 incumbent plus 4 shadow versions), 2,280 records, as_of before tip on all (0 violations), lead median 25.4 h; the panel's as_of precedes each capture on 100% of rows; independent recomputation of 182,635 market-specific probabilities from frozen margin/total and sd: max abs diff 0.
* Inputs: ESPN DK lines (espn-lines-archive, 19 files), rosters/availability (archives exist) are NOT joined, so untested. Half, team-total, overtime and race markets: no model probability exists (`no_half_distribution_in_frozen_model` etc.). Futures/awards/player-award markets (about 14,000 tickers) are unsettled and have no model capability.
* Results (primary challenger pure-0.2.0; 60 challenger cells = 3 families x 4 horizons x 5 model versions): market-only calibrated logloss GAME_WINNER H24 0.267 (36 holdout games), SPREAD H1 0.48, TOTAL H1 0.56 (30 holdout games).
  * GAME_WINNER H24: gain -0.040 [-0.097, +0.006] (109 games): NO_DEMONSTRATED_IMPROVEMENT (model is worse than market, not significantly).
  * SPREAD H1 +0.003 [-0.002, 0.009] (89 games), TOTAL H1 -0.010 [-0.029, 0.008] (90 games): NO_DEMONSTRATED_IMPROVEMENT.
  * All other family x horizon cells (H24 and CLOSE for SPREAD/TOTAL, H6, H1/CLOSE for winners): INCONCLUSIVE_UNDERPOWERED. Totals: 15 NO_DEMONSTRATED, 45 INCONCLUSIVE, 17 MISSING_DATA (no model for half/team-total/OT/race markets).

## SOCCER (chmoses98/soccer-edge-finder data-archive b98b4c2; kickoffs 2026-09-28 to 2026-11-01)
* 118,244 prediction records, 111,797 settlements (0 orphans, 0 duplicated or conflicting settlements). 441 settled fixtures, about 24,100 settled tickers in 13 families (match_result_3way, total_goals, team_total, handicap, btts, first-half result/total/handicap/btts/exact score, second-half result, exact_score, first_to_score). 6,447 predictions for past kickoffs are unsettled (void, postponed or pending: not distinguishable from archive, listed by date).
* Independent re-derivation: 441/441 fixtures have an independent full-time result (results/espn, 0 disagreement with settlement evidence); all regulation-period families re-derived with 0 disagreements. First/second-half contracts are re-derived only from the settlement evidence's own period score (same upstream ESPN source, so weaker). first_to_score cannot be derived (no event data): settlement-only.
* Prices: Kalshi bid/ask stored in each prediction record at `market_as_of`; model and market as_of are within seconds (median 0.02 min; 199 records have the model newer than the quote by more than 5 min, max 7.7 min). 0 records at/after kickoff. 31% of settled records (34,668 of 111,797) have a missing/wide (>0.10) quote and are excluded; the rest deduplicated to 54,746 rows (latest as_of per ticker, horizon, model, engine; time only). No orderbook depth. Horizon labels mean "at least X before kickoff" (T-24h realised lead median 35 h).
* Inputs: lineups NOT available pre-kickoff (`lineup_state='unknown'` on every record), weather and xG not joined. Consensus-bookmaker reference probability exists on 4,635 settled records (4.1%; observed within 10 min of the quote and before kickoff): tested only for match_result_3way (148 fixtures): gain -0.002, NO_DEMONSTRATED.
* Results: 329 cells (all families x 10 horizon labels x model families, plus reference): 275 INCONCLUSIVE_UNDERPOWERED, 45 NO_DEMONSTRATED_IMPROVEMENT, 9 PROMISING_INSUFFICIENT, 0 validated. Best raw: second_half_result T-15m +0.028 [0.000, 0.059] (43 games), team_total T-6h +0.0037 [0.0008, 0.0067] (138 games), match_result_3way T-6h +0.0037 [-0.0002, 0.0076] (290 games); every Holm p = 1.0. Market-only logloss: three-way about 0.56, BTTS about 0.65, total goals about 0.45. Three-way contracts are 3 per fixture and clustered by fixture.

## TENNIS (chmoses98/Tennis-Edge-Finder tennis-data 6bf11f2)
* Ledger: 110,566 prediction rows (hash chain re-verified: 0 violations; 0 duplicate ids), 28,825 tickers, 13,383 matches, 108,727 settled (0 re-settlements), 4,028 `scalar` (fair price) excluded. Families: MATCH_WINNER 66,690, SET_WINNER 16,382, TOTAL_GAMES 10,902, EXACT_SET_SCORE 9,452, GAME_SPREAD 7,116, SET_SPREAD 20, TOTAL_SETS 4. ATP/WTA ITF cannot be independently re-derived (independent results end 2026-04-27).
* **Time validity is the binding limit.** Only 3,340 settled observations (3.1%) are STRICT_PREGAME (entry provably before the first-ball lower bound); 104,941 are START_UNKNOWN, 299 POST_START (8% of classified observations: the contamination risk is real), 33 AMBIGUOUS. START_UNKNOWN rows are never used. 370 STRICT rows lack a verifiable lower bound and are dropped. Re-check `generated_at < first_ball_lower_utc` on every used row. The repo's headline scorecard (market Brier 0.195 vs model 0.214 on 101,636 rows) rests mostly on START_UNKNOWN rows and is not time-validated.
* Used: 2,053 strict rows over 616 matches. Independent outcomes: MATCH_WINNER exchange vs independent 14,208 agree / 14 disagree over all settled rows (disagreements are dropped from tests).
* Models: the ledger carries a model probability only for MATCH_WINNER (PRODUCTION, INCUMBENT; ELO/STRUCTURAL) and `ELO_DP_FAIR` for derivative families. TOTAL_GAMES and TOTAL_SETS have 0 strict rows; hence MISSING_DATA. The market-conditioned Model 4 / shadow-board streams (`frozen_producers`, 41,760 and 89,170 rows) record `first_ball_status_at_prediction = NOT_OBSERVED_STARTED` on every row and need a first-ball-truth join; not done, so not tested.
* Results (primary challenger ELO_DP_FAIR; 70 cells = 7 families x 2 horizons x 5 model columns): MATCH_WINNER 322 matches +0.0049 [-0.004, 0.014] (107 holdout matches), SET_WINNER 208 matches +0.0002: NO_DEMONSTRATED. GAME_SPREAD 42 matches +0.029 [0.004, 0.056] and +0.034: PROMISING_INSUFFICIENT (14 holdout matches; Holm p = 1.0). EXACT_SET_SCORE 43 matches, SET_SPREAD 1 match: INCONCLUSIVE. Totals: 52 MISSING_DATA, 8 INCONCLUSIVE, 8 NO_DEMONSTRATED, 2 PROMISING.
* Not audited: Kalshi capture quote timelines (`kalshi/capture`, books/candles/trades; the 6,559-pass quote archive was too large to fetch in this session), tennis futures/aces/in-play families (no model), external Bovada/Smarkets odds as a challenger input.

## Collection repairs needed
1. CBB: capture every 15 min continuously (H6/H1 windows hold only 3 to 90 games); fix home/away mapping for neutral-site/ESPN-swap games; archive half/team-total/overtime probabilities pregame; join ESPN DK lines and availability with timestamps.
2. Soccer: publish pre-kickoff lineups (all `unknown` today), keep quotes two-sided at every horizon (31% missing/wide), record void/postponed reason for the 6,447 unsettled past-kickoff predictions, archive event data for first_to_score.
3. Tennis: get A/B first-ball truth before the entry quote for far more observations (3.1% STRICT today), join first-ball truth to frozen-producer rows, stop writing START_UNKNOWN rows into scorecards.

## Reproduce
```
D=/home/user/data   # checkouts of the branches above (git init; fetch --depth=1 --filter=blob:none; sparse checkout)
python3 -I research/outcome_intel/cbb_audit.py    --data $D --out reports/outcome_intel/cbb_audit.json
python3 -I research/outcome_intel/soccer_audit.py --root $D/soc_data-archive --out reports/outcome_intel/soccer_audit.json
python3 -I research/outcome_intel/tennis_audit.py --root $D/ten_tennis-data/tennis-edge-finder/data/research --out reports/outcome_intel/tennis_audit.json
python3 -I -m unittest discover -s tests -p 'test_outcome_intel_cbb_soccer_tennis.py'   # 31 tests
```
Reports: `{cbb,soccer,tennis}_audit.json` (per-cell schema: sport, family, horizon, inputs_available, n_games, n_contracts, price_coverage, settlement_source, market_metrics, model_metrics, incremental_gain{mean,lo,hi,holm_p}, status, reason).
No change to `incremental.py` is required. Optional: a Holm helper that pads untestable cells with p = 1 (implemented locally in `cbb_common.holm_over`).

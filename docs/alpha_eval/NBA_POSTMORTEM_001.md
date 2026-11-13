# Alpha postmortem 001: NBA, all archived market families (first real `sift-alpha-eval/1` run)

RESEARCH_ONLY. Read-only. No orders, no authority, no promotion, no production change. Aggregates only; no per-row data is committed.

**Reproduce** (local copies of three archives; no network inside the run):
`python -m alpha_eval nba-shadow --root <nba-edge-finder@nba-shadow-pure> --projection-data <nba-edge-finder@projection-data> --settlements <data-archive settlements/> --board-dir <data-archive kalshi/markets/> --out-dir reports/alpha_eval/nba`
Sources (all `chmoses98/nba-edge-finder`): `nba-shadow-pure` @ `465d3c76`, `projection-data` @ `c6f61913`, `data-archive` @ `869f7d78`. The data-archive was retrieved by targeted file download (settlements, board checkpoints), not cloned. Outputs: `reports/alpha_eval/nba/nba_shadow_cumulative.{md,json}`.

## 1. What was evaluated, and what each source is
| source | what it is | class in this report |
|---|---|---|
| `nba-shadow-pure` | frozen player-stat projections (2 arms: `sim_rotation`, `EWM5`) with a **verifiable hash chain** | PROSPECTIVE |
| `projection-data/game_forecasts` | frozen team-score distributions (`sift.game_forecast.v1`), 1,449 rows over 182 games, plus the producer's own `rho` | BACKTEST (see §2) |
| Kalshi quotes | archived listings (player props, 10-20 to 11-12) and producer market snapshots (game families, **10-18 to 11-06 only**) | n/a |
| outcomes | ESPN-derived box scores / final team scores | n/a |

Game-level forecasts are **derived**: the producer archived score distributions, not market probabilities. Alpha applies one fixed, versioned transformation (`alpha-derive:gauss-copula-notie-v1`: Gaussian copula with the producer's `rho`, both marginals exact, conditioned on no tie). That is an Alpha-owned assumption and is part of `model_version`. The producer itself calls its game-market probabilities approximate.

## 2. Freeze and independence evidence
* **Player props:** hash chain recomputed here, **918 / 918 links verified**, every file archived before kickoff, one `model_frozen_hash` per version, sports-only lineage, no source-time leaks. Class PROSPECTIVE. The chain proves no alteration after `written_at_utc`, which is the producer's own clock.
* **Game families:** no chain exists for this archive, only the producer's `generated_utc`/`archived_utc`. Alpha therefore classes them **BACKTEST** even though capture was live; they can never reach a CONFIRMED verdict. Cells are keyed on the semantic model version (`pf-1.2.1`, `pf-1.3.0`); the 27 git builds behind them are kept in metadata, because keying on build strings had split the multiple-comparison grid into about 45 underpowered cells.
* **Event identity (independent):** every priced/derived ticker's date (ET), teams and player-team were compared with the independent game record: **17,316 player-prop and 17,804 game-level tickers verified, 0 mismatches.** A mismatch would stamp the outcome `event_id` so the standard's join blocks it (unit-tested).
* **Outcome value (independent implementation):** the adapter's own result was compared with the producer's separate settle engine. Player props: **16,514 agree, 3 disagree**, 507 the engine itself calls unsettleable. Game families: **17,340 agree, 0 disagree.** The 3 disagreements are box-score values fetched right after the game that differ from a later settle run (e.g. assists 4 vs 3), consistent with ESPN post-game stat corrections; the standard blocks those rows as conflicting rather than choosing one. **This is not exchange settlement:** Kalshi's own `result` is not retained in the archive.

## 3. Coverage: every one of the 163,477 board tickers, in exactly one category
The eligible universe is every ticker that appeared on any of 208 archived full-board snapshots (a union of snapshots: a market that opened and closed between two snapshots is invisible). 145,981 are game-bound, inside the window (games 2026-10-20 to the data horizon 2026-11-12) and mapped to an ESPN game. The producer's `_support` label is shown as description only; it is never counted as a forecast.

| family | producer label | tickers | graded | fc, not graded | game not forecast | game fc, mkt not fc | frozen input, not eval. | no frozen source | after horizon | before window | not game bound |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| game_overtime | BUILDABLE | 183 | 0 | 0 | 0 | 0 | 0 | 174 | 9 | 0 | 0 |
| game_points_leader | RESEARCH | 2,307 | 0 | 0 | 0 | 0 | 0 | 2,307 | 0 | 0 | 0 |
| game_race_to | RESEARCH | 1,110 | 0 | 0 | 0 | 0 | 0 | 1,056 | 54 | 0 | 0 |
| game_spread | MODELABLE | 7,444 | 5,612 | 132 | 0 | 0 | 0 | 0 | 0 | 1,700 | 0 |
| game_total | MODELABLE | 6,501 | 4,952 | 116 | 0 | 0 | 0 | 0 | 0 | 1,433 | 0 |
| game_win_margin | BUILDABLE | 1,392 | 0 | 0 | 0 | 0 | 0 | 1,392 | 0 | 0 | 0 |
| game_winner | MODELABLE | 534 | 340 | 8 | 0 | 0 | 0 | 0 | 52 | 134 | 0 |
| period_spread | BUILDABLE | 16,428 | 0 | 0 | 0 | 0 | 0 | 15,660 | 0 | 768 | 0 |
| period_team_total | BUILDABLE | 3,828 | 0 | 0 | 0 | 0 | 0 | 3,828 | 0 | 0 | 0 |
| period_total | BUILDABLE | 16,353 | 0 | 0 | 0 | 0 | 0 | 15,660 | 0 | 693 | 0 |
| period_winner | BUILDABLE | 3,492 | 0 | 0 | 0 | 0 | 0 | 3,132 | 162 | 198 | 0 |
| player_assists | MODELABLE | 7,112 | 3,425 | 174 | 121 | 3,392 | 0 | 0 | 0 | 0 | 0 |
| player_blocks | BUILDABLE | 1,707 | 0 | 0 | 0 | 0 | 0 | 1,707 | 0 | 0 | 0 |
| player_double_double | BUILDABLE | 1,367 | 0 | 0 | 0 | 0 | 0 | 1,367 | 0 | 0 | 0 |
| player_points | MODELABLE | 8,014 | 3,952 | 173 | 134 | 3,731 | 0 | 0 | 0 | 24 | 0 |
| player_pra | BUILDABLE | 4,752 | 0 | 0 | 0 | 0 | 4,752 | 0 | 0 | 0 | 0 |
| player_rebounds | MODELABLE | 9,293 | 4,484 | 226 | 145 | 4,438 | 0 | 0 | 0 | 0 | 0 |
| player_steals | BUILDABLE | 3,377 | 0 | 0 | 0 | 0 | 0 | 3,377 | 0 | 0 | 0 |
| player_stocks | BUILDABLE | 1,255 | 0 | 0 | 0 | 0 | 0 | 1,255 | 0 | 0 | 0 |
| player_threes | MODELABLE | 9,659 | 4,648 | 209 | 149 | 4,653 | 0 | 0 | 0 | 0 | 0 |
| player_triple_double | BUILDABLE | 480 | 0 | 0 | 0 | 0 | 0 | 480 | 0 | 0 | 0 |
| player_unknown | UNRESOLVED | 39,827 | 0 | 0 | 0 | 0 | 0 | 37,006 | 2,358 | 0 | 463 |
| team_total | MODELABLE | 6,644 | 6,492 | 152 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| unknown | UNRESOLVED | 1,942 | 0 | 0 | 0 | 0 | 0 | 970 | 0 | 0 | 972 |
| 23 season-long families (awards, futures, franchise, etc.) | mostly UNMODELABLE/RESEARCH | 8,476 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8,476 |
| **ALL BOARD TICKERS** | | **163,477** | **33,905** | **1,190** | **549** | **16,214** | **4,752** | **89,371** | **2,635** | **4,950** | **9,911** |

**Result: complete eligible-market coverage is INCOMPLETE.** Of 145,981 in-window game-bound markets, **33,905 (23.2%) are forecast and graded**, 1,190 forecast but not graded, and 110,886 have no forecast. That is the honest figure; the earlier player-prop-only run (93.5% "coverage") was measured against the producer's own listing archive (18,519 tickers), which undercounts the exchange board by about half.
What the 110,886 are:
* **89,371 have no frozen source at all:** every period/quarter/half market, steals, blocks, double-doubles, stocks, points-leader, race-to, win-margin, overtime, and the 37,006 in-window tickers the producer labels `player_unknown` (this includes its `*PROT` series and `KXNBATOTALPRECISE`; their semantics are not verified here).
* **16,214 are player-prop markets in games that were forecast but whose ticker was never linked to a player.** Measured, not assumed: **11,928** sit in games for which the producer's listing archive holds no listings at all (it covers 111 of the 182 games with a game forecast); **3,073** are in games with listings but not that ticker; **1,213** are listed tickers with no projection for the player or rung. (99% of Kalshi's rungs are on the model's rung grid, so grid mismatch is not the cause.) Accuracy of those players' forecasts is still graded, ticker-less; only their pricing is lost.
* **549** are player-prop markets in games the shadow store never captured.
* **4,752** are PRA markets: a frozen player pmf exists in `projection-data` but is not yet evaluated.
Not-game-bound markets (8,476 in 23 pure season-long families, plus 1,435 inside the mixed `player_unknown`/`unknown` families) cannot be resolved inside a game window and are reported, not hidden.

## 4. Missing box-score outcomes, reconciled
Projected players absent from the box score of a finished game: **1,626 player-games**, partitioned exactly against the official NBA injury report (latest record at or before kickoff; joined by player id = negated ESPN id):
| category | player-games | treatment |
|---|---:|---|
| official **OUT** pre-kickoff | 439 | corroborated non-appearance: `void` (as a box DNP would be) |
| official DOUBTFUL | 5 | not corroborated: unscored, counted |
| reported ACTIVE/PROBABLE/QUESTIONABLE | 66 | unexplained: unscored, counted (possible data gap or coach decision) |
| no report, inside the availability archive window | 728 | unexplained: unscored, counted |
| before the availability archive began (2026-10-19) | 388 | unverifiable: unscored, counted |
| **total** | **1,626** | |
Supporting evidence: only 1 of 3,744 players who did play had been listed OUT. Separately, the settle engine marks 507 priced tickers unsettleable (`player not in box score` / `DNP`); those are counted and never override the adapter. Unexplained absences are never imputed; they appear as `NO_OUTCOME_ROW_EVENT_OVERDUE` (finished event, no outcome), distinct from `PENDING` (inside a 24h grace window).

## 5. Results (descriptive; event-clustered 95% CIs; only the primary grid is Holm/BH adjusted)
| class | family | graded fc | binary Brier | calib. slope | priced+graded rows | games | Δ Brier mkt−model [95% CI] | hyp. ROI, full priced pop. [95% CI] |
|---|---|---:|---:|---:|---:|---:|---|---|
| PROSPECTIVE | player_assists | 71,086 | 0.0773 | 0.85 | 7,772 | 100 | +0.0027 [-0.0042, +0.0102] | -7.2% [-9.8%, -4.8%] |
| PROSPECTIVE | player_points | 91,404 | 0.0868 | 0.84 | 9,452 | 103 | -0.0059 [-0.0141, +0.0023] | -9.2% [-12.2%, -6.3%] |
| PROSPECTIVE | player_rebounds | 81,244 | 0.0997 | 0.85 | 10,676 | 103 | +0.0005 [-0.0062, +0.0072] | -10.5% [-12.8%, -8.2%] |
| PROSPECTIVE | player_threes | 71,092 | 0.1034 | 0.79 | 9,854 | 102 | -0.0046 [-0.0092, +0.0004] | -9.6% [-12.0%, -7.2%] |
| BACKTEST | game_spread | 46,676 | 0.1645 | 1.09 | 27,347 | 132 | -0.0091 [-0.0160, -0.0024] | -9.5% [-18.7%, -0.3%] |
| BACKTEST | game_total | 41,168 | 0.1667 | 1.01 | 24,242 | 132 | -0.0068 [-0.0142, +0.0001] | -5.0% [-13.1%, +3.0%] |
| BACKTEST | game_winner | 2,828 | 0.2101 | 1.85 | 2,144 | 136 | -0.0246 [-0.0389, -0.0096] | -21.5% [-38.5%, -4.4%] |
| BACKTEST | team_total | 53,969 | 0.1660 | 0.97 | 29,827 | 132 | -0.0074 [-0.0126, -0.0026] | -8.4% [-14.5%, -2.7%] |

* **Primary grid (adjusted):** game moneyline, pf-1.3.0, 133 games: market better by 0.025 Brier [0.011, 0.039], Holm p = 0.004. Spread/total/team-total pooled, pf-1.3.0, 129 games: market better by 0.008 [0.003, 0.014], Holm p = 0.006. pf-1.2.1: insufficient sample (15 games). Player props (2 arms, 103 games): not distinguishable from the market.
* **Calibration:** player props OVERCONFIDENT (slope 0.83; model exceeds observed frequency). Moneyline slope 1.85: UNDERCONFIDENT, model probabilities sit too close to 50%, matching the producer's own diagnosis of shrinkage toward the middle. These are the actionable findings, and they concern the model, not the market.
* **Economics (QUOTED_HYPOTHETICAL, top-of-book taker size 1):** model-side ROI on the full priced population is negative in every family: player props -9.3% [-10.7%, -7.8%], game families -7.9% [-13.6%, -2.4%]. **No verified fills exist: NO_PROFITABILITY_CLAIM.**
* **CLV (process diagnostic, not profit):** player props +0.0056 on only 18 games, below the 30-game floor, so not a finding; game families +0.0071 [0.0049, 0.0093] on 118 games, quoted-execution CLV -0.022.
* Consistent with the producer's own independent all-families study (market is the best forecaster in every family; under-dispersed model). Agreement between two separately built analyses is evidence about the data, not a claim of edge.

## 6. Limits and defects
1. **Not exchange settlement.** Outcomes are ESPN-derived and cross-checked against a second implementation of the same source; Kalshi's `result` is unavailable.
2. **Game-family pricing covers only games through 2026-11-06** (snapshot archive); player-prop quotes are listing snapshots (median age 12.5 min), top-of-book only, no depth.
3. **Derived game forecasts depend on Alpha's copula assumption** (and the producer's `rho`); results are about `model + this transformation`.
4. Shared taxonomy defect found and worked around, not edited: `alpha_engine/taxonomy.py` `season_award` regex matches `hart` inside player codes (`NYKJHART3`).
5. Repeated grading of one ticker (slots, arms, forecast refreshes) is handled by game-level clustering and the collapse step; point estimates weight repeats equally.
6. The board universe is a union of snapshots; the producer's `_family`/`_support` labels are unverified descriptions.

## 7. Next
Evaluate PRA (frozen pmf exists); wire the period/quarter families (needs a period-level frozen source: none exists today); obtain Kalshi-official results; then apply the same standard, adapter pattern and reconciliation to the other sports.

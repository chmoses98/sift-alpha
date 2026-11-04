# Outcome & execution intelligence (`sift-research/1`) — RESEARCH_ONLY

Two coordinated studies: **A** which contracts are mispriced (net of fees, out of sample) and **B** whether acquiring early with resting limit orders beats
buying now or waiting, plus a **decision framework** that compares BUY_NOW / LIMIT / WAIT / PASS on fee-adjusted, risk-adjusted EV.
No order is placed, no model is promoted, nothing is wired to auto-betting (`sift_research.decision`/`shadow_orders` contain no client, key or order call; a test enforces it).

**Headline (what the evidence supports):** no rule, model or entry tactic tested has a validated, positive, fee-adjusted edge out of sample.
Unconditional buying loses ≈2–3¢/contract (fee + spread). The walk-forward models are *worse* than the market. Waiting is never worse than buying early for takers.
Resting orders look better than waiting only after an assumed maker-vs-taker fee gap, with queue position unknown and half the orders unevaluable. Details below.

## Reuse (no duplicate infrastructure)
`sift_clv.canonical.estimate_fee` is the fee reference (`sift_research.fees` is a vectorised twin, tested equal); `sift_clv.limit_orders` is the fill-bound semantics
(the vectorised simulator in `nfl_execution.py` is cross-checked against `simulate_limit_buy` on 200/200 real orders and 150 random tapes). The existing real-wager CLV
studies (`docs/CLV_*.md`) are unchanged.

## Code
| Path | Role |
|---|---|
| `sift_research/{fees,stats,nfl25}.py` | fee model, game-cluster bootstrap, Holm/BH, Wilson, Brier/logloss; NFL backfill + nflverse loaders |
| `sift_research/decision.py` | four-action comparison; EV-lower-confidence-bound gate; adverse selection, stale-info and fill-bound inputs |
| `sift_research/shadow_orders.py` | immutable PLACED/OBSERVED/SETTLED ledger for prospective shadow orders (no `FILLED` evidence class exists) |
| `research/outcome_exec/cfb_outcome.py` | A on CFB 2026 research corpus (44,019 prospective snapshots) |
| `research/outcome_exec/nfl_outcome.py` | A on NFL 2025 (all 381 backfilled series; walk-forward matchup model from nflverse PBP) |
| `research/outcome_exec/nfl_execution.py` | B on NFL 2025 (hourly+minute candles, full tape): taker timing, resting-order simulation, chronological selection |
| `research/outcome_exec/integration.py` | selection x execution policy backtest, parameters from discovery only |
| `research/outcome_exec/{inventory,build_summary}.py` | cross-repo tree inventory; dashboard-ready `reports/outcome_exec/summary.json` |

Reproduce (data roots are env/args; sources below): `python3 research/outcome_exec/{cfb_outcome,nfl_outcome,nfl_execution,integration,build_summary}.py`; tests: `python3 -m unittest discover -s tests -p 'test_*.py'` (152 pass).
Data: NFL `market-data` branch `data/kalshi/backfill/{markets,candles,trades}`; CFB `research-data` branch `data/research/{observations,settlements}`; nflverse `games.csv`, `play_by_play_{2024,2025}`. Outputs are aggregates of public market data only.

## 1. Data coverage and missingness (full tables: `summary.json` §1, `nfl_*.json`, `cfb_outcome.json`)
| Sport / family | Outcomes | Price history | Verdict |
|---|---|---|---|
| NFL 2025 moneyline | 566 settled tickers (284 games), 0 mismatches vs nflverse | hourly candles all, m1 last ~24h, tape for all but **capped at newest 10,000 prints/ticker (420/564 hit the cap)**; only ~⅓ of orders have tape back to placement | usable; fill evidence biased to low-volume tickers |
| NFL 2025 spread | 7,420 markets (5,795 no / 1,625 yes) | **22 playoff games only** (349 tickers) | holdout-only, thin |
| NFL totals, team totals, halves/quarters, props (381 series, 61,068 settled yes/no markets in all) | yes | **none** (only close-ish `last_price`) | outcome-only inventory; cannot test mispricing or timing |
| CFB 2026 spread/total/moneyline | 36,798 settled obs / 4,552 tickers / 96 games (wk1–2); 6,040 `pending_not_final` kept missing | EARLY_OPEN…CLOSING snapshots, executable bid/ask, **no depth, no tape, no fills** | 3 weeks; 15.6% of settled rows thin-book (>10¢ spread), 6,405/7,256 in the >72h bucket; 1,181 `ticker_unresolved` |
| NBA / NHL / soccer | archives from 2026-09-18…29 (markets+**orderbook deltas**, predictions) | real depth exists (needs `reconstruct_at`) | ≈5–6 weeks, not analysed here: best prospective maker-research source |
| MLB (edge-finder-api) | 2022-04…2026-09 snapshots/clv_quotes/postmortems/Statcast/Pinnacle | present, format not audited here | best next extension for outcome research |
| CBB / tennis | season just started / 242k files, not audited | — | later |
No fee data exists in any archive (fees are MODELLED: taker 0.07, **maker 0.0175 is an assumption**), no queue data anywhere.

## 2. Outcome-prediction findings (ranked by validated net EV, not win rate)
Chronological splits by game: NFL weeks 1–6 / 7–12 / 13+ (holdout untouched until frozen); CFB by kickoff date (32 games each, holdout = Sep 12–13 only). All CIs resample **games**; every cell tried is counted and Holm/BH adjusted.
* **NFL moneyline is efficiently priced.** Market Brier at 24h 0.2125 vs closing line 0.2117. Buying every contract at the ask: **−2.1¢** (YES, CI −2.16…−2.06) / −1.96¢ (NO). 186 market-only cells tried; 15 survived discovery→validation, **all failed holdout** (−3.8¢…−15.1¢; BH q = 1.0 on all 15).
* **The matchup model does not beat the market.** Opponent-adjusted EPA/pace/rest/weather/key-number model: margin MAE 10.60 vs 9.67 for the closing line (holdout 11.08 vs 10.08); moneyline Brier **+0.021 worse** than market (CI +0.009…+0.033). Every model-vs-ask cell had negative discovery EV (−2.8…−13.5¢), so none was selected. (Caveat: starter QB flag is approximate; injuries not used; the 2025 closing lines are a benchmark only.)
* **CFB model priced observations:** model Brier minus market-mid Brier +0.013 (spread ≤10¢ filter; CI +0.003…+0.023): model worse. Model gap ≥5¢ buys: YES −3.0¢ (CI −9.4…+3.4), NO −2.6¢ (−9.2…+4.5); buy-everything −3.09¢. 192 cells tried, 131 testable, **0 pass BH ≤ 0.10** (best BH-adjusted p 0.988). Four exploratory frozen cells (spread, mostly >72h, discovery means up to +17¢): holdout −0.7…−3.1¢, all CIs span 0 → noise.
* **Favourite–longshot after fees:** no profitable price bucket in either sport (CFB 0.2–0.3: −4.5¢, CI −8.1…−0.9; 0–0.1 bucket +0.8¢, CI spans 0).
* Ranked tables (`ranked_findings*` in the reports/summary) therefore contain only *non-demonstrated* cells, ordered by holdout/validation net-EV lower bound. **There is no validated profitable finding to rank above zero.**

## 3. Early limit-order timing and price improvement (NFL 2025; fills SIMULATED_FROM_TAPE; queue = scenario)
**Taker, moneyline, tight-spread population, early ask minus closing ask** (negative = early was dearer): 7d −1.07¢ (CI −1.33…−0.75), 48h −0.12¢ (−0.16…−0.07), 24h/6h ≈ −0.04¢ (spans 0), 90m +0.04¢ (+0.002…+0.077). Net P&L ≈ −2.1…−2.2¢ at every horizon. **Early taker minus wait-and-take:** 7d −1.1¢, 48h −0.12¢, 24h/6h ≈ 0, 90m +0.04¢. ⇒ buying early is never better than waiting; the 7d all-quote population is −2.9¢ (wide 7d spreads, median 3¢).
**Resting maker buys (moneyline, rest to kickoff, 10 lots, unfilled = 0):**
| 24h, at the bid | fill prob | profit / submitted contract | vs wait-and-take |
|---|---|---|---|
| front of queue (optimistic) | 0.99 | +1.2¢ (CI −2.3…+4.3) | +2.3¢ (+1.7…+3.1) |
| 500-contract queue (central) | 0.93 | +0.9¢ (−2.8…+3.9) | +2.0¢ (+0.6…+3.4) |
| only prints through our price (conservative) | 0.52 | +0.2¢ (−3.4…+3.9) | +1.3¢ (−2.2…+4.6) |
* Price improvement vs closing ask when filled: ≈ +1.0¢ (central), but **about 1.3¢ of the +2.0¢ edge over waiting is the assumed maker-vs-taker fee gap**; if makers pay the taker rate most of it disappears. Absolute profit is not distinguishable from zero in any cell.
* **Adverse selection** is visible but not statistically reliable: contracts that fill look worse on taker-now P&L (−8.0¢, CI −18…+3.3 for 24h ask−2¢; spread holdout −10.6¢, CI −20.4…−0.02); 17.6% of fills occurred when the mid later fell ≥3¢ vs 10.2% of all orders.
* Repost-or-cross at 90m: +1.8¢ vs taker-now (CI +1.5…+2.0), again mostly the fee gap; absolute +0.7¢ (−2.6…+3.7).
* Chronological selection: best discovery rule (90m, ask−2¢) **failed validation** (−3.8¢ / −3.3¢, BH q 0.49–0.83), holdout +1.6¢ with CI spanning 0. 48 cells per family × queue assumption.
* CFB observation-level (no fills): the mid drifts toward the model side after EARLY_OPEN (CLV ≈ +4¢ at T-3D, CI +2.1…+7.0) but paying the ask erases most of it (mark-to-market +4.2¢ CI +0.5…+8.4 at T-3D, ≈+1.5¢ at T-24H, CI spans 0), and early open mids are noisy; the model does not beat the market on settled outcomes, so this is not read as an edge.
* **Does an earlier limit order improve expected profitability versus waiting?** Not demonstrated. It is cheaper than the close *if it fills and if the maker fee is lower*; adverse selection and unknown queue position are unquantified; the covered order set is tape-limited.

## 4. Net returns
Every EV above is per contract net of modelled fees held to settlement (no exit fee). Real-wager P&L is not used or published (see `docs/CLV_EXECUTABLE.md`).

## 5. Combined market-selection / execution framework (`integration.json`, 24h, moneyline, 562 opportunities)
Parameters from weeks 1–6 only: model-vs-market shrinkage **β = 0.0** (the model adds no information beyond the market on discovery), fill table by cents below ask, adverse selection +3–4.5¢.
Validation (n=170) / holdout (n=208), cents per contract net: ALWAYS_BUY_NOW −2.05 (CI −2.14…−1.96) / −2.20 (−2.29…−2.12); raw model gap >2¢ buy-now −2.4 (−6.3…+1.4) / −0.9 (−4.7…+3.2); always limit at ask−2¢ (central queue; ~⅔ of orders unevaluable) −0.4 (−8.7…+7.0) / −2.9 (−9.2…+2.6); **FRAMEWORK = PASS on all 378 opportunities (0.0)**. With β=0 the framework correctly declines every trade; it limits loss, it does not create profit.

## 6. Recommendations for prospective validation
1. **Shadow orders with live books.** Log PLACED snapshots (`shadow_orders.placed`) at 7d/72h/48h/24h/6h/90m for every priced contract (moneyline, spread, total) from a frozen model version, **with depth and queue snapshots every few minutes**, evidence classes TAPE_TOUCH/FILL_BOUND only. NBA/NHL orderbook-delta archives already exist for this; reconstruct them first.
2. **Fix the tape cap:** page the backfill trade collector backward until the market open (currently newest 10,000 prints) so ≥90% of orders have tape from placement; add totals/team totals/halves/props candles+trades (currently outcome-only). These live in the NFL collector; not changed here.
3. **Record the real maker/taker fee per series and per fill** (no archive has one); re-run §3 with observed fees — the main result hinges on it.
4. **Power:** a 2¢ edge on a ≈±0.5 P&L contract needs ≈4,700 independent contracts at 80% power; one NFL season has ≈285 games. Pre-register the cell list and pool families; don't expect single-family confirmation in one season.
5. Pre-register the CFB model/gap rule now and judge it on the next ≥8 weeks of settled games only; capture injury/news timestamps to measure stale-information losses on resting orders.
6. Extend outcome research to MLB (2022–2026 archive) first, then NBA/NHL once ≥1 season of archives exist.

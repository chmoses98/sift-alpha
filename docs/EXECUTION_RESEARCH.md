# Execution & market-entry research track (`sift-exec/1`) — RESEARCH_ONLY

Scope: sift-alpha issue #23 (items 3-5), nfl-edge-finder issue #246. Stacked on PR #25 (aa263fc). **No orders, no execution authority, no model changes, nothing merged.**
Every fill below is `SIMULATED_FROM_TAPE` / `SIMULATED_FROM_CAPTURE_TAPE` or a bound; no archive contains an observed order state. Outputs: `reports/exec_track/*.json` (public market data aggregates only).

## 0. Verdict (does any entry tactic improve net expected profitability?)
**No tactic is shown to be profitable in absolute terms; one tactic is shown to be cheaper than waiting, and only conditionally.**
* *Absolute net EV (don't-bet-if-unfilled resting bids; BUY_NOW; WAIT):* **not demonstrated.** Under the pre-registered protocol (§6) the absolute claim fails validation under the conservative fill bound in every fee scenario
  (holdout −0.35 / −0.61¢ at M0 / M25; both bounds are required), and the only passing variant assumes that every order whose fill status the data cannot resolve filled at an `ask−5¢` limit — an assumption artefact, not evidence. BUY_NOW/WAIT lose ≈2.1¢/contract (fee + spread) at every horizon; the 2026 live capture agrees (WAIT −2.08¢).
* *Relative execution cost (equal exposure, resting bid with taker fallback at the close vs WAIT-and-take at the close):* **cheaper by ≈ +0.2…+0.65¢/contract at the 2026 live displayed queue (M25), ≈ +0.3…+2.6¢ in the 2025 backfill across fill bounds and fee scenarios M0/M25 (queue 500 assumed), and ≈ 0 when makers pay the taker rate (M100).** It passes the pre-registered, Holm-corrected chronological test under M0, is borderline at M25 (Holm p = 0.060; descriptive holdout +0.75¢, ci90 [+0.12, +1.28]) and fails under M100. It is an execution-cost reduction on identical decisions, **not** alpha: it creates no edge when the position itself has none (PR #25: no selection rule beats the market), and absolute EV stays ≈ 0 or negative.
* *Early taker entry:* never better than waiting (7d: −1.10¢ [−1.38,−0.82]; 48h −0.12¢; ≤24h ≈ 0; 90m +0.04¢) — reproduces PR #25.
* The decisive unknowns are the **maker fee** (not observed anywhere; M0/M25/M100 flips the answer) and the **real queue** (2026 displayed best-bid size is 170k-350k contracts, so the 2025 `Q500` central scenario was far too optimistic).

## 1. Independent reproduction (priority 1) — `research/exec_track/repro_pr25.py`
* Rerunning PR #25's `nfl_execution.py` on the market-data backfill reproduces its committed `nfl_execution.json` **bit-for-bit (107,574 numbers)**.
* A from-scratch loader (`sift_exec/nfl_data.py`: quote lookups match PR #25's on 6,405/6,405 probes), fill replay (`sift_exec/fills.py`: per-print state machine, per-fill output; agrees with `sim_fill` on 6,000 random cases) and fee code (`sift_exec/fees.py`) re-derive **all 384 moneyline/spread V0 maker cells: identical order counts, fill probabilities and P&L (max |Δ| = 0.0¢)**.
  The arithmetic of PR #25 is correct; the issues below are about *what is assumed and compared*, not mistakes in computation.
* Early taker vs wait (moneyline, tight spread, determinate): see §0; maker 24h at-bid (FRONT/Q500/THROUGH_ONLY) fill 0.99/0.93/0.52 reproduced exactly (expiry = kickoff in that comparison; this track expires at the close, kickoff−15m, to leave time for the fallback).

## 2. Fee validation by series (priority 2) — `research/exec_track/fee_evidence.py`, `reports/exec_track/fee_evidence.json`
Evidence found on market-data `data/kalshi/fees/*.json` (8 weekly exchange captures of `GET /series` `fee_type` and `GET /series/fee_changes`), which PR #26 did not use ("exchange fee fields could not be fetched"):
| series | exchange `fee_type` | maker evidence |
|---|---|---|
| KXNFLGAME | `quadratic_with_maker_fees` ×1 (fee change effective 2026-01-01T08:00Z; no earlier record in the archive) | **SCHEDULE_ATTESTED**: listed maker multiplier 1.0 ⇒ 0.0175 coefficient (2026 season) |
| KXNFLSPREAD, KXNFLTOTAL | `quadratic_with_maker_fees` ×1 | **UNVERIFIED** (no listed maker multiplier; fail closed) |
| 367 other archived NFL-family series (props, 1H/2H, team totals, …) | `quadratic` (taker-only) | maker fee 0 (exchange type) |
| NBA / NHL / CFB series | not in any fee archive | UNVERIFIED — scenarios only |
Taker 0.07 stays empirically confirmed (643/646 real fees, PR #26). **No real maker fill exists, so no maker fee is observed anywhere.** Correction to PR #26: "0.0175 is an upper bound" is wrong for the NFL moneyline/spread/total series — the exchange labels them maker-fee series, so M0 is *not* supported for 2026 `KXNFLGAME`; M25 is the supported point, M0 and M100 are reported as sensitivities. For the 2025 season (before the 2026-01-01 change record) the maker fee type is undocumented here.
All results are reported under `M0` (0), `M25` (0.0175), `M100` (0.07); fees are whole-order cent-rounded (an upper bound with every fill ceiled independently changes 24h-at-bid by −0.004¢).

## 3. NFL tape truncation and fill provenance (priority 4) — `research/exec_track/tape_audit.py`, `reports/exec_track/tape_audit.json`
* **The cap is exact:** all 420 capped `KXNFLGAME` tickers (of 566) and 19 `KXNFLSPREAD` (of 349) contain exactly 10,000 lines. The newest 10,000 prints are kept, so the **median oldest retained print is 1.4 h *after* kickoff** (78.6% of capped moneyline tickers: the retained tape is in-game only) and **58% of moneyline contract volume (by `volume_fp`) has no tape** (capped tickers retain 37% of their volume).
* **Selection bias:** orders with a determinate tape come from the *least liquid* tickers (uncapped median volume 2.3M vs capped 8.8M contracts) — fill statistics from tape alone describe thin markets, not the games people trade. Only 177/562 (31%) of 24h moneyline orders are tape-determinate.
* **Candles survive the cap and are exact:** on complete-tape tickers hourly candle `price.low` / `price.high` / `volume` equal the tape's min/max/sum in **40,797/40,797** hourly candles, and all 535,279 pre-kickoff prints fall in hours that have a candle. `sift_exec/candles.py` therefore classifies an uncertain order as `THROUGH` (a print strictly below our bid must be a taker sell through our level ⇒ certain fill), `UNFILLED_CERTAIN`, `AT_LEVEL_POSSIBLE` (queue-dependent) or `UNRESOLVED_EDGE`. Validation on complete tapes: **`UNFILLED_CERTAIN`: 564/564 agree (no false "unfilled"); `THROUGH`: 7,414 agree with a tape-through fill, 95 are cases the PR #25 simulator misses** — the market's ask fell through our bid (a taker-*buy* print below our limit); all 95 are explained and are now counted (`through_any_side`). Resolution of the population: 75% of 24h moneyline orders (86% at 7d) have an exactly known fill status instead of 31%.
* **Queue is an assumption, not data, in 2025.** The 2026 live capture shows why it matters: displayed best-bid size at placement is median 170k (24h) / 257k (6h) / 351k (90m) contracts (98% ≥ 500), so `Q500` over-states fills by an order of magnitude.
* **Collector fix (nfl-edge-finder #246) — requested, not made here:** (1) page the backfill trade collector backward until market open (stop at 10,000 prints/ticker); (2) store the page cursor/oldest-timestamp per ticker and mark `tape_complete`; (3) keep per-ticker candle periods (they are exact and cheap); (4) record the real maker/taker role + fee per own fill; (5) log best-bid *queue size* at our level with each shadow-order PLACED record (the capture already has `yes_bid_size_fp`).

## 4. NBA/NHL books (priority 3) — `sift_exec/books.py`, `research/exec_track/book_depth.py`, `reports/exec_track/book_depth_{nba,nhl}.json`
`BookArchive.reconstruct_at(t)` rebuilds the top-10 levels per side for ~300 tracked markets from `kalshi/orderbooks` bases + cumulative `orderbooks_delta` (5-10 min cadence, never uses a later snapshot; tested). **There is no trade tape in either archive**, so fills cannot be simulated — only bounded. Pre-game results (≈500 sampled snapshots each; NBA 2026-09-28→11-04, 360 events; NHL 2026-09-29→11-04, 775 events):
| series, hours to start | spread (median) | best-bid size (median) | share ≥500 | slippage for 100 contracts | at-bid fill upper bound* |
|---|---|---|---|---|---|
| NBA game, 2-6h | 1¢ | 3.3k | 83% | 0¢ | 99.8% |
| NBA game, 24-72h | 3¢ | 348 | 45% | 0¢ | 100% |
| NBA spread, 2-6h | 2¢ | 198 | 35% | 0¢ | 89% |
| NBA total, 24-72h | 32¢ | 15 | 5% | 0.85¢ | 93% |
| NHL game, 2-6h | 1¢ | 23.5k | 88% | 0¢ | 99% |
| NHL spread, 6-24h | 1¢ | 5.7k | 86% | 0¢ | 62% |
| NHL total, 0.5-2h | 2¢ | 85 | 26% | 0.07¢ | 84% |
\*share of (market, snapshot) pairs where cumulative traded volume to the start exceeds the displayed queue — a **necessary** condition only, an upper bound. Findings: game-winner books are deep (100-contract orders walk at the touch; the closing-ask CLV can be called size-adjusted for ≤100 contracts only where the archive covers it), props/totals far from the start are thin (spreads of 27-32¢), and displayed queues of thousands of contracts mean at-bid fills need through-prints. Limits: 10 levels only, ~300 tracked markets (not every game market), settled outcomes were not joined (no fill ⇒ no P&L to attribute).

## 5. Corrections to the shadow-order evaluator (priority 5) — `sift_research/shadow_orders.py` (`sift-shadow-orders/2`)
v1 `evaluate()` was wrong in six ways, all fixed and unit-tested (`tests/test_research_core.py`):
1. **Fee-free P&L** (`(win − price)·100`); now taker 0.07 / maker scenarios M0, M25, M100, whole-order rounding.
2. **Inverted bounds:** `pnl_up = pnl·fill_up`, `pnl_lo = pnl·fill_lo` labelled the *worse* result as the "lower fill bound" whenever a contract loses; now `worst`/`best` = min/max of the P&L at `fill_lo` and `fill_up`.
3. **BUY_NOW never counted** (no tape evidence ⇒ 0 fills) and **WAIT priced at the placement ask**; BUY_NOW is taken at the quote (capped by displayed ask size), WAIT at the close ask (`settled(close_bid, close_ask)`), missing close ⇒ counted `unevaluable_no_close`.
4. **Quantity ignored**; now respected (observed `size` caps a LO fill).
5. **No equal-exposure option**; `fallback="TAKE_AT_CLOSE"` buys the unfilled remainder at the close ask.
6. **Evidence at/after kickoff accepted**; now rejected. A `TAPE_TOUCH` is still never a fill.

## 6. Decision-level counterfactual (priorities 6-8) — `sift_exec/study.py`, `research/exec_track/nfl_study.py`
**Decisions** = every valid moneyline contract-side (10 contracts, horizons 7d/72h/48h/24h/6h/90m, quote spread ≤ 10¢, close quote = last valid two-sided quote ≤ kickoff−15m). No selection signal is applied (none beats the market), so differences between tactics are pure execution; a real edge would add the same amount to each. Tactics on identical decisions: `BUY_NOW`, `WAIT` (taker at close ask), `LIMIT_<rule>` + `FB` (unfilled remainder taken at the close ask = **equal exposure**) or `NB` (unfilled = no bet; exposure = fill). Value per contract in cents, all-in of fees, `V_mark` = close mid − cost (settlement-free) and `V_settle` (held to settlement). At equal exposure the payoff cancels, so `FB − WAIT` is the same under both marks (tested) and has none of the outcome noise PR #25's P&L CIs carried.
* **Population and bounds.** Point estimates use tape-determinate orders; whole-population bounds use candle evidence (`filled_lo` / `filled_hi`, §3) for the rest. 2025, moneyline, `FB − WAIT` (¢/contract, M25 | M0), Q500 [lower bound … upper bound], all 562 (24h) / 399 (7d) valid orders:
| horizon / rule | M25 | M0 |
|---|---|---|
| 7d at bid | +1.21 … +2.26 | +1.54 … +2.65 |
| 24h at bid | +1.07 … +2.06 | +1.37 … +2.48 |
| 24h ask−1 | +1.20 … +1.99 | +1.53 … +2.41 |
| 90m ask−1 | +1.00 … +1.97 | +1.24 … +2.37 |
  Under `THROUGH_ONLY` (no at-level fills, conservative) 24h-at-bid M25 is +0.60 … +1.63. Determinate-only M100: 24h at bid +0.90 [0.67,1.13], 7d +0.82 [−0.30, 2.01]. The 7d horizon benefits from wide early spreads (median 3¢).
* **Missed fills, partials, adverse selection** (24h at bid, Q500, determinate): fill 92.7%, partial 0% (FRONT 1.1%); orders that fill have close-mid edge 3.1¢ *lower* than those that don't (adverse selection −3.1¢; THROUGH_ONLY −2.7¢; point estimates, not separately tested) — the cost of "winning" the queue is that the mid then fell; the fallback leg prices that in, which is why the net improvement is ≈ 1-2¢ rather than the 3¢ naive price improvement. Absolute `NB` value per submitted contract (24h at bid): M0 +0.42 [0.21,0.64], **M25 +0.05 [−0.16, +0.28]**, M100 −0.89 [−1.10,−0.64].
* **Pre-registered protocol** (frozen before validation/holdout; `nfl_study.prereg`): family = moneyline, all valid orders (tape-uncertain included, fill status bounded), Q500, 6 horizons × 8 rules = 48 cells; claim R: `FB − WAIT > 0` on the conservative fill lower bound; claim A: `NB` per submitted contract > 0 under *both* fill bounds; select the top discovery cell (weeks 1-6); validation (weeks 7-12) requires the selected cell's **Holm-adjusted one-sided p < 0.05 over all 48 cells**; only then one holdout test (13+, incl. playoffs), one-sided p < 0.05. Game-clustered bootstrap (1,000 resamples).
  **How to read the numbers (review finding, clarified):** `p_one_sided` is half the two-sided *shift-method* bootstrap p for H1: mean > 0 (floor 1/1001, so 0.0005 means "no resample crossed"); `ci95` is the two-sided 95% percentile interval; `ci90` is reported because a one-sided p < 0.05 corresponds to the *lower end of the 90% interval* being above 0 — a holdout can show ci95 lower < 0 and p_one_sided < 0.05 without contradiction. Holm/BH use one-sided p for every cell (the first draft mixed two-sided cell p-values with a one-sided test on the selected cell).
  Result (Holm-gated): **R passes at M0** (selected 7d at bid: validation +1.21¢, Holm p = 0.024; holdout +1.05¢ ci95 [0.27, 1.71], p = 0.0025), is **borderline-failing at M25** (validation +0.89¢, raw one-sided p = 0.003 but Holm-adjusted p = 0.060 — not tested under the protocol; the descriptive holdout is +0.75¢, ci90 [+0.12, +1.28], 65 games) and **fails at M100** (validation +0.07¢, Holm p = 1.0; holdout −0.04¢). **A fails** on the lower fill bound in every scenario (holdout −0.35 M0, −0.61 M25); the upper-bound variant "passes" (+1.5¢ M25) only because unresolved orders are assumed filled at ask−5¢ — rejected as an artefact; claim A requires both bounds, so it fails. An earlier draft of this document said R passed at M25; that was reported under a gate that did not apply the multiple-comparison correction it claimed.
* **Out-of-sample 2026 live capture, with real depth** (`nfl_live_2026.py`, 121 games, weeks 1-8, 15-min quote snapshots, queue = displayed bid size): fill probability at the bid is only 33% (24h) / 26% (6h) / 14% (90m) (`THROUGH_ONLY` 32% at 24h); `FB − WAIT` at M25: 24h at bid +0.40¢ [+0.29,+0.51]; ask−2 +0.65 [+0.51,+0.78]; 6h +0.29; 90m +0.20; at M0 up to +0.79; at **M100 ≈ 0** (+0.01 [−0.06,+0.09]). Weeks 5-8 ≥ weeks 1-4 at 24h. `NB` per submitted contract is negative (−0.31¢ at 24h, M25). WAIT costs −2.08¢. Gap-free capture only (24h: 176 of 242 contract-sides determinate; 7d is excluded: 194/242 have capture gaps).
* **Validation of `sift_research.decision`** (`validate_decision.py`; p = placement mid, parameters fit on weeks 1-6 only): the module's fill table **over-predicts deep limits out of sample** (ask−2: predicted 72% vs realised 55% validation / 67% holdout) and over-states the `LIMIT_FB − BUY_NOW` advantage there (+2.2 predicted vs +1.3 / +1.5 realised) while under-predicting ask−1 (+1.35 vs +2.05 / +1.92). Two code fixes: maker fee now uses the actual order size and a maker-coefficient scenario (`ExecParams.maker_coef`; the module priced fees on a 1-contract order, whose ceil-to-cent rounding overstates a 10-lot — taker 2¢ vs 1.8¢, maker 1¢ vs 0.5¢ per contract at 50¢ — and the maker side most) and a new equal-exposure action `LIMIT_FB` (`decide(..., include_fallback=True)`); the legacy `LIMIT` (unfilled = no bet), `WAIT` and `BUY_NOW` carry *different exposures* and should not be ranked on EV per submitted contract.

## 7. Statistics and exclusions
Clusters = games (a game contributes ~2 correlated contracts); 1,000 bootstrap resamples; chronological splits as PR #25 (weeks 1-6 / 7-12 / 13+). Exclusions with counts are in each report's `audit` (e.g. 24h moneyline: 562 valid of 566 contract-sides at ≤10¢ spread; 385 tape-uncertain, resolved or bracketed by candle evidence; 2026 live: 36 of 242 excluded for capture gaps, 28 for no valid quote). No real-user wager, private order or amount is used or published; a real wager is never called a SIFT selection here.

## 8. Limits and what would change the answer
* One NFL season of backfill + 8 weeks of live capture, one sport with real depth; NBA/NHL have depth but no tape (so no entry-tactic P&L).
* Maker fee unobserved (§2); 2025-season maker fee type undocumented; spread/total series UNVERIFIED.
* Queue: 2025 scenarios; 2026 displayed size only for the best level (cancellations ahead of us, queue additions, hidden liquidity are unmodelled; they cut both ways).
* Our order does not move the market; 10 contracts only (game-winner depth supports 100; props do not).
* Marking at the close mid assumes an efficient close (PR #25: Brier 0.2117); a post-close information edge would not show here.
* **To settle the question:** ≥ one real maker fill per series (observed role + fee) and a prospective shadow-order ledger with depth snapshots (PLACED rows carry queue size; `OBSERVED` from the full tape; v2 evaluator), judged on the pre-registered claim R at the supported fee.

## Reproduce
```
# data: market-data branches of nfl-edge-finder (backfill, fees, capture) and data-archive branches of nba-/NHL-edge-finder; nflverse games.csv
export SIFT_NFL_BACKFILL=.../data/kalshi/backfill SIFT_NFLVERSE_GAMES=.../games.csv
python3 research/exec_track/repro_pr25.py   --cache ticks.pkl
python3 research/exec_track/nfl_study.py    --cache ticks.pkl
python3 research/exec_track/tape_audit.py   --cache ticks.pkl
python3 research/exec_track/validate_decision.py --cache ticks.pkl
python3 research/exec_track/fee_evidence.py --fees .../data/kalshi/fees --schedule config/kalshi_fee_schedule.json --out reports/exec_track/fee_evidence.json
python3 research/exec_track/extract_nfl_capture.py CLONE EXT_DIR && python3 research/exec_track/nfl_live_2026.py --ext EXT_DIR
python3 research/exec_track/book_depth.py --archive NBA_OR_NHL_CLONE --sport nba --max-snapshots 500 --out reports/exec_track/book_depth_nba.json
python3 -m unittest discover -s tests -p 'test_*.py'   # 175 pass
```

## 9. Independent code review of this track (findings and status)
| # | finding | status |
|---|---|---|
| 1 | Holm/BH mixed two-sided cell p-values with a one-sided test on the selected cell; pass gate ignored the correction | **fixed** (one-sided throughout; Holm gate) — flips the M25 verdict to borderline-fail |
| 2 | `p_one_sided` vs `ci95` looked contradictory (holdout p = 0.021, ci95 lower −0.02) | **clarified** + `ci90` reported |
| 3 | Scenario queue (Q500…) applied to limits *inside* the spread, where the order is first in line (PR #25 did too) | **fixed** (`queue_inside_spread=False`; the reproduction runs with PR #25's parity flag and still matches 384/384) |
| 4 | CI ran only `test_research_*.py`: this track's tests were never run in CI | **fixed** (`research-tests.yml` runs the full suite, includes `sift_exec/**`) |
| 5 | PR #26 / `sift_research.fees` docstrings: "makers pay nothing on most series / 0.0175 is an upper bound" | **corrected** (§2; `docs/FEE_VALIDATION.md` erratum) |
| 6 | Capture trades return ≤ 5,000 prints per run per ticker (observed max) — in-game bursts can exceed it; the 2026 study only uses pre-kickoff windows with gap-free quote cadence, but trade-cadence completeness is not independently proven | **open** → collector change: record per-run counts and cursor exhaustion (nfl-edge-finder #246) |
| 7 | The 7d horizon rests on 399 contracts / 212 games with 3¢ median spreads | noted; selected cell is a sample-size-limited winner of 48 |
| 8 | Fees: whole-order rounding vs the exchange's per-order accumulator; per-fill-ceil upper bound differs by −0.004¢ | acceptable, documented |
| 9 | Marking at the close mid presumes an efficient close | documented limit |

## 10. Infrastructure added after the first review (this revision)
* **Collector (nfl-edge-finder #246 → PR #247):** the 10k cap is `max_pages=10` × `limit=1000` in `backfill.py`, collector-imposed, with a `complete` flag that ignored it. Cursor-resumable pre-kickoff tape recovery, truthful `tape_complete`, candle-vs-tape verification, source-gap marking, capture gap bookkeeping and a family-level coverage report are implemented and unit-tested; **after-coverage is not claimed** because the Kalshi API is unreachable from the build sandbox (HTTP 403) — the repair workflow must be dispatched from Actions.
* **Correction to §1/§2 of PR #25's coverage claim:** totals, team totals, halves and props are *not* price-less: `backfill/horizons` holds 54,364 one-quote-per-horizon rows, 46,077 of them with a two-sided pre-start quote (e.g. KXNFLTOTAL 4,825/5,918). What is missing for them is **tape and candles**, not prices. Horizon-level entry-timing (taker early vs close) can therefore be tested for these families now; fill simulation cannot.
* **Fee reconciliation (`fee_reconcile.py`, `reports/exec_track/fee_reconciliation.json`):** aggregates of already-authorized exchange-reported fills reconciled with the exchange `fee_type` metadata: 23 NFL series consistent, 30 (NBA/NHL/CFB etc.) have no fee metadata; **0 series have an observed maker-class fill**. Maker coefficients remain scenarios.
* **Shadow ledger (docs/SHADOW_LEDGER.md):** matched BUY_NOW / WAIT / LIMIT / LIMIT_FB / PASS ledger with displayed queue, fill-evidence classes and SETTLED rows; 30-minute workflow writing to the `shadow-data` branch; retrospective rows are labelled and excluded from "prospective". Replay of 2026 weeks 1–8: conservative (`lo`) `LIMIT_FB − WAIT` is +0.11…+0.33¢ at M25 and ≈ 0 at M100; the only rule with a positive central estimate at M100 is the deeper `ask−2` limit (+0.28¢ [0.18, 0.37]) whose queue below the best bid is unobserved.
* **Dashboard:** `src/exec-research.jsx` (existing Vite app, no redesign) renders `research/audit/exec/execution_research_summary.json`: strategy costs, maker-fee verification, queue/fill evidence, shadow results, collector health, outcome candidates, and the RESEARCH_ONLY / no-validated-strategy status; `Dashboard CI` privacy checks cover the new payload.
* **Outcome side (kept separate):** `outcome_family_scan.py` — market-only buy-at-ask-and-hold across every family with horizon quotes (T-168h / T-24h / T-90m, 61,974 quote observations, 34 cells with ≥30 observations per split, taker fee 0.07, weeks 1-6 / 7-12 / 13+, game clusters, Holm/BH over all cells): **0 cells positive in both validation and holdout; 0 pass a Holm-corrected holdout test.** Closest to the market (still negative): `KXNFLGAME` T-168h NO (holdout −1.20¢ [−3.67, +2.16]), `KXNFL2TD` YES (−1.21¢ [−3.37, +1.01]), `KXNFLSPREAD` YES at T-90m/T-24h (−1.4…−1.7¢, intervals ±4¢). The market-implied probability is therefore not beaten by any unconditional family rule after fees; the useful outcome work is model-vs-market on the non-moneyline families, where 46k pre-start quotes now exist (the key-number-aware distribution reported in nfl-edge-finder #232/#245 is the nearest candidate and is **not** validated here).

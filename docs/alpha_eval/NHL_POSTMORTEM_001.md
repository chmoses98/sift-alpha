# NHL postmortem 001: NHL-edge-finder frozen forecasts vs Kalshi (sift-alpha-eval/1)

RESEARCH_ONLY. Read-only. No orders, no authority, no promotion, no production change. Aggregates only; no per-row data is committed.

Reproduce: `python -m alpha_eval nhl-archive --root <sparse data-archive checkout> --file-adds <git log listing> --kalshi-dir <settled pages> --as-of 2026-11-13T04:23:45Z --out-dir reports/alpha_eval/nhl`. Inputs and digests: `reports/alpha_eval/nhl/inputs.json`. Full report: `reports/alpha_eval/nhl/nhl_archive_cumulative.{md,json}`.

## What was evaluated

* **Forecasts**: the producer's own frozen per-contract probabilities, three arms, unmodified: `DATA_ONLY_V1` (`p_data_only`), `DATA_ONLY_V2` (`p_data_only_v2`), `PLAYER_SIM_V1` (`p_player`, player props + first goal + goalie saves). Market-anchored columns are excluded because they consume the quote. All three are declared `sports_only` by the producer; Alpha does not verify that.
* **Selection** (fixed before any outcome was read, outcome-independent): per arm × ticker, the latest capture made before the scheduled start whose archive file was committed before that start. 74,749 forecasts on 309 games (2026-09-29 to 2026-11-12 ET).
* **Freeze evidence**: `data-archive` is an append-only git ledger. The commit that first added each forecast file is its freeze attestation. Checks: the earlier audit's pinned head `eacc3b9d` is an ancestor of `a466e2cb` (no rewrite), all 2,966 forecast files were added once and never modified or deleted, and 4/4 sampled commits fall inside the GitHub-recorded window of the Actions run their message names. 74,741 forecasts are attested `PROSPECTIVE`. 8 had no capture committed before puck drop; they carry `frozen_at` = commit time and the standard blocks them.
* **Outcomes**: **Kalshi's own settlement** (`result`). 75,364 settled markets came from the public endpoint in 142 anonymous calls (cap 1,500); the raw pages are kept outside the repository. Two independent checks:
  * **Event identity.** Each Kalshi event ticker's date and team codes were matched to the NHL schedule archive: 75,068/75,068 mapped. The standard's join would block any mismatch with the producer's `game_id`; none occurred.
  * **Value.** Kalshi's result was compared with the producer's settle engine (NHL API box and goal events): 64,930 agree, **44 disagree**, 7,441 have no producer settlement and 2,649 the producer could not settle. The 44 are goalie saves (28) and assist/point credits (16), consistent with NHL stat revisions. A disagreement adds a conflicting row, so the standard **blocks** those markets (18 forecasts). Nothing is resolved by choosing a side.
  * **Scalar settlements.** 1,356 player markets settled `scalar`: Kalshi's rule for "active but never entered" settles at the last pre-start fair price. Player probabilities are conditional on playing, so these are **void**, as NBA DNP contracts were.
* **Quotes**: the Kalshi yes bid/ask each producer capture read from its board at prediction time, so model and market are compared at the same instant. The closing quote is the last capture before start.

## Coverage: INCOMPLETE (measured)

Eligible universe: every settled Kalshi market in a game-bound NHL series in the window (75,068), plus 398 producer-listed tickers Kalshi had not settled. That is **75,466 markets**, each placed in exactly one category (the partition is asserted):

| category | markets | share |
|---|---:|---:|
| forecast and graded | 65,578 | 86.9% |
| forecast, not graded (Nov 12/13 games not yet settled at the data horizon, void, conflict, not frozen) | 1,446 | 1.9% |
| not forecast: never listed by the producer | 5,620 | 7.4% |
| not forecast: listed, probability always null | 2,822 | 3.7% |

The gaps are concentrated:
* **Never listed.** Game spreads (1,186), period totals (1,968), period spreads (616) and player props (1,308): the producer's contract map lists only a subset of the strikes Kalshi offered.
* **Null probability.** Every `game_early_goal` (309) and `game_overtime` (309) market, plus 2,204 player/first-goal/saves contracts.
* **Missing arm/family pairs.** V1 emits no period or player probabilities. V2 emits no player probabilities.

No other game-bound NHL series settled in the window. 296 non-game markets (next-team and similar) are out of scope.

The market comparison has its own gap: 11,078 `PLAYER_SIM_V1` forecasts have no usable quote at freeze (7,661 none, 3,417 older than the standard's limit). They are graded for accuracy and **blocked** for model-vs-market and economics.

## Results (PROSPECTIVE, primary grid, Holm over 7 cells)

Δ Brier = market − model (positive favours the model), event-clustered.

| family | arm | rows | games | Δ Brier [95% CI] | p_holm | verdict |
|---|---|---:|---:|---|---:|---|
| moneyline | V1 | 614 | 307 | −0.0076 [−0.0137, −0.0008] | 0.046 | MARKET_BETTER |
| moneyline | V2 | 614 | 307 | −0.0116 [−0.0188, −0.0044] | 0.006 | MARKET_BETTER |
| spread/total/team-total ladders | V1 | 7,023 | 308 | −0.0036 [−0.0054, −0.0017] | 0.004 | MARKET_BETTER |
| spread/total/team-total ladders | V2 | 7,023 | 308 | −0.0032 [−0.0048, −0.0015] | 0.004 | MARKET_BETTER |
| period | V2 | 7,394 | 309 | −0.0011 [−0.0019, −0.0003] | 0.015 | MARKET_BETTER |
| player props | PLAYER_SIM_V1 | 35,656 | 302 | −0.0020 [−0.0027, −0.0013] | 0.004 | MARKET_BETTER |
| first goal | PLAYER_SIM_V1 | 3,772 | 279 | +0.0004 [−0.0001, +0.0010] | 0.16 | NOT_DISTINGUISHABLE |

* **The market beats every NHL arm in 6 of 7 cells.** The seventh (first goal) is indistinguishable. No cell favours a model.
* **Calibration** is roughly fine overall (Brier 0.128, signed bias −0.008), but the models under-forecast YES from 0.4 to 0.9 (gaps −0.02 to −0.04). Several family slices read UNDERCONFIDENT (moneyline, game total, period spread, period total, period winner).
* **Economics** (`QUOTED_HYPOTHETICAL`): buying the model-favoured side at the archived ask, with taker fee, returns ROI **−7.1%** [−8.6%, −5.5%] over all 62,096 priced rows. The positive-edge subset, which is selection-biased, returns −8.1%. **No verified fills: NO_PROFITABILITY_CLAIM.**
* **CLV**: selection CLV +0.00004 (≈0); quoted-execution CLV −0.011 (the half-spread). The models do not anticipate the closing line.

### Follow-up on the prior audit's only candidate

`reports/outcome_intel/nba_nhl_SUMMARY.md` carried one NHL candidate forward: `PLAYER_SIM_V1` goalie saves, PROMISING_INSUFFICIENT (log-loss gain vs a *calibrated* market, T−1h, data through `eacc3b9d`).

The confirmation test was fixed before any goalie-saves number on later games was computed: games starting after that pin (2026-11-04T19:38:30Z), the standard's paired Brier delta, two-sided, alpha 0.05. Result: **NOT_CONFIRMED**. 104 rows on 60 games, Δ Brier −0.0047 [−0.0123, +0.0034], p 0.25; the point estimate favours the market.

Under this standard's method (raw mid, latest attested capture) the pre-pin window is also indistinguishable (+0.0025 [−0.0068, +0.0109], 230 games). The earlier signal does not survive a change of baseline, and it does not replicate prospectively. It stays RESEARCH_ONLY. Sixty post-pin games is low power, so this is "not confirmed", not "refuted".

The secondary per-native-family table (its own Holm family, not a promotion input) is in the full report. No native-family cell favours a model in any window.

## Limitations

1. **Freeze attestation** rests on the producer runner's git commit times on an append-only branch, corroborated by Actions run windows that are hours long. This is weaker than an external timestamp or a hash chain. "PROSPECTIVE" here means attested by the producer's own ledger.
2. **Kalshi results** were fetched at 04:53–04:55Z, after the archive head (04:23Z). The data horizon for overdue judgements is the archive head.
3. **Quotes** are the producer's board reads (top of book, no depth). The archived full board and delta stream was not replayed here, so the 11,078 unquoted player forecasts may be recoverable.
4. **One forecast per arm and ticker** (the latest attested capture, mostly under 2h before start). Earlier-horizon skill is not measured here.
5. **Model independence** (`sports_only`) is the producer's declaration.
6. **The 44 Kalshi-vs-producer disagreements** are blocked, not adjudicated. No third source (for example official NHL scoring-change logs) was consulted.

## Boundaries

No model promotion, betting or execution change, and no new infrastructure, schedules or runners. The producer archive was read through a blobless partial fetch and sparse checkout (no full clone). Kalshi was read through anonymous public market-data calls only. Raw data is never committed.

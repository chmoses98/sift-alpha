# SIFT Alpha Universal Evaluation Standard v1 (`sift-alpha-eval/1`)

**Status: RESEARCH_ONLY.** Alpha is the independent evaluation authority for every SIFT sport, model and market. This standard changes no production model, order path, betting authority, scheduler or infrastructure. Implementation: `alpha_eval/`; enforcement: `tests/test_alpha_eval_conformance.py` (41 tests, no network).

## 1. What was reused (nothing working was replaced)

| Need | Reused from | How |
|---|---|---|
| Cluster bootstrap, Holm, BH, Brier, log loss | `sift_research/stats.py` | imported directly |
| Kalshi quotes, close selection, CLV (selection / quoted / actual-fill kept apart), fee estimate | `sift_clv/canonical.py` | imported directly; `alpha_eval` adds no second CLV or fee implementation |
| Family taxonomy | `alpha_engine/taxonomy.py` (pinned against `research/audit/master_inventory.json`) | `alpha_eval/families.py` maps its kinds to evaluation families and legal scoring types |
| Per-sport market-first model-vs-market cells | `research/outcome_intel/*` (+ `coverage_ledger.json`) | untouched; summarised in the coverage matrix |
| NBA player-forecast scoring (CRPS, coverage) | `alpha_engine/nba_forecast_eval.py` | untouched; its pmf scoring is the same definition as `scoring.ordinal_row` |
| Player-prop accuracy (PIT histogram, quantile CRPS, ladder CRPS) and value gating | `sift-sports-intelligence/pure-contract/{accuracy,value}_scorecard.py`, `SCORECARDS.md` | **not copied.** They are stdlib-only, prop-specific and live in another repo. `alpha_eval/adapters.py` converts `pure_forecast.v1` rows into this schema so Alpha can evaluate them centrally; the PIT histogram stays in pure-contract |

## 2. The five dimensions (per sport × market family × model version × horizon × evidence class)

1. **Accuracy.** Chosen by the forecast payload, never by the contract's price: BINARY → Brier + log loss; CONTINUOUS → MAE, RMSE, pinball-CRPS approximation; ORDINAL_PMF (counts/ladders) → exact discrete CRPS, log score, RPS; CATEGORICAL (3-way result, margin buckets, exact score) → multiclass Brier + log score. A binary Brier is never computed for a non-binary payload (tested).
2. **Directional calibration.** Signed bias (forecast − actual; + = over-forecast / over-predicts YES), calibration slope (logistic recalibration; <0.9 OVERCONFIDENT, >1.1 UNDERCONFIDENT), ECE, and 10 probability buckets with signed gaps; empty buckets are shown, not dropped.
3. **Model vs market.** Paired Brier and log-loss deltas on identical outcomes, market = mid of the last two-sided quote **at or before the forecast freeze** (not de-vigged). Inference clusters by event after **collapsing** correlated rows (alternate lines, ladder rungs, repeated captures) to one unit per event × model version × family. Signed disagreement is reported but is explicitly not evidence. Verdicts: `INSUFFICIENT_SAMPLE` (<30 events), `MARKET_BETTER`, `NOT_DISTINGUISHABLE`, `MODEL_BETTER_EXPLORATORY_NOT_CONFIRMED`, and `MODEL_BETTER_CONFIRMED`, which additionally requires PROSPECTIVE evidence, a declared sports-only model, and Holm p < 0.05 across the whole primary grid.
4. **Economics.** For every priced eligible row (full population, not selected recommendations) buy the model-favoured side at the archived ask, taker fee via `sift_clv.canonical.estimate_fee`, held to settlement. Labelled `QUOTED_HYPOTHETICAL` (size 1, top of book, no depth/queue/slippage). Reported for the full population, the positive-edge subset (flagged selection-biased) and edge bands. `VERIFIED_FILL` ROI comes only from supplied exchange fills with exchange fees. The claim field is `NO_PROFITABILITY_CLAIM` unless ≥200 verified fills have a positive cluster-CI lower bound, and even then it only says `…REQUIRES_PROSPECTIVE_REVIEW`.
5. **CLV.** Signed, same ticker, close strictly before event start and ≤ 1 h old, from the model-favoured side. `selection_clv`, `quoted_execution_clv` and `actual_fill_clv` are separate fields; actual-fill CLV exists only with fills.

## 3. Completeness: four statuses, explicit reasons

Every forecast yields one row with four independent evaluations (accuracy, market, economics, clv). Each is `GRADED | PENDING | UNSUPPORTED | BLOCKED` with a reason code (`alpha_eval/schema.py::R`). Schema rejects and bad outcome/quote/fill rows are counted in the report, never dropped. `len(rows) + len(rejects) == len(inputs)` is a tested invariant.

Families: MONEYLINE, SPREAD, ALT_SPREAD, TOTAL, ALT_TOTAL, TEAM_TOTAL, ALT_TEAM_TOTAL, PERIOD, PLAYER_PROP, LADDER, FUTURE, OTHER_EVENT, COMBO (UNSUPPORTED: needs a joint distribution), OFF_FIELD (UNSUPPORTED: no sports outcome source), UNCLASSIFIED (UNSUPPORTED, visible). Alternates and ladder rungs are recognised via `line_role` supplied by the producer (`MAIN | ALTERNATE | LADDER_RUNG`); the taxonomy cannot infer it from a family name.

## 4. Integrity rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Freeze predictions and model version before outcomes | `frozen_at < event_start` and `< outcome.observed_at`, non-empty `model_version`, else BLOCKED (`FORECAST_NOT_FROZEN…`, `…AFTER_OUTCOME…`, `MODEL_VERSION_MISSING`). Timestamps only: v1 does **not** verify a hash-chained archive (see §8) |
| Point-in-time joins | strict tz-aware UTC; entry quote ≤ freeze, close < start; later quotes never used (tested) |
| Sports-only independence | a `sports_only` model listing `market_inputs_used` is BLOCKED; `market_informed` or undeclared models are scored for accuracy but cannot be independent evidence (verdict capped, market evaluation BLOCKED when undeclared) |
| Outcome identity | outcomes join on `market_id` **and** `event_id`; a different `event_id` is BLOCKED `OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST`; disagreeing duplicate outcome rows for one market are BLOCKED `CONFLICTING_OUTCOME_ROWS_FOR_MARKET` (exact duplicates collapse) |
| Valid, pre-event fills only | fills must be structurally valid (finite, price in (0,1), count > 0, fee ≥ 0, side YES/NO; otherwise counted as auxiliary rejects) and, per forecast, same `market_id`, `frozen_at ≤ filled_at < event_start`. Excluded fills are listed in `verified_fill.fills_rejected`, never enter verified ROI or actual-fill CLV, and fills naming no forecast are surfaced as `FILL_FORECAST_ID_UNKNOWN` |
| Coverage basis | without `--eligible`, coverage is `FORECAST_ONLY` and complete market coverage is `NOT_ESTABLISHED`. With an independently sourced eligible-market universe (`alpha_eval/universe.py`), every eligible market is `FORECAST_AND_GRADED`, `FORECAST_NOT_GRADED`, `NO_FORECAST_FOR_ELIGIBLE_MARKET`, `FORECAST_EVENT_ID_MISMATCH` or id-conflict; `COMPLETE` only if none is unforecast/mismatched (and the universe is non-empty). Complete forecast coverage is reported separately from graded coverage |
| Accuracy ≠ value | accuracy status/scores are computed without reading quotes (tested: identical with and without quotes) |
| Clustered uncertainty, multiple comparisons | event-clustered bootstrap everywhere; Holm and BH over the primary sport × family × model_version × evidence-class grid. Other slices are descriptive |
| Full eligible population | economics and market cells are built from all graded rows that have a quote; unpriced rows are counted as BLOCKED with a reason |
| Historical / backtest / prospective | `evidence_class` is a cell key; classes are never pooled; the producer declares it (not independently verified) |
| Correlated alternates | collapse step + `n_collapsed_units` reported |
| No profit claim from missing/simulated execution | see dimension 4 (tested with an artificially perfect model) |

## 5. Export schema (read-only JSONL; every row has `"schema": "sift-alpha-eval/1"`)

* **forecast**: `forecast_id` (unique), `sport` (NFL CFB NBA CBB NHL MLB SOCCER TENNIS), `event_id`, `group_id` (cluster; default event_id), `market_id` (exchange ticker, threshold included), `native_family`, `line`, `line_role`, `model_id`, `model_version`, `model_independence` (`sports_only|market_informed`), `market_inputs_used[]`, `frozen_at`, `event_start`, `evidence_class`, `scoring_type`, `payload`.
  Payloads: BINARY `{p_yes}`; CONTINUOUS `{mean, quantiles{q:v}}`; ORDINAL_PMF `{pmf{k:p}}`; CATEGORICAL `{probs{label:p}}`.
* **outcome**: `market_id`, `event_id`, `state` (`final|void|pending`), `observed_at`, `source` (`sports|market_settlement`), `value` (0/1, number or label).
* **eligible** (optional universe, `--eligible`): `market_id`, `event_id`, `sport`, `event_start`[, `native_family`].
* **quote**: `market_id`, `observed_at`, `yes_bid`, `yes_ask` (dollars). **fill**: `forecast_id`, `market_id`, `side`, `price` (fee-exclusive), `count`, `fee`, `is_taker`, `filled_at`.

CLI: `python -m alpha_eval report --forecasts F --outcomes O [--quotes Q] [--fills X] [--eligible E] --kind daily|cumulative [--date YYYY-MM-DD] --out-dir D`; `python -m alpha_eval coverage --out-dir docs/alpha_eval`; `python -m alpha_eval example --out-dir D`.

## 6. Reports

`reports/alpha_eval/examples/` holds a cumulative and a daily postmortem (Markdown + JSON for cumulative). **They are generated from synthetic fixtures** (`alpha_eval/synthetic.py`) to exercise every path; they are not evidence about any real model or market. Reports are organised by evidence class, then sport, family, model version, horizon (`le_2h … gt_72h`) and calibration bucket.

## 7. Coverage and adoption

`docs/alpha_eval/COVERAGE_MATRIX.md` (generated; a test fails if it is stale) maps all 275 inventoried native families across the eight sports to evaluation families, legal scoring types and UNSUPPORTED reasons, summarises the existing outcome-intel ledger, and gives the sport-by-sport adoption table (existing implementation, gaps, blockers, integration).

Incremental integration plan (no engine rewrites; each step is a read-only export from the producer, reviewed in that producer's own PR):
1. **NFL, NBA, CBB** first: they have archived frozen forecasts and quote archives. Export forecast+outcome rows (`archived_utc`, `model_version`, role) through an adapter in Alpha. CBB model research is not touched.
2. **NHL, CFB, MLB, Soccer, Tennis** after their start-time/outcome blockers in the matrix are addressed by their owners.
3. Wire `sift_clv.executable` depth-walk and verified fills into the economics step, and pure-contract scorecard outputs into the prop sections.

## 8. Operational vs still blocked (honest summary)

**Operational and tested:** schema + strict parsing; family/scoring routing; all four scoring types; signed calibration; PIT quote join; paired model-vs-market with collapse + clustered CI + Holm/BH; hypothetical economics with fees; signed CLV with actual-fill separation; verified-fill ROI with claim gating; daily/cumulative reports; coverage + adoption generator; `pure_forecast.v1` adapter.

**Not done / blocked:** (a) **no real producer yet exports `sift-alpha-eval/1`, so no real postmortem exists**; examples are synthetic. (b) Producer repos other than sift-sports-intelligence were not accessible in this session; their adoption rows rely on Alpha's archived audits. (c) Non-binary contracts are scored for accuracy but have **no priced model-vs-market/economics** (needs per-outcome quotes; reason `NOT_APPLICABLE_NONBINARY`); Kalshi `scalar` contracts are not supported. (d) Hypothetical economics is top-of-book taker size 1; depth-walk and maker scenarios exist in `sift_clv`/`sift_research` but are not wired in. (e) Market probability is the raw mid, not de-vigged. (f) Freeze is checked by timestamps; ledger-attested freezes (hash chains like the Tennis ledger) and `evidence_class` verification are not yet implemented. (g) PIT-histogram and quantile-coverage diagnostics remain in pure-contract. (h) Existing outcome-intel results (calibrated-market log-loss gain) are not recomputed and use a different baseline; their ledger shows 0 validated cells across all sports. (i) Two pre-existing unrelated tests (`test_capture_dashboard_authority`, `test_nfl_totals_incremental`) error on the base branch.

## 9. Boundaries

No paid APIs, orders, authority, promotion, scheduler or infrastructure changes. `conductor.yml` and `worker/run.py` are untouched. The 1,649-input market catalog and CBB model research are neither modified nor delayed. The only existing file edited besides docs is the path filter of `research-tests.yml`, so PRs touching `alpha_eval/**` run the unit suite.

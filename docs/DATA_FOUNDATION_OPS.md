# Operation Data Foundation (RESEARCH_ONLY)

Agent-built on 2026-11-14; not human verified. Nothing here changes a production model, a frozen baseline, staking, execution or credentials.

    python -m alpha_engine.foundation.ledger          # rebuild research/data_foundation_ops/{pipeline_ledger,summary}.json
    python -m alpha_engine.foundation.market_watch    # ONE public Kalshi series-list request; diff vs the committed universe
    python -m alpha_engine.foundation.loop            # one bounded pass: (watch) -> (challengers) -> ledger -> health
    python -m unittest tests.test_foundation_ops tests.test_foundation_nba tests.test_foundation_cbb tests.test_foundation_nhl
    node --test tests/data-foundation.test.mjs
    npx playwright test tests/data-foundation.spec.mjs --trace off

## 1. What was reconciled

The Market & Input Map (PR #71) and data-foundation Phases 1–14 were never on `main`: #71 merged into
`claude/sift-alpha-free-data-coverage-wdmcaz`. That lineage continued through `claude/provider-licensing-research-k7d0tj` to
`claude/funny-einstein-5trimq` (123 commits ahead of `main`, 6 behind). This branch merges that tip into current `main`.
Three add/add conflicts (the college direct-API probe) were resolved in favour of `main`, whose copy is the later rewrite merged as PR #69.
After the merge the full suites pass unchanged (1,072 Python tests, 61 probe tests, 74 Node tests), and the map's own counts are unchanged:
170 archetypes, 1,649 distinct inputs, 949 missing PRIMARY slots.

Not merged, and why: `claude/sift-alpha-eval-catalog-38ni9g` (open PR #66) and `claude/adoring-archimedes-8htgcn` (open draft PR #68) are two
competing NHL evaluation adapters still under review; `claude/quirky-darwin-zv0rwc` is a docs-only incident record. They are untouched.

## 2. The pipeline ledger

`alpha_engine/foundation/ledger.py` assigns every one of the 1,649 inputs an explicit position on the research chain

    Identified → Source located → Collected → Verified → Feature built → Research challenger integrated → Evaluated → Validated improvement

plus a separate production track (Production approved, Production active). An input is **at** the last stage it reached without a gap, and the
ledger records what stopped it at the next one (missing, blocked, failed, rejected, partial, unknown) and why. Stages are never merged into a percentage.

| Stage | Evidence that sets it |
|---|---|
| Source located | a SATISFIED_BY dataset in the map that is not paid-only / sample-only / no-free-source |
| Collected | verified bucket FULL / DATA_IN_HAND (ok), PARTIAL / PROXY (partial); prospective-only and no-free-source are **blocked**, not missing |
| Verified | `VERIFIED_FULL` (ok), `VERIFIED_PARTIAL` / `VERIFIED_PROXY` (partial); `DOWNGRADED_BY_VERIFIER` is failed, `PIT_QUARANTINED` is rejected |
| Feature built | a replayed builder in the data-foundation verification, or a feature in a committed challenger evaluation |
| Challenger integrated, Evaluated, Validated improvement | only an `input_stage_claims` row in a committed, contract-valid `evaluation.json` |
| Production active | the published model-use audit (`research/audit/input_research/sport_*.json`); most inputs have no recorded evidence and say unknown |
| Production approved | no approval record exists in this repository, so every input says unknown |

A challenger claim cannot jump a gap: an input the map has not verified stays stopped at its earlier stage even if a challenger used a proxy for it.

## 3. The evaluation contract

Every challenger writes one `research/data_foundation_ops/<SPORT>/<challenger>/evaluation.json` (`sift-foundation-eval/1`,
validated by `alpha_engine.foundation.contract.validate_evaluation`). It lists the datasets read (repository, commit, rows, date range,
historical backfill vs prospective capture vs walk-forward reproduction, rights tier), each feature with its point-in-time rule and data checks,
the design, paired results against each reference, ablations, limitations and the stage it claims for each catalog input.

The promotion rule is fixed in code (`verdict_from`) and re-checked by the tests on every committed result row:
**validated improvement** needs a 95% cluster-bootstrap interval (clustered by game) entirely below zero, a Holm-adjusted p-value below 0.05,
and the same sign in both chronological test cohorts. One favourable cohort is "improved, not validated". Nothing is promoted automatically.

Raw rows never enter this repository. Challengers read the owner's sport repositories from `$SIFT_REPOS_DIR` and commit aggregates only.

## 4. Feedback loop and its safety properties

`alpha_engine/foundation/loop.py` runs one pass: market watch → challenger evaluations → ledger → next task → `loop_health.json`.

* It never commits, pushes, dispatches a workflow or schedules anything, so it cannot start a successor run.
* Every step has a hard timeout; a lock file refuses a concurrent pass; the ledger rewrite is byte-identical on unchanged inputs.
* Health is fail-closed: `HEALTHY` requires every requested step to succeed, the ledger to reconcile to the map and the market watch to be under 8 days old.
  A skipped, failed or timed-out step makes the pass `DEGRADED` or `FAILED`.

`.github/workflows/data-foundation-refresh.yml` runs that pass **only on manual dispatch**. It has no schedule, read-only permissions, a 30-minute
timeout and uploads an artifact instead of committing. **Adding a schedule is an owner decision and has not been made.**

## 5. Dashboard

`src/data-foundation.jsx` adds the "Data foundation pipeline" section at the top of Input Research:
Summary (P0 executive cards, all eight sports, unclassified new listings), Markets (sport → market → required inputs → input → datasets and
collectors → challenger), Challengers (data, features and checks, results, ablations, limitations) and Queue (ranked next engineering actions).
The summary (≈35 KB) is in the main bundle; the 2.9 MB ledger loads when a detail view is opened.
`pages.yml` now also requires the new section's markers in the published bundle.

## 6. Source rights (unchanged, and binding)

The rights registry is fail-closed and this work does not relax it. Everything the challengers read is the owner's existing archive in the sport
repositories, used for internal research only. No new external sports-data collection was run. The only network request made is the public
Kalshi series listing that the existing series sweep already reads.

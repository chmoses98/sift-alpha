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

`.github/workflows/data-foundation-refresh.yml` runs that pass **only on manual dispatch**. It has no schedule, read-only permissions, an 85-minute
timeout and uploads an artifact instead of committing. **Adding a schedule is an owner decision and has not been made.**

## 5. Dashboard

`src/data-foundation.jsx` adds the "Data foundation pipeline" section at the top of Input Research:
Summary (P0 executive cards, all eight sports, unclassified new listings), Markets (sport → market → required inputs → input → datasets and
collectors → challenger), Challengers (data, features and checks, results, ablations, limitations) and Queue (ranked next engineering actions).
The summary (≈0.15 MB) is in the main bundle; the ≈3.4 MB ledger loads when a detail view is opened.
`pages.yml` now also requires the new section's markers in the published bundle.

## 6. Source rights (unchanged, and binding)

The rights registry is fail-closed and this work does not relax it. Everything the challengers read is the owner's existing archive in the sport
repositories, used for internal research only. No new external sports-data collection was run. The only network request made is the public
Kalshi series listing that the existing series sweep already reads.

## 7. Results of the three P0 vertical slices (2026-11-14)

Each slice goes market → inputs → owner-archived data → features with checks → isolated challenger → chronological evaluation → ledger → dashboard.
All three incumbents are **retained**. No challenger beats the Kalshi pre-game mid on any family. Quote mids are not executable fills, and none of this is a profitability claim.

### NBA — `alpha-nba-avail-0.1` (point-in-time availability and minutes redistribution): IMPROVED_NOT_VALIDATED
Train: 2025-26 games before 2026-01-15. Test: 22,259 rotation player-games in 719 games, two chronological cohorts. Source: `nba-edge-finder@c9db017`.

| Measure (pooled test) | Challenger | Reference | Difference [95% CI] | Verdict |
|---|---|---|---|---|
| P(play) Brier, injury gate vs no-report arm | 0.0945 | 0.1434 | −0.0489 [−0.0526, −0.0452] | validated |
| Expected-minutes MAE, injury gate vs no-report arm | 4.91 | 6.56 | −1.65 [−1.75, −1.55] | validated |
| Expected-minutes MAE, + redistribution | 4.72 | 4.91 | −0.19 [−0.23, −0.16] | validated |
| Minutes MAE for teammates of a T-60 Out/Doubtful 20-minute player | 5.17 | 5.25 | −0.08 [−0.16, −0.01] | inconclusive (Holm p 0.20) |
| Kalshi prop Brier vs the no-report arm (11.3k–17.0k markets per family) | | | at most 0.001 | inconclusive, all four families |
| Kalshi prop Brier vs incumbent walk-forward reproduction (~100 games) | | | −0.012 to −0.016 | validated, all four families |
| Kalshi points Brier vs T-60 market mid | 0.1731 | 0.1647 | +0.0083 [+0.0037, +0.0127] | not improved |

* Projections of 10+ expected minutes for players who did not appear: 1,791 without the report, 741 with the gate.
* Players listed Out at T-60 played 0 of 3,090 times in test; Questionable 54%; Probable 93%.
* The gate cannot help Kalshi yes/no prop scoring, because those markets settle only for players who entered the game (2,606 DNP markets settled as scalar and are excluded). The gain over the incumbent reproduction comes from the base model and its later information cutoff, not from the gate, so it is not counted as a validated improvement overall.
* A 4-second leak was found and closed: 118 games had a report stamped exactly T-60 but published 4 s later; selection now uses publication time and matches the owner's snapshots 100%.
* A usage bump for points when a high-usage teammate is out was rejected on train data and is not in the challenger.
* Ticker mapping: 80,574 of 80,582 markets (8 unmatched, counted). Two-sided T-60 quotes exist for only 12% of scored markets.

### NHL — `alpha-nhl-joint-0.1` (one joint regulation-score distribution for every game market): IMPROVED_NOT_VALIDATED
Parameters fitted on 2009–2023; test seasons 2024 and 2025 (2,624 games). Source: `NHL-edge-finder@de1c36a`.

| Family (pooled log loss) | Challenger | Incumbent V1 | Difference [95% CI] | Verdict |
|---|---|---|---|---|
| Regulation tie / overtime | 0.5368 | 0.5456 | −0.0088 [−0.0136, −0.0038] | validated vs V1 |
| Moneyline | 0.6730 | 0.6766 | −0.0037 [−0.0077, +0.0005] | inconclusive (2025 sign flips) |
| Total 5.5 / 6.5, puck line, team totals | | | −0.001 to −0.003 | inconclusive |

* The overtime gain is a level correction only (mean tie probability 0.222 vs V1 0.174, observed 0.228); the calibration slope is about zero, so there is no per-game skill, and the gain disappears against the shadow SIM2 model.
* Against the Kalshi T-60 mid (2025 season) the challenger is worse on all 12 rows; none is significant after Holm correction.
* Ablations: independent Poisson scoring is clearly worse (+0.040 regulation-score NLL, replicated), so the tie structure matters. The finishing term is rejected, the special-teams split is not significant, and an oracle as-played starting-goalie term (not point-in-time, upper bound only) showed no detectable value with a crude save-percentage proxy.
* Data defects found in the archive and handled: MoneyPuck marks both teams AWAY in 115 Phoenix home games (2011–13); 246 Atlanta team-games have a null team id; four regular-season games have no MoneyPuck rows.
* What the audit says is wrong with the incumbent: independent regulation goals (ties 17.4% predicted vs 22.8% observed), many hard-coded constants, a computed-but-unused rating term, no season discount in the goalie table, and an unknown starter treated as league average.

### CBB — `alpha-cbb-joint-periods-0.1` (first-half, team-total and overtime probabilities from the frozen game projection): INCONCLUSIVE
489 games, 2026-11-01 to 11-12, incumbent `pure-0.2.0` projections frozen before tip (median lead 2.65 h). Source: `cbb-edge-finder` archive branches (prospective captures).

* The incumbent publishes no probability for first-half, team-total or overtime markets. The challenger supplies one; that is added coverage, not demonstrated accuracy. Against a naive baseline every derived family is inconclusive on 12 days of games.
* Against the Kalshi mid, full-game moneyline (+0.0143) and spread (+0.0197) are significantly worse. Those use the incumbent's own means, which this slice takes as given.
* The incumbent's assumption that total and margin errors are uncorrelated is not rejected (+0.06 [−0.02, +0.15]). Home and away final-score errors correlate +0.28 [0.19, 0.36].
* A labelling defect was found: for neutral-site games the Kalshi panel's home/away label is in the schedule frame, not the projection frame; 70 contracts were re-labelled by team id, after which 18,026 of 18,026 agree with settled results.
* Not done: a chronological prior-versus-current-season blend study. It needs the multi-season game lake, which is not committed and whose source (SportsDataverse) is rights-unresolved with a frozen collector.

## 8. Blocked, with the reason

| Item | Why it is blocked |
|---|---|
| New collection from ESPN, the NHL API, MoneyPuck, NBA official sources | Rights registry: terms unread, collection not allowed. Several hosts are also denied by this environment's network policy. Owner decision. |
| Comparison against the live frozen NBA `pf-1.3.0` and NHL data-archive forecasts | They live on data branches not read in this pass; the references used are the walk-forward reproductions on `main`. |
| NBA starters and referee crews, NHL confirmed goalies and injuries, CBB injuries (point-in-time) | No historical source; each needs an owner-approved prospective capture schedule. |
| CBB season-blend study | Multi-season game lake not committed; source rights unresolved. |
| Scheduled refresh | The workflow is manual-only until the owner approves a schedule. |
| Published dashboard | GitHub Pages builds `main`; this section is live only after this branch is merged. |

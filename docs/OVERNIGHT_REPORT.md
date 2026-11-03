# SIFT ALPHA — OVERNIGHT ENGINEERING REPORT (2026-11-03)

Status vocabulary: **implemented** (code written) · **tested** (unit tests pass locally) · **live-verified** (ran against real sources on a runner) · **merged** · **deployed**. Nothing below is merged or deployed. Live verification items are marked PENDING until a runner has actually run them.

## 1. Executive summary
- Market-first audit (PR #8, still draft) now carries a **market-specific blueprint layer**: 96 market-class specs mapped onto all 275 inventoried families (outcome, distribution, key numbers, settlement questions to verify, point-in-time hazards, required history, tiered concrete drivers) joined to evidence-based readiness. Implemented + tested + shown in the dashboard.
- **43 new candidate inputs** (57 rows incl. cross-sport market inputs) added and scanned against current sport-repo code. Baseline 285 inputs unchanged (no baseline input was re-classified overnight; 104 code-reference-only remain — honest, not reduced).
- **Two real collector problems found and fixed**: NBA PR #87 context cadence would often miss the ~19-min-pre-tip starter window; soccer PR #39 CI failures were wall-clock date rot on `main` too (test-only fix).
- **New collector**: ESPN per-period scoring history (NFL/CFB/NBA/CBB/NHL) — fills the missing quarter/half/period scoring distributions. Implemented + tested on synthetic payloads; live ESPN verification PENDING.
- **Research infrastructure**: PIT as-of join, Brier/log-loss/calibration, group-bootstrap model-vs-market comparison, exploratory feature screen that can never return "predictive".
- Repo-reported NBA/NHL model readiness recorded with provenance (not reproduced). Notable: NHL goalie-saves = NEEDS IMPROVEMENT vs incumbent.

## 2. Market families by sport (blueprint status — not collection status)
| Sport | Families | Specified | Specified, no markets observed | Unspecified (named) | Out of scope |
|---|---|---|---|---|---|
| NFL | 53 | 52 | 0 | 1 (NFL_MISC_UNCLASSIFIED, 380 mkts/47 series) | 0 |
| CFB | 19 | 19 | 0 | 0 | 0 |
| NBA | 64 | 63 | 0 | 1 (UNMAPPED_SERIES, 2,293 mkts) | 0 |
| CBB | 11 | 10 | 0 | 1 (OTHER) | 0 |
| NHL | 29 | 24 | 4 | 1 (UNMAPPED_SERIES) | 0 |
| MLB | 42 | 38 | 0 | 1 (unknown) | 3 |
| SOCCER | 31 | 12 | 19 | 0 | 0 |
| TENNIS | 26 | 25 | 0 | 0 | 1 |
Anticipated but **unobserved** classes (specified, not mapped to any observed family): soccer corners, cards, shots/SOT, anytime scorer; MLB first-three innings. No Kalshi soccer corners/cards family was observed in the 48 ambiguous series examined.
"Specified" means a requirement list exists. It is not evidence of collection, model use or predictive value.

## 3. Input inventory before → after (verification class)
Baseline 285 inputs, before and after: verified collection 63 · collected PIT-unverified 30 · stale/partial 18 · missing 18 · code-reference-only 104 · derived 30 · unknown 22 (**unchanged**).
Newly added 57 (reported separately, never mixed into the baseline): code-reference-only 48 · unknown/not-audited 6 · missing 3 (soccer shots/corners/cards: ESPN fields confirmed present in probe run 41543056159, not yet archived). Code-reference-only for new inputs comes from loose keyword regexes (e.g. "foul", "round") and should be treated as weak.

## 4. Newly discovered inputs / families
Kicker accuracy & range (NFL/CFB), quarter scoring (NFL/CFB/NBA), opening-drive scripts, TD rates by role, QB status vintage (CFB), foul rates, 3PA volume, steal/block rates, tip/first-shot (NBA), 3P variance, FT, neutral site (CBB), shots-against, penalty rates, goalie workload, shootout record, shot location (NHL), F3 split, times-through-order, K rates, SB context, contact distributions (MLB), corners, shots, fouls/cards, formation, penalty rate (soccer), tiebreak, break points, decider record, round context, first serve (tennis), strike hit rates and trade tape (all).

## 5. Collectors
| Item | State |
|---|---|
| NBA PR #87 ESPN core-roster starters | implemented earlier; full suite passes locally (incl. new cadence test); **live runner coverage by lead-time PENDING** (ESPN unreachable from authoring sandbox; runner probe branch `probe/nba-starters-live` scheduled) |
| NBA conductor cadence fix (commit 5fc63c3 on `feat/pit-espn-starters-capture`) | implemented + tested; not live-verified |
| `.trigger/conductor` | exists on NBA main as an intentional trigger file; PR #87's diff vs its base touches only 5 source/test files — no committed trigger change found in the PR |
| Soccer PR #39 CI | 2 failing tests were wall-clock-dependent and fail identically on `main`; fixed test-only (commit f88f548). Local: ruff clean, full suite passes except `test_committed_schemas_match_code` which fails on `main` too in this sandbox (pydantic version drift; CI environment not reproduced) |
| Soccer ESPN box-score mapping, missing xG, scoreboard_unreconciled | untouched (preserved) |
| ESPN period-scoring collector (`alpha_engine/period_scoring.py`) | implemented + tested (synthetic fixtures modelled on ESPN schema); live backfill PENDING (probe branch `probe/period-scoring`) |

## 6. Archive / point-in-time
No new historical archive was verified live yet. Period-scoring rows carry observed_at (post-response) and are post-game data, valid only as lagged features for later games.

## 7. Repositories / commits
- sift-alpha `audit/market-inventory-schema` (PR #8, draft): see `git log` — d167e0a specs, d88be38 dashboard, 69ade3b research_eval, df3d52f inputs, e91747f soccer evidence, 8638065 period scoring, bffc9d6/ec704e6 validation.
- nba-edge-finder `feat/pit-espn-starters-capture` (PR #87): 5fc63c3.
- soccer-edge-finder `fix/results-cards-from-scoreboard-details` (PR #39): f88f548.
- Probe branches (read-only, not for merge): sift-alpha `probe/nba-starters-live`, `probe/period-scoring`.

## 8. Tests / CI
Alpha local: 267 passed. NBA full suite: passed. Soccer: ruff clean; suite passes minus the sandbox-only schema-drift test. GitHub Actions on all three PRs were **queued** at time of writing (no CI result yet).

## 9. Discoveries
- NBA: starters appear ~19 min before tip and not ~49 min; a 55-min context cadence misses it.
- CFB repo stores only the *count* of linescore periods, so no per-quarter scoring history existed behind CFB 1Q/NFL/NBA quarter markets.
- Soccer CI failures looked like PR regressions but were date rot in tests pinned to 2026-10-10.
- NHL goalie-saves model is reported worse than the incumbent on holdout.
- Soccer: no legitimate free xG source established; ESPN box score has no xG and no referee.

## 10. Blockers / next
1. Read live-runner results (NBA coverage by lead time, period-scoring schema check); fold into registry statuses.
2. Resolve baseline code-reference-only inputs with field-level archive evidence (NBA off/def rating, pace, usage; MLB sp_quality, hitter_quality are the highest-weight).
3. Classify NFL_MISC_UNCLASSIFIED and NBA UNMAPPED_SERIES families.
4. Wire period scoring into the sport repos' archives; build Q1 baseline distributions per market once data is live-verified.
5. No hypothesis has been tested for predictive value; all tiers are candidate relevance only.

# SIFT ALPHA — OVERNIGHT ENGINEERING REPORT (2026-11-03)

Status vocabulary: **implemented** (code written) · **tested** (unit tests pass locally) · **live-verified** (ran against real sources on a runner) · **merged** · **deployed**. Nothing below is merged or deployed. Live verification items are marked PENDING until a runner has actually run them.

## 0. Cycle 2 update (2026-11-03, after live checks) — read this first
Vocabulary used below: **inventoried** (family exists) · **specified** (requirement list exists) · **collected** (records actually populated, seen) · **verified** (collected AND point-in-time clock verified) · **used in a model** · **predictively validated**. Nothing below is predictively validated; nothing is merged or deployed.

**Counts (generated from research/audit, not hand-typed)**
- Market families: 275 inventoried in `master_inventory.json` (unchanged) + 1 added by overlay (`SOCCER/player_goalscorer`, found via mis-filed MLS series) = 276. Status: 244 specified · 23 specified-but-unobserved · 4 specified **by series split** (provisional, see below) · 1 mis-mapped/re-routed (MLB/unknown) · 4 out of scope. **0 families remain without a specification**; residual uncertainty is named, not hidden.
- Authoritative input rows: 342 = 285 baseline + 57 overnight rows (43 distinct new ids; 14 are the same id repeated across sports/common). The 43 are now **linked to market families** (38 by rule, 2 cross-sport market inputs to all/ladder families; soccer corners/shots/cards stay unlinked because no Kalshi family exists) - before this cycle they were attached to NO family and contributed nothing to per-market coverage. 591 family x input links added.
- Verification class, baseline 285: verified collection **64 (was 63)** · collected PIT-unverified 32 (was 30) · stale/partial 20 (was 18) · derived 29 (was 30) · missing 18 · unknown 22 · code-reference-only **100 (was 104)**. The 5 movements: `cfb.half_split`, `cbb.half_split`, `nhl.period_split` (live period-scoring data, 6a); CBB `m.settlement_truth` -> verified collection (all 105 archive snapshots read: 5,623 finalized tickers, result/settlement value/ts on 100%, 2 scalar; `research/audit/lineage/cbb_archive_field_evidence.json`); Tennis `m.settlement_truth` -> partial (only three pinned 2026-10-25 captures, 36 contracts; no continuous archive checked).
- Overnight 57 rows: code-reference-only 44 · collected PIT-unverified 3 (nfl/cfb/nba `q_scoring`) · stale/partial 1 (`nhl.shootout_record`: only the OT flag exists) · missing 3 · unknown 6 (no code scan exists). **"Code-reference-only" is not collected.**
- Essential new-input links: 75 family x input pairs; 25 collected-PIT-unverified, 3 partial, 45 code-reference-only, 2 unknown.

**What changed this cycle**
1. Period-scoring data verified from the published branch (not from the workflow's green tick): 1,224 rows, hashes match, 0 duplicates/malformed, 1,222 reconcile (2 NHL flagged), 0 failed fetch days. Findings + limits in `research/audit/period_scoring_verification.json`. A dead-code throttle in the collector was fixed.
2. Five unspecified families resolved at **series level** (`research/audit/resolutions/unresolved_families.json`, 91 series): NBA 27 -> awards/season futures/news/**new scalar-payout "escalator" class**; CBB 8; NHL 2; NFL 47 (**all title-only, rules text unseen -> provisional**); MLB `unknown` is a **mapping error** (3 duplicates of existing soccer/NHL families, 2 esports, 2 MLS player-goal series that were missing from the soccer inventory).
3. Soccer PR #39: a real coverage defect found and repaired (post-match box-score window, section 5).
4. Live probes launched on runners (results appended in section 11 when they exist).

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
| ESPN period-scoring collector (`alpha_engine/period_scoring.py`) | **live-verified** by backfill run 41686590798 (data branch `period-scoring-data` 46993c5): 164 league-days fetched, 0 failures, 1,224 games. See 6a. Throttle bug fixed after. Not wired into any sport repo or model |

## 5a. NBA #87 / soccer #39 review notes
- NBA: the 6-minute refresh is a **decision rule** in `conductor.decide` (fires only when the NEXT tip is within 40 min and context is older than 6 min). Actual cadence also depends on the capture worker waking: the repo's own comment measured ~3.9% cron delivery, so the rule is necessary, not sufficient. The strict rules (exactly 5 distinct `starter: true`, observed strictly before tip, raw entries stored, roster size never used as a lineup) are in `data/starters.py` and tested. Confirmed starters reach matchup context only when BOTH sides are CONFIRMED at or before the context's `now`.
- Soccer: PR text is stale - the branch also wires box-score shots / shots on target / corners / cards (commits b99aa73, fcf6ead) with raw team statistics archived verbatim, a value emitted only when BOTH teams report an integer, absent (never 0) otherwise, and **xG never filled** (ESPN has none). **Defect found + repaired (2eae76e):** the sync only looked at matches within [-3h,+26h] of now, the final box score exists ~2h after kickoff and the cron is every 2h (and runs get dropped), so a match had ~1h in which its box score could be captured. `select_lineup_events` now also re-fetches FINISHED matches back to 30h, after the pre-kickoff group (so `--max-lineups` cannot starve it); content-hash suppression prevents duplicate rows. Unit-tested; **not exercised against live ESPN** (unreachable from the authoring sandbox).

## 6. Archive / point-in-time
No sport-repo archive gained verified coverage this cycle. Period-scoring rows are post-game data, valid only as lagged features for later games.

## 6a. Period-scoring data (live ESPN scoreboard, verified from the published branch)
| League | Games | Reconciled | Coverage | OT games |
|---|---|---|---|---|
| NFL | 121 | 121 | 2026-09-09..11-02 (25 slates) | 11 |
| CFB | 622 | 622 | 2026-08-29..10-31 (38 slates) | 24 |
| NBA | 107 | 107 | 2026-10-20..11-02 (14) | 5 |
| NHL | 192 | 190 (2 flagged, excluded) | 2026-10-06..11-02 (28) | 43 |
| CBB | 182 | 182 | **one slate** 2026-11-02 | 3 |
Checks passed: manifest SHA-256 (106 files), zero duplicate event ids, zero malformed rows, ESPN source URLs well-formed, every file date = US-Eastern date of start, sum(periods)=final. **A green workflow was not taken as proof**: the job log shows `failed_days: []` and `rejected: {}` for all five leagues. Limits: current season only (n=107 NBA games is thin); `observed_at` is the single backfill time for every row, so an `observed_at`-gated as-of join would drop all of them from any backtest before 2026-11-03 - availability must be game end, which is not recorded; the data branch is a force-pushed orphan (append-only within a run, not across runs); OT vs shootout resolution is not stored. Connected to inputs: `nfl.q_scoring`, `cfb.q_scoring`, `cfb.half_split`, `nba.q_scoring`, `nhl.period_split` (collected, PIT-unverified), `cbb.half_split` (partial: one slate), `nhl.shootout_record` (partial). Not used by any model.

## 7. Repositories / commits
- sift-alpha `audit/market-inventory-schema` (PR #8, draft) - SHAs after the branch rewrite (earlier report text cited pre-rewrite SHAs): 71d669e 43 candidate inputs, 5f86e1b market-class specs, 8aba426 dashboard blueprints, 0b5ac75 research_eval (PIT as-of join, Brier/log-loss, grouped bootstrap), cbf9fe0 soccer box-score evidence + NBA starter cadence finding, 058733f period-scoring collector, 483d86d NBA / 1c15e81 NHL repo-reported validation, d1b623d interim report, 0060443 input links + period-scoring verification, 5888a8a series-level resolution of the five families. Current head: see PR.
- nba-edge-finder `feat/pit-espn-starters-capture` (PR #87): 5fc63c3.
- soccer-edge-finder `fix/results-cards-from-scoreboard-details` (PR #39): f88f548 (CI green incl. py3.11/3.12 + archive-verify) -> 2eae76e (post-match lookback fix; local ruff + full suite pass, CI pending).
- Probe branches (read-only, not for merge): sift-alpha `probe/period-scoring` (b06390b -> data branch `period-scoring-data` 46993c5), `probe/nba-starters-live` (PR #87 code 5fc63c3 polled on a runner tonight), `probe/field-probe` (ESPN/NHL/MLB/Kalshi source fields).

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

## 11. Live probes launched this cycle (results PENDING until a runner finishes; GitHub runners were queueing 15+ minutes)
- `probe/nba-starters-live` -> data branch `nba-starters-probe-data`: coverage-by-minutes-to-tip for tonight's slate using PR #87's own code. Starts polling at T-125 of the first tip; 3-min cadence. Answers "when do 5 starter flags appear" (the 6-min refresh claim is judged against that window).
- `probe/field-probe` -> data branch `field-probe-data`: which fields ESPN (NFL/CFB/NBA/CBB/NHL/MLB/tennis), NHL api-web and MLB statsapi actually return on completed games, plus the public Kalshi Sports series list for an inventory-completeness diff (the current inventory was built from the same snapshots it would be checked against, so its completeness is not independently proven).

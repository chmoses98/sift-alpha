# SIFT ALPHA — OVERNIGHT ENGINEERING REPORT (2026-11-03)

Status vocabulary: **implemented** (code written) · **tested** (unit tests pass locally) · **live-verified** (ran against real sources on a runner) · **merged** · **deployed**. Nothing below is merged or deployed. Live verification items are marked PENDING until a runner has actually run them.

## 0a. Cycle 3 (2026-11-03 evening) — live-probe ingestion
**Field probe run 41695557684 (ESPN/NHL/MLB) — what it does and does not establish.** `tools/probe/field_probe.py` records key/label *presence* only (stat names, label sets, counts). It does not record populated values or timestamps, and the step ends with `|| true`, so a green run proves only that the script exited. Established: the listed team/player fields exist in 3 sampled completed games per league (MLB statsapi: 1 game), NHL api-web play-by-play has x/y on every shot event sampled, ESPN tennis competitor.linescores exist. NOT established: populated values, numeric parseability, historical depth, timestamps. All probe-derived inputs therefore stay SOURCE_AVAILABLE_NOT_COLLECTED. A value-level probe (`probe/value-probe`, `tools/probe/value_probe.py`: populated/numeric counts per field, 1/2/3-year-old games, wallclock/header timestamps, tennis statistics contents, MLB pitcher/hitter values, raw gz copies) was pushed; its result is not yet ingested.

**Soccer PR #39 live probe run 41706413941 (evidence: `research/audit/lineage/soccer_pr39_live_probe.json`, data branch `soccer-live-probe-data` @ 38736d0).** 164 finished matches over 2026-10-29..11-03: 153 carry populated shots, shots on target, corners, yellow and red for both sides with `box_stats_captured_at`; 0 violations (SOT<=shots, non-negative integers); xG 0/164. Run 2 on the same directory appended 0 rows and changed 0 timestamps (idempotent, no duplicate event ids). Gaps: 11 finished matches (bra.1 3, ita.1 2, ksa.1 5, league_cup 1) have no box stats - cause undetermined; 2 UCL matches were finalized 2.72 h after kickoff; weather DEGRADED (probe used a 5 s budget); 235 events skipped as unmapped teams. Only a 5-day window; PR is an unmerged draft, so classification stays SOURCE_AVAILABLE_NOT_COLLECTED.

**NBA starters probe: first run (41694265861) collected nothing, my error (no NBA games on 2026-11-03); relaunch run 41916809395 measured the slate of 2026-11-04** (`research/audit/lineage/nba_starters_probe.json`; PR #87 capture code unchanged, 3-min polls, data branch `nba-starters-probe-data` c47fb99).
- 476 team-observations, 9 games, 0 fetch failures. Starter flags were **absent on all 448 observations earlier than 22 min before tip and present (exactly 5, never 1-4) on all 28 observations from 18.9 min before tip** for the 4 teams (2 games) that were observed through the whole window; first CONFIRMED between 22.0 and 18.9 min before tip; every CONFIRMED row is before tip. This reproduces the earlier 3-game probe (starters at ~19 min, not ~49).
- **Second slate (2026-11-05, run 42122094673, `nba-starters-probe-data` 66daeda):** a light 2-game night (tips 02:00Z and 03:00Z); both games observed from ~119 min before tip to ~1.3 min before tip across the 00:00Z rollover (the ET-date fix works), 160 rows, 0 fetch failures. First CONFIRMED at 19.5 and 25.3 min before tip, exactly 5 flags, never 1-4, starter set unchanged through tip. Over both evenings: 4 fully observed games, first CONFIRMED between 18.9 and 25.3 min before tip - publication time varies by at least 6 min, so a fixed 19-min assumption is unsafe. Still: 4 games, 2 light slates, no busy/back-to-back/holiday night, no production archive.
- 6-minute cadence: the confirmed window is ~19-22 min, so a 6-minute refresh inside 40 min gives ~3 observations per game **if the capture worker really wakes that often - not measured here** (the repo's own comment cites ~3.9% cron delivery).
- **Two defects found (another session found the same ones independently in nba-edge-finder run 41924464469 and fixed them in d31d6dd):** (1) the schedule used by `capture_starters` was queried by UTC date, so the evening slate vanished after 00:00 UTC (my probe copy: 16 future games / 9 fetched at 23:59Z, 11 / 0 at 00:02Z) - this truncated 7 of my 9 games and would have hit production capture; (2) `games_both_confirmed` was 0 whenever a game had repeated polls. Limits: one evening, 2 fully observed games; PR #87 unmerged so there is no production archive; `nba.starters_pit` stays *source available, not collected*.

**New: essential-input readiness** (`alpha_engine/essential_readiness.py` -> `research/audit/essential_readiness.json`, tested). Unit = family x input essential links, strict (only VERIFIED_COLLECTION counts as verified; shared inputs never borrow another sport's class). Essentials verified / required: NFL 120/325, CFB 19/162, NBA 243/419, CBB 44/72, NHL 153/189, MLB 62/250, SOCCER 109/199, TENNIS 25/146. Families with every essential verified: NHL 5 of 29, all other sports 0. Predictive validation is NOT_ASSESSED everywhere (repo-reported NBA/NHL readiness is a separate input).

## 0. Cycle 2 update (2026-11-03, after live checks) — read this first
Vocabulary used below: **inventoried** (family exists) · **specified** (requirement list exists) · **collected** (records actually populated, seen) · **verified** (collected AND point-in-time clock verified) · **used in a model** · **predictively validated**. Nothing below is predictively validated; nothing is merged or deployed.

**Counts (generated from research/audit, not hand-typed)**
- Market families: 275 inventoried in `master_inventory.json` (unchanged) + 3 added by overlay = 278 (`SOCCER/player_goalscorer` from mis-filed MLS series; `SOCCER/corners` (22 live series) and `SOCCER/shots_sot` (8 live series) from the live Kalshi series list - series exist, no market ever archived). Status: 244 specified · 25 specified-but-unobserved · 4 specified **by series split** (provisional, see below) · 1 mis-mapped/re-routed (MLB/unknown) · 4 out of scope. **0 families remain without a specification**; residual uncertainty is named, not hidden.
- Authoritative input rows: 342 = 285 baseline + 57 overnight rows (43 distinct new ids; 14 are the same id repeated across sports/common). The 43 are now **linked to market families** (38 by rule, 2 cross-sport market inputs to all/ladder families; soccer corners/shots/cards stay unlinked because no Kalshi family exists) - before this cycle they were attached to NO family and contributed nothing to per-market coverage. 591 family x input links added.
- Verification class, baseline 285: verified collection **65 (was 63)** · collected PIT-unverified 35 (was 30) · stale/partial 21 (was 18) · derived 29 (was 30) · missing 18 · unknown 22 · code-reference-only **95 (was 104)**. Movements: `cfb.half_split`, `cbb.half_split`, `nhl.period_split` (live period-scoring data, 6a); CBB `m.settlement_truth` and `cbb.venue` -> verified collection (all 105 / 35 archive files read; `lineage/cbb_archive_field_evidence.json`); Tennis `m.settlement_truth` -> partial (three pinned captures only); MLB `hitter_quality`, `platoon`, `sp_workload` -> collected-PIT-unverified and `sp_quality` -> partial from the raw Statcast pitch archive (643 games, 190,107 pitches, 2026-08-11..09-27; `lineage/mlb_statcast_archive_evidence.json`) - raw post-game data, no xFIP/SIERA/Stuff+ stored, commit-time PIT unchecked.
- Overnight 57 rows: code-reference-only 27 (was 44) · collected PIT-unverified 4 (nfl/cfb/nba `q_scoring`, `mlb.k_rates` from the Statcast archive) · stale/partial 1 (`nhl.shootout_record`) · **missing / source-available-not-collected 21 (was 3)** · unknown 4 (no code scan exists). The 19 new 'source available' rows come from the live field probe (section 11): the field EXISTS at a free endpoint on completed games, but no collector archives it. **"Code-reference-only" and "source available" are not collected.**
- Essential new-input links: 75 family x input pairs; 25 collected-PIT-unverified, 3 partial, 45 code-reference-only, 2 unknown.

**What changed this cycle**
1. Period-scoring data verified from the published branch (not from the workflow's green tick): 1,224 rows, hashes match, 0 duplicates/malformed, 1,222 reconcile (2 NHL flagged), 0 failed fetch days. Findings + limits in `research/audit/period_scoring_verification.json`. A dead-code throttle in the collector was fixed.
2. Five unspecified families resolved at **series level** (`research/audit/resolutions/unresolved_families.json`, 91 series): NBA 27 -> awards/season futures/news/**new scalar-payout "escalator" class**; CBB 8; NHL 2; NFL 47 (**all title-only, rules text unseen -> provisional**); MLB `unknown` is a **mapping error** (3 duplicates of existing soccer/NHL families, 2 esports, 2 MLS player-goal series that were missing from the soccer inventory).
3. Soccer PR #39: a real coverage defect found and repaired (post-match box-score window, section 5).
4. Live field probe + Kalshi series list ran (section 11). The Kalshi list shows the inventory is **materially incomplete as a collection target**: 4,081 live Sports series vs 1,524 inventoried tickers.

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

**PIT classification of every source examined: `research/audit/pit_classification.json`** (class, availability field, join rule per source; tested). Key rules: period-scoring and Statcast are post-game with unrecorded availability (lagged only, never `observed_at`-gated); CBB Kalshi snapshots are batch-stamped (latest snapshot <= T); CBB schedule rows are record-stamped.

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

## 11. Live probe results
**Field probe (run 41695557684, `probe/field-probe` 6b9836e, data branch `field-probe-data`; summary in `research/audit/lineage/source_field_probe.json`)** - completed games, 3 per league (MLB statsapi 1 game: season over). Presence only.
- ESPN NBA/CBB summary team stats: fouls, steals, blocks, turnovers, FG/3P/FT made-attempted, fast-break and paint points, lead changes; player PF/STL/BLK/3PT/FT/MIN (and +/- for NBA). ESPN NFL/CFB: drives list (16-28 per game), scoringPlays, kicking category (FG/LONG/PCT/XP; no distance buckets), red-zone attempts (NFL), possession. ESPN NHL: shotsTotal, penalties, PIM, power-play opportunities/goals, shootoutGoals, goalie SA/SV%/SOS/SOSA. NHL api-web play-by-play: x/y coordinates on 115/115, 115/115 and 117/117 shot events; period types REG/OT/SO. MLB statsapi: boxscore batting/pitching incl. battersFaced, strikeOuts, totalBases, stolenBases, caughtStealing; 9-inning linescore. ESPN tennis: set linescores with `tiebreak` scores; break-point / serve statistics NOT verified. **Not found:** MLB pitcher hold time / catcher pop time, football kick-distance buckets, soccer cards in any Kalshi title.
- Consequence: 19 new-input rows moved from code-reference-only to **source-available-not-collected** (nba foul/3pt/steal-block/FT, cbb 3pt/FT/foul, nfl/cfb kicker (partial) and opening-drive, nhl shots-against/penalties/shot-location, mlb K/contact/SB(partial)/F3, tennis tiebreak). None is counted as collected.

**Kalshi public series list (same run; `research/audit/resolutions/kalshi_live_series.json`)** - 4,081 live Sports series (Soccer 1,470, Basketball 725, Football 604, Baseball 236, Tennis 144, Hockey 108). 1,524 tickers are inventoried; 109 inventoried tickers are absent from the live list (expired/renamed). By ticker prefix, series that exist on Kalshi but are not in the inventory: **NFL 54, CFB 49, NBA 22, CBB 40, NHL 12**. A series being listed does not mean it had markets, volume or known rules. Findings:
- Soccer: **22 corners series, 8 shots/SOT/SOG series, 34 goalscorer/assist series exist; 0 card/booking series**. The old claim that these classes were "not observed" referred to our 48 sampled ambiguous series only. Overlay families added; cards stays 'anticipated, likely not offered'.
- MLB first-three-innings was NOT unobserved: KXMLBF3 sits in MLB/inning_result with **1,419 settled markets**. `bs_f3` is now mapped to that family.
- New class candidates visible only as live series (17 NFL/NBA tickers): scalar-payout **escalators** (NFL receiving/rushing/receptions, NBA threes/points), **ladders**, **'protected'** and **'precise'** variants; NHL playoff-series markets (winner, spread, total games, exact score, OT, total goals); per-period BTTS for NHL and for CFB quarters; CBB race-to-N points, first 3-pointer, winning margin and March Madness props; CFB team-stat props (receptions, rush yards, sacks, forced turnovers, field goals, TDs). No rules text for any of them, so no spec was written - this is the next inventory/collection gap.
- Caveat: the inventory was built from archived snapshots, so absence from it is a collection blind spot, not proof a class is unspecified (quarter winners have a family, yet KXNBA1QWINNER etc. are not among its tickers).

**Soccer live probe (branch `probe/soccer-live`, runs PR #39 head 2eae76e twice on a runner, data branch `soccer-live-probe-data`)** - launched; results not yet ingested.


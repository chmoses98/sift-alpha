# Phase 10 (2026-11-10): market-metadata reclassification, rights split, collector audits, deterministic builds (RESEARCH_ONLY, $0)

Agent verification only; **not human verified**. Continues from `256a233`. No orders, purchases, credentials, permission/environment/schedule changes, PRs or merges; nothing is activated. The 1,649-input catalog is untouched (`baseline_lock` OK; `regenerate --check` ok, idempotent). Python 960 tests, JS 52, all pass.

## Before / after
| Measure | Before | After |
|---|---|---|
| Verified FULL / PARTIAL / PROXY (distinct inputs) | 57 / 176 / 19 | **58 / 177 / 19** |
| DATA_IN_HAND (distinct) | 23 | 23 |
| Verified computable | 275 | **277** |
| Predictive slots (market metadata excluded) | 3,755 | **3,675** (80 metadata slots removed) |
| PRIMARY predictive slots / covered F+P+X / missing | 1,283 / 323 / 960 | **1,280 / 325 / 955** |
| Predictive FULL slots | 203 | 204 |
| Built slots rights-cleared for non-commercial research | 149 | **152** (primary 36 to 38) |
| Built slots commercial-cleared (CC0 only) | 8 (not tracked) | **11** (primary 6 to 8) |
| Wrapper-only (nflverse) / unresolved built slots | 227 / 637 | 227 / 637 |
Distinct predictive inputs by category (sport-level, same exclusions both sides): FULL 57 to 58, PARTIAL 176 to 177, FREE_ACCESSIBLE 751 to 749; others unchanged. Independently complete archetypes: still 0 of 170.

## 1. Owner decision 1: metadata is not predictive
`m.settlement_truth`, `m.lifecycle`, `m.stat_correction_risk`, `m.stat_source_mismatch` (64 slots, 3 primary) are settlement/operational metadata; `m.strike_hit_rates` (23 slots, 0 primary) is a market-calibration benchmark; `m.rules_text` stays a semantics dimension. None counts in the predictive denominator or as independent market-free sports data. Catalog entries kept; derived classification only; all 170 archetypes recomputed; no point-in-time cutoff touched. Proposal (not applied): other inputs parsed from Kalshi rules text (`ten.retirement_settlement_rules`, `soc.competition_scope_and_win_definition`, `ten.ace_settlement_source`, `ten.short_format_rules`) are the same kind of metadata and carry 13 primary slots.

## 2. Owner decision 2: rights
nflverse stays `WRAPPER_ONLY` (tier `WRAPPER_LICENCE_UPSTREAM_CAVEAT`), neither research- nor commercial-cleared; its 55 built inputs and evidence are retained. Registry 1.1 adds separate `research_cleared` / `commercial_cleared`: CC0 (openfootball) clears both; Sackmann CC BY-NC-SA clears research only.
**New authoritative evidence:** football-data.co.uk states on its own data page (sha256 in the registry) that the data is free "however its use is intended for private individuals only, NOT commerical or data training products using automated bots/scrapers/AI". Its 14 inputs stay unresolved; an owner decision or written permission is needed. ESPN, NHL, MLB, MoneyPuck, CFBD and NCAA terms pages are still unreachable (DNS), so no clause of them is asserted.

### Source-rights questions, ranked by built inputs a single answer would clear (`rights_questions.json`)
| # | Source | Inputs cleared by this alone | PRIMARY slots | Question |
|---|---|---|---|---|
| 1 | ESPN site API (+ sportsdataverse mirrors) | 60 (+5 with sportsdataverse, 66 touched) | 104 | May Disney/ESPN data pulled from undocumented endpoints be retained and analysed for internal research / commercially? |
| 2 | nflverse upstream (NFL, NGS, FTN) | 55 | 49 | Which upstream terms govern the releases, and does the CC BY wrapper carry them? |
| 3 | Sackmann (commercial only) | 51 | 30 | Commercial licence from Tennis Abstract (research use is already cleared) |
| 4 | NHL API + MoneyPuck | 34 | 41 | NHL terms, MoneyPuck data terms |
| 5 | football-data.co.uk | 14 | 17 | Does the provider permit automated internal research use? (statement read: no) |
| 6 | MLB Stats API | 13 (21 touched) | 11 | MLB bulk-reuse terms |
| 7 | CFBD / NCAA | 9 | 19 | CFBD and NCAA terms |
Registry gap: 8 MLB inputs use an "owner schedule archive" that matches no token (fails closed); identify its provider.

## 3. Collector audits (read-only; `collector_audit/*.json`, proposals in `collector_audit/proposals_nfl_college/` and inside `nba_nhl.json`; NOTHING activated)
| Stream | Verdict | Measured |
|---|---|---|
| NBA starters | READY_WITH_GAPS | 5 days only; polls in T-120..0 median gap 10 min (design 5-6); both sides CONFIRMED at last pre-tip poll in 28/33 games; no publication timestamp in payload |
| NBA injuries | READY_WITH_GAPS | 681 files / 54 days; in-window gap median 60 min; 114/220 games last capture over 30 min pre-tip; game_id/nba_id null in 100%; pit branch only 20% of its hourly cron |
| NHL goalies | READY_WITH_GAPS | 929 files / 43 days; gap median 30 min; 10/285 games no capture in T-6h; 19.5% PROJECTED/PROBABLE at last capture; source_reported_at null 65%; lineup probe NOT_READY (manual, 5 games, rights-gated) |
| NHL injuries | READY_WITH_GAPS | 832 files; same cadence; ESPN `reported` gives newest update only (no status history) |
| NFL injuries / QB | READY_WITH_GAPS | none in sift-alpha `prospective-data`; real vintages in nfl-edge-finder `pit_availability` (118 captures, median gap 4.8 h, max 30.7 h; QB starter status mostly generic "Active") and projected depth-chart starters (never CONFIRMED); legacy 3-hourly capture stopped 2026-10-28 |
| CFB QB status | READY_WITH_GAPS | only a PROJECTED prior-game passer (100% of event-teams); ESPN injuries all stale (2020/2022); 19 files, median gap 24 h |
| CBB availability | **NOT_READY** | 39 files, every row "available/no_report", every raw injury payload empty, cadence 6 h vs 30 min cron |
Proposals (owner approval required, unapplied): NBA starters refresh 6 to 3 min and optional schedule for `starters-live-check`; NBA pit cron to 4 wakes/hour; NHL pregame refresh 20 to 10 min; wire drafted goalie change-log; CBB self-chain capture step; CFB capture-only crons; NFL holiday/Saturday pit slots and night-game depth-chart refresh. Limits: Actions run history, third-party terms, and the `audit/nba-starters-*` branches were not visible.

## 4. Builds (rights-cleared, deterministic, no fitted or outcome-optimised model)
Selection rule: unique PRIMARY slots among inputs whose sole source is research-cleared (Sackmann, openfootball), keeping only raw-data transformations. Most top-ranked candidates are rules-text parses (market metadata), Monte Carlo simulations or fitted models and were NOT built.
| Sport | Input | Result | Evidence |
|---|---|---|---|
| TENNIS | `ten.tiebreak_base_rate_by_event` | **PARTIAL to FULL** (round x best_of split added; every catalog clause mapped, `phase10_round1.json`) | 3 new columns blind exact match; family replay 13 inputs, 2000-2026, min coverage 0.996 |
| SOCCER | `soc.points_gap_state` | new, PARTIAL (6 columns: points / GD / GF and gaps) | blind match; all replay gates |
| SOCCER | `soc.current_win_run_state` | new, PARTIAL (3 columns) | blind match; all replay gates |
Soccer gain: built slots 81 to 84, PRIMARY covered 23 to 25 (CC0, so also commercial-clearable). The matches-left and played-count columns were built and blind-matched but FAILED replay (future fixture list under truncation; counts cannot move under score perturbation), so they are declared missing rather than published. Missing for both: points-deduction log, intra-day as-of, cups/Europe, market-specific window. No input was refused by the gate this phase.
Not attempted: `nfl.opening_script`, `ten.player_set_drop_propensity` (round/format terms), `soc.remaining_schedule_strength`; the other of the 33 PARTIAL inputs miss logistic/NB/GPD fits or FTN data, which are fitted-model steps out of scope.

## 5. Prospective-capture readiness (verified by measurement, not activated)
Ready with gaps: NBA starters and injuries, NHL goalies and injuries, NFL (in nfl-edge-finder), CFB (projected passer only). Not ready: CBB. Prospective PRIMARY gaps 315 to 314 after reclassification; no capture can be backfilled.

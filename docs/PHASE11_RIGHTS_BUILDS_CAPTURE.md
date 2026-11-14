# Phase 11 (2026-11-11): provider-rights evidence, hold-DP tennis builds, metadata component split, capture root causes (RESEARCH_ONLY, $0)

Agent verification only; **not human verified**. Continues from `489a8b1` (verified before any change). No orders, purchases, credentials, workflow/schedule/permission changes, PRs or merges; nothing is activated. Catalog untouched (`baseline_lock` OK; `regenerate --check` ok, no change). Python 987 tests, JS 52, all pass.

## 1. Rights evidence (what could and could not be verified)
- **Exact text NOT verified.** `collegefootballdata.com/terms` and `moneypuck.com/data.htm` are denied by this environment's network policy (proxy CONNECT 403; WebFetch `ENOTFOUND`). I did not work around the policy. The owner's reading is recorded as `OWNER_REPORTED_NOT_AGENT_VERIFIED`; no clause is quoted and the August 12, 2026 effective date is the owner's.
- **Registry 1.2** (`rights_registry.json`, new `supersedes` semantics so a specific entry replaces only the entries it names; fail-closed otherwise):
  - `cfbd_cbbd_direct_api` -> new tier `CLEARED_PROVIDER_TERMS_DIRECT_API` (research and commercial DERIVED outputs, shared quota, no raw redistribution). `collection_allowed: false`: no CFBD key exists in this environment, the host is denied, quota is unmeasured. Applies only to data actually acquired through that path.
  - `moneypuck_listed_downloads` -> `CLEARED_NONCOMMERCIAL_RESEARCH` (attribution; listed files only). `moneypuck_unlisted` and NHL API stay `UNRESOLVED`.
  - **The 14 Phase 8 CFB/CBB inputs stay RIGHTS_UNRESOLVED**: their acquisition path is sportsdataverse/ESPN files, which direct-CFBD terms do not clear (tests: `tests/test_phase11.py`).
- Rights-question ranking regenerated (`rights_questions.json`); MoneyPuck now a separate question.
- **Consequence:** zero inputs change tier from this update. No built input uses either new path, because the data cannot be collected from here.

## 2. Inputs implemented this phase
| Input | Result | Evidence |
|---|---|---|
| `ten.games_per_set_distribution` | DATA_IN_HAND -> **PARTIAL** (11 columns) | replay all gates (3 truncations, 3 perturbations, own-game, non-vacuity; coverage 0.837); blind re-implementation MATCH on all 11 columns over 302,906 rows at 1e-9 |
| `ten.hold_gap_expected_margin` | DATA_IN_HAND -> **PARTIAL** (4 columns) | same |
Builder `alpha_engine/features/tennis_ext4.py` (closed-form hold, set DP averaged over first server, tiebreak recursion, Wald roll-up over the set-count law). No fitted or outcome-optimised model. Missing (so not FULL): the catalog's regression-based opponent adjustment (an additive adjustment is used), the empirical calibration by bins with kernel smoothing, Beta-posterior draws, Slam final-set rules. Sackmann is CC BY-NC-SA: research-cleared, not commercial-cleared.
Not built, with reasons: MoneyPuck and CFBD/CBBD (data and key inaccessible here); CC0 soccer (the remaining deterministic candidate `soc.remaining_schedule_strength` already failed the truncation gate in Phase 10); NBA/NHL archive inputs (rights unresolved, not research-cleared); the other tennis data-in-hand inputs (ridge/MC/logistic fits, out of scope).

## 3. Measured before / after (distinct inputs; slots)
| Measure | Phase 10 | Phase 11 |
|---|---|---|
| Verified FULL / PARTIAL / PROXY | 58 / 177 / 19 | **58 / 179 / 19** |
| DATA_IN_HAND | 23 | 21 |
| Verified computable (FULL+PARTIAL+PROXY+DATA_IN_HAND) | 277 | 277 (the two inputs were already counted as data-in-hand) |
| Predictive slots | 3,675 | **3,670** |
| PRIMARY predictive slots | 1,280 | 1,276 |
| PRIMARY covered F+P+X / missing | 325 / 955 | **327 / 949** |
| Built slots research-cleared (primary) | 152 (38) | **155 (40)** |
| Built slots commercial-cleared (primary) | 11 (8) | 11 (8) |
FULL gains: **0** (no input satisfies its entire definition without fitted-model steps). Commercial-cleared gains: **0**. Newly covered PRIMARY slots: **2**. Independently complete archetypes: still 0 of 170.

## 4. Market metadata vs predictive components
| Input | Metadata component | Predictive component | Denominator |
|---|---|---|---|
| `soc.competition_scope_and_win_definition` | all of it (rules-text flags) | none | **removed** (5 slots, 4 primary) |
| `ten.retirement_settlement_rules` | settlement flags | P(complete), P(retire by state) from the retirement hazard | **retained** |
| `ten.ace_settlement_source` | named source of record | cross-source ace-count disagreement | **retained** |
| `ten.short_format_rules` | format coding | no-ad hold, first-to-four DP, variance inflation from Next Gen Finals | **retained** |
Of the 13 primary slots, 4 moved out; 9 remain predictive. Previously proposed 13-slot blanket reclassification was NOT applied. Implemented as `COMPONENT_SPLIT` and `RULES_PARSE_ONLY_IDS` in `market_completeness.py` (derived classification only).

## 5. Current-season capture (inspection of actual configs; details in `docs/capture_workflows/phase11/README.md`)
Sources inspected: sibling repos' workflows read from anonymous clones, sift-alpha data branches. Actions run history is not visible (API 403), so skipped/queued runs were not measured.
- **Cross-cutting cause:** GitHub cron is not a clock; the repos' own headers record 3.9% (NBA) and 64% (NFL) delivery; CBB measured here at about 7% (37 captures in 10.4 days).
- **NBA starters:** strict `age > 6.0` against 5-minute cycles yields an effective 10-minute cadence. A 3-minute dedicated loop is proven by the probe (181 s median gap). Diffs prepared (not applied) against `ci/nba-starters-live-20261104` and nba-edge-finder main.
- **NBA injuries (114/220):** explained by the old 55-minute threshold (predicts about 50%; observed 52%). After the fast window, 2 of 32 games (Nov 6-11) miss 30 minutes: largely already fixed upstream. Remaining defects: null game_id/nba_id in 100% of rows; "not yet submitted" teams.
- **NHL goalies:** the 10 zero-capture games are one slate after a single 454-minute silence (Nov 3-4); `age > 20` gives about a 30-minute cadence. Diff prepared against nhl-edge-finder main. Status-change history: `alpha_engine/capture_quality/history.py`.
- **NFL:** no injury payloads in sift-alpha; they live in nfl-edge-finder. No worker created, pinned release untouched; Phase 10 holiday-slot diff stands.
- **CFB QB / CBB:** classifier labels the prior-game passer PROJECTED always; empty/placeholder CBB reports rejected as unusable (`availability.py`). 18 regression tests.
Real capture improvements shipped: **none are active** (all need owner approval); preserved data: none newly recoverable.

## 6. Owner approvals still needed
1. Merge `nba_starters_live_check_3min.diff` and `nba_conductor_starter_refresh.diff` (nba-edge-finder main) and decide that a read-only 3-minute ESPN poll is within terms.
2. Merge `nhl_conductor_goalie_context_refresh.diff` (nhl-edge-finder main); DailyFaceoff/NHL terms unread.
3. Network allowance (or owner-run fetch) for `collegefootballdata.com`, `moneypuck.com`, and an authorised workflow that reuses the existing CFBD key; quota to be measured first. Until then nothing from either source can be built.
4. Verification of the exact CFBD and MoneyPuck terms text by the owner or after (3).
5. Carried over: ESPN/NHL/MLB/NCAA terms, nflverse upstream, Sackmann commercial licence, football-data.co.uk permission, Phase 10 CBB/CFB/NFL proposals.

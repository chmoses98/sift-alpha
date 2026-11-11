# Phase 12 (2026-11-11): rights evidence, direct-API paths, one verified build, capture-diff review (RESEARCH_ONLY, $0)

Agent verification only; **not human verified**. Continues from `ee6e50c`. No orders, purchases, credentials, access/network/schedule changes, PRs or merges; nothing is activated. Catalog untouched (1,649 inputs; baseline lock OK; `regenerate --check` clean).

## 1. Rights evidence (still blocked; owner-reported designation preserved)
Dated 2026-11-11 attempts to read `collegefootballdata.com/terms` and `moneypuck.com/data.htm` (curl through the session proxy: CONNECT 403; web-fetch tool: DNS ENOTFOUND), plus API-host reachability for `api.collegefootballdata.com` / `api.collegebasketballdata.com` (CONNECT 403, no key, no data). No mirror, cache or search snippet was used, network policy untouched. **Exact clauses and the August 12, 2026 effective date remain unverified.** Recorded in `rights_registry.json` (`phase12_rights_evidence`): owner-reported restrictions (no raw redistribution, derived outputs only, shared monthly quota; MoneyPuck attribution, non-commercial, listed files only) and four separate paths: direct API (`CLEARED_PROVIDER_TERMS_DIRECT_API`, collection still disallowed), third-party wrappers (sportsdataverse/cfbfastR/hoopR: unresolved), original sources (ESPN/NCAA: unresolved), MoneyPuck listed vs unlisted.

## 2. College (CFB/CBB) direct-API inventory (`phase12_coverage.json`, `alpha_engine/collect/college_direct.py`)
Of the 949 PRIMARY missing slots, 182 are CFB (74) and CBB (108). Raw-data serviceability by an endpoint on paper (need types and catalog datasets mapped to `/games`, `/games/teams`, `/games/players`, `/plays`, `/drives`, `/coaches`, `/recruiting/teams`, `/rankings`; CBB `/plays/game/{id}` and `/lineups/game/{id}` are per-game and expensive):
| | slots fully serviceable | partly | not serviceable |
|---|---|---|---|
| CFB (74) | 30 | 38 | 6 |
| CBB (108) | 31 | 62 | 15 |
**These are upper bounds on raw-data availability, not coverage.** Many of those inputs are model fits, simulations or ratings (e.g. `cbb.ratings`, `cbb.bracket_sim`) that the no-fitted-models rule keeps out; the deterministic subset is smaller and unmeasured. Endpoint names, start seasons (CFB games 2001, plays about 2005, CBB 2002/2013) and PIT notes are from the agent's knowledge of the API surface and are **unverified** against the live OpenAPI (host blocked). Point-in-time caveat: only event-time endpoints (games, plays, box scores) are replayable; ratings/recruiting/poll endpoints are retrospective unless a week stamp is proven.
Quota (calls, formula-based): CFB 2014-2025 static backfill about 828 calls (plays/drives/team and player box 192 each, games 24, coaches/recruiting/rankings 12 each); CBB about 84 static calls plus about 6,200 calls per season if per-game plays/lineups are needed (about 74,000 for 2014-2025, excluded from the static plan). Months to finish at 40% of the shared cap, under three **scenario** caps (not measured): cap 1,000 -> CFB 2.1 months, CBB 0.2; cap 5,000 -> 0.4 / 0.04; cap 25,000 -> 0.08 / 0.01. The real cap, per-call limits and other consumers of the quota are unknown until an authorised probe.
Secrets: no CFBD/CBBD secret or variable exists in this environment or in this repository's workflows (checked by name only; no value read). The owner's reported existing key lives outside the visible scope; its secret name must be confirmed by the owner.
Ingestion scaffold: plans and budgets with no network. It refuses to run without an owner-written authorization file (absent), a key in the environment (absent), a call ledger below `max_share_of_cap` (at most 50%) of the monthly cap, and an output directory outside the repo; it stops at the first 401/403/429; `main` has no run command. 14 tests (`tests/test_phase12.py`). **Collection not activated; no key used.**

## 3. NHL / MoneyPuck
87 PRIMARY NHL slots (56 inputs). Only three files are evidenced as MoneyPuck downloads in use (the owner's nhl-edge-finder `moneypuck.py` at `de1c36a`): `seasonSummary/{year}/regular/teams.csv`, `.../goalies.csv`, `careers/gameByGame/all_teams.csv`. The data page itself was not read, so "explicitly listed" cannot be confirmed; shot-level and skater files that the agent remembers are recorded as `remembered_unverified` and not mapped to coverage. By need type, 66 of the 87 slots touch an evidenced file (team and goalie box), 1 touches only unverified listings; need-type mapping is generous and no input was built, because MoneyPuck is unreachable and no MoneyPuck data exists locally. Isolation: derived outputs would carry `CLEARED_NONCOMMERCIAL_RESEARCH` (never commercial); unlisted resources and the NHL API stay unresolved (tests).

## 4. Capture fixes (`docs/capture_workflows/phase12/README.md`)
Upstream heads unchanged (`c6120ad`, `de1c36a`). NBA diff: tested against upstream's conductor tests (14/14 with a new regression test), **held** (doubles ESPN roster polling in the pre-tip window; source-rights approval needed). NHL diff: applying it breaks 2 upstream tests and would quadruple context polling; **withdrawn and deleted**. No PR, no schedule change, no polling activated.

## 5. Coverage actually gained
`ten.tiebreak_sweep_joint_table` (secondary role): DATA_IN_HAND -> **PARTIAL** (7 columns). Deterministic counting, add-0.5 smoothing and shrinkage `N/(N+80)`; hold inputs are the verified ext4 columns. Gates: determinism, 3 truncations, 3 perturbations (new seeds), own-game, non-vacuity, coverage 0.835; blind re-implementation from the brief (given only match files and the verified hold columns) **MATCH on all 7 columns over 302,906 rows** at 1e-9. Missing (so not FULL): catalog's regression-based opponent adjustment (additive used). Sackmann CC BY-NC-SA: research-cleared, not commercial. No FULL gained; no fitting, calibration, training or market-derived inputs.

## 6. Before / after (Phase 11 -> Phase 12)
| Measure | Before | After | Nature of change |
|---|---|---|---|
| FULL / PARTIAL / PROXY (distinct) | 58 / 179 / 19 | 58 / **180** / 19 | actual build +1 |
| DATA_IN_HAND | 21 | 20 | same input moved to PARTIAL |
| Verified computable | 277 | 277 | no change (already counted) |
| Predictive slots | 3,670 | 3,670 | none (no reclassification this phase) |
| PRIMARY covered / missing | 327 / 949 | 327 / **949** | **0 primary gain** (the input is secondary) |
| Built slots F/P/X | 204 / 722 / 93 | 204 / **723** / 93 | +1 |
| Built slots research-cleared (primary) | 155 (40) | **156** (40) | +1 |
| Built slots commercial-cleared (primary) | 11 (8) | 11 (8) | 0 |
| Independently complete archetypes | 0 / 170 | 0 / 170 | 0 |
Actual coverage gain this phase is **one PARTIAL input, one slot**. Metadata reclassification: none. Everything else is inventory and preparation; the 949-slot primary gap is unchanged and cannot move until CFBD/MoneyPuck access (or other cleared data) exists.

## 7. Next 20 missing inputs (ranked by primary slots x feasibility weight; source = catalog provenance)
| # | Input | Primary slots | Sources | Feasibility | Best source tier |
|---|---|---|---|---|---|
| 1 | `NBA:nba.lineup_adj_rating` | 7 | derived, nba_official, nba_stats_api | free source exists; rights/builder open | unresolved internal only |
| 2 | `NBA:nba.rating_blowout_minutes_curve` | 7 | bbref, nba_cdn, nba_official | free source exists; rights/builder open | unresolved internal only |
| 3 | `TENNIS:ten.retirement_settlement_rules` | 7 | kalshi_api | free source exists; rights/builder open | unresolved internal only |
| 4 | `CBB:cbb.ratings` | 5 | barttorvik, epm_darko, odds_paid | direct CFBD/CBBD API (needs owner authorization) | unresolved internal only |
| 5 | `MLB:mlb.sp_workload` | 5 | bbref_baseball, mlb_statsapi, savant | free source exists; rights/builder open | unresolved internal only |
| 6 | `NFL:nfl.model_team_points_mean` | 5 | nflverse | free source exists; rights/builder open | wrapper licence upstream caveat |
| 7 | `NHL:nhl.player_season_points_projection` | 5 | nhl_api, nst | MoneyPuck listed download (evidenced files only) | unresolved internal only |
| 8 | `SOCCER:soc.comp_sim` | 5 | football_data_org, football_data_uk, openfootball | free source exists; rights/builder open | cleared open licence |
| 9 | `CBB:cbb.bracket_sim` | 4 | barttorvik, massey, ncaa_official | direct CFBD/CBBD API (needs owner authorization) | unresolved internal only |
| 10 | `MLB:mlb.sp_hook_hazard_curve` | 4 | mlb_statsapi, retrosheet | free source exists; rights/builder open | unresolved internal only |
| 11 | `MLB:mlb.team_wrc_vs_hand` | 4 | fangraphs, mlb_statsapi, savant | free source exists; rights/builder open | unresolved internal only |
| 12 | `SOCCER:soc.tiebreaker_rules` | 4 | football_data_org, rules_docs, uefa_fifa_official | free source exists; rights/builder open | unresolved internal only |
| 13 | `CBB:cbb.player_usage` | 3 | barttorvik, ncaa_official, sports_reference | direct CFBD/CBBD API (needs owner authorization) | unresolved internal only |
| 14 | `CBB:cbb.stat_dist` | 3 | barttorvik, espn_cbb, sports_reference | direct CFBD/CBBD API (needs owner authorization) | unresolved internal only |
| 15 | `MLB:mlb.run_dist` | 3 | chadwick, mlb_statsapi, retrosheet | free source exists; rights/builder open | unresolved internal only |
| 16 | `NFL:nfl.model_margin_lattice` | 3 | derived, nflverse | free source exists; rights/builder open | wrapper licence upstream caveat |
| 17 | `NFL:nfl.model_team_td_mean` | 3 | nflverse | free source exists; rights/builder open | wrapper licence upstream caveat |
| 18 | `NFL:nfl.player_stat_variance` | 3 | nflverse | free source exists; rights/builder open | wrapper licence upstream caveat |
| 19 | `NFL:nfl.rz_share` | 3 | nflverse | free source exists; rights/builder open | wrapper licence upstream caveat |
| 20 | `NFL:nfl.skill_avail` | 3 | news_press, nflverse | free source exists; rights/builder open | wrapper licence upstream caveat |
Honest reading: most top items are model/simulation inputs or have rights-unresolved sources; the CBB entries depend on owner authorization of the CBBD key, the NFL entries on the nflverse upstream-terms question, SOCCER `comp_sim` is the only one on a commercially open (CC0) tier but is a simulation.

## 8. Owner actions (none taken by the agent)
1. Allow the two provider hosts or verify both terms texts yourself; confirm the exact secret names and the shared monthly cap.
2. If you want collection: write `college_direct_authorization.json` (cap, `max_share_of_cap` <= 0.5, expiry); first run should be a ~10-call probe to measure quota and confirm endpoints.
3. Decide ESPN/NHL polling terms before the held NBA diff is proposed as a PR.

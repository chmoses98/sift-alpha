# Provider-level acquisition plan (RESEARCH_ONLY — planning only)

Source: Market & Input Map on `claude/sift-alpha-free-data-coverage-wdmcaz` @ `88b0a77` (PR #71 merged).
Inputs: `research/input_research/market_input_map/map.json`, `data_foundation/datasets.json`, `data_foundation/rights_registry.json`.
Nothing here was collected, probed, purchased, registered, scheduled or cleared. No licence approval is asserted.
"Accessible" (data in hand or reachable) is never the same as "cleared" (rights registry permits research use + collection).

## Method

- Scope: the 86 `RIGHTS_APPROVAL_NEEDED` queue datasets, which cover **857 distinct missing PRIMARY slots** (of 949).
- Each dataset's non-cleared sources were rolled up to the upstream rights holder (68 source ids → 36 providers;
  e.g. `espn_json` + `espn_cbb` + `espn_nba_archive` → ESPN; `bbref` + `pfr` + `sports_reference` → Sports Reference;
  `nhl_api` + `nhl_archive` → NHL; `mlb_statsapi` + `savant` → MLBAM).
- Slots are deduplicated as (archetype, input) pairs. "Unlock alone" = slots on a dataset whose **only** blocking provider is this one.
  Datasets needing several providers count only once all of them are cleared (greedy marginal order below).
- Wrapper sources (nflverse, sportsdataverse/hoopR) are attributed to the wrapper; their upstream holder is noted separately.

## Provider ranking (rights-group slots, deduplicated)

| # | Provider | Datasets | Slots touched | Unlock alone | Cumulative (greedy) | Archetypes cum. | Access state | Rights evidence on file |
|---|---|---|---|---|---|---|---|---|
| 1 | ESPN (Disney) | 16 | 280 | 224 | 224 | 56 | **219 of 224 already archived** (NBA team/player/PBP/stints, CBB, CFB games) | None. Undocumented endpoints; Disney ToS not reached (DNS) |
| 2 | nflverse (CC BY 4.0 wrapper) | 12 | 167 | 162 | 385 | 83 | All reachable (HTTP 206); none archived | Wrapper licence read verbatim; upstream NFL/FTN/NGS/PFR terms not granted |
| 3 | MLB Advanced Media | 9 | 151 | 134 | 519 | 108 | 82 archived, +48 reachable (pitch/PA), Savant blocked from runner | None; MLB Stats API bulk-reuse terms unverified |
| 4 | NHL | 8 | 68 | 66 | 585 | 123 | **All 66 already archived** | None; NHL API terms unverified |
| 5 | football-data.co.uk | 1 | 65 | 65 | 650 | 146 | Reachable | **Restrictive** provider statement read: private individuals only; not commercial, not automated/AI training |
| 6 | CollegeFootballData | 4 | 52 | 34 | 688 | 152 | Blocked from runner / key required | Owner-reported terms permit research + derived commercial outputs; text not agent-verified; registry `collection_allowed=false`; source id `cfbd` not tokenised to registry entry (fails closed) |
| 7 | football-data.org | 1 | 31 | 31 | 715 | 152 | Reachable (key) | None (no registry entry) |
| 8 | Kalshi | 2 | 32 | 32 | 738 | 163 | Reachable | None (no registry entry) — this is the market venue itself |
| — | Sports Reference LLC | 13 | 139 | 13 | | | Mostly unprobed; high ToS risk | None |
| — | Wikimedia | 18 | 285 | 1 | | | Unprobed / reference | None recorded (public open licences exist but not read into the registry) |
| — | Governing-body rulebooks | 7 | 200 | 0 | | | Reference documents | None recorded |
| — | NCAA / conferences | 8 | 210 | 3 | | | Unprobed | None; ncaa.com not reached |
| — | NOAA/NWS, Open-Meteo | 4 + 2 | 79 + 46 (overlap) | 0 | | | Blocked from runner | None recorded |

The top five providers alone reach **650 of 857** rights-group slots and 146 of 170 archetypes. The long tail (Wikimedia, rulebooks, NCAA,
Sports Reference, weather) touches many slots but almost never alone: e.g. 120 slots need rulebooks + NCAA + Wikimedia together, 71 need
NOAA + Wikimedia + Chadwick together.

## Accessible vs cleared

- **Already archived, rights-blocked:** ESPN + NHL + MLB archives = **367 slots, 95 archetypes, 295 inputs** (250 of them need no prospective or paid
  dataset at all). No collection would be needed; only a rights decision, then build + blind verification.
- **Reachable, rights-blocked:** nflverse 162, football-data.co.uk 65, MLB pitch/PA 48, Kalshi 32, football-data.org 31.
- **Cleared:** only openfootball (CC0), Sackmann (CC BY-NC-SA, non-commercial) and MoneyPuck listed downloads (owner-reported, NC) are research-cleared,
  and CFBD direct API is cleared-by-owner-report but `collection_allowed=false`. Nothing in this plan changes that.

## Licensing / ToS uncertainties and the evidence needed

| Provider | Open question | Evidence or permission needed |
|---|---|---|
| ESPN | Do Disney terms allow retaining and analysing data pulled from undocumented `site.api.espn.com` endpoints for internal non-commercial research? | Owner reads disneytermsofuse.com (not reachable from runner) and records the clause; likely no explicit grant, so written permission or an owner risk decision for internal-only use |
| nflverse | Does CC BY 4.0 on the wrapper carry through to NFL/FTN/NGS/PFR-derived columns? | Per-column upstream mapping + upstream terms (NFL, FTN, NGS); owner decision on which columns are usable |
| MLBAM | Bulk reuse of `statsapi.mlb.com` / Savant | MLBAM copyright notice / terms text; the commonly cited notice limits use to individual non-commercial non-bulk — must be read verbatim before any decision |
| NHL | `api-web.nhle.com` terms | NHL terms of use text; owner decision |
| football-data.co.uk | Statement excludes automated/AI-training use; disclaimer page unread | Read disclaimer.php; otherwise written permission from the operator. Treat as **not usable** pending that |
| CFBD | Terms text not agent-verified; registry token gap | Owner-pasted or archived copy of collegefootballdata.com/terms with clause text; then an owner-approved registry change (not done here) |
| Kalshi | Public market-data API terms for retention/analysis | Kalshi API / developer terms text; owner decision |
| football-data.org | Free-tier terms | Terms text; key registration would be a new account (not done) |
| MoneyPuck | `nhl.shots_xy` mixes listed (NC) and unlisted data | Exact file list from data.htm; unlisted data needs MoneyPuck approval |

## Reusable coverage across sports

- **Kalshi** spans 6 sports / 30 archetypes from 2 datasets (rules text + prices) — highest archetype breadth per dataset, and it is the settlement venue.
- **ESPN** spans 4 sports (NBA, CBB, CFB, NFL) and is the largest single unlock.
- **Wikimedia, rulebooks, NOAA/weather, Chadwick** each span 7–8 sports but only unlock jointly; clearing one alone yields ~0 slots.
- Sport-specific: nflverse (NFL), MLBAM (MLB), NHL, football-data (soccer), CFBD (CFB).

## Top 5 actions (prioritised; none executed)

1. **Owner rights decision on the three already-archived providers (ESPN, NHL, MLBAM).** 367 slots / 95 archetypes with zero new collection.
   Needs: owner reads each provider's terms off-runner and records verbatim text + decision in `rights_registry.json` (a permissions change — requires approval).
2. **nflverse column-level upstream audit.** Paper exercise over already-read licence + data dictionary: classify columns by upstream (NFL/FTN/NGS/PFR/nflverse-derived).
   Unlocks up to 162 NFL slots; output is the evidence the owner needs. Free, no collection.
3. **Close registry token gaps (CFBD, Kalshi) as a documented proposal, not a change.** `cfbd` and `kalshi_api` fail closed only because no registry entry matches;
   CFBD already has owner-reported terms. Avoid duplicating PR #69 (CFBD/CBBD direct-API probe, on `main`). Needs owner confirmation of terms text before any registry edit.
4. **Split `soc.fixtures_intl` scope proposal.** It is blocked only by football-data.org while its other source, openfootball, is CC0-cleared.
   Assess (from archived openfootball snapshots only) whether openfootball alone covers the 31 slots; if so, propose a dataset split. Free, no permission needed to assess.
5. **Joint reference-source licence read (Wikimedia, rulebooks, NOAA).** These unlock nothing alone but appear in datasets covering 285 (Wikimedia), 200 (rulebooks) and 79 (NOAA) slots.
   One owner pass recording the published licences (Wikimedia CC BY-SA/CC0, US-government public domain for NOAA, rulebook copyright) would clear many multi-provider datasets at once.

Deprioritised: football-data.co.uk (explicit restrictive statement), Sports Reference (high ToS risk, little unlocked alone), paid/blocked group.

## Requires approval before any step proceeds

Any registry/rights edit, any fetch of provider terms from the runner, API keys/accounts (CFBD, football-data.org), network allowlist changes,
collection or capture schedules, builders/verification runs, and any merge.

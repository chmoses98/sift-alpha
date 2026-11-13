# Provider-level acquisition plan (RESEARCH_ONLY — planning only)

Source: Market & Input Map on `claude/sift-alpha-free-data-coverage-wdmcaz` @ `88b0a77` (PR #71 merged), carried onto
`claude/provider-licensing-research-k7d0tj` (2026-11-13 revision: licensing evidence review, need-level recalculation, openfootball check).
Inputs: `research/input_research/market_input_map/map.json`, `data_foundation/datasets.json`, `data_foundation/rights_registry.json`.
Licensing evidence: `docs/PROVIDER_LICENSING_EVIDENCE.md`. Reproducible numbers: `research/provider_licensing/priority_recalc.{py,json}`.
Nothing here was collected, probed, purchased, registered, scheduled or cleared. No licence approval is asserted; the registry is unchanged.
"Accessible" (data in hand or reachable) is never the same as "cleared" (rights registry permits research use + collection).

## What changed in this revision

1. **The first ranking overstated what a single rights decision buys by about 4×.** It credited a provider with every slot on a dataset whose
   only blocker is that provider. But most inputs need several datasets (results + rules + venue + availability…). Re-counted per input *need*:
   clearing all eight top providers completes **192 of 857** slots (166 with data reachable or archived; **37** with zero new collection),
   not 738.
2. **Order changes.** nflverse moves to #1 (74 completed slots). NHL falls from #4 to ~0: its 66 archived slots also need `nhl.shots_xy` (MoneyPuck + NHL),
   shifts, injuries, etc. The "367 archived slots" headline for ESPN+NHL+MLBAM becomes **37 need-complete with zero collection**: ESPN 35, NHL 1, MLBAM 1.
3. **openfootball does not replace football-data.org for `soc.fixtures_intl`.** The archived material is club domestic leagues only. It covers the results need for 10 of
   31 slots, and those only for league-format competitions. It covers 1 slot completely. See below.
4. **nflverse's explicit open licences don't reach the slots that matter.** The FTN CC BY-SA lane completes 0 slots alone. 73 of nflverse's 74 need NFL-feed
   fields, which nflreadr itself says remain "governed by their [owners'] terms of use".
5. Official terms for CFBD, ESPN/Disney, MLB, NHL, football-data.org, Kalshi and FTN were **unreachable** from this container (DNS policy).
   Search-index excerpts are recorded as leads only, not as evidence for a decision.

## Method

- Scope: the 86 `RIGHTS_APPROVAL_NEEDED` queue datasets, which cover **857 distinct missing PRIMARY slots** (archetype × input pairs).
- Sources roll up to the upstream rights holder (e.g. `espn_json` + `espn_cbb` + `espn_nba_archive` → ESPN; `nhl_api` + `nhl_archive` → NHL;
  `mlb_statsapi` + `savant` → MLBAM; `bbref` + `pfr` + `sports_reference` → Sports Reference). A source is non-blocking only if the registry has
  `research_cleared` and `collection_allowed` (today: openfootball, Sackmann; nflverse has `collection_allowed` but not `research_cleared`, so it blocks).
- **Dataset-level (upper bound, the previous method):** a slot counts for provider P if any dataset listing it is blocked only by P.
- **Need-level (this revision):** a slot counts only if *every* `need` of its input in `dataset_edges` (SATISFIED_BY) has at least one usable dataset.
  A dataset is usable if all its non-cleared providers are in the hypothetical clearance set. Gates:
  `rights_only` (dataset is not prospective-only/paid/no-source/sample), `reachable_or_archived`, `archived_only` (zero collection).
  Baseline check: with no new clearance, 0 of the 857 slots are need-complete, as expected.
- **PIT-strict:** input `pit_verdict = PIT_SAFE`, slot not `PROSPECTIVE`, and the dataset edge's pit is `EVENT_TIME`/`PIT_NATIVE`/`STATIC`.
- Caveat: the map's need lists may be over-specified for some inputs, so need-level is a conservative estimate, while dataset-level is an upper bound.
  The true figure lies between them.

## Recalculated provider priority (distinct missing PRIMARY slots)

| Provider | Dataset-level upper bound | of which archived / reachable / needs collection | **Need-level (rights only)** | Need-level, reachable or archived | Need-level, **archived (zero collection)** | …and PIT-strict | Reachable + PIT-strict |
|---|---|---|---|---|---|---|---|
| nflverse | 162 | 0 / 162 / 0 | **74** | 74 | 0 | 0 | 55 |
| MLBAM | 134 | 82 / 48 / 4 | **38** | 34 | 1 | 0 | 22 |
| ESPN | 224 | 219 / 0 / 5 | **37** | 35 | **35** | **27** | 27 |
| CFBD | 34 | 0 / 0 / 34 | **16** | 0 (host blocked, key) | 0 | 0 | 0 |
| Kalshi | 32 | 0 / 32 / 0 | **11** | 11 | 0 | 0 | 9 |
| football-data.co.uk | 65 | 0 / 65 / 0 | 4 | 4 | 0 | 0 | 3 |
| football-data.org | 31 | 0 / 31 / 0 | 4 | 4 | 0 | 0 | 4 |
| NHL | 66 | 66 / 0 / 0 | 2 | 1 | 1 | 1 | 1 |
| Sports Reference, NBA, NCAA, Wikimedia, Rulebooks, MoneyPuck, NOAA | 0–13 each | — | 0–1 each alone | | | | |

Every need-level slot above is exclusive to its provider: no other single provider completes it.
Joint (all eight above cleared): 192 rights-only / 166 reachable-or-archived / 37 archived.

Need-level greedy order (rights only), which shows the pairings that matter:
nflverse +74 → MLBAM +38 → ESPN +37 → **NBA +21** (with ESPN: `nba.injury_report_vintages`) → **Sports Reference +22** → **NCAA +27** → CFBD +20 →
Kalshi +14 → Rulebooks +11 → Wikimedia +14 → **UEFA/FIFA official +41** → nba_transactions +15 (cumulative 334).
The long tail (NCAA, rulebooks, Wikimedia, UEFA/FIFA) is worth more at need level than the old table suggested, because those sources are joint needs of many inputs.

## `soc.fixtures_intl` without football-data.org (openfootball check)

Detail: `research/provider_licensing/soc_fixtures_intl_openfootball.json` (read-only; the raw clones are not in this container).
Archived scope: `openfootball/{england,deutschland,espana,italy}` at the pinned SHAs (Phase 8), parsed by `alpha_engine/features/soccer_of_ext.py`.
It holds ENG tiers 1–5 (2000-01+), GER/ESP/ITA tiers 1–2 (2010-11+), 82,195 matches with date, teams and FT score. There are no internationals, World Cup/Euro,
UEFA club competitions, domestic cups, play-offs, ET/penalty fields or venues.

| Verdict | Slots | Which |
|---|---|---|
| Results need met by archive, league-format only | 10 | `h2h_zero_sum_fixtures` (h2h); `tournament_joint_finish_distribution` (h2h, winner/top-n, relegation); `remaining_schedule_strength` (winner/top-n, relegation, team points); `fixture_sequence_win_vector` (team points, win streak); `calendar_year_fixture_sequence` (win streak) |
| …of which completed by the archive alone | **1** | `competition_head_to_head × h2h_zero_sum_fixtures`, for the 4 archived countries only. Its remaining fixtures need a current-season snapshot, which is a new clone |
| Not supported by archive | 21 | knockout/bracket/UEFA (6), extra time / knockout factor / ties (4), World Cup groups/KOs/goal environment/team expectation (5), awards, qualifying windows, play-off bracket, cross-tier, playoff formats, host relocation (prospective) |

- The other 9 "met" slots still need uncleared datasets: `soc.competition_rules` (rulebooks/UEFA/Wikimedia), `env.venue_geo` (Wikimedia/NOAA/Chadwick)
  and `soc.results_shots_cards` (football-data.co.uk, restrictive).
- Two more slots, `group_table_pattern_probability` and `tournament_goal_environment` (tournament_aggregate_event_props), have results as their *only* need.
  `openfootball/worldcup` (CC0 per the repo sidebar) could satisfy them, but that needs a verbatim LICENSE read plus collection. Neither was done.
- **Conclusion:** a dataset split into "openfootball domestic leagues" and "international/tournament" is justified, but it completes at most 1 slot now
  (3 with a World Cup clone). football-data.org remains the only listed route for the rest, and its free-tier terms are unread.

## Decision table

| Provider | Verified permissions (grade) | Research / commercial limitations | Datasets affected | Unique slots potentially unlocked (need-level; dataset-level upper bound) | Remaining blockers | Exact next action |
|---|---|---|---|---|---|---|
| **nflverse** | CC BY 4.0 on nflverse-data and nflverse-pbp (PRIMARY_READ); FTN charting and participation 2023+ CC BY-SA 4.0 "FTN Data via nflverse" (PRIMARY_READ, nflverse's statement); ffopportunity CC BY-SA 4.0 (PRIMARY_READ) | NFL-feed fields "governed by their [owners'] terms" (nflreadr README); ShareAlike on FTN/ffverse; PFR and betting-line columns separate | 12 NFL datasets (9 alone) | **74** (162); FTN lane alone: 0 | NFL upstream terms (lane C), PFR (lane D), FTN's own text unread | Owner reads the column audit and decides lane C for internal research; until then **blocked** |
| **MLBAM** | none; indexed copyright.txt: "individual, non-commercial, non-bulk use" (SECONDARY) | Bulk archives conflict with "non-bulk"; automated collection prohibited (SEARCH_EXCERPT) | 9 MLB datasets (5 alone) | **38** (134), archived 1 | Written MLBAM permission | Owner reads gdx.mlb.com/components/copyright.txt off-runner; expect a written-permission request; **blocked** |
| **ESPN** | none; Disney terms bar automated extraction, TDM and ML use (SEARCH_EXCERPT/SECONDARY) | Undocumented endpoints; no data licence | 16 datasets (9 alone) | **37** (224), **35 archived, 27 archived + PIT-strict** | Disney terms text; written permission | Owner reads disneytermsofuse.com and records clauses; highest zero-collection value **if** ever permitted; **blocked** |
| **CFBD / CBBD** | Search-index excerpts of the Aug 12 2026 terms: commercial use, caching, model training and Derived Outputs permitted; raw redistribution barred; shared CFBD/CBBD quota (SEARCH_EXCERPT; owner-reported in registry) | Third-party-originated data (lines, recruiting, polls) not addressed; key may not be shared | 4 CFB datasets (`cfb.pbp_cfbd` alone) | **16** (34) | Live terms not agent-read; registry token gap `cfbd`; key + host access; quota | Owner pastes or archives the live terms with clause numbers; then a separate approved registry proposal; **unchanged** |
| **Kalshi** | none; Developer Agreement v1.1 exists, use = acceptance (SEARCH_EXCERPT) | Possible member-only / own-trading restriction (SECONDARY) | `mkt.kalshi_rules`, `mkt.kalshi_prices` | **11** (32) | Agreement text | Owner reads the Developer Agreement PDF verbatim; **blocked** |
| **NHL** | none; terms (Oct 29 2025) prohibit scraping/harvesting (SEARCH_EXCERPT) | No API licence | 8 NHL datasets | **2** (66, all archived) | NHL terms + MoneyPuck unlisted data + shifts/injuries datasets | Deprioritise: a rights decision alone yields ≤2 slots |
| **football-data.org** | none; 2018 terms: attribution clause 7.1, post-subscription clause 9.1 (SEARCH_EXCERPT) | Free-tier commercial use unstated; key = new account | `soc.fixtures_intl` | **4** (31) | Terms text; account | Defer; split `soc.fixtures_intl` first (below) |
| **football-data.co.uk** | Provider statement read 2026-11-10: private individuals only; not commercial, not automated/AI (PRIMARY, Phase 10) | Explicitly excludes this use | `soc.results_shots_cards` | 4 (65) | Written permission | None; **not usable** |
| **openfootball** | CC0 1.0 (PRIMARY_READ; registry `CLEARED_OPEN_LICENCE` for 4 repos); worldcup/euro CC0 per sidebar only | None (CC0) | `soc.fixtures_intl` (partial), league builders | 1 now (+2 with a World Cup clone) | worldcup LICENSE.md verbatim read; collection approval | Propose a dataset split (domestic leagues vs international) |
| **Chadwick** | ODC-By 1.0 (PRIMARY_READ) | Attribution | `xx.id_crosswalk`, `env.venue_geo` (joint) | 0 alone | Joint needs (Wikimedia, NOAA) | Record as open-licence evidence for a future registry proposal |

## Zero-cost next steps (none executed; each needs only reading and owner time)

1. **Owner reads five terms pages off-runner and pastes the verbatim clauses into the evidence file:** collegefootballdata.com/terms,
   ftnfantasy.com/data (FTN grant), gdx.mlb.com/components/copyright.txt, disneytermsofuse.com, the Kalshi Developer Agreement PDF.
   These hosts are blocked here, so the owner's reading is the cheapest way to verify them.
2. **Owner decision on nflverse lane C** using `nflverse_column_audit.csv`. It is the largest single lever (74 need-level slots, 55 reachable + PIT-strict) and
   needs no collection decision. Collection is already allowed in the registry; only research clearance is missing.
3. **Approve (or reject) a `soc.fixtures_intl` split proposal:** `soc.fixtures_domestic_openfootball` (already CC0-cleared, archived) vs
   `soc.fixtures_international` (openfootball/worldcup + football-data.org). It is documentation-only and makes the 1–3 openfootball-supportable slots visible.
4. **Treat the earlier headline figures as superseded:** "367 archived slots" and "738 cumulative" appeared only in the previous revision of this plan (not elsewhere in `docs/`).
   Prioritise rights work on the need-level column; ask that the Market & Input Map add a need-level completion count per queue row.
5. **Optional, owner decision:** add the read-only terms hosts above to the network allowlist, so that future evidence reviews can read terms pages directly
   (documentation hosts only, no data endpoints).

## Requires approval before any step proceeds

Any registry/rights edit, any fetch of provider terms from the runner beyond read-only documentation, API keys/accounts (CFBD, football-data.org, Kalshi),
network allowlist changes, collection or capture schedules, builders/verification runs, dataset splits in the catalog, and any merge.

# Market & Input Map (RESEARCH_ONLY)

A read-only, navigable join of the approved catalog (baseline lock unchanged) and the latest data-foundation artifacts (Phase 14 head).
Nothing is researched, collected, probed, built, verified or scored anew. Agent-built, not independently or human verified.

    python -m alpha_engine.input_research.data_foundation.market_input_map     # regenerates research/input_research/market_input_map/
    python -m unittest tests.test_market_input_map                            # reconciliation + byte-identical regeneration
    node --test tests/market-input-map.test.mjs                               # UI helpers against the real artifact
    npx playwright test tests/market-input-map.spec.mjs --trace off           # navigation, filters, exports, iPhone overflow

UI: `src/market-input-map.jsx`, mounted in the existing Input Research section directly under Catalog Completeness. Views: Markets, Inputs, Datasets, Queue, Export.
Navigation: Market → Input → Raw dataset → Affected markets (with Back).
The Export view lists the committed CSV/JSON paths rather than serving them: the public build must contain no raw data files (gate in `.github/workflows/dashboard-ci.yml`).

## Units (never conflated)

| Unit | Count | Meaning |
|---|---|---|
| market archetypes | 170 | 118 registered + 52 unregistered |
| distinct inputs | 1,649 | rows of `verified_coverage.json` (sport × input id; 1,572 ids across sports); 1,614 sit under ≥1 market, 35 under none |
| catalog edges | 4,243 | every (archetype, input) listing: 3,670 predictive, 276 market-derived benchmark, 187 rules/settlement metadata, 110 operational |
| predictive slots | 3,670 | market_completeness predictive denominator (1,276 PRIMARY) |
| missing PRIMARY slots | 888 | PRIMARY predictive slots not FULL/PARTIAL/PROXY: FREE_ACCESSIBLE 490, PROSPECTIVE 300, NO_FREE_SOURCE 80, DATA_IN_HAND 8, CONTESTED 10 (949 before Phase 15: `docs/PHASE15_NBA_NHL_ARCHIVE_BUILDERS.md`) |

The predictive/non-predictive split is imported from `market_completeness.py` (per-archetype match is tested). The display split of the non-predictive
edges is: RULES_SETTLEMENT_METADATA = m.rules_text, soc.competition_scope_and_win_definition, m.settlement_truth, m.stat_correction_risk, m.stat_source_mismatch;
OPERATIONAL = m.lifecycle, m.fees, m.orderbook_depth, m.trade_tape, m.volume_oi; MARKET_BENCHMARK = every other verified EXCLUDED_BENCHMARK_ONLY input plus m.strike_hit_rates.

Statuses are copied verbatim: verified bucket (FULL/PARTIAL/PROXY/DATA_IN_HAND/REQUIRES_COLLECTION/BLOCKED/FAILED/UNVERIFIED/EXCLUDED), verified_status, audit status, market-completeness category. Null history/provenance is shown as UNKNOWN.

## Datasets, sources and rights

5,196 dataset–input edges (4,266 SATISFIED_BY = one per recorded requirement; 930 CANDIDATE_ALTERNATIVE), each carrying the requirement's need, trigger and PIT.
Built inputs also show their builder columns and raw sources from the verification replays. Proposed raw links are the probed URLs in `probes.json`.
Rights are fail-closed via `rights.py`: a dataset takes the weakest tier of its sources; a source with no registry entry (e.g. kalshi_api) is UNRESOLVED.
A source/dataset is labelled usable (RESEARCH_USE_PERMITTED) only when its tier is research-cleared AND the registry allows collection; commercial use only for commercial-cleared tiers.

## Acquisition queue

One row per dataset (120 datasets) for the 888 missing PRIMARY slots; each slot is listed under every dataset its input's requirements name (one dataset per requirement: the full definition needs ALL of them; `candidates` are the any-of alternatives for a single requirement and are not queued), so the 2,231 slot–dataset pairs
are not a slot total (distinct slots covered: 888; slots without a dataset: 0). Order uses only recorded factors, no composite score:
`access_rank` (datasets.json) → rights tier (strongest first) → `pit_rank` → cost → missing PRIMARY slots → id.
“Sole outstanding” is an ESTIMATE (every other satisfying dataset already archived; n/a for archived datasets). Next actions are proposals; none is executed.

### Action groups (follow-up)

Each queue dataset gets exactly one `action_group`, by the first matching rule in this precedence (recorded access status + rights only; ranks unchanged):
BLOCKED_OR_PAID (PAID_ONLY / SAMPLE_ONLY / NO_FREE_SOURCE) → PROSPECTIVE_CAPTURE_REQUIRED (PROSPECTIVE_CAPTURE_ONLY) → RIGHTS_APPROVAL_NEEDED (rights do not permit research use)
→ ARCHIVED_BUILD_NEXT (COLLECTED_ARCHIVE, research use permitted) → FREE_COLLECTION_POSSIBLE (any other free path, research use permitted). `also_needs_rights_approval` flags
blocked/prospective rows whose rights are also pending.

| Group | datasets | distinct slots | only in this group | by access status |
|---|---|---|---|---|
| Already archived · build next | 1 | 21 | 8 | archived 1 (ten.matches, Sackmann, non-commercial) |
| Rights approval needed | 85 | 796 | 495 | archived 14 · free reachable 20 · unprobed 38 · host-blocked 7 · unconfirmed 1 · reference doc 5 |
| Free collection possible | 0 | 0 | 0 | — every free path is on a source whose rights do not yet permit research use |
| Prospective capture required | 26 | 318 | 66 | prospective 26 (all also need rights) |
| Blocked / paid | 8 | 91 | 4 | paid 3 · sample-only 2 · no free source 3 (7 also need rights) |

Per-group slot counts overlap (315 slots need datasets in several groups); the “only in this group” counts plus 315 equal the 888 distinct slots. In `reconciliation.json` → `queue_groups`.

### Filters (follow-up)

One linked model drives every view: filters select matching market→input edges/inputs; Markets show markets owning a matching edge, Inputs the matching inputs,
Datasets those feeding a matching input (commercial-use also requires the dataset itself to be commercial-cleared), Queue the rows with ≥1 matching missing-PRIMARY slot
(“n of N slots match”; ranks, groups and committed totals never change). Each view prints its rule. Tested by brute-force recomputation in `tests/market-input-map.test.mjs`.

### Mobile loading (follow-up)

The summary renders from `reconciliation.json` (≈4 KB gz in the main bundle); the 2.9 MB index (`map.json`, ≈280 KB gz) loads only when the section is within ~1,200 px of the
viewport or on “Load the map now”. iPhone 13 emulation, production build, 1.6 Mbps / 150 ms RTT / 4× CPU (median of 3): map summary 8.9 s → 6.0 s, bytes at summary
1,140 KB → 627 KB, index no longer fetched at first load; scroll-to-interactive ≈2.9 s. The page shell (~5.7 s) is bounded by the existing main bundle, unchanged here.

## Unmapped / unlinked (reported, not hidden)

0 catalog edges with an unknown input · 0 unknown dataset references · 0 missing PRIMARY slots without a dataset · 0 in-scope live series (of 2,610) unmapped to an archetype ·
35 distinct inputs with no market edge · 11 datasets no requirement names · 11 archetypes with no in-scope live series. Full lists: `reconciliation.json`.

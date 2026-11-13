# Market & Input Map (RESEARCH_ONLY)

A read-only, navigable join of the approved catalog (baseline lock unchanged) and the latest data-foundation artifacts (Phase 14 head).
Nothing is researched, collected, probed, built, verified or scored anew. Agent-built, not independently or human verified.

    python -m alpha_engine.input_research.data_foundation.market_input_map     # regenerates research/input_research/market_input_map/
    python -m unittest tests.test_market_input_map                            # reconciliation + byte-identical regeneration
    node --test tests/market-input-map.test.mjs                               # UI helpers against the real artifact
    npx playwright test tests/market-input-map.spec.mjs --trace off           # navigation, filters, exports, iPhone overflow

UI: `src/market-input-map.jsx`, mounted in the existing Input Research section directly under Catalog Completeness. Views: Markets, Inputs, Datasets, Queue, Export.
Navigation: Market → Input → Raw dataset → Affected markets (with Back).

## Units (never conflated)

| Unit | Count | Meaning |
|---|---|---|
| market archetypes | 170 | 118 registered + 52 unregistered |
| distinct inputs | 1,649 | rows of `verified_coverage.json` (sport × input id; 1,572 ids across sports); 1,614 sit under ≥1 market, 35 under none |
| catalog edges | 4,243 | every (archetype, input) listing: 3,670 predictive, 276 market-derived benchmark, 187 rules/settlement metadata, 110 operational |
| predictive slots | 3,670 | market_completeness predictive denominator (1,276 PRIMARY) |
| missing PRIMARY slots | 949 | PRIMARY predictive slots not FULL/PARTIAL/PROXY: FREE_ACCESSIBLE 534, PROSPECTIVE 314, NO_FREE_SOURCE 80, DATA_IN_HAND 11, CONTESTED 10 |

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

One row per dataset (121 datasets) for the 949 missing PRIMARY slots; each slot is listed under every dataset its input's requirements name, so the 2,413 slot–dataset pairs
are not a slot total (distinct slots covered: 949; slots without a dataset: 0). Order uses only recorded factors, no composite score:
`access_rank` (datasets.json) → rights tier (strongest first) → `pit_rank` → cost → missing PRIMARY slots → id.
“Sole outstanding” is an ESTIMATE (every other satisfying dataset already archived; n/a for archived datasets). Next actions are proposals; none is executed.

## Unmapped / unlinked (reported, not hidden)

0 catalog edges with an unknown input · 0 unknown dataset references · 0 missing PRIMARY slots without a dataset · 0 in-scope live series (of 2,610) unmapped to an archetype ·
35 distinct inputs with no market edge · 11 datasets no requirement names · 11 archetypes with no in-scope live series. Full lists: `reconciliation.json`.

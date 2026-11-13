# Market & Input Map — read-only dependency dashboard

**Research only.** This feature is a new navigation surface **inside the existing** \`InputResearch\` view. It does not create an independent research system, change the frozen catalog, train models, access external sources, or authorize collection.

## Reproduce

\`\`\`sh
npm ci
npm run map:generate
npm test
npm run build
\`\`\`

\`npm run dev\` and \`npm run build\` run the generator automatically. The generated folder \`public/market-input-map/\` is intentionally ignored by git; \`dist/market-input-map/\` contains the deployable snapshot after building. No requests to data providers occur. The React interface fetches the snapshot only after a visitor expands **Explore dependencies**.

### Generated output

- \`graph.json\`: 170 markets, 1,649 verified-registry input records, deduplicated raw-dataset candidates, source rights and point-in-time notes, market-input edges, dataset-input candidates, categorical acquisition queue and full mapping diagnostics.
- \`market-input-edges.csv\`: **one record per market + catalog input**, with catalog role, predictive/benchmark/rules/operations class and verified status.
- \`distinct-inputs.csv\`: **one record per sport-qualified input ID**, with every affected market and candidate dataset.
- \`dataset-input-edges.csv\`: **one candidate dataset + input record**; real field IDs only when explicitly declared in an existing audit, otherwise \`FIELD_UNMAPPED\`.
- \`acquisition-queue.csv\`: one candidate dataset with deduplicated **potential** missing PRIMARY market-input edge count, feasibility/rights/PIT/cost gates and a concrete first action.
- \`reconciliation.json\`: exact source denominator counts and all unmapped records. The generator prints count totals; tests validate the frozen invariants and CSV row counts.

### Denominators (approved artifacts)

| Measure | Source artifact | Exact count |
|---|---|---:|
| Distinct sport-qualified catalog inputs | \`data_foundation/verified_coverage.json\` | **1,649** |
| Market archetypes across 8 sports | \`market_completeness/market_completeness.json\` | **170** |
| Predictive requirement slots (repeated across markets) | Market completeness rows, \`predictive_required\` | **3,670** |
| Predictive PRIMARY slots | Market completeness rows, \`predictive_primary\` | **1,276** |
| Verified FULL/PARTIAL/PROXY PRIMARY slots | \`primary_FULL+primary_PARTIAL+primary_PROXY\` | **327** |
| Missing predictive PRIMARY slots | 1,276 − 327 | **949** |

These are **not interchangeable counts**. Nonpredictive benchmark prices, rules/settlement metadata, settlement operations and calibration/operations are displayed under their markets but excluded from predictive counts. An input that appears on 20 markets is still one distinct input.

### Truth and rights safeguards

This view joins existing \`catalog/*.json\`, \`market_completeness/*.json\`, \`data_foundation/coverage_matrix.csv\`, \`verified_coverage.json\`, \`datasets.json\`, \`sources.json\`, \`rights_registry.json\`, \`input_audit.json\`, \`probes.json\`, \`market_universe/series_assignment.json\` and \`reconciliation.json\`. It does not mutate any of them.

- An observed or proposed dataset dependency **does not** mean the dataset alone supplies the full input. Multiple dataset candidates may be mutually dependent or alternatives. Acquisition counts are **within-dataset set cardinalities**, never a claim of incremental, additive coverage when multiple datasets overlap.
- An available free source is not automatically usable. The rights tier must cover the specific provider and acquisition path, and raw provenance, contractual use, exact fields and point-in-time windows must independently support use. Unresolved rights never appear as approved.
- \`FIELD_UNMAPPED\` is intentional if the catalog/audit does not establish raw column identifiers. A prose measurement idea is **not** converted into a fictional source field.
- Direct \`series_assignment.json\` rows are used when they match a sport/archetype; the existing series reconciliation supplies only a documented grouping fallback. Series ≠ contracts. Unmatched assignments are exported as unresolved.
- \`FULL\`, \`PARTIAL\`, \`PROXY\`, \`DATA_IN_HAND\`, \`REQUIRES_COLLECTION\`, \`BLOCKED\`, \`FAILED\`, \`UNVERIFIED\` and \`EXCLUDED\` are shown as source statuses; "available free" and "potential market impact" are not verification buckets.
- The queue is sorted deterministically by **categorical feasibility** (provenance/right-to-use/PIT, then access) and deduplicated potential missing PRIMARY edges, with cost exposed. No invented performance or probabilistic scores are assigned.

## UI

Four views within the existing Input Research page: **Markets → Inputs → Raw datasets → Acquisition queue**. Tap a market to see every catalog edge and role; tap an input to see all markets and datasets; tap a dataset to inspect candidate raw fields and source rights; tap a queue item to see next action and its affected links. Cross-navigation resets filters so the selected record cannot be hidden by an old filter. Sport, market, input, status, PRIMARY-only, free candidates, prospective and commercial-rights-candidate filters remain explicit.

**Review boundary:** Branch only. No merges, API requests, credentials, schedules, orders, production predictions, paid services or catalog modifications.

# Catalog-completeness review: authoring and independent-review brief (RESEARCH_ONLY)

Goal: SIFT Alpha must know **what information is needed to evaluate every market** before any model is optimised. This is NOT a model task. No predictive experiments, no data downloads for modelling. Work from domain knowledge of how the sport actually produces the outcome and from the actual Kalshi contract text.

A populated list is not completeness. A record that merely reorders the existing catalog is a failure. The existing catalog entry is a *prior draft to be challenged*, not an answer to be copied.

## Per-archetype method (author)

For each archetype key in your assignment (evidence pack: `research/input_research/completeness/evidence/<SPORT>.json`, keyed exactly as the review file must be keyed; `unreg:<name>` for unregistered contract types):

1. **Derive the mechanism first, independently.** Before reading `existing_inputs`, write down from first principles how the contract's outcome is generated, as a chain of stages (e.g. for a player-points ladder: availability -> role/minutes scenarios -> possessions -> usage/attempt share -> shot-quality/conversion -> free-throw trips -> game-script truncation -> settlement/DNP handling). Name what makes each stage vary and its distributional shape (overdispersion, discreteness, zero-inflation, heavy tail, correlation with other stages).
2. **Read the contract.** Read every `rules_samples` entry for the archetype's `live_series`. State exactly what settles YES: period, overtime/extra time/penalties, DNP/void/postponement, ties, rounding, strike construction (floor_strike, "N+" vs over/under), source of truth. Quote verbatim (>=25 chars) from the sampled rules for >=2 distinct series where rules exist; the validator checks quotes are verbatim substrings. Note variants that differ inside one archetype (different periods, different thresholds, different resolution sources). If a series is TITLE_ONLY (no rules sampled) say so; do not infer settlement details you cannot see; put them in `unresolved` as CONTRACT_AMBIGUOUS.
3. **Challenge the existing inputs.** Every pre-existing input of the archetype must appear in `input_audit` with a verdict (`KEEP_PRIMARY|KEEP_SECONDARY|KEEP_CONTEXT|WEAK|IRRELEVANT|BENCHMARK_ONLY|DUPLICATE_OF:<id>`) and a specific reason. Look for: duplicated inputs measuring the same thing under two names, irrelevant variables, market-derived inputs that are benchmarks and not inputs, shallow "why" text, and role mislabelled (primary vs context).
4. **Find what is missing.** For each of the 13 taxonomy categories (`talent_strength, opponent_matchup, role_personnel, availability_news, coaching_scheme, environment, game_context_script, pace_volume, efficiency_conversion, distribution_variance, situational_schedule_motivation, officiating_rules, settlement_contract`) declare COVERED (input ids), NOT_APPLICABLE (a specific >=60 char reason, not "n/a") or GAP (also an `unresolved` entry with `category`). Think about: advanced statistics, opponent adjustments, player roles and personnel (who replaces whom), coaching, environment, game context, pace, volume, efficiency, distributions, situational effects, and the contract's own mechanics (e.g. ladder rungs are nested events with a monotone probability curve; DNP rules change the effective distribution).
5. **Define new inputs fully.** Each discovered input goes in `new_inputs` with: `label, category (catalog CATEGORIES), mechanism, rationale (why it matters here and what is subtle), measurement (exact calculation: window, half-life, opponent adjustment, shrinkage constant, units, as-of timestamp rule), pregame_knowable (yes|partial|no), free_sources, registry_ids ([] if none), raw_data (tables/fields), why (market-specific), role (primary|secondary|context)`. Ids use the sport's existing prefix. Do not re-add an existing input id. Inputs derived from a price/line/market are benchmarks: do not add them as inputs.
6. **Map interactions and non-linearities.** >=4 interactions, each with `inputs`, `form` (multiplicative|threshold|saturating|convex|concave|piecewise|conditional|joint-distribution|regime-switch|diminishing-returns|other-nonlinear), `mechanism` (why, direction, regime), `how_to_test` (the feature or contrast that would reveal it). >=2 `nonlinearities` (`input_id, shape, why`): response shape of a single input (e.g. minutes truncation in a blowout is a threshold in the spread).
7. **Define the raw data.** `required_data`: dataset, grain, fields, timestamp_requirement (as-of rule, vintage), history_needed, `candidate_sources` (name + access in `free|free_scrape|free_limited|paid|own_capture|unavailable_public|derived`; name real providers, including paid or inaccessible ones, honestly labelled), `feeds_inputs`. Do not claim a source exposes a field unless you know it does; if unsure use `SOURCE_UNVERIFIED` in `unresolved`.
8. **List what is still unresolved.** >=1 entry per archetype, type in `MECHANISM_UNCERTAIN|CONTRACT_AMBIGUOUS|DATA_UNAVAILABLE|INPUT_DEFINITION_UNCERTAIN|SOURCE_UNVERIFIED|OTHER`, with `description` (>=60 chars), `what_would_resolve` (>=30 chars) and optional `category`. Never write that an archetype is complete.

## Record schema (one JSON object per archetype; file = `research/input_research/completeness/reviews/<SPORT>_<part>.json` = `{archetype_key: record}`)

```
{
 "reviewer": "<agent label>", "review_date": "2026-11-07",
 "contract": {"settlement_definition": str>=120, "rules_verification": VERIFIED_FROM_RULES_TEXT|PARTIALLY_VERIFIED|NOT_VERIFIED_NO_RULES_TEXT|NO_LIVE_SERIES,
              "rules_evidence": [{"ticker","quote"(verbatim),"establishes"}], "variants_and_edge_cases": [str,>=2], "settlement_data_source": str},
 "mechanism": {"summary": str>=300,
               "stages": [{"id":"s1","name","description">=200,"distribution">=40,"categories":[taxonomy],"input_ids":[ids]}, >=3],
               "category_coverage": {<each of the 13>: {"status": COVERED|NOT_APPLICABLE|GAP, "input_ids":[..], "note": str}}},
 "new_inputs": {id: {...}}, "input_audit": {existing_id: {"verdict","reason"}},
 "interactions": [{"inputs":[..],"form","mechanism","how_to_test"}], "nonlinearities": [{"input_id","shape","why"}],
 "required_data": [{"dataset","grain","fields":[..],"timestamp_requirement","history_needed","candidate_sources":[{"name","access","note"}],"feeds_inputs":[..]}],
 "unresolved": [{"id","type","description","what_would_resolve","category"?}]
}
```

Check your work with `python -m alpha_engine.input_research.completeness` (prints per-archetype status) and read `gate.json` rows for `problems`. A structurally valid record is still worthless if the text is generic: each stage, interaction and gap must be specific to this contract and this sport. Text near-duplicated across archetypes is flagged and fails.

## Independent review (a different reviewer, not the author)

Write `research/input_research/completeness/independent/<SPORT>.json` = `{archetype_key: {"reviewer","date","verdict": "PASS_WITH_OPEN_GAPS|REVISE","findings":[{"id","severity":"BLOCKER|MAJOR|MINOR","text","resolution":"OPEN"}]}}`. Re-derive the mechanism chain yourself first from the contract text and your knowledge of the sport, then compare with the record. Look for: missing mechanisms or stages, wrong or generic mechanism claims, settlement details contradicted by the rules text, sources that do not expose what is claimed, inputs mislabelled (primary/context), duplicates or irrelevant variables left in, interactions that are not actually interactions, missing nonlinearities, gaps the author failed to disclose, and market-derived values smuggled in as inputs. Be adversarial and specific; "looks fine" without a re-derivation is a failure. Findings that would change which inputs/data are required are BLOCKER or MAJOR; wording issues are MINOR. Do not edit the reviewed files.

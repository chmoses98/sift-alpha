# Universal input verification engine

`python -m alpha_engine.verification_engine` regenerates `research/audit/verification/{summary,inputs,families,repair_tasks}.json` from the committed audit artifacts. Status is a pure function of recorded evidence; an unrecorded stage is UNKNOWN, never PASS.

Statuses: VALIDATED_PREDICTIVE, VERIFIED, COLLECTED_UNVERIFIED, COLLECTED_UNUSED, STALE, MISSING, UNSUPPORTED, UNKNOWN. Verified collection is not predictive validation, and predictive validation is not an executable after-fee edge.

Chain: source → archive → timestamp → transform → consumption (input level); market_mapping → projection → historical_eval → outcomes (family level). The first non-PASS stage is the recorded failure and drives `repair_tasks.json` (feeds the #7 remediation queue; tasks stay OPEN until a re-run changes the evidence).

Reference family: `CFB/quarter_total` — `CFB_quarter_total_chain.json` (26 candidate factors → inputs, registry gaps explicit), `CFB_quarter_total_ablation.json` (chronological input ablation, Bonferroni over all comparisons tried + both-halves check; regenerate with `python -m alpha_engine.cfb_q1_ablation DATA_DIR COMMIT`).

Overlay (`OVERLAY` in the engine) adds contextual links market_specs omitted; never essential, so the 1,762-link denominator is unchanged.

Not done: no market-price baseline for Q1 (no joined quote history); sports other than CFB have chain status but no factor trace/ablation; external sources (ESPN, nflverse) were unreachable from the build sandbox, so no new collection was possible.

## Multisport evidence layers (PR: multisport audits)
- `model_use_static.json` (`alpha_engine.model_use_probe`): AST identifier-level evidence in sport repos (docstrings excluded). Gives at most PARTIAL on the transform stage.
- `projection_outputs.json` (`scripts/audit_projection_outputs.py`): what NBA/CBB/NFL actually PUBLISH (pinned commits). An input-derived field populated and varying in the output + recorded USED gives consumption PASS; absence is never proof of non-use. A published output never makes a projection independently reproduced.
- `pricing_paths.json` (`scripts/audit_pricing_paths.py`): per-family module list that prices the market; each driver is REFERENCED or NOT_FOUND_IN_PRICING_PATH (bounded static negative).
- `source_verifications.json` (`scripts/measure_cfb_sources.py`): measurements of data already in sibling repos; can lift an input out of UNKNOWN/MISSING to COLLECTED_UNVERIFIED/STALE, never to VERIFIED.
- `repair_ledger.json`: disposition of investigated repair tasks (states checked by tests against the regenerated engine output).
- `CFB_quarter_total_ablation_pace_efficiency.json`: expanding-window ridge ablation using ESPN team-game pace/efficiency features.

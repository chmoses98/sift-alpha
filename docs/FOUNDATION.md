# Data foundation (generated artifacts)

`research/audit/` is the source of truth the dashboard renders. Nothing is hand-set to "done".

| file | what | built by |
|---|---|---|
| `master_inventory.json`, `inventory/<SPORT>.json` | observed Kalshi market families per sport (series, counts with basis + as-of, settlement text, evidence) | `python -m alpha_engine.master_inventory SRC_ROOT` |
| `snapshots/*` | pinned per-series aggregates of the latest archived market snapshots; archive branch trees | scratch scripts (see PR), inputs are public git blobs |
| `input_registry.json` | candidate inputs per sport + per family (ESSENTIAL/CONTEXTUAL/EXPLORATORY). Hypotheses only | `alpha_engine/input_catalog.py` via `foundation_report` |
| `code_evidence.json` | keyword code references per input per repo | `python -m alpha_engine.code_evidence SRC_ROOT` |
| `collection_status.json`, `collection_gap_report.json` | collection/archival/model-use status with evidence; ranked gaps | `python -m alpha_engine.foundation_report` |
| `audits/*.json` | end-to-end per-family audits (NFL TEAM_TOTAL first) | hand-verified, validated by `audit_schema` |

Rules: counts use per-sport denominators and are never summed across sports; 0 observed ≠ nonexistent; a code-reference hit
≠ collected or correctly used (uncurated inputs stay `CODE_REFERENCE_ONLY`/`NO_REFERENCE_FOUND` with model use `UNKNOWN`);
curated statuses must cite evidence. Tiers are candidate relevance, not validated predictive value.

## Added in the lineage pass
- `variant_audit.py` (NBA PROT equivalence), `tennis_intervals.py`, `soccer_ambiguity.py`, `family_coverage.py`, `timestamp_integrity.py`, `pit_guard.py` (soccer pregame weather guard; quarantines, never edits the archive), `series_sweep.py` + `.github/workflows/kalshi-series-sweep.yml`.
- Automated code->output-path tracing of the 136 code-reference-only inputs was tried and NOT adopted: it paired inputs with unrelated archive directories (the code file names many paths). Conversions are made only by directory-level probes with record timestamps (`lineage/context_probe.json`).

#!/usr/bin/env bash
# Regenerate every catalog / coverage artifact that depends on dataset evidence (RESEARCH_ONLY; no network, no model).
# Run after research/input_research/data_collection/*_ledger.json or research/certification/* changes.
#   bash scripts/research/regen_coverage_chain.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
DF="market_completeness full_promotion_audit rights_questions capture_plan prospective_plan source_mapping market_input_map"
python -m alpha_engine.input_research.regenerate --apply >/dev/null
for m in $DF verified_coverage; do python -m alpha_engine.input_research.data_foundation.$m >/dev/null; done
python -m alpha_engine.input_research.regenerate --apply >/dev/null          # second pass: verified_coverage feeds the catalog layer
for m in $DF; do python -m alpha_engine.input_research.data_foundation.$m >/dev/null; done
for m in sources ledger acquisition phase10 market_coverage; do
  python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('alpha_engine.foundation.$m') else 3)" || continue
  python -m alpha_engine.foundation.$m >/dev/null
done
python -m alpha_engine.input_research.regenerate --check | tail -1

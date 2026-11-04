"""Audit source-verified NBA/NHL literal contract identities (research-only)."""
import gzip
import json
from pathlib import Path
from .contract_lineage import audit_contract_lineage

if __name__ == "__main__":
    report = json.loads(Path("artifacts/verified_sparse_tape_status.json").read_text())
    with gzip.open("artifacts/verified_sparse_quote_tape.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    out = audit_contract_lineage(report, rows)
    target = Path("artifacts/contract_lineage_qualification.json")
    target.write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    for sport, row in sorted(out["sports"].items()):
        print(sport, "literal identity", row.get("n_literal_identity_observed_at_end", 0),
              "term conflicts", row.get("n_term_conflict_tickers", 0),
              "unresolved", row.get("n_unresolved_identity_tickers", 0))
    print("RESEARCH_ONLY, no game/settlement join:", target)

"""Emit the as-of literal event group ledger from pinned verified NBA/NHL tape."""
import gzip
import json
from pathlib import Path
from .event_groups import audit_event_groups
from .verified_tape import write_gzip_jsonl

if __name__ == "__main__":
    report = json.loads(Path("artifacts/verified_sparse_tape_status.json").read_text())
    with gzip.open("artifacts/verified_sparse_quote_tape.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    status, groups = audit_event_groups(report, rows)
    dest = write_gzip_jsonl("artifacts/literal_event_group_ledger.jsonl.gz", groups)
    Path("artifacts/literal_event_group_status.json").write_text(
        json.dumps(status, sort_keys=True, indent=2) + "\n")
    for sport, info in sorted(status["sports"].items()):
        first, last = info["snapshots"][0], info["snapshots"][-1]
        print(sport, "events at first/last board ticks",
              first["n_literal_event_tickers"], last["n_literal_event_tickers"],
              "multi-contract at last", last["n_multi_contract_events"])
    print("RESEARCH_ONLY; no physical-game joins:", dest)

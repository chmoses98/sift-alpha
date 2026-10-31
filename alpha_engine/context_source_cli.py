"""Qualify real independent NBA/NHL schedule and settlement archives."""
import gzip
import json
from pathlib import Path
from .context_source_audit import audit
if __name__=="__main__":
    manifest=json.loads(Path("research/context_join_pins.json").read_text())
    report=json.loads(Path("artifacts/verified_sparse_tape_status.json").read_text())
    with gzip.open("artifacts/verified_sparse_quote_tape.jsonl.gz","rt") as f:
        tape=[json.loads(line) for line in f]
    result=audit(manifest,report,tape)
    dest=Path("artifacts/context_join_qualification.json")
    dest.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    for sport,row in sorted(result["sports"].items()):
        print(sport, "schedule asof",row["schedule_capture_at"],
              "exact result ticker matches",row["n_exact_ticker_matches_to_sparse_tape"])
        for src in row["source_profiles"]:
            print(" ",src["kind"],src["captured_at"],src["profile"]["n_rows"],
                  "keys",src["profile"]["top_level_fields"][:30],
                  "nested",src["profile"]["nested_fields"][:35])
    print("RESEARCH_ONLY:",dest)

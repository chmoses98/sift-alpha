"""Verify and emit a bounded real Tennis hourly-full/changed quote prefix."""
import gzip
import json
from pathlib import Path
from .tennis_capture import audit

if __name__ == "__main__":
    spec=json.loads(Path("research/tennis_capture_pins.json").read_text())
    report, rows=audit(spec)
    root=Path("artifacts")
    root.mkdir(exist_ok=True)
    (root/"tennis_capture_status.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    with gzip.open(root/"tennis_observed_quote_rows.jsonl.gz","wt",encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row,sort_keys=True)+"\n")
    print("Tennis: verified",len(rows),"literal observed quote rows over",len(report["capture_reports"]),"captures")
    print("RESEARCH_ONLY; later complete boards, match starts, exchange settlement, fills not verified")

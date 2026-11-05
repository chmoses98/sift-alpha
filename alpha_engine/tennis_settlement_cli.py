"""Emit bounded pinned Tennis settlement evidence and strict historical quote overlap."""
import gzip
import json
from pathlib import Path
from .tennis_settlement import audit,join_prior_quotes

if __name__=="__main__":
    spec=json.loads(Path("research/tennis_settlement_pins.json").read_text())
    report,rows=audit(spec)
    quotes=Path("artifacts/tennis_observed_quote_rows.jsonl.gz")
    if not quotes.is_file():
        raise RuntimeError("Prior verified Tennis quote artifact required; do not fabricate joins")
    with gzip.open(quotes,"rt",encoding="utf-8") as f:
        quote_rows=[json.loads(line) for line in f]
    report["historical_quote_overlap"]=join_prior_quotes(rows,quote_rows)
    root=Path("artifacts")
    root.mkdir(exist_ok=True)
    (root/"tennis_settlement_status.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    with gzip.open(root/"tennis_settlement_rows.jsonl.gz","wt",encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row,sort_keys=True)+"\n")
    print("Pinned Tennis collector exchange-result fields:",len(rows),
          "records,",report["n_distinct_exchange_event_tickers"],"event tickers;",
          report["exchange_result_counts"])
    print("RESEARCH_ONLY: occurrence != actual match start, no execution authority")

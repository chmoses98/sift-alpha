"""Emit immutable research-only sparse Kalshi quote tape for NBA/NHL."""
import json
from pathlib import Path
from .verified_tape import build_tape, asof_ticker, write_gzip_jsonl

if __name__ == "__main__":
    manifest = json.loads(Path("research/verified_chain_pilot.json").read_text())
    report, rows = build_tape(manifest)
    target = write_gzip_jsonl("artifacts/verified_sparse_quote_tape.jsonl.gz", rows)
    for sport, status in sorted(report["sports"].items()):
        first = next(row for row in rows if row["sport"] == sport)
        probe = asof_ticker(rows, report, sport, first["ticker"], status["base_at"])
        assert probe["direct_quotes_dollars"] == first["direct_quotes_dollars"]
        assert probe["pregame_status"] == "UNVERIFIED"
        print(sport, "rows", status["n_sparse_tape_rows"],
              "quote changes", status["n_direct_quote_changed_rows"])
    Path("artifacts/verified_sparse_tape_status.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print("RESEARCH_ONLY:", target)

# Verified sparse quote tape — research only

The `verified_tape` module reconstructs actual, immutable NBA and NHL Kalshi market boards from the existing checkpoint and contiguous three-delta source pilot, validating all Git blob hashes and every upstream board hash **before** emitting a sparse event tape. No new paid data sources, API keys, or live orders.

Run `python3 -m unittest discover -s tests -p 'test_verified_tape.py' -v` and `python3 -m alpha_engine.verified_tape_cli`. Output is `artifacts/verified_sparse_quote_tape.jsonl.gz` and `artifacts/verified_sparse_tape_status.json`, both ephemeral CI research artifacts (not production data).

Each source event records sport, exact ticker, source file SHA1 and path, capture observation timestamp, lifecycle, four independently observed YES/NO bid/ask prices, source contract terms, and whether a direct quote differs from the previous ticker record. The checkpoint records every ticker once. Subsequent delta events record touched tickers only, including removals. A ticker unchanged at a later board tick is not emitted as a fresh quote.

`asof_ticker` returns the last known ticker state at or before an explicit timestamp, strictly within the **verified** prefix. It refuses queries before the checkpoint or after the last verified delta. The last ticker observation is not proof of an exchange quote update at that instant.

This does not establish event start time, pregame eligibility, settlement correctness, actual execution price/depth, trading profitability or full-day coverage. These remain P0 in issue #4. The next stage must join official physical game start times and unambiguous contract settlement rules before any pregame calibration research.

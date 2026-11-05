# Verified Kalshi delta-chain replay — milestone proof

Both NBA and NHL originally implemented `kalshi.board.delta/1` checkpoint+delta reconstruction. We have **reused their exact original core hash-chain implementation** in `alpha_engine/source_delta.py` (sourced from `chmoses98/nba-edge-finder/src/nba_edge/archive/delta.py`, Git blob `702eed5e55aedfa0aa355960622758aaa023db76`; the identical NHL implementation was inspected; the only functional import adaptation is Alpha's local ISO-8601 UTC compatibility helper).

`research/verified_chain_pilot.json` pins one **2026-10-25 checkpoint and three immediately following deltas** in each sport, using immutable full source git commits and each gzip file's Git blob hash. Total compressed input is approximately 1.86 MB. This is a **chain-prefix pilot**, not a full-day or all-season reconstruction.

```sh
python3 -m unittest discover -s tests -p 'test_verified_chains.py' -v
python3 -m alpha_engine.chain_cli
```

Checks: no unapproved API host or credentials, strict file-size and aggregate transfer budget, content identity with Git blob hash and checkpoint SHA256, correct base checkpoint and observation time, unique market tickers, contiguous delta sequences, strictly increasing times, verified intermediate parent/child board SHA256, final board SHA256 and market count. Extract a small sample of literal YES/NO bid/ask movements with exact tick timestamps and a denominator for unique changing tickers. Deliberately hostile unit tests target tampering, missing sequence and wrong provider.

**It does not** assume that any tick occurred before the affected game. Game start, line semantics, actual settlement outcome, bid/ask execution and liquidity are not joined yet. No profitable opportunity claims are permitted. A price that moves after kickoff must never be used as a pregame prediction input.

Next priority: stream source manifest partitions for a complete game day, reconstruct every checkpoint+delta chain, link verified sport physical-game timestamps and Kalshi event/rules/settlement, preserve event-clustered denominators, then test calibrated prospective strategies after fees and realistic execution.

See [P0 Issue #4](https://github.com/chmoses98/sift-alpha/issues/4).

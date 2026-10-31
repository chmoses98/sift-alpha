# Tennis historical Kalshi capture qualification (third sport)

The Tennis upstream writer records an hourly **full** capture and subsequent **changed-fingerprint** quote records. These are *not* NBA/NHL checkpoint+delta chains. We pinned three consecutive real capture runs on Oct 25 2026: 00:45, 00:55, and 01:05 UTC. The first run's manifest reports 1,411 open markets and 1,411 full quote records. The next runs report 286 and 357 changed-fingerprint records respectively. These counts are manifest observations until this PR's actual source-verified CI finishes.

```sh
python3 -m unittest discover -s tests -p 'test_tennis_capture.py' -v
python3 -m alpha_engine.tennis_capture_cli
```

The audit checks immutable full Git commit and six blob SHA-1 digests, compressed byte limits, gzip expansion budget, capture run identity and UTC windows, per-row capture timestamps, duplicate ticker rejection, exact reported counts, full-vs-changed source flags, incomplete upstream runs, and decimal quote range. Output: `artifacts/tennis_capture_status.json` and `artifacts/tennis_observed_quote_rows.jsonl.gz`.

**Crucial limitation:** a changed-fingerprint row can be caused by size or status rather than a price change. Later runs do not list unchanged markets or removals, so a *full subsequent board cannot be reconstructed* without a separately verified open-set ledger. A recorded quote timestamp is a capture timestamp, not necessarily when the quote changed. This stage does not assert market-to-physical-match mapping, actual start, exchange-native settlement joins, execution or profitability. It performs only free, read-only, bounded public GitHub source reads. Other sports remain at their documented individual evidence tiers.

Next: independently validate open-market membership/removals and exchange-native settlement rows, then expand a bounded contiguous archive prefix; no pregame or trading authority before actual-start and exact contract-rule joins.

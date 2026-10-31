# Unified Game-and-Market Timeline — V0 / Read-only Pilot

This begins the **Kalshi archive-first** intelligence foundation. The market tape should become a unified record linking:

`game context at time t → observed market quote and depth at time t → outcome → research`.

The current implementation is a **bounded, immutable, two-sport contract-observation replay**, not yet a full game-and-market timeline. It deliberately leaves game starts and physical-game identities unverified until an independent event mapping exists.

### Real archive test

Seven historical gzip JSONL archives, pinned by full Git commit and Git blob SHA from NBA and NHL `data-archive` branches, are enumerated in `research/timeline_pilot_sources.json`. The two-sport checkpoint sample is from 2026-10-25, with attached settlement partition(s). The total compressed download is capped at 4 MB. File bytes and decompressed sizes are checked; immutable SHA-256 provenance is emitted. No Kalshi API access or accounts.

```sh
python3 -m unittest discover -s tests -p 'test_timeline*.py' -v
python3 -m alpha_engine.timeline_cli --out artifacts/unified_timeline_pilot.json
```

The script extracts literal YES/NO bids and asks (including prices expressed as USD decimals), preserves row-level observed timestamps when available, and marks file-timestamp fallbacks as lower confidence. It groups repeated observations by **exact ticker**, sorts timestamps, reports observed quote movement, counts possible settlement matches, and explicitly refuses to treat contract count as independent-game sample size.

### Deliberate exclusions and limitations

- No full checkpoint/delta chain reconstruction yet; archive samples are not an exhaustive history.
- No proven independent game-start timestamp or physical game mapping. `event_ticker` must not be silently treated as physical-game ID; therefore, **no pregame strategy evaluation or predictive signal may be declared**.
- A market `result` field or derived settled record is not independent external validation of settlement rules. Ambiguity is unresolved.
- Quote snapshots alone are not proof that a trade could be executed at that price; no side-specific fee/depth, cancellation, halt or fill model yet.
- External source licensing and distribution rules require verification.
- No autonomous cron, paid services or betting. Everything is research-only.

### Next engineering steps

1. Verify source-specific JSON schemas and endpoint timing, obtain full checkpoint+delta+orderbook reconstructions with independent hashes.
2. Join actual sport schedule/physical-game IDs, lineups, role changes, injuries and time-varying game contexts **strictly available before each quote**.
3. Join contract result and market rules; validate against real scores and void semantics.
4. Produce stratified prospective market-calibration and movement research, separate market families and calculate bettable after-fee economics only where order-book depth and actual contemporaneous asks permit.
5. Let Alpha's autonomous director select and independently verify studies after this quality foundation passes.

No automated profitability claims are authorized by this pilot. Track in [Issue #4](https://github.com/chmoses98/sift-alpha/issues/4).

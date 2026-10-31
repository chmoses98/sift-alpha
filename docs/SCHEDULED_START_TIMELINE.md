# Point-in-time independent scheduled starts (NBA/NHL)

This audit builds a bounded, source-verified **schedule** timeline using the two immutable historical NBA and NHL schedule captures already pinned in `research/context_join_pins.json`. It does not infer game starts from market tickers, closing prices or final scores.

A row is admitted only if its official/ESPN game ID, two distinct official team IDs, timezone-aware scheduled start, and independent `_observed_at_utc` are valid. The row observation timestamp must fall within the archive filename's capture second. This matters because filename capture timestamps are second-granularity: a row observed at `23:15:57.500Z` is **not** known at `23:15:57.250Z`, even though its filename says `23:15:57Z`.

Duplicates within one snapshot are quarantined; conflicting home/away identities for one game across snapshots quarantine the entire game. Legitimate observed start-time revisions are counted without rewriting the earlier as-of view. Source paths, immutable commits and blob hashes are retained on output. Bad or unbounded gzip sources fail closed via the existing context-source reader.

Run after the verified quote tape has been emitted:

```sh
python3 -m unittest discover -s tests -p 'test_schedule_timeline.py' -v
python3 -m alpha_engine.schedule_timeline_cli
```

The output is `artifacts/scheduled_start_timeline_status.json` with per-sport counts at the **verified tape base and end**. **Scheduled start is not actual tip/puck drop**. This does not establish an exact Kalshi event/contract-to-game join, valid pregame quote, contract rule, official settlement, or executable profit. The eight-sport archive registry remains separate; this scoped step deepens NBA/NHL evidence without pretending the other six sports are complete.

Next: independently validate exact market event ticker-to-game identity and the *actual* start/cancellation/void semantics, then extend bounded full checkpoint+delta history before any calibration or execution research.

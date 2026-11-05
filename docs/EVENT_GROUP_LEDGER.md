# Point-in-time literal event grouping

This stage consumes the hash-verified NBA/NHL sparse market tape and contract lineage, then groups **active exact market tickers by the literal observed Kalshi `event_ticker`** at each of four independently verified checkpoint/delta board observation ticks. The output is a compressed JSONL event-group ledger and a JSON diagnostics report. It is not a physical-game join.

```sh
python3 -m unittest discover -s tests -p 'test_event_groups.py' -v
python3 -m alpha_engine.event_groups_cli
```

Each group contains the exact event and series identifier(s), constituent active contract tickers, observation time, and explicit quarantine status. Event identifiers with conflicting literal series, cross-sport collisions, or tickers with changing contract semantics are not silently normalized. A ticker removed from the observed board is not an active member at later observations. Event grouping uses only evidence available by the requested tick, never later changes.

**Boundaries:** An exchange event is not necessarily a sports game (it may be a season future, player award or other contract family). The source does not establish physical game IDs, actual tip/puck drop, official Kalshi resolution, a fillable price, or profitability. The sampled source chain is a short historical prefix, not a full day or season. This is a prerequisite to a conservative source-backed game ontology, not a model-ready labeled training set.

Outputs: `artifacts/literal_event_group_ledger.jsonl.gz`, `artifacts/literal_event_group_status.json`.

Other six sports (NFL, CFB, MLB, CBB, soccer, tennis) remain covered by the separately verified source inventory but lack equivalent end-to-end time-series replay.

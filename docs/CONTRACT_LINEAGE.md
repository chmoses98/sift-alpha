# Literal Kalshi contract identity over verified market observations

This qualification consumes the already verified NBA/NHL checkpoint and three contiguous deltas per sport. It compares exact ticker, observed event and series identifiers, strikes and YES/NO subtitle terms. Missing fields are unresolved; contradictions are quarantined only from the observation when they become known. Descriptive title changes are counted separately. Duplicate ticker observations and invalid price sides fail closed.

**Critical boundary:** a contract/event ticker is not an independently identified physical game; an observed schedule is not an actual start; a quote `result` field is not exchange-native settlement. The output counts unique literal contract tickers within a **small verified historical prefix**, not games, bets, opportunities or independent outcomes. Series counts are raw identifiers, not validated family classifications.

After `python3 -m alpha_engine.verified_tape_cli` run:

```sh
python3 -m unittest discover -s tests -p 'test_contract_lineage.py' -v
python3 -m alpha_engine.contract_lineage_cli
```

Output `artifacts/contract_lineage_qualification.json` is descriptive research evidence only. No full-day history, execution, pregame eligibility or ROI. NFL, CFB, MLB, CBB, soccer and tennis remain in the separate eight-sport source audit until verified source-specific time-series replay is implemented.

Next gate: independently documented Kalshi contract semantics, official game identifiers, actual start evidence and exchange-native settlement matching, with unresolved/ambiguous mappings quarantined.

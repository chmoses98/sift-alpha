# Tennis exchange-result capture — verified source, research-only

This module examines three **immutable, pinned** 2026-10-25 Tennis settlement captures from the existing public Tennis repo, alongside their collector manifests. The archived data contain Kalshi `status`, `result`, `settlement_value_dollars` and `settlement_ts` fields. Source bytes are verified against their Git blob SHA-1 and upstream counts. This is evidence of **archived exchange-result fields**, not independently authenticated exchange API responses.

Crucial observed semantic edge case: a pair of contracts has `result="scalar"` and `settlement_value_dollars="0.5000"`. It is incorrect to classify either as a YES win or a NO loss. Further, many recorded `occurrence_datetime` fields are **after** settlement timestamps. They cannot serve as independently verified actual match start times, even when the result fields are finalized.

```sh
python3 -m unittest discover -s tests -p 'test_tennis_settlement.py' -v
python3 -m alpha_engine.tennis_capture_cli
python3 -m alpha_engine.tennis_settlement_cli
```

The second CLI consumes the verified quote-capture artifact and performs **exact-ticker, timestamp-constrained overlap only**. A quote seen before settlement is *not necessarily pregame*; no execution, liquidity, fees, settlement-rule validation or profitability authority is conferred. This is a bounded 3-capture pilot, not a full day or season. Other sports continue to use the eight-sport metadata inventory and NBA/NHL historical tapes. No paid services or live orders.

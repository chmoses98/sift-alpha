# Canonical CLV measures (`sift_clv`, version `sift-clv-canonical/1`)

All prices are dollars per contract **on the purchased side** (NO uses `no_mid = 1 - yes_mid`, `no_ask = 1 - yes_bid`).

| Measure | Formula | Fees? | Spread? |
|---|---|---|---|
| Selection CLV | close_mid(side) − recommendation_mid(side) | no | no |
| Quoted execution CLV | close_mid(side) − recommendation_ask(side) | no | half-spread included |
| Actual execution CLV | close_mid(side) − quantity-weighted exchange fill VWAP (fee-**exclusive**) | no | real slippage included |
| Fee-adjusted difference | actual execution CLV − entry fees ÷ contracts | **once** | included |

## Rules
* A 50¢ fill that Kalshi displays as ~51.7¢ (fee-inclusive cost basis) with the market still at 50¢ is **0¢ CLV**; the 1.7¢ is entry fee drag, counted once in the fee-adjusted difference only. `stake ÷ contracts` is refused as a price (`FILL_PRICE_FEE_INCLUSIVE`).
* No closing/exit fee is ever charged to a position held to settlement.
* Net P&L = gross return − stake. `stake` already contains the entry fee; the settlement `fee_cost` is that same fee (settlement-economics v1 subtracted it twice; v2 amendments fix this).
* A close is a two-sided, uncrossed quote of the *same ticker* observed strictly before the start and no older than the age cap. Settled 0/1 values, last trades, one-sided books, and other-line tickers are never closes. Missing evidence is a status code, never zero.
* Selection CLV for a real wager needs a verified recommendation → order join. Current router ledgers carry none (`recommendation_generated_at`, order and fill ids are null), so it is reported as unverifiable, not inferred.
* Observations are clustered by physical game; many tickers/horizons of one game are not independent.

Reproduce: `python3 -m unittest tests.test_clv_canonical`; `scripts/recalc_nfl_real_wagers.py`; `scripts/recalc_nfl_shadow_clv.py`.
Aggregates of hypothetical model selections only are committed under `reports/clv_recalc/`; real-wager P&L is deliberately not committed.

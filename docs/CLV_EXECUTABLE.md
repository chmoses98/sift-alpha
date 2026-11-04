# Executable-purchase CLV (`sift-clv-executable/1`) and limit-order research (`sift-clv-limit/1`)

The midpoint measure (`sift-clv-canonical/1`) is a mark-to-market and is **kept unchanged**. This adds the question it cannot answer:
*did we pay less than someone buying the same contract at the close?*

| Code | Measure | Formula (held side, per contract) |
|---|---|---|
| A | selection CLV | close mid − recommendation/horizon mid |
| **B** | **executable purchase CLV** | **close ASK − our fee-exclusive fill VWAP** (>0 we paid less; 0 unchanged; <0 waiting was cheaper) |
| C | liquidation vs close BID | close BID − fill VWAP |
| D | midpoint execution CLV | close mid − fill VWAP (traditional, kept) |
| E | fee-adjusted | each of B/C/D − exchange entry fee/contract, **once**; sale fee only for a hypothetical liquidation, labelled modelled |
| F | size-adjusted | depth-walked ask VWAP for our quantity − fill VWAP; only with a same-ticker archived book observed before the start |

`B = D + s/2` and `C = D − s/2` (s = closing spread): a wider closing spread raises B and lowers C with fair value unchanged.
NO is derived from the YES book (`no_ask = 1 − yes_bid`, `no_bid = 1 − yes_ask`); a bid is never a purchase price.

## Limit orders are never assumed filled
`sift_clv.limit_orders`: a resting buy fills only when the trade tape shows an aggressor selling that side into it, reported as
a conservative bound (back of queue, no cancellation credit) and an optimistic bound (front of queue); `UNCERTAIN` where the tape
or queue depth is missing; every opportunity is evaluated, including unfilled ones. A displayed limit price is not evidence of execution.

## Reproduce
`scripts/recalc_executable.py` (real wagers: NFL/CFB/NBA/NHL) · `scripts/recalc_nfl_shadow_exec.py` (hypothetical early taker) ·
`research/limitsim_nfl/` (tape simulation, one week) · `scripts/build_exec_public_summary.py` → `reports/clv_recalc/execution_summary_*.json`
(aggregates only; `tests/test_clv_execution_summary.py` enforces privacy and the identities above).

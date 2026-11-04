# Recommendation → order → fills → close linkage (`sift_clv.linkage`, `sift-clv-linkage/1`)

The router is an **independent accounting source** and never learns about recommendations
(`routed_ledger.PROVENANCE_FIELDS` forbids it). Linkage is a separate join over two ledgers, made on the edge-finder
side, and it reuses the router's existing identifiers and join rule (kalshi-bet-router `execution_evidence` and
`contract/standalone/execution_evidence_ledger.py`, `link_recommendation`).

## Identifiers are digests, never raw ids
Both repositories are public and the router treats order, fill and recommendation ids as private. Every identifier that
crosses a ledger is `sha256("kalshi-router.execution-evidence.v1|<kind>|<id>")[:32]` (`id_digest`). A recommendation is
`recommendation_ref(rec_id)`; an order is the router's `source_bet_key` (itself a digest). The four golden vectors in
`tests/test_clv_linkage.py` are the same ones the router and every destination assert, so a drifted formula fails CI.

## Evidence tiers
| Tier | Evidence | Verified? |
|---|---|---|
| `EXACT_CLIENT_ORDER_ID` | exchange `client_order_id == "sift:<recommendation_ref>"` | yes |
| `OWNER_ATTESTED` | append-only attestation naming `recommendation_ref` and the router `source_bet_key` | yes |
| `UNIQUE_WINDOW_MATCH` | the router's rule: exact ticker + side, recommendation created before the first fill and within an **explicit** window (no default), exactly one distinct recommendation | **no** — sensitivity view only |
| ambiguous | two or more distinct recommendations in the window | never resolved by "nearest" |

Every verified link also requires: identical ticker (threshold included) and side; recommendation strictly before the
first fill; first fill strictly before the scheduled start; the order claimed by at most one recommendation. Failures are
quarantined with a reason code, never repaired. `measure(..., include_unique_window=True)` returns a window match's numbers
tagged `evidence_grade="UNIQUE_WINDOW"` and `verified=false`; it is off by default and never enters verified CLV.

## Forward capture (what must be emitted so future bets can be matched)
1. **Recommendation record** (immutable, in the sport repo's own private store): `rec_id`, `created_at`, exact `ticker`,
   `side`, original `yes_bid`/`yes_ask`, recommended price, `model_version`, projection, confidence. Publish only
   `recommendation_ref` and `model_run_ref` digests.
2. **Order tag**: when an order is placed from a recommendation surface, set `client_order_id` to
   `client_order_token(rec_id)` = `sift:<recommendation_ref>`.
3. **Attestation fallback** for manual orders: `{recommendation_ref, order_key, attested_at, attested_by}`, append-only.
4. **Close**: archived two-sided pregame quote of the same ticker, strictly before start, age-capped.

**Blocked, needs live verification:** the router currently refuses raw `client_order_id` and does not ingest it. Whether the
Kalshi fills payload exposes `client_order_id` (or only the orders endpoint does) cannot be checked from this environment
(Kalshi host unreachable). Until that is confirmed, tier 1 cannot be populated; tier 2 and the window view work today.
The router's execution-evidence emission remains default-off and its delivery contract change is the owner's decision.

## Privacy
Public outputs use `public_row()`: one-way link id, tier, evidence grade, flags and measure values. No ticker, price, amount,
raw id, order id or recommendation id.

## Historical recovery status (2026-11-04)
No ledger contains an explicit link. NFL `handicap-data` holds a single synthetic end-to-end recommendation and no client
order ids, so verified historical links = **0**. Window matches were not minted: the sport repos' decision records for
the real wagers are not in a shared store, so there is nothing to join and nothing was inferred.

# Recommendation → order → fills → close linkage (`sift_clv.linkage`, `sift-clv-linkage/1`)

The router is an **independent accounting source** and never learns about recommendations. Linkage is a separate
join over two ledgers, and a join is *verified* only on explicit evidence.

| Tier | Evidence | Counts as verified? |
|---|---|---|
| `EXACT_CLIENT_ORDER_ID` | exchange order's `client_order_id == "sift:<rec_id>"` | yes |
| `OWNER_ATTESTED` | append-only attestation naming both `rec_id` and the router `source_bet_key` | yes |
| `CANDIDATE_ONLY` | same ticker + side, a single rec and a single order in the window | **never** (count only) |

Every verified link also requires: identical ticker (threshold included) and side; recommendation created strictly
before the first fill; first fill strictly before the scheduled start; the order claimed by at most one recommendation.
Failures are quarantined with a reason code, never repaired.

## Forward capture (what must be emitted so future bets can be matched)
1. **Recommendation record** (immutable, in the sport repo's own store): `rec_id`, `created_at`, exact `ticker`, `side`,
   original `yes_bid`/`yes_ask`, recommended price, `model_version`, projection, confidence.
2. **Order tag**: when an order is placed from a recommendation surface, set the exchange `client_order_id` to
   `client_order_token(rec_id)`. The router's read-only fill ingestion already carries order identity; surfacing
   `client_order_id` on the router's wager row is the one router change needed (additive, defaults null).
3. **Attestation fallback** for manually placed orders: an append-only record `{rec_id, order_key, attested_at,
   attested_by}` written by the owner. Order key is the router's one-way `source_bet_key`.
4. **Close**: resolved from archived two-sided pregame quotes (same ticker), strictly before start, age-capped.

## Privacy
Public outputs use `public_row()`: one-way link id, tier, flags and measure values. No ticker, price, amount, order
id or recommendation id. Raw joins run only in a private/ephemeral environment.

## Historical recovery status (2026-11-04)
No ledger contains an explicit link. NFL `handicap-data` holds a single synthetic end-to-end recommendation and no
client order ids on any of 253 wagers, so verified historical links = **0**; time/ticker coincidence is not accepted.

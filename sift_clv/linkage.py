"""Recommendation -> order -> fills -> close linkage with explicit evidence tiers (``sift-clv-linkage/1``).

The router stays the independent accounting source: it never learns about recommendations.  This module joins the
two ledgers on EVIDENCE, and a join is only ``verified`` when the evidence is explicit:

  EXACT_CLIENT_ORDER_ID   the exchange order's client_order_id carries the recommendation token ``sift:<rec_id>``
  OWNER_ATTESTED          an append-only attestation names BOTH the recommendation id and the order key
  CANDIDATE_ONLY          same ticker + side, one rec, one order in the window.  NEVER verified, never counted in
                          verified CLV; reported only as a count so the gap is visible.

Every verified tier additionally requires: same exact ticker (threshold included) and side; recommendation created
strictly before the first fill; first fill strictly before the scheduled start; an order claimed by at most one
recommendation.  Violations are quarantined with a reason, never repaired.

Public-safe projection (``public_row``) carries a salted-free one-way link id, tier, flags and measure values only:
no ticker, amount, price, order id or recommendation id.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from . import canonical as C

VERSION = "sift-clv-linkage/1"
EXACT = "EXACT_CLIENT_ORDER_ID"
ATTESTED = "OWNER_ATTESTED"
CANDIDATE = "CANDIDATE_ONLY"
VERIFIED_TIERS = (EXACT, ATTESTED)
TOKEN_PREFIX = "sift:"

# quarantine reasons
TICKER_SIDE_MISMATCH = "TICKER_OR_SIDE_MISMATCH"
REC_NOT_BEFORE_FILL = "RECOMMENDATION_NOT_BEFORE_FIRST_FILL"
FILL_NOT_PREGAME = "FIRST_FILL_NOT_BEFORE_START"
NO_START = "NO_SCHEDULED_START"
ORDER_CLAIMED_TWICE = "ORDER_CLAIMED_BY_MULTIPLE_RECOMMENDATIONS"
UNKNOWN_REC = "ATTESTATION_NAMES_UNKNOWN_RECOMMENDATION"
UNKNOWN_ORDER = "ATTESTATION_NAMES_UNKNOWN_ORDER"
AMBIGUOUS_CANDIDATE = "CANDIDATE_AMBIGUOUS"


@dataclass(frozen=True)
class Recommendation:
    rec_id: str
    created_at: datetime
    ticker: str
    side: str
    yes_bid: Optional[Decimal]          # original market bid/ask at recommendation time (YES axis)
    yes_ask: Optional[Decimal]
    recommended_price: Optional[Decimal] = None
    model_version: Optional[str] = None
    projection: Optional[Decimal] = None
    confidence: Optional[Decimal] = None


@dataclass(frozen=True)
class Order:
    order_key: str                       # router source_bet_key (already a one-way hash of the exchange order)
    ticker: str
    side: str
    first_fill_at: datetime
    fills: tuple                         # tuple[C.Fill] fee-exclusive
    stake: Optional[Decimal] = None
    client_order_id: Optional[str] = None


@dataclass(frozen=True)
class Attestation:
    rec_id: str
    order_key: str
    attested_at: datetime
    attested_by: str = "owner"


@dataclass(frozen=True)
class Link:
    rec_id: str
    order_key: str
    tier: str
    verified: bool
    quarantine: Optional[str] = None

    @property
    def link_id(self) -> str:
        return hashlib.sha256(f"{self.rec_id}|{self.order_key}".encode()).hexdigest()[:16]


def client_order_token(rec_id: str) -> str:
    """The value forward capture must place in the exchange order's client_order_id."""
    return f"{TOKEN_PREFIX}{rec_id}"


def _same_contract(r: Recommendation, o: Order) -> bool:
    return r.ticker == o.ticker and C.norm_side(r.side) == C.norm_side(o.side) and C.norm_side(r.side) is not None


def _check(r: Recommendation, o: Order, start: Optional[datetime]) -> Optional[str]:
    if not _same_contract(r, o):
        return TICKER_SIDE_MISMATCH
    if not r.created_at < o.first_fill_at:
        return REC_NOT_BEFORE_FILL
    if start is None:
        return NO_START
    if not o.first_fill_at < start:
        return FILL_NOT_PREGAME
    return None


def link_all(recs: Iterable[Recommendation], orders: Iterable[Order], attestations: Iterable[Attestation],
             starts: dict) -> list:
    """``starts``: {ticker: scheduled start}.  Returns Link rows (verified and quarantined)."""
    recs, orders = {r.rec_id: r for r in recs}, {o.order_key: o for o in orders}
    claims = defaultdict(set)                       # order_key -> {(rec_id, tier)}
    for o in orders.values():
        cid = o.client_order_id or ""
        if cid.startswith(TOKEN_PREFIX) and cid[len(TOKEN_PREFIX):] in recs:
            claims[o.order_key].add((cid[len(TOKEN_PREFIX):], EXACT))
    out = []
    for a in attestations:
        if a.rec_id not in recs:
            out.append(Link(a.rec_id, a.order_key, ATTESTED, False, UNKNOWN_REC)); continue
        if a.order_key not in orders:
            out.append(Link(a.rec_id, a.order_key, ATTESTED, False, UNKNOWN_ORDER)); continue
        if not a.attested_at:
            continue
        claims[a.order_key].add((a.rec_id, ATTESTED))
    for okey, cl in claims.items():
        rec_ids = {rid for rid, _ in cl}
        o = orders[okey]
        for rid, tier in sorted(cl):
            if len(rec_ids) > 1:
                out.append(Link(rid, okey, tier, False, ORDER_CLAIMED_TWICE)); continue
            why = _check(recs[rid], o, starts.get(o.ticker))
            out.append(Link(rid, okey, tier, why is None, why))
    # heuristic candidates: only for orders with no explicit claim; unique 1:1 on ticker+side, never verified
    claimed = {l.order_key for l in out}
    by_contract_recs = defaultdict(list)
    for r in recs.values():
        by_contract_recs[(r.ticker, C.norm_side(r.side))].append(r)
    by_contract_orders = defaultdict(list)
    for o in orders.values():
        if o.order_key not in claimed:
            by_contract_orders[(o.ticker, C.norm_side(o.side))].append(o)
    for key, os_ in by_contract_orders.items():
        rs = by_contract_recs.get(key, [])
        if not rs:
            continue
        if len(rs) == 1 and len(os_) == 1 and _check(rs[0], os_[0], starts.get(os_[0].ticker)) is None:
            out.append(Link(rs[0].rec_id, os_[0].order_key, CANDIDATE, False, None))
        else:
            for o in os_:
                out.append(Link(rs[0].rec_id, o.order_key, CANDIDATE, False, AMBIGUOUS_CANDIDATE))
    return out


def measure(link: Link, rec: Recommendation, order: Order, close: Optional[C.Quote], start: Optional[datetime],
            max_close_age_seconds: Optional[int] = 3600) -> dict:
    """Canonical CLV for one link.  Unverified links return no actual-execution numbers at all."""
    if not link.verified:
        return {"link_id": link.link_id, "tier": link.tier, "verified": False, "quarantine": link.quarantine}
    res = C.evaluate(ticker=order.ticker, side=order.side,
                     recommendation=C.Quote(rec.ticker, rec.yes_bid, rec.yes_ask, rec.created_at), close=close,
                     start=start, fills=list(order.fills), stake=order.stake,
                     max_close_age_seconds=max_close_age_seconds)
    return {"link_id": link.link_id, "tier": link.tier, "verified": True, "quarantine": None, "clv": res}


def public_row(m: dict) -> dict:
    """Privacy-safe aggregate row: no ticker, price, amount, order id or recommendation id."""
    out = {"link_id": m["link_id"], "tier": m["tier"], "verified": m["verified"], "quarantine": m.get("quarantine")}
    r = m.get("clv")
    if r is not None:
        out.update(status=r.status, selection_clv=_f(r.selection_clv), quoted_execution_clv=_f(r.quoted_execution_clv),
                   actual_execution_clv=_f(r.actual_execution_clv),
                   fee_adjusted_difference=_f(r.fee_adjusted_difference),
                   fee_adjustment_count=r.fee_adjustment_count)
    return out


def _f(x):
    return None if x is None else float(x)


def coverage(links: Iterable[Link], n_recs: int, n_orders: int) -> dict:
    links = list(links)
    tiers = defaultdict(int)
    for l in links:
        tiers[(l.tier, "verified" if l.verified else "unverified")] += 1
    return {"version": VERSION, "recommendations": n_recs, "orders": n_orders,
            "verified_links": sum(1 for l in links if l.verified),
            "by_tier": {f"{t}:{v}": n for (t, v), n in sorted(tiers.items())},
            "quarantine": dict(sorted(_count(l.quarantine for l in links if l.quarantine).items()))}


def _count(xs):
    d = defaultdict(int)
    for x in xs:
        d[x] += 1
    return d

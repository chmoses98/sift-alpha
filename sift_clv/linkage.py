"""Recommendation -> order -> fills -> close linkage with explicit evidence tiers (``sift-clv-linkage/1``).

The router stays the independent accounting source: it never learns about recommendations.  This module joins the
two ledgers on EVIDENCE, and a join is only ``verified`` when the evidence is explicit:

  EXACT_CLIENT_ORDER_ID   the exchange order's client_order_id is ``sift:<recommendation_ref>``
  OWNER_ATTESTED          an append-only attestation names BOTH the recommendation_ref and the order key
  UNIQUE_WINDOW_MATCH     the router's own ``link_recommendation`` rule: exact ticker + side, recommendation created before
                          the first fill and within an EXPLICIT window (no default), exactly one distinct recommendation.
                          Two or more -> AMBIGUOUS, never "pick the nearest". NOT verified: ticker/time coincidence is
                          not attribution. Counted separately and only usable as a labelled sensitivity view.
  CANDIDATE_ONLY          (kept for compatibility) alias of UNIQUE_WINDOW_MATCH grade; see ``UNIQUE_WINDOW``.

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
UNIQUE_WINDOW = "UNIQUE_WINDOW_MATCH"
CANDIDATE = UNIQUE_WINDOW          # backwards-compatible name
VERIFIED_TIERS = (EXACT, ATTESTED)
TOKEN_PREFIX = "sift:"
DIGEST_DOMAIN = "kalshi-router.execution-evidence.v1"
DIGEST_HEX_CHARS = 32


def id_digest(kind: str, value: str) -> str:
    """The router's domain-separated digest (copy of the formula, as the router's contract instructs)."""
    if kind not in ("order", "fill", "recommendation", "model_run"):
        raise ValueError(f"unknown id kind {kind!r}")
    return hashlib.sha256(f"{DIGEST_DOMAIN}|{kind}|{value}".encode()).hexdigest()[:DIGEST_HEX_CHARS]


def recommendation_ref(rec_id: str) -> str:
    return id_digest("recommendation", rec_id)

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

    @property
    def ref(self) -> str:
        return recommendation_ref(self.rec_id)


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
    recommendation_ref: str              # digest, never the raw recommendation id
    order_key: str
    attested_at: datetime
    attested_by: str = "owner"


@dataclass(frozen=True)
class Link:
    rec_ref: str                         # recommendation_ref digest (never the raw id)
    order_key: str
    tier: str
    verified: bool
    quarantine: Optional[str] = None

    @property
    def link_id(self) -> str:
        return hashlib.sha256(f"{self.rec_ref}|{self.order_key}".encode()).hexdigest()[:16]

    @property
    def grade(self) -> str:
        """EXPLICIT (client_order_id / attestation), UNIQUE_WINDOW (router rule; not verified), or UNLINKED."""
        if self.tier in VERIFIED_TIERS:
            return "EXPLICIT"
        return "UNIQUE_WINDOW" if self.tier == UNIQUE_WINDOW and self.quarantine is None else "UNLINKED"


def client_order_token(rec_id: str) -> str:
    """The value forward capture must place in the exchange order's client_order_id: ``sift:<recommendation_ref>``."""
    return f"{TOKEN_PREFIX}{recommendation_ref(rec_id)}"


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
             starts: dict, *, window_seconds: Optional[float] = None) -> list:
    """``starts``: {ticker: scheduled start}.  Returns Link rows (verified and quarantined), keyed by digests.

    ``window_seconds`` enables the router's unique-window rule for orders with NO explicit claim; there is no default
    window (a default would hide a guess). Without it only explicit evidence produces links."""
    if window_seconds is not None and window_seconds <= 0:
        raise ValueError("window_seconds must be positive: there is no default window to hide a guess in")
    by_ref = {r.ref: r for r in recs}
    orders = {o.order_key: o for o in orders}
    claims = defaultdict(set)                       # order_key -> {(rec_ref, tier)}
    for o in orders.values():
        cid = o.client_order_id or ""
        if cid.startswith(TOKEN_PREFIX) and cid[len(TOKEN_PREFIX):] in by_ref:
            claims[o.order_key].add((cid[len(TOKEN_PREFIX):], EXACT))
    out = []
    for a in attestations:
        if a.recommendation_ref not in by_ref:
            out.append(Link(a.recommendation_ref, a.order_key, ATTESTED, False, UNKNOWN_REC)); continue
        if a.order_key not in orders:
            out.append(Link(a.recommendation_ref, a.order_key, ATTESTED, False, UNKNOWN_ORDER)); continue
        if not a.attested_at:
            continue
        claims[a.order_key].add((a.recommendation_ref, ATTESTED))
    for okey, cl in claims.items():
        refs = {rf for rf, _ in cl}
        o = orders[okey]
        for rf, tier in sorted(cl):
            if len(refs) > 1:
                out.append(Link(rf, okey, tier, False, ORDER_CLAIMED_TWICE)); continue
            why = _check(by_ref[rf], o, starts.get(o.ticker))
            out.append(Link(rf, okey, tier, why is None, why))
    if window_seconds is not None:
        claimed = {l.order_key for l in out}
        for o in orders.values():
            if o.order_key in claimed:
                continue
            hits = [r for r in by_ref.values() if _same_contract(r, o) and
                    0 <= (o.first_fill_at - r.created_at).total_seconds() <= window_seconds]
            refs = sorted({r.ref for r in hits})
            if not refs:
                continue
            if len(refs) > 1:
                out.append(Link(refs[0], o.order_key, UNIQUE_WINDOW, False, AMBIGUOUS_CANDIDATE))   # never pick the nearest
                continue
            why = _check(by_ref[refs[0]], o, starts.get(o.ticker))
            out.append(Link(refs[0], o.order_key, UNIQUE_WINDOW, False, why))
    return out


def measure(link: Link, rec: Recommendation, order: Order, close: Optional[C.Quote], start: Optional[datetime],
            max_close_age_seconds: Optional[int] = 3600, *, include_unique_window: bool = False) -> dict:
    """Canonical CLV for one link.  Unverified links return no actual-execution numbers at all, unless the caller asks
    for the labelled sensitivity view (``include_unique_window``): a unique, un-quarantined window match is then measured
    and tagged ``evidence_grade="UNIQUE_WINDOW"`` so it can never be mistaken for verified."""
    sens = include_unique_window and link.grade == "UNIQUE_WINDOW"
    if not link.verified and not sens:
        return {"link_id": link.link_id, "tier": link.tier, "verified": False, "quarantine": link.quarantine}
    res = C.evaluate(ticker=order.ticker, side=order.side,
                     recommendation=C.Quote(rec.ticker, rec.yes_bid, rec.yes_ask, rec.created_at), close=close,
                     start=start, fills=list(order.fills), stake=order.stake,
                     max_close_age_seconds=max_close_age_seconds)
    return {"link_id": link.link_id, "tier": link.tier, "verified": link.verified, "quarantine": None,
            "evidence_grade": link.grade, "clv": res}


def public_row(m: dict) -> dict:
    """Privacy-safe aggregate row: no ticker, price, amount, order id or recommendation id."""
    out = {"link_id": m["link_id"], "tier": m["tier"], "verified": m["verified"], "quarantine": m.get("quarantine"),
           "evidence_grade": m.get("evidence_grade", "UNLINKED")}
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
            "unique_window_unverified": sum(1 for l in links if l.grade == "UNIQUE_WINDOW"),
            "by_tier": {f"{t}:{v}": n for (t, v), n in sorted(tiers.items())},
            "quarantine": dict(sorted(_count(l.quarantine for l in links if l.quarantine).items()))}


def _count(xs):
    d = defaultdict(int)
    for x in xs:
        d[x] += 1
    return d

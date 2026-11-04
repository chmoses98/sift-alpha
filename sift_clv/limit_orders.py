"""Limit-order fill research model (version ``sift-clv-limit/1``). RESEARCH ONLY: nothing here places or routes an order.

A resting bid is NOT an executed trade. A hypothetical resting BUY of a side at limit price ``p`` is credited with a fill
only when the historical TRADE TAPE shows an aggressor selling that side into it, and the result is always reported as a
pair of bounds, never one point:

  LOWER bound (conservative)  we join the BACK of the queue. ``queue_ahead`` = size resting at ``p`` when we placed (0 if
                              ``p`` is inside the spread, i.e. we create a new best level). No credit for cancellations
                              ahead of us. Trades at exactly ``p`` first consume the queue; only the excess fills us.
                              A trade strictly THROUGH ``p`` exhausts the level, so we are filled in full.
  UPPER bound (optimistic)    we are FIRST in the queue: any qualifying trade at <= ``p`` fills us.

Qualifying trade for a BUY of ``side`` at ``p``: the aggressor SELLS that side (a YES buy is hit by taker_side == "no",
a NO buy by taker_side == "yes") at a side-price <= ``p``. Side-price is the trade's yes_price for YES, no_price for NO.
Our fill price is OUR limit price (a maker fill never fills better than the limit) -- price improvement versus the close
comes only from where we posted. If the tape does not cover the whole window the outcome is UNCERTAIN for that bound: an
unobserved interval is neither a fill nor proof of a miss. A displayed limit price in a snapshot is never evidence of
execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from . import canonical as C

VERSION = "sift-clv-limit/1"
ZERO, ONE = Decimal(0), Decimal(1)
TICK = Decimal("0.01")

FILLED, PARTIAL, UNFILLED, UNCERTAIN = "FILLED", "PARTIAL", "UNFILLED", "UNCERTAIN"
RULES = ("AT_BID", "BID_PLUS_1TICK", "INSIDE_MID", "AT_ASK")


@dataclass(frozen=True)
class Trade:
    ts: datetime
    yes_price: Decimal
    size: Decimal
    taker_side: str                # "yes" | "no"
    trade_id: Optional[str] = None

    @staticmethod
    def of(ts, yes_price, size, taker_side, trade_id=None) -> "Trade":
        return Trade(ts, C.D(yes_price), C.D(size), str(taker_side).lower(), trade_id)

    def side_price(self, side: str) -> Decimal:
        return self.yes_price if side == "YES" else ONE - self.yes_price


def qualifies(t: Trade, side: str, limit: Decimal) -> str:
    """'through' (strictly better than our bid), 'at' (exactly our price) or '' (does not touch us)."""
    aggressor_sells_our_side = (t.taker_side == "no") if side == "YES" else (t.taker_side == "yes")
    if not aggressor_sells_our_side:
        return ""
    p = t.side_price(side)
    return "through" if p < limit else ("at" if p == limit else "")


def limit_price(rule: str, *, best_bid: Optional[Decimal], best_ask: Optional[Decimal]) -> Optional[Decimal]:
    """Where a rule would post (side prices). None when the book cannot support the rule."""
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}")
    if best_bid is None or best_ask is None or best_ask < best_bid:
        return None
    if rule == "AT_ASK":
        return best_ask
    if rule == "AT_BID":
        return best_bid
    if rule == "BID_PLUS_1TICK":
        p = best_bid + TICK
        return p if p < best_ask else best_bid            # never cross the spread by accident
    mid = (best_bid + best_ask) / 2
    p = (mid * 100).to_integral_value(rounding="ROUND_FLOOR") / 100
    return p if best_bid < p < best_ask else best_bid


@dataclass(frozen=True)
class BoundOutcome:
    status: str
    filled: Decimal
    requested: Decimal

    @property
    def fraction(self) -> Decimal:
        return self.filled / self.requested if self.requested > 0 else ZERO


@dataclass(frozen=True)
class LimitOutcome:
    rule: str
    limit: Optional[Decimal]
    lower: BoundOutcome
    upper: BoundOutcome
    queue_ahead: Optional[Decimal]
    maker_fee_per_contract: Optional[Decimal]
    notes: tuple = ()


def simulate_limit_buy(*, side, limit: Decimal, qty, placed_at: datetime, expires_at: datetime,
                       trades: Sequence[Trade], tape_complete: bool, queue_ahead: Optional[Decimal],
                       rule: str = "AT_BID") -> LimitOutcome:
    """Simulate one resting BUY. ``queue_ahead`` None = depth unknown (lower bound becomes UNCERTAIN)."""
    s = C.norm_side(side)
    if s is None:
        raise ValueError("side must be YES or NO")
    qty, limit = C.D(qty), C.D(limit)
    seen, lo_filled, up_filled = set(), ZERO, ZERO
    remaining_queue = queue_ahead if queue_ahead is not None else ZERO
    for t in sorted(trades, key=lambda x: x.ts):
        if not (placed_at < t.ts < expires_at):
            continue
        if t.trade_id is not None:                              # the tape repeats rows across runs: count once
            if t.trade_id in seen:
                continue
            seen.add(t.trade_id)
        kind = qualifies(t, s, limit)
        if not kind:
            continue
        if kind == "through":
            lo_filled = up_filled = qty                         # the level was exhausted ahead of this print: full fill
        else:
            up_filled = min(qty, up_filled + t.size)
            if remaining_queue >= t.size:
                remaining_queue -= t.size
            else:
                excess = t.size - remaining_queue
                remaining_queue = ZERO
                lo_filled = min(qty, lo_filled + excess)
    def bound(filled, known_depth=True):
        if filled >= qty:
            return BoundOutcome(FILLED, qty, qty)
        if filled > 0:
            return BoundOutcome(PARTIAL, filled, qty)
        return BoundOutcome(UNFILLED if (tape_complete and known_depth) else UNCERTAIN, ZERO, qty)
    up_filled = max(up_filled, lo_filled)                       # invariant: the optimistic bound is never below the conservative
    lower = bound(lo_filled, known_depth=queue_ahead is not None)
    if queue_ahead is None and lower.status == FILLED:
        lower = BoundOutcome(UNCERTAIN, lo_filled, qty)         # a "fill" counted with an unknown queue is not evidence
    upper = bound(up_filled)
    if not tape_complete and upper.status == UNFILLED:
        upper = BoundOutcome(UNCERTAIN, ZERO, qty)
    fee = C.estimate_fee(limit, qty, role="maker") / qty if qty > 0 else None
    return LimitOutcome(rule, limit, lower, upper, queue_ahead, fee,
                        () if tape_complete else ("TAPE_INCOMPLETE",))


def taker_at_ask(*, ask: Optional[Decimal], qty, displayed_ask_size: Optional[Decimal]) -> BoundOutcome:
    """AT_ASK crosses immediately; it fills only up to the displayed size (None size = unknown = UNCERTAIN)."""
    qty = C.D(qty)
    if ask is None:
        return BoundOutcome(UNCERTAIN, ZERO, qty)
    if displayed_ask_size is None:
        return BoundOutcome(UNCERTAIN, ZERO, qty)
    got = min(qty, displayed_ask_size)
    return BoundOutcome(FILLED if got >= qty else (PARTIAL if got > 0 else UNFILLED), got, qty)

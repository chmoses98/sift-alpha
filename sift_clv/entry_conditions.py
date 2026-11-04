"""Entry-market conditions for a real fill (``sift-clv-entry/1``).  RESEARCH ONLY.

What the market looked like when we bought: best bid/ask, spread, displayed depth, and what the fill paid relative to it.

MISSING-DATA POLICY (the point of this module)
  * An entry quote exists only if a snapshot of the SAME contract was OBSERVED AT OR BEFORE the first fill and is no older
    than ``max_age_seconds``.  A snapshot observed after the first fill is future information and is refused, never used.
  * Nothing is reconstructed, interpolated, or borrowed from the close.  No snapshot => ``NO_SNAPSHOT``; the measure stays
    unavailable and is counted as unavailable, never imputed.
  * Depth is walked only from an archived book of the same contract that satisfies the same rule.

All prices are dollars per contract on the PURCHASED side (NO derived from the YES book, as in ``executable``).
Public output (``public_row`` / ``coverage``) carries statuses, counts and cent-level means only: no ticker, order id,
price level, quantity or timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from . import canonical as C
from . import executable as X

VERSION = "sift-clv-entry/1"
ZERO = Decimal(0)

ENTRY_OK = "ENTRY_QUOTE_OK"
NO_SNAPSHOT = "NO_SNAPSHOT"
SNAPSHOT_AFTER_FILL = "SNAPSHOT_AFTER_FIRST_FILL"      # future information: refused
SNAPSHOT_STALE = "SNAPSHOT_STALE"
TICKER_MISMATCH = "SNAPSHOT_TICKER_MISMATCH"
ONE_SIDED = "SNAPSHOT_ONE_SIDED_OR_CROSSED"
NO_FILLS = "NO_FILLS"
STATUSES = (ENTRY_OK, NO_SNAPSHOT, SNAPSHOT_AFTER_FILL, SNAPSHOT_STALE, TICKER_MISMATCH, ONE_SIDED, NO_FILLS)


@dataclass(frozen=True)
class Snapshot:
    """One observation of a contract: two-sided top of book and, when archived, the resting-bid ladders."""
    ticker: str
    observed_at: datetime
    yes_bid: Optional[Decimal]
    yes_ask: Optional[Decimal]
    book: Optional[X.Book] = None

    @staticmethod
    def of(ticker, observed_at, yes_bid, yes_ask, book=None) -> "Snapshot":
        return Snapshot(ticker, observed_at, C.D(yes_bid), C.D(yes_ask), book)


def select_snapshot(snaps: Iterable[Snapshot], *, ticker: str, first_fill_at: datetime) -> tuple[Optional[Snapshot], str]:
    """Latest snapshot of ``ticker`` observed at or before the first fill.  Returns (snapshot, reason-if-none)."""
    best, saw_other, saw_after = None, False, False
    for s in snaps:
        if s.ticker != ticker:
            saw_other = True
            continue
        if s.observed_at > first_fill_at:
            saw_after = True
            continue
        if best is None or s.observed_at > best.observed_at:
            best = s
    if best is not None:
        return best, ""
    if saw_after:
        return None, SNAPSHOT_AFTER_FILL
    return None, TICKER_MISMATCH if saw_other else NO_SNAPSHOT


@dataclass(frozen=True)
class EntryResult:
    version: str
    side: Optional[str]
    status: str
    snapshot_age_seconds: Optional[int] = None
    entry_bid: Optional[Decimal] = None
    entry_ask: Optional[Decimal] = None
    entry_spread: Optional[Decimal] = None
    actual_vwap: Optional[Decimal] = None
    contracts: Optional[Decimal] = None
    paid_vs_entry_ask: Optional[Decimal] = None          # vwap - ask: >0 paid above the displayed best ask (walked the book / moved)
    paid_vs_entry_mid: Optional[Decimal] = None          # vwap - mid: the entry cost beyond mid (half-spread + slippage)
    entry_fee_per_contract: Optional[Decimal] = None
    taker_share: Optional[Decimal] = None
    maker_share: Optional[Decimal] = None
    depth_status: str = X.DEPTH_NOT_AVAILABLE
    depth_walk_ask_vwap: Optional[Decimal] = None
    depth_walk_premium_over_best_ask: Optional[Decimal] = None
    notes: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        out = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}
        out["notes"] = list(self.notes)
        return out


def evaluate_entry(*, ticker: str, side, first_fill_at: Optional[datetime], fills: Sequence[C.Fill],
                   snapshots: Iterable[Snapshot], max_age_seconds: int = 900) -> EntryResult:
    s = C.norm_side(side)
    if s is None:
        return EntryResult(VERSION, None, C.SIDE_INVALID)
    if not fills or first_fill_at is None:
        return EntryResult(VERSION, s, NO_FILLS)
    snap, why = select_snapshot(snapshots, ticker=ticker, first_fill_at=first_fill_at)
    if snap is None:
        return EntryResult(VERSION, s, why)
    age = int((first_fill_at - snap.observed_at).total_seconds())
    if max_age_seconds is not None and age > max_age_seconds:
        return EntryResult(VERSION, s, SNAPSHOT_STALE, snapshot_age_seconds=age)
    q = C.Quote.of(ticker, snap.yes_bid, snap.yes_ask, snap.observed_at)
    bid, ask, mid = X.side_bid(q, s), X.side_ask(q, s), q.mid(s)
    if bid is None or ask is None or mid is None or ask < bid:
        return EntryResult(VERSION, s, ONE_SIDED, snapshot_age_seconds=age)
    vw = C.vwap(fills)
    n = sum((f.count for f in fills), ZERO)
    fees = C.total_fee(fills)
    known = [f for f in fills if f.is_taker is not None]
    full_known = len(known) == len(fills)
    taker = (sum((f.count for f in fills if f.is_taker), ZERO) / n) if full_known and n else None
    dstat, dvw, prem = X.DEPTH_NOT_AVAILABLE, None, None
    if snap.book is not None and vw is not None:
        if snap.book.ticker != ticker:
            dstat = X.DEPTH_TICKER_MISMATCH
        else:
            walk = X.walk_asks(snap.book, s, n)
            dstat = walk.status
            if walk.status == X.DEPTH_FULL:
                dvw, prem = walk.vwap, walk.vwap - ask
    return EntryResult(
        VERSION, s, ENTRY_OK, snapshot_age_seconds=age, entry_bid=bid, entry_ask=ask, entry_spread=ask - bid,
        actual_vwap=vw, contracts=n, paid_vs_entry_ask=None if vw is None else vw - ask,
        paid_vs_entry_mid=None if vw is None else vw - mid,
        entry_fee_per_contract=None if fees is None or not n else fees / n,
        taker_share=taker, maker_share=None if taker is None else Decimal(1) - taker,
        depth_status=dstat, depth_walk_ask_vwap=dvw, depth_walk_premium_over_best_ask=prem)


def coverage(results: Iterable[EntryResult]) -> dict:
    """Privacy-safe aggregate: status counts, shares, cent-level means.  Unavailable stays unavailable (not imputed)."""
    rs = list(results)
    n = len(rs)
    by = {k: 0 for k in STATUSES}
    for r in rs:
        by[r.status] = by.get(r.status, 0) + 1
    ok = [r for r in rs if r.status == ENTRY_OK]
    cents = lambda xs: None if not xs else round(float(sum(xs) / len(xs)) * 100, 4)          # noqa: E731
    depth = {}
    for r in ok:
        depth[r.depth_status] = depth.get(r.depth_status, 0) + 1
    known_taker = [r.taker_share for r in rs if r.taker_share is not None]
    return {
        "version": VERSION, "fills": n, "status_counts": by,
        "entry_quote_coverage": None if not n else round(len(ok) / n, 4),
        "entry_spread_cents_mean": cents([r.entry_spread for r in ok]),
        "paid_vs_entry_ask_cents_mean": cents([r.paid_vs_entry_ask for r in ok if r.paid_vs_entry_ask is not None]),
        "paid_vs_entry_mid_cents_mean": cents([r.paid_vs_entry_mid for r in ok if r.paid_vs_entry_mid is not None]),
        "depth_status_counts_among_ok": depth,
        "taker_share_known_fills": len(known_taker),
        "taker_share_mean": None if not known_taker else round(float(sum(known_taker) / len(known_taker)), 4),
    }


def public_row(r: EntryResult) -> dict:
    """One-fill public projection: statuses and cent means only (no prices, quantities, timestamps or ids)."""
    return {"version": r.version, "status": r.status, "depth_status": r.depth_status,
            "taker": None if r.taker_share is None else bool(r.taker_share == 1)}

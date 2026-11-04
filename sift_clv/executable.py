"""Executable-price CLV (version ``sift-clv-executable/1``) -- additive to ``sift_clv.canonical`` (v1 is unchanged).

Question answered: did we obtain a better EXECUTABLE purchase price than someone buying the same contract at the close?
The midpoint benchmark is kept; it answers a different question (mark-to-market). The two are never merged.

All prices are dollars per contract on the PURCHASED side. A NO position is measured on NO prices, derived from the
YES book: no_ask = 1 - yes_bid, no_bid = 1 - yes_ask. For a NO side the book's resting NO bids are the sellers' side of
the YES asks, so YES-ask levels are 1 - (NO bid price) and NO-ask levels are 1 - (YES bid price).

  B  executable_purchase_clv   close ASK(side) - actual fee-exclusive fill VWAP       >0 we paid LESS than a closing buyer
  C  liquidation_clv           close BID(side) - actual fee-exclusive fill VWAP       what we could sell for vs what we paid
  D  midpoint_execution_clv    close MID(side) - actual fee-exclusive fill VWAP       the traditional mark-to-market measure
  F  size_adjusted_purchase_clv  depth-walked ask VWAP for OUR quantity - actual VWAP  only with a real archived book

Identities (spread s = ask - bid): B = D + s/2, C = D - s/2, so a wider closing spread moves B up and C down with D
unchanged: a widened spread is NOT improved fair value.

Fees (kept apart, entry fee subtracted exactly once):
  *_net_of_entry_fee  = measure - actual exchange entry fee per contract
  liquidation_net_all = (close_bid - modelled_sale_fee) - (vwap + entry_fee)   -- sale fee is a MODEL, labelled as such,
                        and exists only for the hypothetical liquidation; a position held to settlement has no sale fee.

Rules: a closing bid is never a purchase price; a missing/one-sided/crossed/stale/post-start quote withholds the measure;
top-of-book without a depth snapshot is NOT assumed to fill the order (size-adjusted CLV is then unavailable, never
approximated); insufficient depth is reported with the quantity that could be filled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from . import canonical as C

VERSION = "sift-clv-executable/1"
ZERO, ONE = Decimal(0), Decimal(1)

DEPTH_FULL = "DEPTH_FULL"
DEPTH_INSUFFICIENT = "INSUFFICIENT_DEPTH"
DEPTH_NO_ASKS = "NO_ASKS_IN_BOOK"
DEPTH_NOT_AVAILABLE = "TOP_OF_BOOK_ONLY_NO_DEPTH"
DEPTH_STALE = "BOOK_STALE"
DEPTH_AFTER_START = "BOOK_AFTER_START"
DEPTH_TICKER_MISMATCH = "BOOK_TICKER_MISMATCH"


# ----------------------------------------------------------------------------------------- side-normalised quotes
def side_ask(q: C.Quote, side: str) -> Optional[Decimal]:
    """Price a taker pays to BUY ``side`` now (a bid is never a purchase price)."""
    return q.ask(side)


def side_bid(q: C.Quote, side: str) -> Optional[Decimal]:
    """Price a seller of ``side`` receives now."""
    if q.yes_bid is None or q.yes_ask is None:
        return None
    b = q.yes_bid if side == "YES" else ONE - q.yes_ask
    return b if ZERO < b < ONE else None


# ------------------------------------------------------------------------------------------------------- the book
@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class Book:
    """Resting BIDS per side, exactly as the archive stores them (``yes_dollars`` / ``no_dollars``)."""
    ticker: str
    yes_bids: tuple
    no_bids: tuple
    observed_at: Optional[datetime] = None

    @staticmethod
    def of(ticker, yes_levels, no_levels, observed_at=None) -> "Book":
        mk = lambda ls: tuple(Level(C.D(p), C.D(s)) for p, s in ls)          # noqa: E731
        return Book(ticker, mk(yes_levels), mk(no_levels), observed_at)

    def ask_levels(self, side: str) -> list:
        """Executable ask ladder for BUYING ``side``, cheapest first: the opposite side's bids, complemented."""
        opp = self.no_bids if side == "YES" else self.yes_bids
        lv = [Level(ONE - l.price, l.size) for l in opp if l.size > 0 and ZERO < l.price < ONE]
        return sorted(lv, key=lambda l: l.price)

    def bid_levels(self, side: str) -> list:
        own = self.yes_bids if side == "YES" else self.no_bids
        return sorted((l for l in own if l.size > 0), key=lambda l: -l.price)


@dataclass(frozen=True)
class DepthWalk:
    status: str
    requested: Decimal
    filled: Decimal
    vwap: Optional[Decimal]          # VWAP of what could be filled (the FULL quantity only when status == DEPTH_FULL)
    levels_used: int = 0
    worst_price: Optional[Decimal] = None


def walk_asks(book: Book, side: str, qty: Decimal) -> DepthWalk:
    qty = C.D(qty)
    lv = book.ask_levels(side)
    if not lv:
        return DepthWalk(DEPTH_NO_ASKS, qty, ZERO, None)
    need, cost, used = qty, ZERO, 0
    worst = None
    for l in lv:
        take = min(need, l.size)
        cost += take * l.price
        need -= take
        used += 1
        worst = l.price
        if need <= 0:
            break
    got = qty - max(need, ZERO)
    vw = (cost / got) if got > 0 else None
    return DepthWalk(DEPTH_FULL if need <= 0 else DEPTH_INSUFFICIENT, qty, got, vw, used, worst)


def validate_book(book: Optional[Book], *, ticker: str, start: Optional[datetime],
                  max_age_seconds: Optional[int] = 3600, close: Optional[C.Quote] = None) -> Optional[str]:
    """None when usable; else the reason code. The book must be for the SAME contract, strictly before the start, fresh."""
    if book is None:
        return DEPTH_NOT_AVAILABLE
    if book.ticker != ticker:
        return DEPTH_TICKER_MISMATCH
    if start is None or book.observed_at is None:
        return DEPTH_STALE
    if book.observed_at >= start:
        return DEPTH_AFTER_START
    if max_age_seconds is not None and (start - book.observed_at).total_seconds() > max_age_seconds:
        return DEPTH_STALE
    return None


# ------------------------------------------------------------------------------------------------------ the result
@dataclass(frozen=True)
class ExecResult:
    version: str
    side: Optional[str]
    ticker: str
    status: str
    contracts: Optional[Decimal] = None
    actual_vwap: Optional[Decimal] = None
    close_bid: Optional[Decimal] = None
    close_ask: Optional[Decimal] = None
    close_mid: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    executable_purchase_clv: Optional[Decimal] = None          # B
    liquidation_clv: Optional[Decimal] = None                  # C
    midpoint_execution_clv: Optional[Decimal] = None           # D
    entry_fee_per_contract: Optional[Decimal] = None
    executable_purchase_net_of_entry_fee: Optional[Decimal] = None
    midpoint_execution_net_of_entry_fee: Optional[Decimal] = None
    liquidation_net_of_entry_fee: Optional[Decimal] = None
    modelled_sale_fee_per_contract: Optional[Decimal] = None   # MODELLED, hypothetical liquidation only
    liquidation_net_all_fees: Optional[Decimal] = None
    fee_adjustment_count: int = 0
    maker_fill_share: Optional[Decimal] = None                 # share of contracts the exchange reported as maker fills
    depth_status: str = DEPTH_NOT_AVAILABLE
    depth_filled: Optional[Decimal] = None
    size_adjusted_ask_vwap: Optional[Decimal] = None
    size_adjusted_purchase_clv: Optional[Decimal] = None       # F, only when the FULL quantity is displayed
    notes: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        out = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}
        out["notes"] = list(self.notes)
        return out


def evaluate_executable(*, ticker: str, side, close: Optional[C.Quote], start: Optional[datetime],
                        fills: Sequence[C.Fill], stake: Optional[Decimal] = None, book: Optional[Book] = None,
                        max_close_age_seconds: Optional[int] = 3600, max_book_age_seconds: Optional[int] = 3600,
                        model_sale_fee: bool = True) -> ExecResult:
    s = C.norm_side(side)
    if s is None:
        return ExecResult(VERSION, None, ticker, C.SIDE_INVALID)
    cstat = C.validate_close(close, ticker=ticker, start=start, max_close_age_seconds=max_close_age_seconds)
    if cstat != C.OK:
        return ExecResult(VERSION, s, ticker, cstat)
    if not fills:
        return ExecResult(VERSION, s, ticker, C.NO_FILLS)
    vw = C.vwap(fills)
    if vw is None:
        return ExecResult(VERSION, s, ticker, C.FILL_INCOMPLETE)
    if C.fill_price_is_fee_inclusive(fills, C.D(stake)):
        return ExecResult(VERSION, s, ticker, C.FILL_PRICE_FEE_INCLUSIVE)
    n = sum((f.count for f in fills), ZERO)
    bid, ask, mid = side_bid(close, s), side_ask(close, s), close.mid(s)
    if bid is None or ask is None or mid is None:
        return ExecResult(VERSION, s, ticker, C.CLOSE_ONE_SIDED)
    notes = []
    fees = C.total_fee(fills)
    fee_pc = None if fees is None else fees / n
    if fee_pc is None:
        notes.append(C.FEES_UNKNOWN)
    B, Cl, Dm = ask - vw, bid - vw, mid - vw
    sale_fee = (C.estimate_fee(bid, n, role="taker") / n) if model_sale_fee else None
    maker = [f.count for f in fills if f.is_taker is False]
    known = [f for f in fills if f.is_taker is not None]
    maker_share = (sum(maker, ZERO) / n) if len(known) == len(fills) else None
    # depth
    dstat, dfilled, sa_vwap, sa_clv = DEPTH_NOT_AVAILABLE, None, None, None
    why = validate_book(book, ticker=ticker, start=start, max_age_seconds=max_book_age_seconds)
    if why is None:
        walk = walk_asks(book, s, n)
        dstat, dfilled = walk.status, walk.filled
        if walk.status == DEPTH_FULL:
            sa_vwap, sa_clv = walk.vwap, walk.vwap - vw
    else:
        dstat = why
    return ExecResult(
        VERSION, s, ticker, C.OK, contracts=n, actual_vwap=vw, close_bid=bid, close_ask=ask, close_mid=mid,
        close_spread=ask - bid, executable_purchase_clv=B, liquidation_clv=Cl, midpoint_execution_clv=Dm,
        entry_fee_per_contract=fee_pc,
        executable_purchase_net_of_entry_fee=None if fee_pc is None else B - fee_pc,
        midpoint_execution_net_of_entry_fee=None if fee_pc is None else Dm - fee_pc,
        liquidation_net_of_entry_fee=None if fee_pc is None else Cl - fee_pc,
        modelled_sale_fee_per_contract=sale_fee,
        liquidation_net_all_fees=None if (fee_pc is None or sale_fee is None) else (bid - sale_fee) - (vw + fee_pc),
        fee_adjustment_count=0 if fee_pc is None else 1, maker_fill_share=maker_share,
        depth_status=dstat, depth_filled=dfilled, size_adjusted_ask_vwap=sa_vwap, size_adjusted_purchase_clv=sa_clv,
        notes=tuple(notes))

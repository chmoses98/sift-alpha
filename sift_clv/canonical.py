"""Canonical CLV measurements for Kalshi binary contracts (version ``sift-clv-canonical/1``).

Four measures, never merged, each carrying its own price-basis label.  All prices are dollars per contract on the
side RECOMMENDED / PURCHASED (a NO position is measured on NO prices: no_bid = 1 - yes_ask, no_ask = 1 - yes_bid,
no_mid = 1 - yes_mid).

  selection_clv            close_mid(side) - recommendation_mid(side)        fee-exclusive, spread-exclusive
  quoted_execution_clv     close_mid(side) - recommendation_ask(side)        pre-fee, includes the half-spread paid
  actual_execution_clv     close_mid(side) - VWAP of exchange fills           pre-fee, fee-EXCLUSIVE fill price
  fee_adjusted_difference  actual_execution_clv - entry_fees / contracts     the entry fee is subtracted ONCE

Hard rules enforced here:
  * A fill price must be the exchange's fee-exclusive price.  Kalshi's position display (e.g. ~51.7c for a 50c fill)
    is fee-inclusive cost basis; ``stake / contracts`` is refused as a price when fees are non-zero.
  * Fees enter exactly one measure (``fee_adjusted_difference``) and are counted once (``fee_adjustment_count``).
    Closing fees are never charged: a position held to settlement pays no exit fee.
  * A close must be a two-sided, uncrossed quote for the SAME ticker, observed strictly before the start and not
    older than ``max_close_age_seconds``.  Settlement values (0/1), last trades and model values are never closes.
  * Missing or ambiguous evidence yields a status string, never a guess, and never zero.

Pure stdlib; exact ``Decimal`` arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from typing import Iterable, Optional, Sequence

VERSION = "sift-clv-canonical/1"
ZERO, ONE = Decimal(0), Decimal(1)
TOL = Decimal("0.0000001")

OK = "OK"
# eligibility statuses (the measure is withheld, never defaulted)
NO_RECOMMENDATION_QUOTE = "NO_RECOMMENDATION_QUOTE"
NO_CLOSE = "NO_CLOSE"
CLOSE_ONE_SIDED = "CLOSE_ONE_SIDED"
CLOSE_CROSSED = "CLOSE_CROSSED"
CLOSE_AFTER_START = "CLOSE_AFTER_START"
CLOSE_STALE = "CLOSE_STALE"
CLOSE_NO_TIMESTAMP = "CLOSE_NO_TIMESTAMP"
TICKER_MISMATCH = "TICKER_MISMATCH"
SIDE_INVALID = "SIDE_INVALID"
NO_FILLS = "NO_FILLS"
FILL_INCOMPLETE = "FILL_INCOMPLETE"
FILL_PRICE_FEE_INCLUSIVE = "FILL_PRICE_FEE_INCLUSIVE"
FEES_UNKNOWN = "FEES_UNKNOWN"


def D(x) -> Optional[Decimal]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return Decimal(str(x))
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class Quote:
    """A YES-axis two-sided quote in dollars.  ``ticker`` is the immutable contract identity (threshold included)."""
    ticker: str
    yes_bid: Optional[Decimal]
    yes_ask: Optional[Decimal]
    observed_at: Optional[datetime] = None

    @staticmethod
    def of(ticker, yes_bid, yes_ask, observed_at=None) -> "Quote":
        return Quote(ticker, D(yes_bid), D(yes_ask), observed_at)

    def two_sided(self) -> bool:
        # 0 bid / 1 ask are empty-book sentinels, not prices
        return (self.yes_bid is not None and self.yes_ask is not None
                and ZERO < self.yes_bid < ONE and ZERO < self.yes_ask < ONE)

    def crossed(self) -> bool:
        return self.two_sided() and self.yes_ask < self.yes_bid

    def mid(self, side: str) -> Optional[Decimal]:
        if not self.two_sided():
            return None
        m = (self.yes_bid + self.yes_ask) / 2
        return m if side == "YES" else ONE - m

    def ask(self, side: str) -> Optional[Decimal]:
        """Executable price a taker pays to BUY ``side``."""
        if self.yes_ask is None or self.yes_bid is None:
            return None
        a = self.yes_ask if side == "YES" else ONE - self.yes_bid
        return a if ZERO < a < ONE else None


@dataclass(frozen=True)
class Fill:
    """One exchange fill, FEE-EXCLUSIVE ``price`` on the purchased side, with its own fee (None = unknown)."""
    price: Optional[Decimal]
    count: Optional[Decimal]
    fee: Optional[Decimal] = None
    is_taker: Optional[bool] = None

    @staticmethod
    def of(price, count, fee=None, is_taker=None) -> "Fill":
        return Fill(D(price), D(count), D(fee), is_taker)


def norm_side(side) -> Optional[str]:
    s = str(side or "").strip().upper()
    return s if s in ("YES", "NO") else None


def validate_close(close: Optional[Quote], *, ticker: str, start: Optional[datetime],
                   max_close_age_seconds: Optional[int] = 3600) -> str:
    if close is None:
        return NO_CLOSE
    if close.ticker != ticker:
        return TICKER_MISMATCH
    if close.crossed():
        return CLOSE_CROSSED
    if not close.two_sided():
        return CLOSE_ONE_SIDED
    if start is None or close.observed_at is None:
        return CLOSE_NO_TIMESTAMP
    if close.observed_at >= start:
        return CLOSE_AFTER_START
    if max_close_age_seconds is not None and (start - close.observed_at).total_seconds() > max_close_age_seconds:
        return CLOSE_STALE
    return OK


def select_close(observations: Iterable[Quote], *, ticker: str, start: datetime) -> Optional[Quote]:
    """Last valid two-sided, uncrossed observation of THIS ticker strictly before ``start``.  Later or other-ticker
    observations are ignored; none -> None (no fallback to a stale, one-sided or settled value)."""
    best = None
    for q in observations:
        if q.ticker != ticker or q.observed_at is None or q.observed_at >= start:
            continue
        if not q.two_sided() or q.crossed():
            continue
        if best is None or q.observed_at >= best.observed_at:
            best = q
    return best


def vwap(fills: Sequence[Fill]) -> Optional[Decimal]:
    if not fills or any(f.price is None or f.count is None or f.count <= 0 for f in fills):
        return None
    n = sum((f.count for f in fills), ZERO)
    return sum((f.price * f.count for f in fills), ZERO) / n


def total_fee(fills: Sequence[Fill]) -> Optional[Decimal]:
    if not fills or any(f.fee is None for f in fills):
        return None
    return sum((f.fee for f in fills), ZERO)


def estimate_fee(price, contracts, *, role: str = "taker") -> Decimal:
    """Hypothetical Kalshi fee (general schedule): ceil_to_cent(rate * C * P * (1-P)); taker 0.07, maker 0.0175.
    ONLY for hypothetical entries.  Real wagers use the exchange-reported fee."""
    rate = {"taker": Decimal("0.07"), "maker": Decimal("0.0175")}[role]
    p, c = D(price), D(contracts)
    raw = rate * c * p * (ONE - p)
    return (raw * 100).to_integral_value(rounding=ROUND_CEILING) / 100


@dataclass(frozen=True)
class CLVResult:
    version: str
    side: Optional[str]
    ticker: str
    status: str
    selection_clv: Optional[Decimal] = None
    quoted_execution_clv: Optional[Decimal] = None
    actual_execution_clv: Optional[Decimal] = None
    fee_adjusted_difference: Optional[Decimal] = None
    entry_spread_component: Optional[Decimal] = None   # recommendation ask - recommendation mid (side axis)
    fee_per_contract: Optional[Decimal] = None
    fee_adjustment_count: int = 0
    # provenance labels
    selection_basis: str = "close_mid(side) - recommendation_mid(side); fee-exclusive; spread-exclusive"
    quoted_basis: str = "close_mid(side) - recommendation_ask(side); pre-fee"
    actual_basis: str = "close_mid(side) - fill_vwap (fee-exclusive); pre-fee"
    fee_basis: str = "exchange-reported entry fees / contracts; subtracted once; no exit fee"
    notes: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        out = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}
        out["notes"] = list(self.notes)
        return out


def fill_price_is_fee_inclusive(fills: Sequence[Fill], stake: Optional[Decimal]) -> bool:
    """True when the supplied fill price equals ``stake / contracts`` although fees are non-zero, i.e. someone passed
    the fee-inclusive cost basis (Kalshi UI ~51.7c) where the raw fill (50c) belongs."""
    fees, p, n = total_fee(fills), vwap(fills), sum((f.count or ZERO for f in fills), ZERO)
    if stake is None or fees is None or fees <= 0 or p is None or n <= 0:
        return False
    return abs(p - stake / n) <= TOL and abs(p - (stake - fees) / n) > TOL


def evaluate(*, ticker: str, side, recommendation: Optional[Quote], close: Optional[Quote],
             start: Optional[datetime], fills: Sequence[Fill] = (), stake: Optional[Decimal] = None,
             max_close_age_seconds: Optional[int] = 3600) -> CLVResult:
    s = norm_side(side)
    if s is None:
        return CLVResult(VERSION, None, ticker, SIDE_INVALID)
    cstat = validate_close(close, ticker=ticker, start=start, max_close_age_seconds=max_close_age_seconds)
    if cstat != OK:
        return CLVResult(VERSION, s, ticker, cstat)
    close_mid = close.mid(s)
    notes = []
    sel = qex = spread = None
    if recommendation is not None and recommendation.ticker == ticker and recommendation.two_sided() \
            and not recommendation.crossed():
        rmid, rask = recommendation.mid(s), recommendation.ask(s)
        sel = close_mid - rmid
        if rask is not None:
            qex = close_mid - rask
            spread = rask - rmid
    else:
        notes.append(NO_RECOMMENDATION_QUOTE if recommendation is None or recommendation.ticker == ticker
                     else TICKER_MISMATCH)
    aex = fadj = fee_pc = None
    fee_count = 0
    status = OK
    if fills:
        p = vwap(fills)
        if p is None:
            status = FILL_INCOMPLETE
        elif fill_price_is_fee_inclusive(fills, D(stake)):
            status = FILL_PRICE_FEE_INCLUSIVE
        else:
            aex = close_mid - p
            fees = total_fee(fills)
            if fees is None:
                notes.append(FEES_UNKNOWN)          # AEX still valid; fee-adjusted withheld, NOT treated as zero
            else:
                n = sum((f.count for f in fills), ZERO)
                fee_pc = fees / n
                fadj = aex - fee_pc
                fee_count = 1
    else:
        notes.append(NO_FILLS)
    return CLVResult(VERSION, s, ticker, status, selection_clv=sel, quoted_execution_clv=qex,
                     actual_execution_clv=aex, fee_adjusted_difference=fadj, entry_spread_component=spread,
                     fee_per_contract=fee_pc, fee_adjustment_count=fee_count, notes=tuple(notes))

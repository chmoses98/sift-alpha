"""End-to-end evidence pipeline (``sift-clv-pipeline/1``):  Recommendation -> Order -> Fill -> Entry book -> Closing book -> Settlement.

Each order is walked through the stages in turn and records, per stage, either a value or an explicit UNAVAILABLE reason; a missing stage
never borrows evidence from another and never aborts the others, so the funnel shows exactly where evidence runs out.

  recommendation  only an EXPLICIT, verified link counts (``linkage``: client_order_id token or owner attestation). A unique ticker/time
                  window match is reported separately as ``unverified_window`` and is never a verified link.
  order / fill    the exchange order's PLACEMENT time and fee-exclusive fills. Placement time is REQUIRED for the entry stage: a quote observed
                  after placement is future information, and the first-fill time is not a substitute (it can be later than placement).
  entry book      ``entry_conditions``: a same-contract snapshot observed at or before placement and no older than ``ENTRY_FRESH_SECONDS``.
                  Older is labelled near-not-entry and excluded from entry statistics. Never reconstructed.
  closing book    ``executable``: matched two-sided close strictly before the start, executable purchase CLV (close ask - fill VWAP) and
                  size-adjusted depth walk only from a real archived book.
  settlement      exchange result for the contract; net per contract = payout - fee-exclusive VWAP - entry fee (fee counted once).

Public output (``funnel``) is counts and reasons only: no ticker, id, price, quantity, amount or timestamp.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from . import canonical as C
from . import entry_conditions as E
from . import executable as X
from . import linkage as L

VERSION = "sift-clv-pipeline/1"
ENTRY_FRESH_SECONDS = 45
PLACEMENT_UNKNOWN = "PLACEMENT_TIME_UNKNOWN"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Item:
    order: L.Order
    placed_at: Optional[datetime]
    start: Optional[datetime]
    snapshots: Sequence[E.Snapshot] = ()
    close: Optional[C.Quote] = None
    close_book: Optional[X.Book] = None
    result: Optional[str] = None                    # exchange settlement for the contract: "yes" | "no" | None (unsettled/unknown)


@dataclass(frozen=True)
class Row:
    link: str                                       # VERIFIED / UNVERIFIED_WINDOW / UNLINKED
    link_tier: Optional[str]
    fills: str
    entry: str                                      # an entry_conditions status or PLACEMENT_TIME_UNKNOWN
    entry_is_fresh: bool
    close: str
    close_depth: str
    settlement: str
    paid_vs_entry_ask_cents: Optional[float] = None
    entry_spread_cents: Optional[float] = None
    executable_purchase_clv_cents: Optional[float] = None
    net_per_contract_cents: Optional[float] = None


def _settle(side: Optional[str], result: Optional[str], vwap: Decimal, fee_pc: Optional[Decimal]) -> tuple[str, Optional[float]]:
    if result not in ("yes", "no"):
        return "UNSETTLED_OR_UNKNOWN", None
    if fee_pc is None:
        return "FEES_UNKNOWN", None
    payout = ONE if side == result.upper() else ZERO
    return "SETTLED", float((payout - vwap - fee_pc) * 100)


ONE = Decimal(1)


def run(items: Iterable[Item], recs: Iterable[L.Recommendation], attestations: Iterable[L.Attestation] = (), *,
        window_seconds: Optional[float] = None, entry_max_age: int = ENTRY_FRESH_SECONDS) -> list[Row]:
    items = list(items)
    starts = {i.order.ticker: i.start for i in items if i.start}
    links = L.link_all(list(recs), [i.order for i in items], list(attestations), starts, window_seconds=window_seconds)
    by_order: dict = {}
    for l in links:
        cur = by_order.get(l.order_key)
        if cur is None or (l.verified and not cur.verified):
            by_order[l.order_key] = l
    rows = []
    for it in items:
        o, lk = it.order, by_order.get(it.order.order_key)
        if lk is not None and lk.verified:
            link, tier = "VERIFIED", lk.tier
        elif lk is not None and lk.grade == "UNIQUE_WINDOW":
            link, tier = "UNVERIFIED_WINDOW", lk.tier
        else:
            link, tier = "UNLINKED", (lk.quarantine if lk is not None else None)
        vw, n = C.vwap(list(o.fills)), sum((f.count for f in o.fills if f.count), ZERO)
        if vw is None or n <= 0:
            rows.append(Row(link, tier, "FILLS_INCOMPLETE", "NO_FILLS", False, "NO_FILLS", "NA", "NO_FILLS")); continue
        side = C.norm_side(o.side)
        # --- entry book (placement time required)
        if it.placed_at is None:
            entry, fresh, paid, spread = PLACEMENT_UNKNOWN, False, None, None
        else:
            er = E.evaluate_entry(ticker=o.ticker, side=side, first_fill_at=it.placed_at, fills=list(o.fills),
                                  snapshots=it.snapshots, max_age_seconds=entry_max_age)
            entry, fresh = er.status, er.status == E.ENTRY_OK
            paid = None if not fresh or er.paid_vs_entry_ask is None else float(er.paid_vs_entry_ask * 100)
            spread = None if not fresh else float(er.entry_spread * 100)
        # --- closing book + executable CLV
        xr = X.evaluate_executable(ticker=o.ticker, side=side, close=it.close, start=it.start, fills=list(o.fills), stake=o.stake, book=it.close_book)
        close = "CLOSE_OK" if xr.status == C.OK else xr.status
        clv = None if xr.executable_purchase_clv is None else float(xr.executable_purchase_clv * 100)
        # --- settlement (fee once)
        fee_pc = xr.entry_fee_per_contract if xr.status == C.OK else (C.total_fee(list(o.fills)) / n if C.total_fee(list(o.fills)) is not None else None)
        sett, net = _settle(side, it.result, vw, fee_pc)
        rows.append(Row(link, tier, "FILLS_OK", entry, fresh, close, xr.depth_status if xr.status == C.OK else "NA", sett,
                        paid, spread, clv, net))
    return rows


def funnel(rows: Iterable[Row]) -> dict:
    """Counts of orders that reach each stage, and why the rest do not. Privacy-safe."""
    rs = list(rows)
    c = Counter()
    for r in rs:
        c["orders"] += 1
        c["fills_ok"] += r.fills == "FILLS_OK"
        c["link_verified"] += r.link == "VERIFIED"
        c["link_unverified_window"] += r.link == "UNVERIFIED_WINDOW"
        c["entry_fresh_book"] += r.entry_is_fresh
        c["close_ok"] += r.close == "CLOSE_OK"
        c["close_with_full_depth"] += r.close_depth == X.DEPTH_FULL
        c["settled"] += r.settlement == "SETTLED"
        c["entry_fresh_and_close_ok"] += r.entry_is_fresh and r.close == "CLOSE_OK"
        c["complete_chain"] += (r.link == "VERIFIED" and r.entry_is_fresh and r.close == "CLOSE_OK" and r.settlement == "SETTLED")
    return {"version": VERSION, "stages": dict(c),
            "entry_status": dict(Counter(r.entry for r in rs)), "close_status": dict(Counter(r.close for r in rs)),
            "settlement_status": dict(Counter(r.settlement for r in rs)), "link_status": dict(Counter(r.link for r in rs))}

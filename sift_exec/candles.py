"""Fill evidence from OHLC candles when the trade tape is truncated (research only).

Why this is sound (validated in ``research/exec_track/tape_audit.py``): on tickers whose tape is complete, the hourly/minute candle's
``price.low``/``price.high``/``volume`` equal the min/max/sum of that period's prints in 100% of 27,563 hourly candles, and PRE-kickoff
periods with prints always have a candle (a missing candle period before kickoff means no prints).  Candles survive the 10,000-print
tape cap, so they bound the fill status of orders the tape cannot decide.

For a resting BUY at ``limit`` (own-side cents) over (placed, expiry), using only candle periods wholly inside the window:
  THROUGH            some period's low (YES) / high (NO, as 100-high) is strictly below the limit.  While our bid rests, every ask is above it, so a
                     print below the limit must be a taker SELL through our level => the order is certainly FILLED (queue-independent).
  UNFILLED_CERTAIN   the window is fully covered by candle periods (hourly + minute) and no print traded at or below the limit.
  AT_LEVEL_POSSIBLE  fully covered, lowest print == limit exactly: filled only if the queue ahead drained (queue-dependent).
  UNRESOLVED_EDGE    no through evidence but part of the window (partial hours at the edges, outside minute coverage) is not covered.
"""
from __future__ import annotations

THROUGH, UNFILLED_CERTAIN, AT_LEVEL_POSSIBLE, UNRESOLVED_EDGE = "THROUGH", "UNFILLED_CERTAIN", "AT_LEVEL_POSSIBLE", "UNRESOLVED_EDGE"


def classify(t, side: str, limit: int, placed: float, expiry: float) -> str:
    through, level = False, False
    spans = []
    for periods in (t.hp, t.mp):
        for s, e, lo, hi in periods:
            if s < placed or e > expiry:
                continue
            own_low = lo if side == "YES" else 100 - hi
            if own_low < limit:
                through = True
            elif own_low == limit:
                level = True
    if through:
        return THROUGH
    # coverage: whole hours inside the window plus the minute-candle region (periods without a candle there = no prints)
    h0 = -(-placed // 3600) * 3600
    h1 = (expiry // 3600) * 3600
    if h1 > h0:
        spans.append((h0, h1))
    if t.m_first is not None:
        spans.append((max(placed, t.m_first - 60), expiry))
    spans.sort()
    cur, merged = placed, []
    for a, b in spans:
        if a > cur + 1e-6:
            merged.append((cur, a))
        cur = max(cur, b)
    uncovered = (sum(b - a for a, b in merged) + max(0.0, expiry - cur)) > 1e-6
    if uncovered:
        return UNRESOLVED_EDGE
    return AT_LEVEL_POSSIBLE if level else UNFILLED_CERTAIN

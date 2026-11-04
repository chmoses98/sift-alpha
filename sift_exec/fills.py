"""Independent resting-buy fill replay with explicit evidence classes (research only; nothing is placed).

This is a from-scratch event replay (a per-print state machine with an explicit queue-ahead counter and per-fill output).  It is
NOT a copy of ``research.outcome_exec.nfl_execution.sim_fill`` (vectorised cumulative sums) nor of ``sift_clv.limit_orders``; tests assert
that all three agree on random tapes so that a bug in any one is visible.

Print semantics (verified on 574k prints of the 2025 NFL tape against concurrent 1-minute candles, docs/EXECUTION_RESEARCH.md §3):
  taker_side == 'no'  -> the print is a taker SELL of YES hitting resting YES bids at ``yes_price``  (fills a resting YES buy)
  taker_side == 'yes' -> a taker BUY of YES lifting the YES ask at ``yes_price`` (= hitting resting NO bids at 100-yes; fills a NO buy)
Fill rules for a resting BUY at ``limit`` (cents, own side):
  THROUGH   a qualifying print strictly below ``limit``: every bid at/above that price was consumed first, so our whole remainder fills at ``limit``
  AT_LEVEL  a qualifying print AT ``limit``: it first drains the ``queue_ahead`` contracts already resting at our level, the excess fills us
Unmodelled (stated, never silently assumed): cancellations ahead of us (would help us), queue additions behind us (irrelevant), our own market
impact, hidden/self-trade prevention.  A displayed bid or a last-trade touch is never a fill.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

THROUGH, AT_LEVEL = "THROUGH", "AT_LEVEL"


@dataclass
class Fill:
    ts: float
    price_c: int
    qty: float
    evidence: str


@dataclass
class FillResult:
    fills: list = field(default_factory=list)
    qty: float = 10.0

    @property
    def filled(self) -> float:
        return sum(f.qty for f in self.fills)

    @property
    def first_ts(self):
        return self.fills[0].ts if self.fills else None

    @property
    def status(self) -> str:
        f = self.filled
        return "FILLED" if f >= self.qty - 1e-9 else ("PARTIAL" if f > 1e-9 else "UNFILLED")


class Tape:
    """De-duplicated, time-sorted prints for ONE ticker, pre-split into the prints that can fill a YES buy or a NO buy."""
    def __init__(self, ts, yes_c, size, taker_no):
        o = np.argsort(np.asarray(ts, float), kind="stable")
        self.ts = np.asarray(ts, float)[o]
        self.yes_c = np.asarray(yes_c, np.int16)[o]
        self.size = np.asarray(size, float)[o]
        self.taker_no = np.asarray(taker_no, bool)[o]
        self._side = {}
        for side in ("YES", "NO"):
            q = self.taker_no if side == "YES" else ~self.taker_no
            sc = self.yes_c if side == "YES" else (100 - self.yes_c)
            self._side[side] = (self.ts[q], sc[q].astype(np.int16), self.size[q])

    def __len__(self):
        return len(self.ts)

    def qualifying(self, side):
        return self._side[side]

    def all_prints(self, side):
        """(ts, own-side price, size, qualifying-mask) for EVERY print; qualifying = the taker hits our bids."""
        if side == "YES":
            return self.ts, self.yes_c.astype(np.int16), self.size, self.taker_no
        return self.ts, (100 - self.yes_c).astype(np.int16), self.size, ~self.taker_no


def replay_buy(tape: Tape, side: str, limit_c: int, qty: float, t0: float, t1: float, queue_ahead: float = 0.0,
               through_only: bool = False, through_any_side: bool = False) -> FillResult:
    """Replay prints with t0 < ts < t1 (open interval: nothing at or before placement, nothing at/after expiry).
    ``through_any_side``: also treat a print BELOW the limit by the OTHER taker side (the market's ask fell through our bid) as THROUGH -- a resting
    bid cannot coexist with an ask below it, so our order would have been executed first (PR #25 omits these: 95 of ~10k candle-THROUGH orders)."""
    if through_any_side:
        ts, sc, sz, qual = tape.all_prints(side)
    else:
        ts, sc, sz = tape.qualifying(side)
        qual = None
    i0, i1 = int(np.searchsorted(ts, t0, "right")), int(np.searchsorted(ts, t1, "left"))
    res = FillResult(qty=qty)
    if i1 <= i0:
        return res
    cand = np.nonzero(sc[i0:i1] <= limit_c)[0] + i0          # only prints that can matter; semantics below are per-print
    q_left, rem = float(queue_ahead), float(qty)
    for k in cand:
        p, s, t = int(sc[k]), float(sz[k]), float(ts[k])
        if p < limit_c:
            res.fills.append(Fill(t, limit_c, rem, THROUGH)); rem = 0.0
        elif not through_only and (qual is None or qual[k]):    # p == limit_c, taker hits our bids
            take = max(0.0, s - q_left); q_left = max(0.0, q_left - s)
            take = min(take, rem)
            if take > 0:
                res.fills.append(Fill(t, limit_c, take, AT_LEVEL)); rem -= take
        if rem <= 1e-12:
            break
    return res

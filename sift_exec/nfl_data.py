"""Independent loader for the 2025 NFL Kalshi backfill (market-data branch) -> per-ticker ``Tick`` objects.
Written separately from ``research.outcome_exec.nfl_execution.load_tick`` (pure python, bisect) and tested to return identical quotes."""
from __future__ import annotations
import bisect, datetime as dt, json, os
from dataclasses import dataclass, field
import numpy as np
from sift_research import nfl25 as N
from .fills import Tape

TAPE_CAP = 10000
CLOSE_MIN = 15


@dataclass
class Tick:
    ticker: str
    series: str
    game: dict
    outcome: int
    h: list = field(default_factory=list)      # [(end_ts, bid_c, ask_c)] hourly candle closes (-1 = none)
    m: list = field(default_factory=list)      # minute candles
    tape: Tape = None
    raw_lines: int = 0
    first_ts: float | None = None
    m_first: float | None = None
    h_ends: list = field(default_factory=list)
    m_ends: list = field(default_factory=list)
    hp: list = field(default_factory=list)     # [(start_ts, end_ts, low_c, high_c)] hourly candles that traded (price low/high of ALL prints)
    mp: list = field(default_factory=list)     # same for minute candles

    @property
    def kickoff(self):
        return self.game["kickoff"].timestamp()

    @property
    def capped(self):
        return self.raw_lines >= TAPE_CAP


def _c(x):
    return -1 if x is None else int(round(float(x) * 100))


def _candles(rows):
    out = []
    for r in rows or []:
        out.append((int(r["end_period_ts"]), _c((r.get("yes_bid") or {}).get("close")), _c((r.get("yes_ask") or {}).get("close"))))
    out.sort()
    return out


def _price_candles(rows, period):
    out = []
    for r in rows or []:
        lo, hi = (r.get("price") or {}).get("low"), (r.get("price") or {}).get("high")
        if lo is None or hi is None:
            continue
        e = int(r["end_period_ts"])
        out.append((e - period, e, int(round(float(lo) * 100)), int(round(float(hi) * 100))))
    out.sort()
    return out


def load_tick(series, m, idx, root):
    game = N.resolve_event(m["event_ticker"], idx)
    out = N.outcome_yes(m)
    if game is None or out is None:
        return None
    cd = N.load_candles(series, m["ticker"], root)
    if not cd:
        return None
    t = Tick(m["ticker"], series, game, out, _candles(cd.get("h60")), _candles(cd.get("m1")))
    t.h_ends, t.m_ends = [x[0] for x in t.h], [x[0] for x in t.m]
    t.hp, t.mp = _price_candles(cd.get("h60"), 3600), _price_candles(cd.get("m1"), 60)
    t.m_first = min((int(r["end_period_ts"]) for r in cd.get("m1") or []), default=None)   # start of minute-candle coverage
    p = os.path.join(root, "trades", series, m["ticker"] + ".jsonl")
    ts, yc, sz, tn, seen = [], [], [], [], set()
    if os.path.exists(p):
        for l in open(p):
            t.raw_lines += 1
            r = json.loads(l)
            if r["trade_id"] in seen or r.get("is_block_trade"):
                continue
            seen.add(r["trade_id"])
            ts.append(dt.datetime.fromisoformat(r["created_time"].replace("Z", "+00:00")).timestamp())
            yc.append(_c(r["yes_price_dollars"])); sz.append(float(r["count_fp"])); tn.append(r["taker_side"] == "no")
    t.tape = Tape(ts, yc, sz, tn)
    t.first_ts = float(t.tape.ts[0]) if len(t.tape) else None
    return t


def quote_at(t: Tick, when: float):
    """Last valid two-sided YES quote at/before ``when``: (bid_c, ask_c, age_s, source) or None.
    Minute candle if its close is <=180 s old, else hourly candle (any age).  A one-sided/empty/crossed candle is NOT a quote and
    does not fall back to an older source (same rule as PR #25 so that the reproduction is like-for-like)."""
    for ends, rows, maxage, src in ((t.m_ends, t.m, 180, "m1"), (t.h_ends, t.h, 10 ** 12, "h60")):
        i = bisect.bisect_right(ends, when) - 1
        if i < 0 or when - ends[i] > maxage:
            continue
        _, b, a = rows[i]
        if b <= 0 or a >= 100 or a <= b:
            return None
        return b, a, when - ends[i], src
    return None


def side_quote(q, side):
    b, a, age, src = q
    return (b, a, age, src) if side == "YES" else (100 - a, 100 - b, age, src)


def tape_complete(t: Tick, placed: float) -> bool:
    """A window starting at ``placed`` is observable iff the tape was not truncated, or the oldest retained print precedes placement.
    (A truncated tape keeps the NEWEST prints; a market with zero retained prints cannot be called either way when capped.)"""
    return (not t.capped) or (t.first_ts is not None and t.first_ts <= placed)

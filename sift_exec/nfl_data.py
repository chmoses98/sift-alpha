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

# Recovered pre-kickoff tape (nfl-edge-finder #246): ``<root>/trades_v2/<SERIES>/<TICKER>.jsonl`` + audit rows in ``<root>/tape_meta.jsonl``.
# Used ONLY when the audit row says the tape is anchored at a real KICKOFF (never market close_time) and it holds prints.  Research only.
V2_ANCHORS = ("kickoff", "kickoff_ticker_parse")
V2_STATUSES = ("COMPLETE", "COMPLETE_WITH_SOURCE_GAP", "INCOMPLETE_RESUMABLE", "INCOMPLETE_ERROR")
SRC_LEGACY, SRC_V2, SRC_NONE = "legacy_trades_capped", "recovered_trades_v2", "no_archived_tape"


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
    tape_source: str = SRC_LEGACY              # which archive the tape came from (never mixed per ticker)
    v2_status: str | None = None               # audit status of the recovered tape if one exists (even when not used)

    @property
    def kickoff(self):
        return self.game["kickoff"].timestamp()

    @property
    def capped(self):
        """True when the tape may be missing OLDER prints (it keeps the newest).  Legacy: exactly the 10,000-line cap.  Recovered tape: anything
        short of a COMPLETE audit status (a source gap or a pending resume is NOT observable history)."""
        if self.tape_source == SRC_NONE:
            return True              # no archived tape at all: the history is UNKNOWN, never "complete and empty"
        if self.tape_source == SRC_V2:
            return self.v2_status != "COMPLETE"
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


_META = {}


def v2_meta(root):
    """Last audit row per ticker from ``tape_meta.jsonl`` (cached on file identity)."""
    p = os.path.join(root, "tape_meta.jsonl")
    if not os.path.exists(p):
        return {}
    key = (p, os.path.getmtime(p), os.path.getsize(p))
    if _META.get(p, (None,))[0] != key:
        rows = {}
        for l in open(p):
            try:
                r = json.loads(l)
                rows[r["ticker"]] = r
            except (ValueError, KeyError):
                continue
        _META[p] = (key, rows)
    return _META[p][1]


def read_tape(root, series, ticker, mode="auto"):
    """-> (ts, yes_c, size, taker_no, raw_lines, source, v2_status).  Recovered v2 tape replaces the legacy one only if audited, kickoff-anchored and non-empty;
    prints after the audit row's anchor are dropped defensively.  Block trades are excluded exactly as for the legacy tape."""
    meta = v2_meta(root).get(ticker)
    v2_status = meta.get("status") if meta else None
    ts, yc, sz, tn, seen, raw, src = [], [], [], [], set(), 0, SRC_LEGACY
    p2 = os.path.join(root, "trades_v2", series, ticker + ".jsonl")
    if mode == "auto" and meta and meta.get("anchor_kind") in V2_ANCHORS and v2_status in V2_STATUSES and meta.get("anchor_ts") and os.path.exists(p2):
        anchor = float(meta["anchor_ts"])
        for l in open(p2):
            raw += 1
            r = json.loads(l)
            t = dt.datetime.fromisoformat(r["created_time"].replace("Z", "+00:00")).timestamp()
            if r["trade_id"] in seen or r.get("is_block_trade") or t > anchor:
                continue
            seen.add(r["trade_id"])
            ts.append(t); yc.append(_c(r["yes_price_dollars"])); sz.append(float(r["count_fp"])); tn.append(r["taker_side"] == "no")
        if ts:
            return ts, yc, sz, tn, raw, SRC_V2, v2_status
        ts, yc, sz, tn, seen, raw = [], [], [], [], set(), 0           # empty recovered tape: never overrides the legacy archive
    p = os.path.join(root, "trades", series, ticker + ".jsonl")
    if not os.path.exists(p):
        return [], [], [], [], 0, SRC_NONE, v2_status
    if True:
        for l in open(p):
            raw += 1
            r = json.loads(l)
            if r["trade_id"] in seen or r.get("is_block_trade"):
                continue
            seen.add(r["trade_id"])
            ts.append(dt.datetime.fromisoformat(r["created_time"].replace("Z", "+00:00")).timestamp())
            yc.append(_c(r["yes_price_dollars"])); sz.append(float(r["count_fp"])); tn.append(r["taker_side"] == "no")
    return ts, yc, sz, tn, raw, SRC_LEGACY, v2_status


def tape_source_counts(ticks):
    """Coverage diagnostics: how many tickers used which tape, and how many are still truncated."""
    out = {SRC_LEGACY: 0, SRC_V2: 0, SRC_NONE: 0, "truncated": 0}
    for t in ticks:
        out[t.tape_source] += 1
        out["truncated"] += bool(t.capped)
    return out


def load_tick(series, m, idx, root, tape_mode="auto"):
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
    ts, yc, sz, tn, t.raw_lines, t.tape_source, t.v2_status = read_tape(root, series, m["ticker"], tape_mode)
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

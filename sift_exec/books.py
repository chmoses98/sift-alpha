"""NBA/NHL order-book reconstruction from the immutable ``data-archive`` branch (``kalshi/orderbooks`` bases + ``kalshi/orderbooks_delta`` deltas).

Archive facts (verified, docs/EXECUTION_RESEARCH.md §5): a BASE file holds the top-10 price levels per side for ~300 tracked markets; every DELTA is
cumulative against its base (``base_path``) and carries the FULL new book for each market that differs from the base (``changed``/``added``) plus
``removed`` tickers.  Snapshots are 5-10 minutes apart.  Levels beyond the 10th are NOT archived, so depth beyond ~10 levels is unknown (a lower bound),
and there is NO trade tape in these archives: fills cannot be simulated, only bounded (sift_exec.fills docstring; research/exec_track/book_depth.py).
Book format: ``yes``/``no`` = [[price_cents, size], ...] resting BID levels on each side, best first.  YES ask = 100 - best NO bid.
"""
from __future__ import annotations
import bisect, datetime as dt, glob, gzip, json, os


def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _read_jsonl_gz(p):
    return [json.loads(l) for l in gzip.open(p, "rt")]


class BookArchive:
    def __init__(self, root: str):
        self.root = root
        self.deltas = []                       # (captured_ts, path)
        for p in sorted(glob.glob(os.path.join(root, "orderbooks_delta", "*", "*.json.gz"))):
            stamp = os.path.basename(p).split("_")[3]                       # kalshi_orderbooks_delta_<YYYYmmddTHHMMSSZ>_<run>.json.gz
            ts = dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
            self.deltas.append((ts, p))
        self.deltas.sort()
        self._base_cache = {}
        self._ts = [x[0] for x in self.deltas]

    def _base(self, base_path):
        if base_path not in self._base_cache:
            if len(self._base_cache) > 6:
                self._base_cache.clear()
            rows = _read_jsonl_gz(os.path.join(self.root, "..", base_path))
            self._base_cache[base_path] = {r["ticker"]: r for r in rows}
        return self._base_cache[base_path]

    def snapshot(self, i: int):
        """Reconstructed {ticker: {'yes': [[c,size],..], 'no': [...]}} at delta index ``i`` and its capture time."""
        ts, p = self.deltas[i]
        d = json.loads(gzip.open(p).read())
        base_path = d["base_path"]
        books = {k: {"yes": v.get("yes") or [], "no": v.get("no") or []} for k, v in self._base(base_path).items()}
        for k, v in list(d["changed"].items()) + list(d["added"].items()):
            books[k] = {"yes": v.get("yes") or [], "no": v.get("no") or []}
        for k in d["removed"]:
            books.pop(k, None)
        return ts, books

    def reconstruct_at(self, t: float, max_age_s: float = 900.0):
        """Book as of the last snapshot at or before ``t`` (None if older than ``max_age_s``): never uses a later snapshot."""
        i = bisect.bisect_right(self._ts, t) - 1
        if i < 0 or t - self._ts[i] > max_age_s:
            return None
        return self.snapshot(i)


def best(book):
    """(bid_c, ask_c, bid_size, ask_size) on the YES axis, or None when a side is empty."""
    if not book["yes"] or not book["no"]:
        return None
    b, bs = book["yes"][0]
    na, ns = book["no"][0]
    return int(b), 100 - int(na), float(bs), float(ns)


def walk_buy_yes(book, qty: float):
    """Cost (cents, total) of buying ``qty`` YES contracts by lifting the ask side (NO bids at 100-p).  Returns (vwap_c, filled_qty); filled < qty when the
    archived 10 levels are exhausted (depth beyond is unknown, so the VWAP is a floor for the true cost of the missing part)."""
    got, cost = 0.0, 0.0
    for p_no, sz in book["no"]:
        take = min(sz, qty - got)
        got += take; cost += take * (100 - int(p_no))
        if got >= qty - 1e-9:
            break
    return (cost / got if got else None), got


def depth_within(book, side: str, cents: int):
    """Displayed size within ``cents`` of the best price on ``side`` ('yes' bid side or 'no' bid side)."""
    lv = book[side]
    if not lv:
        return 0.0
    top = int(lv[0][0])
    return float(sum(sz for p, sz in lv if top - int(p) <= cents))

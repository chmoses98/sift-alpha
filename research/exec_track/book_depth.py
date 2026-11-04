#!/usr/bin/env python3
"""NBA/NHL pre-game depth, executable-price and volume-bounded fill-feasibility study from reconstructed books (research only).
usage: book_depth.py --archive DIR_with_kalshi --sport nba|nhl --out reports/exec_track/book_depth_<sport>.json
Fill feasibility is a NECESSARY-CONDITION UPPER BOUND only: a resting bid at the best level can fill only if the market's cumulative traded volume
(``volume_fp`` in markets_delta) grows by at least the displayed queue ahead of us before the start.  There is no trade tape, so no fill is ever asserted."""
import argparse, bisect, collections, datetime as dt, glob, gzip, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_exec import books as B                       # noqa: E402

SERIES = {"nba": ("KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL"), "nhl": ("KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL")}
BUCKETS = [(0.5, 2), (2, 6), (6, 24), (24, 72)]       # hours before start


def load_market_meta(root, series):
    """start time (occurrence_datetime) and a (ts -> cumulative volume) timeline per ticker from markets bases + markets_delta."""
    start, vol = {}, collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(root, "markets", "*", "*.jsonl.gz"))):
        for l in gzip.open(p, "rt"):
            if series not in l:
                continue
            r = json.loads(l)
            if r["ticker"].startswith(series) and r.get("occurrence_datetime"):
                start[r["ticker"]] = B._ts(r["occurrence_datetime"])
                vol[r["ticker"]].append((B._ts(r["_observed_at_utc"]), float(r.get("volume_fp") or 0)))
    for p in sorted(glob.glob(os.path.join(root, "markets_delta", "*", "*.json.gz"))):
        d = json.loads(gzip.open(p).read()); t = B._ts(d["captured_at_utc"])
        for k, v in list(d["changed"].items()) + list(d["added"].items()):
            if k.startswith(series) and "volume_fp" in v:
                vol[k].append((t, float(v["volume_fp"])))
    for k in vol:
        vol[k].sort()
    return start, vol


def vol_at(timeline, t):
    ts = [x[0] for x in timeline]
    i = bisect.bisect_right(ts, t) - 1
    return timeline[i][1] if i >= 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True); ap.add_argument("--sport", choices=("nba", "nhl"), required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--max-snapshots", type=int, default=0)
    a = ap.parse_args(argv)
    root = os.path.join(a.archive, "kalshi")
    arch = B.BookArchive(root)
    ser = SERIES[a.sport]
    start, vol = {}, {}
    for s in ser:
        st, v = load_market_meta(root, s); start.update(st); vol.update(v)
    rows = []
    idxs = range(len(arch.deltas)) if not a.max_snapshots else range(0, len(arch.deltas), max(1, len(arch.deltas) // a.max_snapshots))
    first_ts = arch.deltas[0][0]; last_ts = arch.deltas[-1][0]
    for i in idxs:
        t, books = arch.snapshot(i)
        for k, bk in books.items():
            if not k.startswith(ser) or k not in start:
                continue
            h = (start[k] - t) / 3600.0
            if not (0.5 <= h < 72):
                continue
            bt = B.best(bk)
            if bt is None:
                continue
            b, ask, bs, asz = bt
            if not (0 < b < ask < 100):
                continue
            v0, v1 = (vol_at(vol[k], t) if k in vol else None), (vol_at(vol[k], start[k] - 60) if k in vol else None)
            w10, f10 = B.walk_buy_yes(bk, 10); w100, f100 = B.walk_buy_yes(bk, 100); w500, f500 = B.walk_buy_yes(bk, 500)
            rows.append(dict(series=k.split("-")[0], ticker=k, event=k.rsplit("-", 1)[0], h=h, spread=ask - b, bid=b, ask=ask, bid_size=bs, ask_size=asz,
                             d3_bid=B.depth_within(bk, "yes", 3), d3_ask=B.depth_within(bk, "no", 3),
                             slip10=None if w10 is None else w10 - ask, slip100=None if w100 is None else w100 - ask, full100=f100 >= 100, full500=f500 >= 500,
                             slip500=None if w500 is None or f500 < 500 else w500 - ask,
                             dvol_to_start=None if (v0 is None or v1 is None) else max(0.0, v1 - v0)))
    out = dict(version="sift-exec-book-depth/1", status="RESEARCH_ONLY", sport=a.sport, archive_span_utc=[dt.datetime.fromtimestamp(first_ts, dt.timezone.utc).isoformat(), dt.datetime.fromtimestamp(last_ts, dt.timezone.utc).isoformat()],
               snapshots_used=len(list(idxs)), snapshots_total=len(arch.deltas), n_rows=len(rows),
               tickers=len({r["ticker"] for r in rows}), events=len({r["event"] for r in rows}),
               limits=["top-10 price levels per side only (depth beyond is unknown; slip is a floor)", "NO trade tape: fills are bounded, never observed",
                       "snapshots are 5-10 min apart (queue changes in between are invisible)", "~300 markets tracked per snapshot (not every game market)"])
    for s in ser:
        for lo, hi in BUCKETS:
            R = [r for r in rows if r["series"] == s and lo <= r["h"] < hi]
            if len(R) < 30:
                continue
            g = lambda f: [r[f] for r in R if r[f] is not None]
            bs = np.array(g("bid_size")); sp = np.array(g("spread"))
            dv = [r for r in R if r["dvol_to_start"] is not None]
            out[f"{s}|{lo}-{hi}h"] = dict(
                n_snapshots_markets=len(R), events=len({r["event"] for r in R}), tickers=len({r["ticker"] for r in R}),
                spread_c=dict(p25=float(np.percentile(sp, 25)), median=float(np.median(sp)), p75=float(np.percentile(sp, 75))),
                best_bid_size=dict(p25=float(np.percentile(bs, 25)), median=float(np.median(bs)), p75=float(np.percentile(bs, 75)),
                                   share_ge_500=float((bs >= 500).mean()), share_ge_5000=float((bs >= 5000).mean())),
                depth_within_3c_bid_median=float(np.median(g("d3_bid"))), depth_within_3c_ask_median=float(np.median(g("d3_ask"))),
                slip_c_per_contract=dict(q10=float(np.median(g("slip10"))) if g("slip10") else None, q100=float(np.median(g("slip100"))) if g("slip100") else None,
                                         q500=float(np.median(g("slip500"))) if g("slip500") else None),
                share_archived_depth_covers_100=float(np.mean([r["full100"] for r in R])), share_archived_depth_covers_500=float(np.mean([r["full500"] for r in R])),
                at_bid_fill_necessary_condition_upper_bound=dict(n=len(dv), share_volume_to_start_ge_queue=float(np.mean([r["dvol_to_start"] >= r["bid_size"] for r in dv])) if dv else None,
                                                                   median_volume_to_start=float(np.median([r["dvol_to_start"] for r in dv])) if dv else None))
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in out.items() if "|" not in k}, indent=1))


if __name__ == "__main__":
    main()

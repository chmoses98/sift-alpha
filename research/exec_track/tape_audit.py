#!/usr/bin/env python3
"""NFL 2025 tape truncation / fill-provenance audit (feeds nfl-edge-finder issue #246).  Research only.
usage: tape_audit.py --backfill DIR --games games.csv --out reports/exec_track/tape_audit.json [--cache ticks.pkl]"""
import argparse, collections, datetime as dt, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from research.exec_track import nfl_study as NS            # noqa: E402
from sift_exec import candles as CA, study as ST            # noqa: E402
from sift_exec.fills import replay_buy                      # noqa: E402
from sift_exec.nfl_data import CLOSE_MIN, quote_at, side_quote, tape_complete   # noqa: E402
from sift_research import nfl25 as N                        # noqa: E402


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", default=N.BACKFILL); ap.add_argument("--games", default=N.GAMES_CSV)
    ap.add_argument("--cache", default=None); ap.add_argument("--out", default="reports/exec_track/tape_audit.json")
    a = ap.parse_args(argv)
    ticks = NS.load_ticks(a.backfill, a.games, a.cache)
    mk = {}
    for s in ("KXNFLGAME", "KXNFLSPREAD"):
        for m in N.load_markets(s, a.backfill):
            mk[m["ticker"]] = m
    out = dict(version="sift-exec-tape-audit/1", status="RESEARCH_ONLY")
    # 1) truncation signature
    per = {}
    for s in ("KXNFLGAME", "KXNFLSPREAD"):
        R = [t for t in ticks if t.series == s]
        cap = [t for t in R if t.capped]; unc = [t for t in R if not t.capped]
        vol = lambda L: float(sum(float(mk[t.ticker].get("volume_fp") or 0) for t in L))
        ret = lambda L: float(sum(t.tape.size.sum() for t in L if len(t.tape)))
        pre_first = [(t.kickoff - t.first_ts) / 3600 for t in cap if t.first_ts]
        per[s] = dict(tickers=len(R), capped=len(cap), capped_raw_lines_exactly_10000=sum(t.raw_lines == 10000 for t in cap), empty=sum(len(t.tape) == 0 for t in R),
                      volume_total=vol(R), volume_retained=ret(R), volume_retained_share=round(ret(R) / max(1, vol(R)), 4),
                      capped_volume_retained_share=round(ret(cap) / max(1, vol(cap)), 4) if cap else None,
                      uncapped_volume_retained_share=round(ret(unc) / max(1, vol(unc)), 4) if unc else None,
                      capped_median_oldest_print_hours_before_kickoff=round(float(np.median(pre_first)), 2) if pre_first else None,
                      capped_share_oldest_print_AFTER_kickoff=round(float(np.mean([x < 0 for x in pre_first])), 4) if pre_first else None,
                      capped_median_volume=float(np.median([float(mk[t.ticker].get("volume_fp") or 0) for t in cap])) if cap else None,
                      uncapped_median_volume=float(np.median([float(mk[t.ticker].get("volume_fp") or 0) for t in unc])) if unc else None)
    out["truncation"] = per
    # 2) candle <-> tape consistency on complete-tape tickers
    hrs = lowm = him = volm = pre_prints = pre_missing = 0
    for t in [x for x in ticks if not x.capped and len(x.tape)]:
        H = {e: (lo, hi) for s0, e, lo, hi in t.hp}
        cd = json.load(open(os.path.join(a.backfill, "candles", t.series, t.ticker + ".json")))
        V = {int(r["end_period_ts"]): float(r["volume"]) for r in cd["h60"]}
        end = (np.floor(t.tape.ts / 3600) + 1) * 3600
        by = collections.defaultdict(list)
        for e, p, sz, x in zip(end, t.tape.yes_c, t.tape.size, t.tape.ts):
            by[int(e)].append((int(p), float(sz), x))
        for e, L in by.items():
            pre = [q for q in L if q[2] < t.kickoff]
            pre_prints += len(pre)
            if e not in H:
                pre_missing += len(pre); continue
            hrs += 1; lowm += H[e][0] == min(q[0] for q in L); him += H[e][1] == max(q[0] for q in L); volm += abs(V[e] - sum(q[1] for q in L)) < 0.5
    out["candle_vs_tape"] = dict(hourly_candles_compared=hrs, low_equals_tape_min=lowm, high_equals_tape_max=him, volume_equals_tape_sum=volm,
                                 pre_kickoff_prints=pre_prints, pre_kickoff_prints_in_hours_without_candle=pre_missing)
    # 3) candle through-evidence vs tape on tickers with a complete tape (agreement for FRONT-queue THROUGH status)
    agree = collections.Counter()
    for t in [x for x in ticks if not tape_complete(x, 0.0) is False and len(x.tape)]:
        ko = t.kickoff
        cq = quote_at(t, ko - CLOSE_MIN * 60)
        if cq is None:
            continue
        for hn, hm in ST.HORIZONS.items():
            placed = ko - hm * 60; q = quote_at(t, placed)
            if q is None:
                continue
            for side in ("YES", "NO") if t.series == "KXNFLSPREAD" else ("YES",):
                b, ask, _, _ = side_quote(q, side)
                if ask - b > ST.MAX_SPREAD:
                    continue
                for rule in ("AT_BID", "BID_PLUS_1", "ASK_MINUS_1"):
                    lim = ST.limit_price(rule, b, ask)
                    if lim is None:
                        continue
                    expiry = ko - CLOSE_MIN * 60
                    tp = replay_buy(t.tape, side, lim, ST.QTY, placed, expiry, 0.0, True)    # through-only on the tape
                    fr = replay_buy(t.tape, side, lim, ST.QTY, placed, expiry, 0.0, False)   # front of queue
                    c = CA.classify(t, side, lim, placed, expiry)
                    tape_through, tape_any = tp.filled > 0, fr.filled > 0
                    agree[(c, "tape_through" if tape_through else "tape_front_fill" if tape_any else "tape_no_fill")] += 1
    out["candle_class_vs_tape_complete_tickers"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(agree.items())}
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

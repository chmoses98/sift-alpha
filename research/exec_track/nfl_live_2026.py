#!/usr/bin/env python3
"""NFL 2026 live-capture out-of-sample check of the equal-exposure entry study, WITH displayed depth (research only; nothing is placed).
Data = extract_nfl_capture.py output (quotes / trades / books of KXNFLGAME on market-data).  Quotes are ~15-minute observations of the live book top (bid/ask + displayed sizes),
trades are the capture's de-duplicated prints.  Differences from the 2025 backfill study (nfl_study.py):
  * the AT_BID queue is the DISPLAYED size at the bid when the order is placed (scenario DISPLAYED), not an assumed 500;
  * quotes are 15-minute snapshots (not 1-minute candles), so placement/close quotes are up to 30 min old (reported);
  * no outcomes are needed: values are settlement-free close-mid marks;  orders are INDETERMINATE when the capture has a gap > 45 min inside the window.
usage: nfl_live_2026.py --ext DIR --games games.csv(optional) --out reports/exec_track/nfl_live_2026.json"""
import argparse, collections, datetime as dt, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_exec import fees as FE, study as ST            # noqa: E402
from sift_exec.fills import Tape, replay_buy              # noqa: E402
from research.exec_track import nfl_study as NS           # noqa: E402

CLOSE_MIN, MAX_AGE, MAX_GAP = 15, 30 * 60, 45 * 60
QUEUES = {"FRONT": "front", "DISPLAYED": "displayed", "THROUGH_ONLY": "through"}


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load(ext, now):
    quotes = collections.defaultdict(list); ko = {}; game = {}
    for l in open(os.path.join(ext, "quotes.jsonl")):
        if '"series_ticker":"KXNFLGAME"' not in l:
            continue
        r = json.loads(l)
        k = ts(r["kickoff_utc"])
        if k > now - 3 * 3600:                      # only games that have started (+3h): no unfinished pre-game windows
            continue
        t = r["ticker"]; ko[t] = k; game[t] = r["game_id"]
        try:
            b, a = round(float(r["yes_bid_dollars"]) * 100), round(float(r["yes_ask_dollars"]) * 100)
            bs = float(r.get("yes_bid_size_fp") or 0); az = float(r.get("yes_ask_size_fp") or 0)
        except (TypeError, ValueError):
            b = a = -1; bs = az = 0.0
        quotes[t].append((ts(r["observed_at"]), b, a, bs, az))
    for t in quotes:
        quotes[t].sort()
    tr = collections.defaultdict(list)
    for l in open(os.path.join(ext, "trades.jsonl")):
        if '"KXNFLGAME-' not in l:
            continue
        r = json.loads(l)
        t = r["ticker"]
        if t in ko:
            c = ts(r["created_time"])
            if c < ko[t]:
                tr[t].append((c, round(float(r["yes_price_dollars"]) * 100), float(r["count_fp"]), r["taker_side"] == "no"))
    tapes = {t: Tape(*zip(*sorted(v))) for t, v in tr.items() if v}
    return quotes, ko, game, tapes


def quote_at(q, when):
    """Last valid two-sided observation at/before ``when`` within MAX_AGE; returns (bid, ask, bid_size, ask_size, age) or None."""
    lo, hi = 0, len(q)
    while lo < hi:
        mid = (lo + hi) // 2
        if q[mid][0] <= when:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    t, b, a, bs, az = q[lo - 1]
    if when - t > MAX_AGE or b <= 0 or a >= 100 or a <= b:
        return None
    return b, a, bs, az, when - t


def gap_free(q, t0, t1):
    obs = [x[0] for x in q if t0 - MAX_AGE <= x[0] <= t1]
    return bool(obs) and obs[0] <= t0 + MAX_GAP and t1 - obs[-1] <= MAX_GAP and all(b - a <= MAX_GAP for a, b in zip(obs, obs[1:]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ext", required=True); ap.add_argument("--out", default="reports/exec_track/nfl_live_2026.json")
    ap.add_argument("--now", default="2026-11-04T17:00:00+00:00")
    a = ap.parse_args(argv)
    quotes, ko, game, tapes = load(a.ext, ts(a.now))
    weeks = {}
    for t, k in ko.items():
        weeks[t] = int(game[t].split("_")[1])
    rows, audit = [], collections.Counter()
    depth = collections.defaultdict(list)
    for t, q in quotes.items():
        k = ko[t]; close_t = k - CLOSE_MIN * 60
        cq = quote_at(q, close_t)
        for hn, hm in ST.HORIZONS.items():
            placed = k - hm * 60
            audit[hn, "contracts"] += 1
            pq = quote_at(q, placed)
            if pq is None or cq is None:
                audit[hn, "excl_no_valid_quote" if pq is None else "excl_no_close_quote"] += 1; continue
            b, ask, bs, az, age = pq
            if ask - b > ST.MAX_SPREAD:
                audit[hn, "excl_wide_spread"] += 1; continue
            if not gap_free(q, placed, close_t):
                audit[hn, "indeterminate_capture_gap"] += 1; continue
            audit[hn, "determinate"] += 1
            depth[hn].append(bs)
            tape = tapes.get(t) or Tape([], [], [], [])
            for rule in ST.RULES:
                lim = ST.limit_price(rule, b, ask)
                if lim is None:
                    continue
                for qn, mode in QUEUES.items():
                    qa = bs if (mode == "displayed" and lim == b) else 0.0
                    fr = replay_buy(tape, "YES", lim, ST.QTY, placed, close_t, qa, mode == "through", True)
                    rows.append(dict(game=game[t], ticker=t, family="moneyline", horizon=hn, rule=rule, queue=qn, week=weeks[t], limit=lim, bid=b, ask=ask,
                                     close_bid=cq[0], close_ask=cq[1], win=0, filled=fr.filled, filled_lo=fr.filled, filled_hi=fr.filled,
                                     fills=[(f.price_c, f.qty, f.evidence) for f in fr.fills], quote_age=age, bid_size=bs))
    out = dict(version="sift-exec-nfl-live-2026/1", status="RESEARCH_ONLY", labels=dict(fills="SIMULATED_FROM_CAPTURE_TAPE", queue="displayed bid size at placement (AT_BID) else 0", fees="taker 0.07; maker scenarios",
                                                                                         outcomes="none needed (close-mid mark)"),
               games=len({game[t] for t in quotes}), tickers=len(quotes), weeks=sorted({weeks[t] for t in quotes}), audit={f"{h}|{k}": v for (h, k), v in sorted(audit.items())},
               displayed_bid_size_at_placement={h: dict(n=len(v), p25=NS.num(np.percentile(v, 25)), median=NS.num(np.median(v)), p75=NS.num(np.percentile(v, 75)),
                                                       share_ge_500=NS.num(np.mean(np.array(v) >= 500)), share_ge_5000=NS.num(np.mean(np.array(v) >= 5000))) for h, v in depth.items() if v},
               cells={})
    groups = collections.defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["horizon"], r["rule"], r["queue"])].append(i)
    for sc, coef in FE.SCENARIOS.items():
        ev = ST.evaluate(rows, coef)
        sub = {}
        for key, ix in sorted(groups.items()):
            ix = np.array(ix); g = [rows[i]["game"] for i in ix]
            f = ev["filled"][ix]
            c = dict(n=len(ix), games=len(set(g)), fill_prob=NS.num((f > 0).mean()), partial=NS.num(((f > 0) & (f < ST.QTY - 1e-9)).mean()),
                     mark_wait_cents=NS.ci(ev["v_mark_wait"][ix], g, 61), mark_fb_minus_wait_cents=NS.ci(ev["v_mark_fb"][ix] - ev["v_mark_wait"][ix], g, 62),
                     mark_nobet_per_submitted_cents=NS.ci(ev["v_mark_nb"][ix], g, 63))
            wk = np.array([rows[i]["week"] for i in ix])
            c["by_half"] = {nm: NS.ci((ev["v_mark_fb"][ix] - ev["v_mark_wait"][ix])[m], [x for x, mm in zip(g, m) if mm], 64) for nm, m in
                            (("weeks_1_4", wk <= 4), ("weeks_5_plus", wk >= 5)) if m.sum() >= 20}
            sub["|".join(key)] = c
        out["cells"][sc] = sub
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print("games", out["games"], "tickers", out["tickers"], "weeks", out["weeks"])
    for h in ("24h", "6h", "90m"):
        print(h, out["audit"].get(f"{h}|determinate"), out["displayed_bid_size_at_placement"].get(h))
    for key in ("24h|AT_BID|DISPLAYED", "24h|AT_BID|THROUGH_ONLY", "24h|ASK_MINUS_1|DISPLAYED", "90m|AT_BID|DISPLAYED"):
        c = out["cells"]["M25"].get(key)
        if c:
            print(key, c["n"], c["games"], "fill", c["fill_prob"], "FB-WAIT", c["mark_fb_minus_wait_cents"], "NB", c["mark_nobet_per_submitted_cents"]["mean"] if c["mark_nobet_per_submitted_cents"] else None)


if __name__ == "__main__":
    main()

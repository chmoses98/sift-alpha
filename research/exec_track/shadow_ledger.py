#!/usr/bin/env python3
"""Prospective shadow-order ledger builder (RESEARCH_ONLY: no client, no keys, no order call).  Append-only JSONL via sift_research.shadow_orders (v2).

For every KXNFLGAME contract and every horizon (7d/72h/48h/24h/6h/90m before kickoff) the FIRST live quote at or after crossing the horizon becomes the decision
snapshot (placed_at = that quote's observation time, so the record is point-in-time and quote age is ~0), and the same matched decision is logged for each tactic:
  BUY_NOW, WAIT, PASS, LIMIT(rule), LIMIT_FB(rule) for rule in AT_BID, BID_PLUS_1, ASK_MINUS_2     (qty 10, deadline = last quote <= kickoff-15m)
PLACED carries bid/ask/spread/displayed sizes, the DISPLAYED QUEUE at the limit price, quote age and source run.  After the deadline: OBSERVED rows (fill evidence from the
capture tape: through-print = confirmed lower bound, any qualifying print that could fill a front-of-queue order = upper bound, displayed-queue fill estimate) and a SETTLED row
(close bid/ask = fallback / WAIT price, mid movement, settlement when the game result is known).  Nothing here is a personal order fill: every record is HYPOTHETICAL_SHADOW.
``prospective`` = recorded within PROSPECTIVE_GRACE_S of the decision snapshot; rows rebuilt later from the archive are RETROSPECTIVE_REPLAY and must not be counted as
prospective validation.  usage: shadow_ledger.py --ext EXT_DIR --ledger shadow_orders/nfl_2026.jsonl [--games games.csv] [--now ISO]"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_research import shadow_orders as SO                     # noqa: E402
from sift_exec.fills import Tape, replay_buy                       # noqa: E402

HORIZONS = {"7d": 168 * 60, "72h": 72 * 60, "48h": 48 * 60, "24h": 24 * 60, "6h": 6 * 60, "90m": 90}
RULES = ("AT_BID", "BID_PLUS_1", "ASK_MINUS_2")
QTY, CLOSE_MIN, MAX_SPREAD, PROSPECTIVE_GRACE_S, MAX_QUOTE_AGE_S = 10, 15, 10, 1800, 1800
GENERATED = "HYPOTHETICAL_SHADOW"
K2N = {"JAC": "JAX", "LAR": "LA"}


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc)


def limit_for(rule, b, a):
    if rule == "AT_BID":
        return b
    if rule == "BID_PLUS_1":
        return b + 1 if b + 1 < a else b
    p = a - 2
    return p if p >= 1 else None


def load_quotes(ext):
    q, meta = collections.defaultdict(list), {}
    for l in open(os.path.join(ext, "quotes.jsonl")):
        if '"series_ticker":"KXNFLGAME"' not in l:
            continue
        r = json.loads(l)
        try:
            b, a = round(float(r["yes_bid_dollars"]) * 100), round(float(r["yes_ask_dollars"]) * 100)
            bs, az = float(r.get("yes_bid_size_fp") or 0), float(r.get("yes_ask_size_fp") or 0)
        except (TypeError, ValueError):
            continue
        t = r["ticker"]
        meta[t] = dict(ko=ts(r["kickoff_utc"]), game_id=r["game_id"], team=t.rsplit("-", 1)[1])
        q[t].append((ts(r["observed_at"]), b, a, bs, az, r["run_id"]))
    for t in q:
        q[t].sort()
    return q, meta


def load_tapes(ext, tickers):
    raw, seen = collections.defaultdict(list), set()
    for l in open(os.path.join(ext, "trades.jsonl")):
        if '"KXNFLGAME-' not in l:
            continue
        r = json.loads(l)
        if r["trade_id"] in seen:
            continue
        seen.add(r["trade_id"])
        if r["ticker"] in tickers:
            raw[r["ticker"]].append((ts(r["created_time"]), round(float(r["yes_price_dollars"]) * 100), float(r["count_fp"]), r["taker_side"] == "no"))
    return {t: Tape(*zip(*sorted(v))) for t, v in raw.items()}


def results(games_csv):
    res = {}
    for r in csv.DictReader(open(games_csv)):
        if r["season"] == "2026" and r["home_score"] != "":
            h, a = float(r["home_score"]), float(r["away_score"])
            res[r["game_id"]] = (r["home_team"] if h > a else r["away_team"] if a > h else None)
    return res


def decisions_for(t, q, m, now):
    """Yield (horizon, snapshot) for the first valid two-sided quote at/after each horizon crossing (point-in-time)."""
    ko = m["ko"]
    for hn, hm in HORIZONS.items():
        cross = ko - hm * 60
        if cross > now:
            continue
        for (o, b, a, bs, az, run) in q:
            if o >= cross and o < ko - CLOSE_MIN * 60 and 0 < b < a < 100:
                if o - cross <= MAX_QUOTE_AGE_S and a - b <= MAX_SPREAD:
                    yield hn, (o, b, a, bs, az, run)
                break


def close_quote(q, ko):
    last = None
    for (o, b, a, bs, az, run) in q:
        if o <= ko - CLOSE_MIN * 60:
            last = (o, b, a, bs, az, run)
        else:
            break
    if last and 0 < last[1] < last[2] < 100 and ko - CLOSE_MIN * 60 - last[0] <= MAX_QUOTE_AGE_S:
        return last
    return None


def build(ext, ledger, games_csv=None, now=None, recorded_at=None):
    now = now or dt.datetime.now(dt.timezone.utc).timestamp()
    recorded_at = recorded_at or now
    quotes, meta = load_quotes(ext)
    have = set()
    if os.path.exists(ledger):
        for l in open(ledger):
            r = json.loads(l)
            if r["kind"] == "PLACED":
                have.add(r["decision_id"])
    LG = SO.Ledger(ledger)
    tapes = load_tapes(ext, set(quotes))
    res = results(games_csv) if games_csv else {}
    n = collections.Counter()
    for t, q in quotes.items():
        m = meta[t]; ko = m["ko"]
        if ko - CLOSE_MIN * 60 - now > 0 and False:
            continue
        cq = close_quote(q, ko) if now > ko - CLOSE_MIN * 60 else None
        for hn, (o, b, a, bs, az, run) in decisions_for(t, q, m, now):
            placed_at = iso(o); kickoff = iso(ko)
            prospective = (recorded_at - o) <= PROSPECTIVE_GRACE_S
            common = dict(ticker=t, side="YES", placed_at=placed_at, kickoff=kickoff, bid=b / 100, ask=a / 100, bid_size=bs, ask_size=az, p=(a + b) / 200.0, p_se=0.0,
                          model_version="MARKET_MID_BENCHMARK", qty=QTY)
            specs = [("BUY_NOW", None, "NONE", f"{hn}"), ("WAIT", None, "NONE", f"{hn}"), ("PASS", None, "NONE", f"{hn}")]
            for rule in RULES:
                lim = limit_for(rule, b, a)
                if lim is not None:
                    specs.append(("LIMIT", lim, "NONE", f"{hn}|{rule}")); specs.append(("LIMIT", lim, "TAKE_AT_CLOSE", f"{hn}|{rule}|FB"))
            for action, lim, fb, tag in specs:
                rec = SO.placed(action=action, limit=None if lim is None else lim / 100, horizon=tag, fallback=fb, **common)
                rec.update(generated=GENERATED, prospective=bool(prospective), generation="PROSPECTIVE" if prospective else "RETROSPECTIVE_REPLAY",
                           recorded_at=iso(recorded_at).isoformat(), spread_c=a - b, quote_age_s=0, source_run_id=run, game_id=m["game_id"], horizon_name=hn,
                           displayed_queue_at_limit=(bs if (lim is not None and lim == b) else 0.0 if lim is not None else None), deadline=iso(ko - CLOSE_MIN * 60).isoformat())
                rec["decision_id"] = SO.decision_id(rec)
                if rec["decision_id"] in have:
                    continue
                LG.append(rec); have.add(rec["decision_id"]); n["placed"] += 1
                if cq is None:
                    continue
                dl = ko - CLOSE_MIN * 60
                if action == "LIMIT":
                    tape = tapes.get(t) or Tape([], [], [], [])
                    thr = replay_buy(tape, "YES", lim, QTY, o, dl, 0.0, True, True)            # confirmed: print strictly through our price (queue-independent)
                    ftq = replay_buy(tape, "YES", lim, QTY, o, dl, 0.0, False, True)            # possible: front-of-queue
                    dq = replay_buy(tape, "YES", lim, QTY, o, dl, rec["displayed_queue_at_limit"] or 0.0, False, True)   # central: behind the displayed queue
                    if thr.filled > 0:
                        LG.append(SO.observed(rec, evidence="TAPE_FILL_BOUND_LO", observed_at=iso(thr.first_ts), price=lim / 100, size=thr.filled)); n["lo"] += 1
                    if ftq.filled > 0:
                        LG.append(SO.observed(rec, evidence="TAPE_FILL_BOUND_UP", observed_at=iso(ftq.first_ts), price=lim / 100, size=ftq.filled)); n["up"] += 1
                    if dq.filled > thr.filled:                               # displayed-queue estimate recorded as a TOUCH-class note, never as a fill
                        LG.append(SO.observed(rec, evidence="TAPE_TOUCH", observed_at=iso(dq.first_ts), price=lim / 100, size=dq.filled, queue_ahead_assumed=rec["displayed_queue_at_limit"])); n["central"] += 1
                win = None
                if m["game_id"] in res and res[m["game_id"]] is not None:
                    win = int(K2N.get(m["team"], m["team"]) == res[m["game_id"]])
                st = SO.settled(rec, win=win if win is not None else 0, settled_at=iso(max(now, ko)), close_bid=cq[1] / 100, close_ask=cq[2] / 100)
                st.update(win_known=win is not None, close_quote_at=iso(cq[0]).isoformat(), mid_move_to_close_c=(cq[1] + cq[2]) / 2 - (a + b) / 2)
                if win is None:
                    st["win"] = None
                LG.append(st); n["settled"] += 1
    LG.close()
    return dict(n)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ext", required=True); ap.add_argument("--ledger", required=True); ap.add_argument("--games"); ap.add_argument("--now")
    a = ap.parse_args(argv)
    os.makedirs(os.path.dirname(os.path.abspath(a.ledger)), exist_ok=True)
    print(json.dumps(build(a.ext, a.ledger, a.games, ts(a.now) if a.now else None)))


if __name__ == "__main__":
    main()

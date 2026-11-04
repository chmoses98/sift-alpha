#!/usr/bin/env python3
"""Workstream B, NFL 2025: early limit-order intelligence (research only, nothing is placed).  version ``sift-nfl-exec/1``.

Evidence labels
  * every fill is SIMULATED_FROM_TAPE (public trade prints).  It is never an observed fill and a price touch is not a fill.
  * fees are MODELLED (sift_research.fees; taker 0.07 / maker 0.0175 -- the maker rate is an assumption).
  * the archive has NO depth/queue data and the tape is capped at the newest 10,000 prints per ticker, so:
      - queue position is a scenario (FRONT, Q500, Q5000, THROUGH_ONLY), never an observation;
      - an order whose window starts before the oldest retained print is UNCERTAIN and excluded from fill statistics.
Prices are handled in integer cents.  Outcomes (results, scores) are used only to score, never to place orders.
"""
from __future__ import annotations
import argparse, bisect, glob, json, math, os, sys, datetime as dt
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_research import nfl25 as N                                    # noqa: E402
from sift_research import fees as F                                     # noqa: E402
from sift_research import stats as S                                    # noqa: E402

VERSION = "sift-nfl-exec/1"
HORIZONS = {"7d": 168 * 60, "72h": 72 * 60, "48h": 48 * 60, "24h": 24 * 60, "6h": 6 * 60, "90m": 90}   # minutes before kickoff
RULES = ["AT_BID", "BID_PLUS_1", "MID"] + [f"ASK_MINUS_{k}" for k in range(1, 6)]
QUEUES = {"FRONT": ("q", 0), "Q500": ("q", 500), "Q5000": ("q", 5000), "THROUGH_ONLY": ("through", None)}
QTY = 10
TAPE_CAP = 10000
CLOSE_MIN = 15            # closing quote = last quote at or before kickoff - 15 min
MAX_SPREAD = 10           # cents; wider placement quotes are excluded (counted)
SPLITS = {"discovery": (1, 6), "validation": (7, 12), "holdout": (13, 99)}
N_BOOT = 1000
MIN_ORDERS = 30


# ----------------------------------------------------------------------------- data
class Tick:
    __slots__ = ("ticker", "series", "event", "game", "outcome", "h_end", "h_bid", "h_ask", "m_end", "m_bid", "m_ask",
                 "ts", "yes_c", "size", "taker_no", "capped", "first_ts", "n_trades")


def _c(x):
    return None if x is None else int(round(float(x) * 100))


def _candles(rows):
    end, bid, ask = [], [], []
    for r in rows or []:
        b, a = _c((r.get("yes_bid") or {}).get("close")), _c((r.get("yes_ask") or {}).get("close"))
        end.append(int(r["end_period_ts"])); bid.append(-1 if b is None else b); ask.append(-1 if a is None else a)
    return np.array(end, dtype=np.int64), np.array(bid, dtype=np.int16), np.array(ask, dtype=np.int16)


def load_tick(series, m, idx, root):
    ev = m["event_ticker"]
    game = N.resolve_event(ev, idx)
    out = N.outcome_yes(m)
    if game is None or out is None:
        return None
    t = Tick()
    t.ticker, t.series, t.event, t.game, t.outcome = m["ticker"], series, ev, game, out
    cd = N.load_candles(series, m["ticker"], root)
    if not cd:
        return None
    t.h_end, t.h_bid, t.h_ask = _candles(cd.get("h60"))
    t.m_end, t.m_bid, t.m_ask = _candles(cd.get("m1"))
    p = os.path.join(root, "trades", series, m["ticker"] + ".jsonl")
    ts, yc, sz, tn = [], [], [], []
    raw = 0
    if os.path.exists(p):
        seen = set()
        for l in open(p):
            raw += 1
            r = json.loads(l)
            if r["trade_id"] in seen or r.get("is_block_trade"):
                continue
            seen.add(r["trade_id"])
            ts.append(dt.datetime.fromisoformat(r["created_time"].replace("Z", "+00:00")).timestamp())
            yc.append(_c(r["yes_price_dollars"])); sz.append(float(r["count_fp"])); tn.append(r["taker_side"] == "no")
    o = np.argsort(np.array(ts)) if ts else np.array([], dtype=int)
    t.ts = np.array(ts)[o] if ts else np.array([]); t.yes_c = np.array(yc, dtype=np.int16)[o] if ts else np.array([], dtype=np.int16)
    t.size = np.array(sz)[o] if ts else np.array([]); t.taker_no = np.array(tn, dtype=bool)[o] if ts else np.array([], dtype=bool)
    t.capped = raw >= TAPE_CAP
    t.first_ts = float(t.ts[0]) if len(t.ts) else None
    t.n_trades = len(t.ts)
    return t


def quote_at(t: Tick, when: float):
    """Last two-sided YES quote (bid_c, ask_c) at or before ``when`` (epoch s) + age (s) + source; None if none/invalid."""
    best = None
    for end, bid, ask, src, maxage in ((t.m_end, t.m_bid, t.m_ask, "m1", 180), (t.h_end, t.h_bid, t.h_ask, "h60", 10 ** 9)):
        if len(end) == 0:
            continue
        i = int(np.searchsorted(end, when, side="right")) - 1
        if i < 0:
            continue
        age = when - float(end[i])
        if age > maxage:
            continue
        best = (int(bid[i]), int(ask[i]), age, src)
        break
    if best is None:
        return None
    b, a, age, src = best
    if b <= 0 or a >= 100 or a <= b:
        return None                         # one-sided / empty / crossed: never a quote
    return b, a, age, src


def side_quote(q, side):
    b, a, age, src = q
    return (b, a, age, src) if side == "YES" else (100 - a, 100 - b, age, src)


def limit_cents(rule, b, a):
    if rule == "AT_BID":
        return b
    if rule == "BID_PLUS_1":
        return b + 1 if b + 1 < a else b
    if rule == "MID":
        m = (a + b) // 2
        return m if b < m < a else b
    k = int(rule.rsplit("_", 1)[1])
    p = a - k
    return p if p >= 1 else None


# ----------------------------------------------------------------------------- fill simulation (vectorised, cents)
def sim_fill(ts, side_c, size, qual, placed, end, limit, qty, queue):
    """Fill of a resting BUY at ``limit`` (side cents) over the open interval (placed, end).
    queue = ("q", Q): back of a queue of Q contracts at our level (Q=0 front); ("through", None): only strictly-through prints fill.
    Returns (filled, first_fill_ts or None).  Mirrors sift_clv.limit_orders.simulate_limit_buy (tested)."""
    i0, i1 = int(np.searchsorted(ts, placed, "right")), int(np.searchsorted(ts, end, "left"))
    if i1 <= i0:
        return 0.0, None
    sc, qa, sz, tt = side_c[i0:i1], qual[i0:i1], size[i0:i1], ts[i0:i1]
    thr = qa & (sc < limit)
    at = qa & (sc == limit)
    jt = int(np.argmax(thr)) if thr.any() else None
    kind, Q = queue
    if kind == "through":
        return (float(qty), float(tt[jt])) if jt is not None else (0.0, None)
    if jt is not None:
        at_before = at.copy(); at_before[jt:] = False
    else:
        at_before = at
    cum = np.cumsum(np.where(at_before, sz, 0.0))
    filled_at = max(0.0, (cum[-1] if len(cum) else 0.0) - Q)
    first = None
    if len(cum) and cum[-1] > Q:
        first = float(tt[int(np.searchsorted(cum, Q, side="right"))]) if Q > 0 else float(tt[int(np.argmax(at_before))])
    if jt is not None:
        ft = float(tt[jt])
        first = ft if first is None else min(first, ft)
        return float(qty), first
    return float(min(qty, filled_at)), first


# ----------------------------------------------------------------------------- order construction
def week_split(week):
    for k, (lo, hi) in SPLITS.items():
        if lo <= week <= hi:
            return k
    return None


MAKER_TAB = {(p, n): float(F.fee_dollars(p / 100, n, "maker")) for p in range(1, 100) for n in range(0, QTY + 1)}
TAKER_TAB = {(p, n): float(F.fee_dollars(p / 100, n, "taker")) for p in range(1, 100) for n in range(0, QTY + 1)}


def build(ticks, horizons=HORIZONS, queues=QUEUES, rules=RULES, sides_for=None, cross_check=None):
    """Returns (rows, audit).  One row per (order, queue) for the rest-to-kickoff variant V0 plus the V1 repost-or-cross fields."""
    rows, audit = [], defaultdict(int)
    for t in ticks:
        fam = "moneyline" if t.series == "KXNFLGAME" else "spread"
        sides = ("YES",) if fam == "moneyline" else ("YES", "NO")
        ko = t.game["kickoff"].timestamp()
        for side in sides:
            win = t.outcome if side == "YES" else 1 - t.outcome
            qual = t.taker_no if side == "YES" else ~t.taker_no
            side_c = t.yes_c if side == "YES" else (100 - t.yes_c)
            cq = quote_at(t, ko - CLOSE_MIN * 60)
            c90 = quote_at(t, ko - 90 * 60)
            for hn, hm in horizons.items():
                placed = ko - hm * 60
                q = quote_at(t, placed)
                audit[fam, hn, "contracts"] += 1
                if q is None:
                    audit[fam, hn, "no_valid_quote"] += 1; continue
                if cq is None:
                    audit[fam, hn, "no_close_quote"] += 1; continue
                b, a, age, src = side_quote(q, side)
                if a - b > MAX_SPREAD:
                    audit[fam, hn, "wide_spread_excluded"] += 1; continue
                cb, ca, _, _ = side_quote(cq, side)
                complete = (not t.capped) or (t.first_ts is not None and t.first_ts <= placed)
                audit[fam, hn, "tape_complete" if complete else "tape_uncertain"] += 1
                mid = (a + b) / 2; cmid = (ca + cb) / 2
                x90 = side_quote(c90, side) if (c90 and hm > 90) else None
                for rule in rules:
                    lim = limit_cents(rule, b, a)
                    if lim is None:
                        continue
                    for qn, qspec in queues.items():
                        f0, ft0 = sim_fill(t.ts, side_c, t.size, qual, placed, ko, lim, QTY, qspec)
                        if x90 is not None:
                            f1, ft1 = sim_fill(t.ts, side_c, t.size, qual, placed, ko - 90 * 60, lim, QTY, qspec)
                        else:
                            f1, ft1 = None, None
                        rows.append(dict(
                            game_id=t.game["game_id"], ticker=t.ticker, family=fam, side=side, horizon=hn, rule=rule, limit=lim,
                            placed_at=dt.datetime.fromtimestamp(placed, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            bid=b, ask=a, mid=mid, quote_age_s=int(age), quote_src=src, close_bid=cb, close_ask=ca, close_mid=cmid,
                            ask90=None if x90 is None else x90[1],
                            fill_status=("FILLED" if f0 >= QTY else "PARTIAL" if f0 > 0 else ("UNFILLED" if complete else "UNCERTAIN")),
                            filled=f0, fill_ts=ft0, filled_v1=f1, win=win,
                            kickoff=dt.datetime.fromtimestamp(ko, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            week=t.game["week"], split=week_split(t.game["week"]), queue_assumption=qn, tape_complete=complete,
                            label="SIMULATED_FROM_TAPE"))
    return rows, dict(audit)


# ----------------------------------------------------------------------------- economics per row
def order_pnl(r, variant):
    """Net P&L per SUBMITTED contract (dollars), capital per submitted contract, and filled fraction. Fees MODELLED."""
    p = r["limit"]
    win = r["win"]
    if variant == "V0":
        f = r["filled"]
        if f <= 0:
            return 0.0, 0.0, 0.0
        fee = MAKER_TAB[(p, int(round(f)))]
        return (f * (win - p / 100) - fee) / QTY, f * p / 100 / QTY, f / QTY
    f = r["filled_v1"]
    if f is None:
        return None
    nf = int(round(f))
    fee = MAKER_TAB[(p, nf)] if nf else 0.0
    rem = QTY - nf
    a = r["ask90"]
    pnl = nf * (win - p / 100) - fee + (rem * (win - a / 100) - TAKER_TAB[(a, rem)] if rem else 0.0)
    cap = nf * p / 100 + rem * a / 100
    return pnl / QTY, cap / QTY, f / QTY


def taker_pnl(win, price_c):
    """Net P&L per contract of taking ``price_c`` and holding to settlement; fee = ceil-to-cent on a QTY-contract order, per contract."""
    return win - price_c / 100 - TAKER_TAB[(price_c, QTY)] / QTY


# ----------------------------------------------------------------------------- aggregation
def _num(x):
    if x is None:
        return None
    x = float(x)
    return None if (math.isnan(x) or math.isinf(x)) else round(x, 6)


def _ci(vals, clus, seed=7):
    r = S.cluster_bootstrap(vals, clus, n_boot=N_BOOT, seed=seed)
    return dict(mean=_num(r["mean"]), lo=_num(r["lo"]), hi=_num(r["hi"]), p=_num(r["p"]), n=r["n"], n_clusters=r["n_clusters"])


def diff_ci(a, ca, b, cb, seed=11):
    """Cluster-bootstrap CI of mean(a) - mean(b) with independent resampling of the games in each group."""
    if len(a) < 5 or len(b) < 5:
        return None
    sa, na = S._group(a, ca); sb, nb = S._group(b, cb)
    rng = np.random.default_rng(seed)
    ia = rng.integers(0, len(sa), (N_BOOT, len(sa))); ib = rng.integers(0, len(sb), (N_BOOT, len(sb)))
    d = sa[ia].sum(1) / na[ia].sum(1) - sb[ib].sum(1) / nb[ib].sum(1)
    est = sa.sum() / na.sum() - sb.sum() / nb.sum()
    return dict(diff=_num(est), lo=_num(np.quantile(d, .025)), hi=_num(np.quantile(d, .975)))


def cell_stats(rs, variant):
    """rs: rows of ONE (family,horizon,rule,queue[,split]) cell, determinate (tape complete)."""
    vals = [order_pnl(r, variant) for r in rs]
    keep = [(r, v) for r, v in zip(rs, vals) if v is not None]
    if len(keep) < 1:
        return None
    rs = [k[0] for k in keep]
    pnl = np.array([k[1][0] for k in keep]); cap = np.array([k[1][1] for k in keep]); fr = np.array([k[1][2] for k in keep])
    cl = [r["game_id"] for r in rs]
    win = np.array([r["win"] for r in rs], float)
    tk_now = np.array([taker_pnl(r["win"], r["ask"]) for r in rs])
    tk_close = np.array([taker_pnl(r["win"], r["close_ask"]) for r in rs])
    filled = fr > 0
    lim = np.array([r["limit"] for r in rs], float)
    ask = np.array([r["ask"] for r in rs], float); cask = np.array([r["close_ask"] for r in rs], float)
    cmid = np.array([r["close_mid"] for r in rs], float); mid = np.array([r["mid"] for r in rs], float)
    d_now, d_close = pnl - tk_now, pnl - tk_close
    out = dict(n_orders=len(rs), n_games=len(set(cl)), fill_prob=_num(filled.mean()), full_fill_share=_num((fr >= 0.999).mean()),
               partial_fill_share=_num(((fr > 0) & (fr < 0.999)).mean()), mean_filled_fraction=_num(fr.mean()))
    out["profit_per_submitted_contract"] = _ci(pnl, cl)
    out["delta_vs_taker_now"] = _ci(d_now, cl, 8)
    out["delta_vs_wait_and_take_close"] = _ci(d_close, cl, 9)
    out["roi_on_capital"] = _num(pnl.sum() / cap.sum()) if cap.sum() > 0 else None
    if filled.any():
        cf = [c for c, f in zip(cl, filled) if f]
        fw = fr[filled]
        out["profit_per_filled_contract"] = _num((pnl[filled] * 1.0).sum() / fr[filled].sum())
        out["price_improvement_vs_ask_at_placement_cents"] = _num(((ask - lim)[filled]).mean())
        out["price_improvement_vs_close_ask_cents"] = _num(((cask - lim)[filled]).mean())
        out["clv_vs_close_mid_cents"] = _num(((cmid - lim)[filled]).mean())
        out["mid_drift_to_close_filled_cents"] = _num(((cmid - mid)[filled]).mean())
    if (~filled).any():
        out["mid_drift_to_close_unfilled_cents"] = _num(((cmid - mid)[~filled]).mean())
    # adverse selection: would TAKING at placement have done worse on the contracts that fill?
    out["adverse_selection"] = dict(
        taker_now_pnl_filled=_ci(tk_now[filled], [c for c, f in zip(cl, filled) if f], 12) if filled.sum() >= 5 else None,
        taker_now_pnl_unfilled=_ci(tk_now[~filled], [c for c, f in zip(cl, filled) if not f], 13) if (~filled).sum() >= 5 else None,
        diff_filled_minus_unfilled=diff_ci(tk_now[filled], [c for c, f in zip(cl, filled) if f], tk_now[~filled], [c for c, f in zip(cl, filled) if not f]),
        win_rate_filled=_num(win[filled].mean()) if filled.any() else None, win_rate_unfilled=_num(win[~filled].mean()) if (~filled).any() else None,
        mean_mid_at_placement_filled=_num(mid[filled].mean() / 100) if filled.any() else None,
        share_fills_when_mid_fell_3c_plus=_num((((cmid - mid) <= -3)[filled]).mean()) if filled.any() else None,
        share_orders_when_mid_fell_3c_plus=_num(((cmid - mid) <= -3).mean()))
    return out


def group(rows, keys):
    g = defaultdict(list)
    for r in rows:
        g[tuple(r[k] for k in keys)].append(r)
    return g


def taker_tables(ticks, horizons=HORIZONS):
    """Entry comparison for TAKER buys at each horizon (population = every valid contract-side; no model signal)."""
    recs = []
    for t in ticks:
        fam = "moneyline" if t.series == "KXNFLGAME" else "spread"
        ko = t.game["kickoff"].timestamp()
        cq = quote_at(t, ko - CLOSE_MIN * 60)
        if cq is None:
            continue
        for side in (("YES",) if fam == "moneyline" else ("YES", "NO")):
            win = t.outcome if side == "YES" else 1 - t.outcome
            cb, ca, _, _ = side_quote(cq, side)
            hq = {}
            for hn, hm in horizons.items():
                q = quote_at(t, ko - hm * 60)
                if q is None:
                    continue
                b, a, age, src = side_quote(q, side)
                # cross-check with tape: last print within 60 min before placement vs this quote's mid
                tape_gap = None
                if len(t.ts):
                    i = int(np.searchsorted(t.ts, ko - hm * 60, "right")) - 1
                    if i >= 0 and ko - hm * 60 - t.ts[i] <= 3600:
                        sc = int(t.yes_c[i]) if side == "YES" else 100 - int(t.yes_c[i])
                        tape_gap = sc - (a + b) / 2
                hq[hn] = (b, a, age, tape_gap)
            for hn, (b, a, age, tg) in hq.items():
                recs.append(dict(game_id=t.game["game_id"], family=fam, horizon=hn, week=t.game["week"], split=week_split(t.game["week"]),
                                 win=win, ask=a, bid=b, mid=(a + b) / 2, spread=a - b, close_ask=ca, close_mid=(ca + cb) / 2, age=age, tape_gap=tg,
                                 common=len(hq) == len(horizons)))
    return recs


BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]


def taker_summary(recs):
    out = {}
    for (fam, hn), rs in sorted(group(recs, ["family", "horizon"]).items()):
        entry = {}
        for scope, sel in (("all_valid", rs), ("common_support", [r for r in rs if r["common"]]),
                           ("tight_spread_le_10c", [r for r in rs if r["spread"] <= MAX_SPREAD])):
            if not sel:
                continue
            cl = [r["game_id"] for r in sel]
            ask = np.array([r["ask"] for r in sel], float); cask = np.array([r["close_ask"] for r in sel], float)
            cmid = np.array([r["close_mid"] for r in sel], float); mid = np.array([r["mid"] for r in sel], float)
            now = np.array([taker_pnl(r["win"], r["ask"]) for r in sel]); close = np.array([taker_pnl(r["win"], r["close_ask"]) for r in sel])
            e = dict(n=len(sel), n_games=len(set(cl)),
                     taker_net_pnl_per_contract=_ci(now, cl), wait_and_take_close_net_pnl=_ci(close, cl, 8),
                     price_improvement_early_ask_vs_close_ask_cents=_ci(cask - ask, cl, 9),
                     clv_vs_close_mid_cents=_ci(cmid - ask, cl, 10), mid_move_to_close_cents=_ci(cmid - mid, cl, 11),
                     early_taker_minus_wait_take_net_pnl=_ci(now - close, cl, 12),
                     median_quote_age_s=_num(np.median([r["age"] for r in sel])),
                     median_spread_cents=_num(np.median([r["spread"] for r in sel])))
            tg = [r["tape_gap"] for r in sel if r["tape_gap"] is not None]
            e["tape_vs_quote_mid_gap_cents"] = dict(n=len(tg), median_abs=_num(np.median(np.abs(tg))) if tg else None)
            entry[scope] = e
        out[f"{fam}|{hn}"] = entry
    by_bucket, by_split = {}, {}
    for (fam, hn, bk), rs in sorted(group([dict(r, bucket=next(f"{lo}-{hi}c" for lo, hi in BUCKETS if lo <= r["ask"] < hi or (hi == 100 and r["ask"] == 100))) for r in recs if r["spread"] <= MAX_SPREAD],
                                      ["family", "horizon", "bucket"]).items()):
        if len(rs) < MIN_ORDERS:
            continue
        cl = [r["game_id"] for r in rs]
        now = np.array([taker_pnl(r["win"], r["ask"]) for r in rs]); close = np.array([taker_pnl(r["win"], r["close_ask"]) for r in rs])
        by_bucket[f"{fam}|{hn}|ask {bk}"] = dict(n=len(rs), n_games=len(set(cl)), taker_net_pnl=_ci(now, cl), wait_take_close_net_pnl=_ci(close, cl, 8),
                                                 early_minus_wait=_ci(now - close, cl, 12), price_improvement_vs_close_ask_cents=_ci(np.array([r["close_ask"] - r["ask"] for r in rs], float), cl, 9))
    for (fam, hn, sp), rs in sorted(group([r for r in recs if r["spread"] <= MAX_SPREAD and r["split"]], ["family", "horizon", "split"]).items()):
        if len(rs) < MIN_ORDERS:
            continue
        cl = [r["game_id"] for r in rs]
        now = np.array([taker_pnl(r["win"], r["ask"]) for r in rs]); close = np.array([taker_pnl(r["win"], r["close_ask"]) for r in rs])
        by_split[f"{fam}|{hn}|{sp}"] = dict(n=len(rs), early_minus_wait=_ci(now - close, cl, 12), price_improvement_vs_close_ask_cents=_ci(np.array([r["close_ask"] - r["ask"] for r in rs], float), cl, 9))
    return dict(by_family_horizon=out, by_price_bucket=by_bucket, by_chronological_split=by_split)


# ----------------------------------------------------------------------------- coverage audit
def coverage_audit(ticks_all, idx, root):
    out = {}
    for s in ("KXNFLGAME", "KXNFLSPREAD"):
        tl = [t for t in ticks_all if t.series == s]
        if not tl:
            continue
        e = dict(tickers_with_game_candles_result=len(tl), games=len({t.game["game_id"] for t in tl}),
                 tape_capped_at_10000=sum(t.capped for t in tl), tape_empty=sum(t.n_trades == 0 for t in tl),
                 m1_candles_present=sum(len(t.m_end) > 0 for t in tl), depth_data="NONE (no book snapshots in this archive)",
                 fee_data="NONE in archive: fees MODELLED by sift_research.fees (taker 0.07, maker 0.0175 assumed)",
                 queue_data="NONE: queue position is a scenario")
        for hn, hm in HORIZONS.items():
            cov = h2 = qv = 0
            for t in tl:
                ko = t.game["kickoff"].timestamp(); placed = ko - hm * 60
                if (not t.capped) or (t.first_ts is not None and t.first_ts <= placed):
                    cov += 1
                if quote_at(t, placed) is not None:
                    qv += 1
                if len(t.h_end) and t.h_end[0] <= placed:
                    h2 += 1
            e[f"tape_covers_placement_to_kickoff_{hn}"] = cov
            e[f"valid_two_sided_quote_{hn}"] = qv
            e[f"hourly_candle_history_reaches_{hn}"] = h2
        # gaps in the tape inside the final 48h (minutes without prints > 180 min while market active)
        gaps = 0
        for t in tl:
            ko = t.game["kickoff"].timestamp()
            w = t.ts[(t.ts > ko - 48 * 3600) & (t.ts < ko)]
            if len(w) > 1 and np.max(np.diff(w)) > 180 * 60:
                gaps += 1
        e["tickers_with_gap_over_180min_in_final_48h"] = gaps
        e["tickers_with_zero_prints_in_final_48h"] = sum(1 for t in tl if not ((t.ts > t.game["kickoff"].timestamp() - 48 * 3600) & (t.ts < t.game["kickoff"].timestamp())).any())
        out[s] = e
    return out


# ----------------------------------------------------------------------------- chronological selection
def selection(rows):
    res = {}
    for fam in ("moneyline", "spread"):
        for qn in ("Q500", "FRONT"):
            sel = [r for r in rows if r["family"] == fam and r["queue_assumption"] == qn and r["tape_complete"] and r["split"]]
            cells = {}
            for (hn, rule), rs in group(sel, ["horizon", "rule"]).items():
                per = {}
                for sp in SPLITS:
                    x = [r for r in rs if r["split"] == sp]
                    if len(x) < MIN_ORDERS:
                        continue
                    pn = np.array([order_pnl(r, "V0")[0] - taker_pnl(r["win"], r["close_ask"]) for r in x])
                    per[sp] = (pn, [r["game_id"] for r in x], x)
                cells[(hn, rule)] = per
            disc = sorted(((np.mean(v["discovery"][0]), k) for k, v in cells.items() if "discovery" in v), reverse=True)
            tried = len(disc)
            entry = dict(cells_tried=tried, criterion="delta_vs_wait_and_take_close, profit per submitted contract (V0, unfilled=0), $",
                         discovery_top5=[dict(horizon=k[0], rule=k[1], mean=_num(m)) for m, k in disc[:5]])
            # validation: BH/Holm over all cells with discovery+validation data
            vk = [k for k, v in cells.items() if "validation" in v]
            vp = [S.cluster_bootstrap(cells[k]["validation"][0], cells[k]["validation"][1], N_BOOT, 21)["p"] for k in vk]
            bh = S.benjamini_hochberg(vp) if vp else []; hm_ = S.holm(vp) if vp else []
            vmap = {k: (p, b, h) for k, p, b, h in zip(vk, vp, bh, hm_)}
            hp = [S.cluster_bootstrap(cells[k]["holdout"][0], cells[k]["holdout"][1], N_BOOT, 22)["p"] for k in cells if "holdout" in cells[k]]
            hk = [k for k in cells if "holdout" in cells[k]]
            hbh = dict(zip(hk, S.benjamini_hochberg(hp))) if hp else {}
            entry["validation_cells_with_bh_q_below_0.10"] = int(sum(1 for k in vmap if vmap[k][1] < 0.10))
            entry["validation_cells_with_holm_p_below_0.05"] = int(sum(1 for k in vmap if vmap[k][2] < 0.05))
            entry["holdout_cells_with_bh_q_below_0.10_exploratory"] = int(sum(1 for k in hbh if hbh[k] < 0.10))
            if disc:
                top = disc[0][1]
                ev = {}
                for sp in ("discovery", "validation", "holdout"):
                    if sp in cells[top]:
                        pn, cl, x = cells[top][sp]
                        ev[sp] = _ci(pn, cl, 30)
                        ev[sp]["fill_prob"] = _num(np.mean([r["filled"] > 0 for r in x]))
                if top in vmap:
                    ev["validation_bh_q"] = _num(vmap[top][1]); ev["validation_holm_p"] = _num(vmap[top][2])
                entry["frozen_choice_from_discovery"] = dict(horizon=top[0], rule=top[1], evaluation=ev,
                                                              confirmed_on_validation=bool(top in vmap and ev.get("validation", {}).get("mean", -1) > 0 and vmap[top][1] < 0.10),
                                                              holdout_mean_positive=bool(ev.get("holdout", {}).get("mean") is not None and ev["holdout"]["mean"] > 0),
                                                              holdout_ci_excludes_zero=bool(ev.get("holdout") and ev["holdout"]["lo"] is not None and ev["holdout"]["lo"] > 0))
            res[f"{fam}|{qn}"] = entry
    return res


def aggregate(rows):
    cells = {}
    det = [r for r in rows if r["tape_complete"]]
    for variant in ("V0", "V1"):
        for (fam, hn, rule, qn), rs in sorted(group(det, ["family", "horizon", "rule", "queue_assumption"]).items()):
            if variant == "V1" and (hn == "90m" or rs[0]["ask90"] is None):
                continue
            if variant == "V1":
                rs = [r for r in rs if r["filled_v1"] is not None]
            for sp in ("all",) + tuple(SPLITS):
                x = rs if sp == "all" else [r for r in rs if r["split"] == sp]
                if len(x) < MIN_ORDERS:
                    continue
                c = cell_stats(x, variant)
                if c:
                    cells[f"{variant}|{fam}|{hn}|{rule}|{qn}|{sp}"] = c
    return cells


def write_orders(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(dict(r, fill_status_up=r["fill_status"] if r["queue_assumption"] == "FRONT" else None,
                                    fill_price=r["limit"] / 100 if r["filled"] > 0 else None,
                                    fee=MAKER_TAB[(r["limit"], int(round(r["filled"])))] if r["filled"] > 0 else 0.0,
                                    price_at_placement=dict(bid=r["bid"], ask=r["ask"], mid=r["mid"])), separators=(",", ":")) + "\n")


def crosscheck(ticks, rows_sample=200, seed=3):
    """Compare the vectorised simulator with sift_clv.limit_orders.simulate_limit_buy on random orders."""
    from decimal import Decimal
    from sift_clv import limit_orders as LO
    rng = np.random.default_rng(seed)
    agree = total = 0
    cand = [t for t in ticks if t.n_trades > 20 and len(t.ts) and t.series == "KXNFLGAME"]
    for _ in range(rows_sample):
        t = cand[int(rng.integers(len(cand)))]
        ko = t.game["kickoff"].timestamp()
        i = int(rng.integers(len(t.ts))); placed = float(t.ts[i]) - 1
        lim = int(np.clip(t.yes_c[i] + rng.integers(-3, 4), 1, 99)); Q = float(rng.choice([0, 500, 5000]))
        end = float(t.ts[-1]) + 1
        trades = [LO.Trade.of(dt.datetime.fromtimestamp(float(a), dt.timezone.utc), Decimal(int(b)) / 100, Decimal(float(c)), "no" if d else "yes", str(k))
                  for k, (a, b, c, d) in enumerate(zip(t.ts, t.yes_c, t.size, t.taker_no))]
        o = LO.simulate_limit_buy(side="YES", limit=Decimal(lim) / 100, qty=QTY, placed_at=dt.datetime.fromtimestamp(placed, dt.timezone.utc),
                                  expires_at=dt.datetime.fromtimestamp(end, dt.timezone.utc), trades=trades, tape_complete=True, queue_ahead=Decimal(Q))
        f, _ = sim_fill(t.ts, t.yes_c, t.size, t.taker_no, placed, end, lim, QTY, ("q", Q))
        total += 1; agree += int(abs(float(o.lower.filled) - f) < 1e-6)
    return dict(orders_checked=total, lower_bound_agreement=agree)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", default=N.BACKFILL); ap.add_argument("--games", default=N.GAMES_CSV)
    ap.add_argument("--out", default="reports/outcome_exec/nfl_execution.json")
    ap.add_argument("--orders", default="/home/user/work/nfl_exec_orders.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="debug: only first N tickers per series")
    a = ap.parse_args(argv)
    games = N.load_games(a.games); idx = N.game_index(games)
    ticks, skipped = [], defaultdict(int)
    for s in ("KXNFLGAME", "KXNFLSPREAD"):
        ms = N.load_markets(s, a.backfill)
        n = 0
        for m in ms:
            if not os.path.exists(os.path.join(a.backfill, "candles", s, m["ticker"] + ".json")):
                skipped[s, "no_candles_file"] += 1; continue
            t = load_tick(s, m, idx, a.backfill)
            if t is None:
                skipped[s, "no_game_or_unsettled_or_no_candles"] += 1; continue
            ticks.append(t); n += 1
            if a.limit and n >= a.limit:
                break
    print("tickers", len(ticks), dict(skipped), file=sys.stderr)
    rows, audit = build(ticks)
    print("rows", len(rows), file=sys.stderr)
    write_orders(rows, a.orders)
    rep = dict(version=VERSION, status="RESEARCH_ONLY", labels=dict(fills="SIMULATED_FROM_TAPE", fees="MODELLED", queue="SCENARIO"),
               design=dict(horizons_minutes_before_kickoff=HORIZONS, rules=RULES, queue_assumptions={k: v[1] if v[0] == "q" else "only prints strictly through the limit" for k, v in QUEUES.items()},
                           order_qty=QTY, close_quote="last quote at or before kickoff-15m", max_placement_spread_cents=MAX_SPREAD, splits=SPLITS,
                           variants=dict(V0="rest to kickoff, unfilled = 0 (order simply not executed)", V1="rest until T-90m, then cancel and TAKE the remainder at the T-90m ask"),
                           population="moneyline: YES contract of each team (NO side is the other team's YES); spread: YES and NO of every ticker with candles+tape; preseason excluded",
                           n_bootstrap=N_BOOT, cluster="game", tape_cap="newest 10,000 prints per ticker; orders whose window starts before the oldest retained print are UNCERTAIN and excluded"),
               coverage=coverage_audit(ticks, idx, a.backfill), skipped={f"{k[0]}|{k[1]}": v for k, v in skipped.items()},
               order_construction_audit={f"{k[0]}|{k[1]}|{k[2]}": v for k, v in sorted(audit.items())},
               simulator_crosscheck_vs_sift_clv=crosscheck(ticks))
    recs = taker_tables(ticks)
    rep["taker_entry_comparison"] = taker_summary(recs)
    rep["maker_cells"] = aggregate(rows)
    rep["chronological_selection"] = selection(rows)
    json.dump(rep, open(a.out, "w"), indent=1, sort_keys=True)
    print("wrote", a.out, file=sys.stderr)


if __name__ == "__main__":
    main()

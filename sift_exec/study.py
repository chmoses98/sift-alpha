"""Decision-level, equal-exposure entry counterfactuals on the NFL 2025 backfill (research only; every fill is SIMULATED_FROM_TAPE).

One DECISION = "acquire 10 contracts of contract-side X, decided at horizon H before kickoff, no later than the close (kickoff-15m)".
Population = every valid moneyline/spread contract-side (no selection signal: PR #25 showed no model beats the market, so this
isolates EXECUTION cost; a selection edge would add the same amount to every tactic).  Tactics, all on the same decisions:
  BUY_NOW        taker at the ask at H
  WAIT           taker at the close ask (kickoff-15m)
  LIMIT_<rule>   rest a buy from H to the close; the unfilled remainder is
      FB         taken at the close ask (maker->taker fallback: EQUAL exposure to BUY_NOW/WAIT, the like-for-like comparison)
      NB         not bought (don't-bet; exposure = filled quantity only, reported per submitted contract AND per filled contract)
Value per contract acquired, cents (negative = cost):
  V_mark   close_mid - all-in cost      (fair value of the exposure at the pre-start close; settlement-free, no outcome noise)
  V_settle 100*win   - all-in cost      (held to settlement, no exit fee; PR #25 convention)
All-in cost = price + fee.  Taker coefficient 0.07 always; MAKER coefficient scenario M0 / M25 / M100 (sift_exec.fees.SCENARIOS).
A tape-truncated order whose window starts before the oldest retained print is UNCERTAIN: excluded from point estimates, bounded separately.
"""
from __future__ import annotations
import numpy as np
from . import fees as FE, candles as CA
from .fills import replay_buy
from .nfl_data import quote_at, side_quote, tape_complete, CLOSE_MIN

QTY = 10
HORIZONS = {"7d": 168 * 60, "72h": 72 * 60, "48h": 48 * 60, "24h": 24 * 60, "6h": 6 * 60, "90m": 90}
RULES = ["AT_BID", "BID_PLUS_1", "MID"] + [f"ASK_MINUS_{k}" for k in range(1, 6)]
QUEUES = {"FRONT": (0.0, False), "Q500": (500.0, False), "Q5000": (5000.0, False), "THROUGH_ONLY": (0.0, True)}
MAX_SPREAD = 10
SPLITS = {"discovery": (1, 6), "validation": (7, 12), "holdout": (13, 99)}


def week_split(w):
    for k, (lo, hi) in SPLITS.items():
        if lo <= w <= hi:
            return k


def limit_price(rule, b, a):
    """Integer-cent limit for a BUY on own-side quote (b,a).  None if the rule is not placeable inside the book."""
    if rule == "AT_BID":
        return b
    if rule == "BID_PLUS_1":
        return b + 1 if b + 1 < a else b
    if rule == "MID":
        m = (a + b) // 2
        return m if b < m < a else b
    p = a - int(rule.rsplit("_", 1)[1])
    return p if p >= 1 else None


def build_rows(ticks, horizons=HORIZONS, rules=RULES, queues=QUEUES, expiry_min=CLOSE_MIN, through_any_side=True):
    """List of order dicts, one per (contract-side, horizon, rule, queue).  Outcome (``win``) is attached but never used for placement."""
    rows, audit = [], {}

    def bump(k):
        audit[k] = audit.get(k, 0) + 1

    for t in ticks:
        fam = "moneyline" if t.series == "KXNFLGAME" else "spread"
        ko = t.kickoff
        close_t = ko - CLOSE_MIN * 60
        cq = quote_at(t, close_t)
        for side in (("YES",) if fam == "moneyline" else ("YES", "NO")):
            win = t.outcome if side == "YES" else 1 - t.outcome
            for hn, hm in horizons.items():
                placed = ko - hm * 60
                bump((fam, hn, "contract_sides"))
                q = quote_at(t, placed)
                if q is None:
                    bump((fam, hn, "excl_no_valid_quote")); continue
                if cq is None:
                    bump((fam, hn, "excl_no_close_quote")); continue
                b, a, age, src = side_quote(q, side)
                if a - b > MAX_SPREAD:
                    bump((fam, hn, "excl_wide_spread")); continue
                cb, ca, _, _ = side_quote(cq, side)
                comp = tape_complete(t, placed)
                bump((fam, hn, "tape_determinate" if comp else "tape_uncertain"))
                cclass = {}
                for rule in rules:
                    lim0 = limit_price(rule, b, a)
                    if lim0 is not None:
                        cclass[(side, lim0)] = CA.classify(t, side, lim0, placed, ko - expiry_min * 60)
                for rule in rules:
                    lim = limit_price(rule, b, a)
                    if lim is None:
                        continue
                    for qn, (qa, thr) in queues.items():
                        fr = replay_buy(t.tape, side, lim, QTY, placed, ko - expiry_min * 60, qa, thr, through_any_side)
                        cc = cclass[(side, lim)]
                        if cc == CA.THROUGH:
                            flo = fhi = float(QTY)
                        elif cc == CA.UNFILLED_CERTAIN:
                            flo = fhi = 0.0
                        else:
                            flo, fhi = fr.filled, float(QTY)
                        if comp:
                            flo = fhi = fr.filled
                        rows.append(dict(filled_lo=flo, filled_hi=fhi,
                            game=t.game["game_id"], ticker=t.ticker, family=fam, side=side, horizon=hn, rule=rule, queue=qn,
                            week=t.game["week"], split=week_split(t.game["week"]), win=win, limit=lim, bid=b, ask=a, close_bid=cb, close_ask=ca,
                            quote_age=age, determinate=comp, candle_class=cclass[(side, lim)], filled=fr.filled,
                            fills=[(f.price_c, f.qty, f.evidence) for f in fr.fills], first_fill_ts=fr.first_ts, placed=placed))
    return rows, audit


# ----------------------------------------------------------------------------- economics
def cost_cents(price_c, qty, coef):
    """All-in cents for ``qty`` contracts at integer-cent ``price_c`` (whole-order fee)."""
    return price_c * qty + 100.0 * FE.order_fee(price_c, qty, coef)


def evaluate(rows, maker_coef, fee_rounding="whole", which="point"):
    """Vectorised per-order values (cents per submitted contract) for every tactic under one maker-fee coefficient.
    which = 'point' (simulated fill), 'lo' / 'hi' (fill-status bounds for tape-uncertain orders, see build_rows)."""
    n = len(rows)
    if which != "point":
        rows = [dict(r, filled=r["filled_" + which], fills=[(r["limit"], r["filled_" + which], "BOUND")] if r["filled_" + which] > 0 else []) for r in rows]
    lim = np.array([r["limit"] for r in rows], float); ask = np.array([r["ask"] for r in rows], float)
    bid = np.array([r["bid"] for r in rows], float); cask = np.array([r["close_ask"] for r in rows], int)
    cbid = np.array([r["close_bid"] for r in rows], float)
    win = np.array([r["win"] for r in rows], float); fil = np.array([r["filled"] for r in rows], float)
    cmid = (cask + cbid) / 2.0
    # per-order costs (use lookup tables over integer prices for speed)
    tk_now = np.array([cost_cents(int(a), QTY, FE.TAKER_COEF) for a in ask])
    tk_close = np.array([cost_cents(int(a), QTY, FE.TAKER_COEF) for a in cask])
    if fee_rounding == "whole":
        mk = np.array([cost_cents(r["limit"], r["filled"], maker_coef) if r["filled"] > 0 else 0.0 for r in rows])
    else:   # each fill ceiled independently: worst-case fragmentation
        mk = np.array([sum(p * q + 100.0 * FE.order_fee(p, q, maker_coef) for p, q, _ in r["fills"]) for r in rows])
    rem = QTY - fil
    fb_cost = mk + np.array([cost_cents(int(a), x, FE.TAKER_COEF) if x > 1e-9 else 0.0 for a, x in zip(cask, rem)])
    out = dict(n=n, cmid=cmid, win=win, filled=fil, lim=lim, ask=ask, cask=cask.astype(float), tk_now=tk_now, tk_close=tk_close,
               mk_cost=mk, fb_cost=fb_cost)
    out["v_mark_now"] = (cmid * QTY - tk_now) / QTY
    out["v_mark_wait"] = (cmid * QTY - tk_close) / QTY
    out["v_mark_fb"] = (cmid * QTY - fb_cost) / QTY
    out["v_settle_now"] = (win * 100 * QTY - tk_now) / QTY
    out["v_settle_wait"] = (win * 100 * QTY - tk_close) / QTY
    out["v_settle_fb"] = (win * 100 * QTY - fb_cost) / QTY
    out["v_mark_nb"] = (cmid * fil - mk) / QTY
    out["v_settle_nb"] = (win * 100 * fil - mk) / QTY
    return out

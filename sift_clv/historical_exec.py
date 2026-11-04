"""Executable-price summaries of REAL wagers (``sift-clv-executable/1`` over verified fills). Stdlib only, aggregates only.

Cost identity for one fill, per contract, versus the closing midpoint:
    (vwap + entry_fee) - close_mid  =  (vwap - close_ask)  +  (close_ask - close_mid)  +  entry_fee
                                    =  -B                  +  closing half-spread      +  fee
so B (executable purchase CLV) isolates timing/slippage versus a closing buyer, the half-spread is what ANY taker pays at
the close, and the fee is the exchange's. Entry spread is not observable for owner-placed fills and is not invented.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Optional

from . import canonical as C, executable as X, historical as H

MEASURES = ("executable_purchase_clv", "liquidation_clv", "midpoint_execution_clv",
            "executable_purchase_net_of_entry_fee", "midpoint_execution_net_of_entry_fee",
            "liquidation_net_of_entry_fee", "liquidation_net_all_fees")
BUCKETS = (("<1h", 0, 1), ("1-6h", 1, 6), ("6-24h", 6, 24), (">24h", 24, 10 ** 6))


def _bucket(hours: Optional[float]) -> str:
    if hours is None:
        return "unknown"
    for name, lo, hi in BUCKETS:
        if lo <= hours < hi:
            return name
    return "unknown"


def evaluate(o: H.Obs, *, max_close_age_seconds: Optional[int] = 3600) -> X.ExecResult:
    return X.evaluate_executable(
        ticker=o.ticker, side=o.side, close=o.close, start=o.start, stake=o.stake, book=o.book,
        fills=[C.Fill(o.price, o.contracts, o.fees)] if o.price is not None else [],
        max_close_age_seconds=max_close_age_seconds)


def _cents_stats(xs):
    s = H.stats(xs)
    return {k: (round(v * 100, 4) if k in ("mean", "median") else v) for k, v in s.items()}


def cell(rows) -> dict:
    """``rows``: list of (Obs, ExecResult) that are verified. One measure block per MEASURE, game-clustered."""
    out = {"n": len(rows), "games": len({o.game for o, _ in rows})}
    for m in MEASURES:
        pairs = [(o.game, float(getattr(r, m))) for o, r in rows if getattr(r, m) is not None]
        by_game = defaultdict(list)
        for g, v in pairs:
            by_game[g].append(v)
        st = _cents_stats([v for _, v in pairs])
        if st.get("n", 0) >= 10:
            ci = H.cluster_bootstrap_mean(by_game)
            st["game_cluster_ci95_cents"] = None if ci["ci95"] is None else [round(x * 100, 4) for x in ci["ci95"]]
        out[m] = st
    sp = [float(r.close_spread) for _, r in rows]
    fee = [float(r.entry_fee_per_contract) for _, r in rows if r.entry_fee_per_contract is not None]
    if sp:
        out["closing_spread_cents_mean"] = round(100 * sum(sp) / len(sp), 4)
        out["closing_half_spread_cents_mean"] = round(50 * sum(sp) / len(sp), 4)
    if fee:
        out["entry_fee_cents_mean"] = round(100 * sum(fee) / len(fee), 4)
    if sp and fee and rows:
        b = [float(r.executable_purchase_clv) for _, r in rows]
        out["cost_decomposition_cents_vs_close_mid"] = {
            "price_disadvantage_vs_closing_ask": round(-100 * sum(b) / len(b), 4),      # = -mean(B)
            "closing_half_spread": out["closing_half_spread_cents_mean"],
            "entry_fee": out["entry_fee_cents_mean"],
            "total_shortfall": round(-100 * sum(b) / len(b) + out["closing_half_spread_cents_mean"] + out["entry_fee_cents_mean"], 4)}
    return out


def depth_block(rows) -> dict:
    """Closing-depth evidence for the verified fills: coverage, insufficiency, and what size really costs."""
    st = Counter(r.depth_status for _, r in rows)
    full = [(o, r) for o, r in rows if r.depth_status == X.DEPTH_FULL]
    out = {"verified_fills": len(rows), "depth_status_counts": dict(sorted(st.items())),
           "with_depth_snapshot": sum(v for k, v in st.items() if k in (X.DEPTH_FULL, X.DEPTH_INSUFFICIENT, X.DEPTH_NO_ASKS)),
           "insufficient_depth_share_of_snapshotted": None}
    snap = out["with_depth_snapshot"]
    if snap:
        out["insufficient_depth_share_of_snapshotted"] = round((st[X.DEPTH_INSUFFICIENT] + st[X.DEPTH_NO_ASKS]) / snap, 4)
    if full:
        prem = [float(r.size_adjusted_ask_vwap - r.close_ask) for _, r in full]
        sa = [float(r.size_adjusted_purchase_clv) for _, r in full]
        top = []
        for o, r in full:
            lv = o.book.ask_levels(r.side)
            top.append(1.0 if lv and o.contracts > lv[0].size else 0.0)
        out["size_adjusted"] = {
            "n": len(full), "games": len({o.game for o, _ in full}),
            "premium_over_best_ask_cents_mean": round(100 * sum(prem) / len(prem), 4),
            "size_adjusted_purchase_clv_cents": _cents_stats(sa),
            "share_of_fills_larger_than_best_ask_level": round(sum(top) / len(top), 4)}
    return out


def summarize(obs, *, label: str = "", max_close_age_seconds: Optional[int] = 3600) -> dict:
    status, verified = Counter(), []
    for o in obs:
        if not o.entry_eligible:
            status["NOT_A_PREGAME_ENTRY"] += 1
            continue
        r = evaluate(o, max_close_age_seconds=max_close_age_seconds)
        status[r.status] += 1
        if r.status == C.OK:
            verified.append((o, r))
    out = {"label": label, "version": X.VERSION, "wagers": len(obs),
           "entry_eligible": sum(1 for o in obs if o.entry_eligible), "verified": len(verified),
           "unverifiable_by_reason": dict(sorted(status.items())),
           "overall": cell(verified), "depth": depth_block(verified)}
    fam = defaultdict(list)
    for o, r in verified:
        fam[o.family].append((o, r))
    out["by_family"] = {k: cell(v) for k, v in sorted(fam.items(), key=lambda kv: -len(kv[1])) if len(v) >= 8}
    tim = defaultdict(list)
    for o, r in verified:
        hrs = None if (o.executed_at is None or o.start is None) else (o.start - o.executed_at).total_seconds() / 3600.0
        tim[_bucket(hrs)].append((o, r))
    out["by_entry_hours_before_start"] = {k: cell(v) for k, v in sorted(tim.items()) if len(v) >= 5}
    out["verified_games"] = len({o.game for o, _ in verified})
    return out

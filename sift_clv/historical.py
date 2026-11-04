"""Historical re-measurement of REAL wagers with the canonical CLV measures (stdlib only).

Input: normalized wager records (see ``Obs``).  Output: before/after summaries with verified-vs-unverifiable counts,
game-clustered confidence intervals and the one-fee money identity.  Nothing here fabricates a fill, a close or a
recommendation link: absent evidence is counted under its reason code.

"Before" figures are whatever the producing repository published (passed through unchanged); "after" figures are
recomputed here from the raw ledger fields and the raw close quote.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from . import canonical as C

MONEY_TOL = Decimal("0.02")


@dataclass
class Obs:
    wager_id: str
    ticker: str
    side: str
    contracts: Optional[Decimal]
    price: Optional[Decimal]          # exchange fee-exclusive VWAP on the purchased side
    fees: Optional[Decimal]           # exchange-reported entry fees (dollars, total)
    stake: Optional[Decimal]          # cash consumed = price*contracts + fees
    game: str
    family: str
    start: Optional[datetime]
    close: Optional[C.Quote]
    entry_eligible: bool = True       # pregame BUY that opens a position (exits / live entries are not CLV observations)
    gross_return: Optional[Decimal] = None
    net_recorded: Optional[Decimal] = None   # as filed by the producing repo (may carry the v1 double fee)
    recommendation_linked: bool = False      # a verified recommendation -> order join exists
    executed_at: Optional[datetime] = None   # first fill time (entry timing), when the ledger has it
    book: Optional[object] = None            # sift_clv.executable.Book of the CLOSING depth, when an archive has one


def money_identity(o: Obs) -> str:
    """Is ``stake`` really price*contracts + fees (i.e. is ``price`` fee-exclusive and are fees counted once)?"""
    if None in (o.price, o.contracts, o.fees, o.stake):
        return "UNVERIFIABLE"
    return "OK" if abs(o.price * o.contracts + o.fees - o.stake) <= MONEY_TOL else "STAKE_NE_PRICE_X_QTY_PLUS_FEES"


def net_once(o: Obs) -> Optional[Decimal]:
    """Net P&L with the entry fee counted exactly once: gross_return - stake (stake already contains the fee)."""
    if o.gross_return is None or o.stake is None:
        return None
    return o.gross_return - o.stake


def stats(xs: list) -> dict:
    xs = [float(x) for x in xs]
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    return {"n": len(xs), "mean": sum(xs) / len(xs), "median": statistics.median(s),
            "positive_pct": 100.0 * sum(1 for x in xs if x > 0) / len(xs),
            "zero_pct": 100.0 * sum(1 for x in xs if x == 0) / len(xs),
            "negative_pct": 100.0 * sum(1 for x in xs if x < 0) / len(xs)}


def cluster_bootstrap_mean(values_by_cluster: dict, *, reps: int = 4000, seed: int = 7) -> dict:
    """Mean over observations, resampling whole games (clusters).  Returns the 95% percentile interval."""
    keys = list(values_by_cluster)
    flat = [v for k in keys for v in values_by_cluster[k]]
    if len(keys) < 2 or not flat:
        return {"clusters": len(keys), "ci95": None}
    rng, means = random.Random(seed), []
    for _ in range(reps):
        pick = [values_by_cluster[rng.choice(keys)] for _ in keys]
        vals = [v for grp in pick for v in grp]
        means.append(sum(vals) / len(vals))
    means.sort()
    return {"clusters": len(keys), "ci95": [means[int(0.025 * reps)], means[int(0.975 * reps)]]}


def measure(o: Obs, *, max_close_age_seconds: Optional[int] = 3600) -> C.CLVResult:
    return C.evaluate(ticker=o.ticker, side=o.side, recommendation=None, close=o.close, start=o.start,
                      fills=[C.Fill(o.price, o.contracts, o.fees)] if o.price is not None else [],
                      stake=o.stake, max_close_age_seconds=max_close_age_seconds)


def summarize(obs: list, *, max_close_age_seconds: Optional[int] = 3600, label: str = "") -> dict:
    status = Counter()
    ident = Counter(money_identity(o) for o in obs)
    rows = []
    for o in obs:
        if not o.entry_eligible:
            status["NOT_A_PREGAME_ENTRY"] += 1
            continue
        r = measure(o, max_close_age_seconds=max_close_age_seconds)
        status[r.status] += 1
        if r.status == C.OK and r.actual_execution_clv is not None:
            rows.append((o, r))
    aex = [float(r.actual_execution_clv) for _, r in rows]
    fee = [float(r.fee_per_contract) for _, r in rows if r.fee_per_contract is not None]
    fadj = [float(r.fee_adjusted_difference) for _, r in rows if r.fee_adjusted_difference is not None]
    by_game = defaultdict(list)
    for (o, r) in rows:
        by_game[o.game].append(float(r.actual_execution_clv))
    by_family = defaultdict(list)
    for (o, r) in rows:
        by_family[o.family].append(r)
    fam = {}
    for k, rs in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        fam[k] = {"n": len(rs), "games": len({o.game for o, _ in rows if o.family == k}),
                  "actual_execution_clv_mean": sum(float(r.actual_execution_clv) for r in rs) / len(rs),
                  "fee_per_contract_mean": sum(float(r.fee_per_contract) for r in rs if r.fee_per_contract is not None)
                  / max(1, sum(1 for r in rs if r.fee_per_contract is not None))}
    settled = [o for o in obs if o.gross_return is not None and o.stake is not None]
    stake = sum((o.stake for o in settled), Decimal(0))
    once = sum((net_once(o) for o in settled), Decimal(0))
    rec = sum((o.net_recorded for o in settled if o.net_recorded is not None), Decimal(0))
    rec_n = sum(1 for o in settled if o.net_recorded is not None)
    return {
        "label": label, "version": C.VERSION, "wagers": len(obs),
        "entry_eligible": sum(1 for o in obs if o.entry_eligible),
        "verified_clv_observations": len(rows),
        "unverifiable_by_reason": dict(sorted(status.items())),
        "recommendation_linked": sum(1 for o in obs if o.recommendation_linked),
        "selection_clv": {"verified": 0, "reason": "no recommendation->order join in the ledger" if not any(
            o.recommendation_linked for o in obs) else "see linked subset"},
        "actual_execution_clv": {**stats(aex), "game_cluster": cluster_bootstrap_mean(by_game)},
        "fee_per_contract": stats(fee),
        "fee_adjusted_difference": stats(fadj),
        "fee_adjustment_count_max": max([r.fee_adjustment_count for _, r in rows] or [0]),
        "money_identity": dict(ident),
        "by_family": fam,
        "economics": {
            "settled_with_stake_and_gross": len(settled), "stake": float(stake),
            "net_fee_counted_once": float(once),
            "roi_fee_counted_once": float(once / stake) if stake else None,
            "net_as_recorded_same_wagers": float(rec), "net_recorded_n": rec_n,
            "recorded_minus_once": float(rec - sum((net_once(o) for o in settled if o.net_recorded is not None),
                                                   Decimal(0))),
        },
    }

"""Same-cohort execution-strategy comparison (``sift-clv-cohort/1``).  RESEARCH ONLY: nothing here routes an order.

Every strategy is scored on the SAME original decision cohort, per contract of the intended size, against the same fair-value
proxy (the matched closing midpoint of the held side).  Value of one decision under a strategy:

    value = filled_fraction * (fair - price - fee_per_contract)           [what the strategy actually acquires]

and the comparison to the baseline (immediate taker at the entry ask) is the PAIRED difference

    delta_i = value_strategy_i - value_baseline_i

so an order that never fills is charged the baseline's forgone value; it is NOT scored as a free zero.  ("Don't bet" is a
different question and is reported separately via ``missed_exposure_share``.)

Fill fractions arrive as a LOWER and an UPPER bound (queue-back / queue-front, see ``limit_orders``) and are never merged into
one point.  A decision whose fill is UNCERTAIN for a strategy carries ``None`` for that bound and is excluded from that bound's
statistics with the count reported -- never imputed.  Uncertainty resamples whole GAMES (clusters); the chronological split
reports the first half and the second half of the cohort separately so a result must hold out of sample.  Maker fees are a
sensitivity (0 and 0.0175), because the maker schedule is unverified.

Selection edge (fair - entry mid) is NOT execution advantage and is reported only as the cohort's own context.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, Optional

from . import canonical as C

VERSION = "sift-clv-cohort/1"
ZERO = Decimal(0)
BASELINE = "IMMEDIATE_TAKER_AT_ASK"
STRATEGIES = (BASELINE, "REST_AT_BID", "INSIDE_SPREAD", "MAKER_THEN_TAKER_FALLBACK", "WAIT_TO_KICKOFF_TAKER")


@dataclass(frozen=True)
class StratOutcome:
    """One strategy on one decision. Fractions in [0, 1] or None (UNCERTAIN); price/fee are per contract in dollars."""
    fill_lo: Optional[Decimal]
    fill_up: Optional[Decimal]
    price: Optional[Decimal]
    fee: Decimal = ZERO
    rest_fill_price: Optional[Decimal] = None        # price of the remainder bought by a fallback (None = no fallback)
    rest_fee: Decimal = ZERO


@dataclass(frozen=True)
class Decision:
    game: str
    placed_at_epoch: float                           # chronology only; never used to look forward
    fair: Decimal                                    # matched closing midpoint of the held side (fair-value proxy)
    outcomes: Dict[str, StratOutcome] = field(default_factory=dict)


def _value(o: StratOutcome, fair: Decimal, frac: Optional[Decimal]) -> Optional[Decimal]:
    if frac is None or o.price is None:
        return None
    v = frac * (fair - o.price - o.fee)
    if o.rest_fill_price is not None and frac < 1:                  # taker fallback buys the remainder
        v += (1 - frac) * (fair - o.rest_fill_price - o.rest_fee)
    return v


def paired_deltas(cohort: Iterable[Decision], strategy: str, bound: str) -> tuple[list, int]:
    """[(game, delta_cents, placed_at)] for decisions where BOTH the strategy and the baseline are determinate; plus the
    number of decisions excluded as uncertain. ``bound`` is 'lo' or 'up'."""
    rows, excluded = [], 0
    for d in cohort:
        s, b = d.outcomes.get(strategy), d.outcomes.get(BASELINE)
        if s is None or b is None:
            excluded += 1
            continue
        sv = _value(s, d.fair, s.fill_lo if bound == "lo" else s.fill_up)
        bv = _value(b, d.fair, b.fill_lo if bound == "lo" else b.fill_up)
        if sv is None or bv is None:
            excluded += 1
            continue
        rows.append((d.game, float((sv - bv) * 100), d.placed_at_epoch))
    return rows, excluded


def _cluster_ci(rows, reps=1000, seed=11):
    by: dict = {}
    for g, x, _ in rows:
        a = by.setdefault(g, [0.0, 0])
        a[0] += x; a[1] += 1
    if len(by) < 2:
        return None
    keys, rng, ms = list(by.values()), random.Random(seed), []
    for _ in range(reps):
        s = n = 0
        for _ in keys:
            a = keys[rng.randrange(len(keys))]
            s += a[0]; n += a[1]
        ms.append(s / n)
    ms.sort()
    return [round(ms[int(.025 * reps)], 4), round(ms[int(.975 * reps)], 4)]


def summarize(rows, excluded: int) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "games": 0, "excluded_uncertain_or_missing": excluded, "mean_delta_cents_vs_baseline": None}
    games = len({g for g, _, _ in rows})
    return {"n": n, "games": games, "excluded_uncertain_or_missing": excluded,
            "mean_delta_cents_vs_baseline": round(sum(x for _, x, _ in rows) / n, 4),
            "game_cluster_ci95_cents": _cluster_ci(rows)}


def compare(cohort: Iterable[Decision], *, strategies: Iterable[str] = STRATEGIES) -> dict:
    """Per strategy and bound: pooled, plus chronological first-half / second-half. A strategy is flagged ``HOLDS_OOS`` only
    when BOTH halves are determinate (>= 2 games each) and BOTH have a cluster interval entirely above zero on the CONSERVATIVE
    (lower) bound -- the optimistic bound can never promote a strategy."""
    cohort = sorted(cohort, key=lambda d: d.placed_at_epoch)
    out = {"version": VERSION, "decisions": len(cohort), "baseline": BASELINE, "strategies": {}}
    half = len(cohort) // 2
    for st in strategies:
        if st == BASELINE:
            continue
        cell = {}
        for bound in ("lo", "up"):
            rows, ex = paired_deltas(cohort, st, bound)
            first = [r for r in rows if r[2] <= (cohort[half - 1].placed_at_epoch if half else -1)]
            second = [r for r in rows if r not in first]
            cell[bound] = {"pooled": summarize(rows, ex), "first_half": summarize(first, 0), "second_half": summarize(second, 0)}
        lo = cell["lo"]
        ok = all((lo[h].get("game_cluster_ci95_cents") or [0, 0])[0] > 0 for h in ("first_half", "second_half"))
        cell["verdict"] = "HOLDS_OOS" if ok else "NOT_DEMONSTRATED"
        out["strategies"][st] = cell
    return out


def missed_exposure_share(cohort: Iterable[Decision], strategy: str, bound: str = "lo") -> Optional[float]:
    """Share of intended exposure NOT acquired by the strategy (the 'missed bet' rate), on determinate decisions only."""
    miss, n = Decimal(0), 0
    for d in cohort:
        o = d.outcomes.get(strategy)
        f = None if o is None else (o.fill_lo if bound == "lo" else o.fill_up)
        if f is None:
            continue
        extra = 0 if o.rest_fill_price is None else (1 - f)
        miss += 1 - min(Decimal(1), f + extra)
        n += 1
    return None if not n else round(float(miss / n), 4)

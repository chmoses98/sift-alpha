"""Combined market-selection / execution decision framework (research only).

For ONE opportunity (a contract side with a calibrated fair probability and a live quote) compare four actions and choose by
FEE-ADJUSTED RISK-ADJUSTED EXPECTED PROFIT, not win probability:

  BUY_NOW   taker at the ask                 EV = p - ask - taker_fee(ask)
  LIMIT     resting maker bid at L (<ask)    EV = f * (p_f - L - maker_fee(L))       (unfilled = 0)
  WAIT      do nothing now, re-decide later  EV = E[ max(0, p - ask' - fee(ask')) ] over a price-drift distribution
  PASS      0

where f = P(fill) and p_f = P(win | filled) = p - adverse_selection (fills concentrate in losers when information arrives).
Every parameter is an input estimated by the experiments (fill table, adverse selection, drift) with its own uncertainty;
nothing is inferred from a price touch without the touch->fill haircut being explicit. Output is a ranked list, never an order.
The module cannot place, route or size a wager: ``STATUS == "RESEARCH_ONLY"`` and ``decide`` returns advice records only.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence
import math
import numpy as np

from . import fees

STATUS = "RESEARCH_ONLY"
BUY_NOW, LIMIT, WAIT, PASS = "BUY_NOW", "LIMIT", "WAIT", "PASS"


@dataclass(frozen=True)
class Opportunity:
    p: float                       # calibrated fair probability the held side wins
    p_se: float                    # standard error of p (calibration/model uncertainty)
    bid: float                     # best bid of the held side (dollars)
    ask: float                     # best ask of the held side
    hours_to_kickoff: float
    contracts: int = 1


@dataclass(frozen=True)
class ExecParams:
    """Estimated by the execution experiments (nfl_execution / shadow orders). All explicit assumptions."""
    fill_prob: Dict[int, float] = field(default_factory=dict)     # cents below ask -> P(fill before kickoff); keys 0..N
    fill_prob_lo: Dict[int, float] = field(default_factory=dict)  # conservative bound
    adverse_selection: float = 0.0                                # P(win|unfilled) - P(win|filled), added to loss for fills
    drift_mean: float = 0.0                                       # E[ask(later) - ask(now)] (dollars)
    drift_sd: float = 0.02                                        # sd of ask drift to the later decision point
    stale_haircut: float = 0.0                                    # extra p haircut for stale information on a resting order
    risk_aversion: float = 0.5                                    # lambda in ev - 0.5*lambda*variance
    min_lcb: float = 0.0                                          # required lower confidence bound on EV/contract
    z: float = 1.64


@dataclass(frozen=True)
class ActionEval:
    action: str
    limit: Optional[float]
    ev: float                      # fee-adjusted expected profit per contract submitted
    ev_lcb: float                  # EV lower confidence bound using p_se (and conservative fill bound)
    sd: float                      # sd of the profit per submitted contract
    score: float                   # mean-variance: ev - 0.5 * risk_aversion * sd^2
    fill_prob: Optional[float]
    notes: tuple = ()


def _sd_buy(p, price):
    # P&L = win - price (fee deterministic): variance p(1-p)
    return math.sqrt(max(p * (1 - p), 0.0))


def _eval_buy_now(o: Opportunity, ep: ExecParams) -> ActionEval:
    fee = float(fees.fee_per_contract(o.ask, o.contracts, "taker"))
    ev = o.p - o.ask - fee
    lcb = ev - ep.z * o.p_se
    sd = _sd_buy(o.p, o.ask)
    return ActionEval(BUY_NOW, o.ask, ev, lcb, sd, ev - 0.5 * ep.risk_aversion * sd ** 2, 1.0)


def _eval_limit(o: Opportunity, ep: ExecParams, cents_below: int) -> Optional[ActionEval]:
    L = round(o.ask - cents_below / 100.0, 2)
    if L <= 0 or L <= o.bid - 1e-9 and cents_below == 0:
        return None
    if L < 0.01:
        return None
    f = ep.fill_prob.get(cents_below)
    if f is None:
        return None
    f_lo = ep.fill_prob_lo.get(cents_below, f)
    fee = float(fees.fee_per_contract(L, o.contracts, "maker"))
    p_f = max(0.0, o.p - ep.adverse_selection - ep.stale_haircut)
    ev = f * (p_f - L - fee)
    # conservative: lower fill probability only matters if per-fill EV>0; LCB also shades p by its se
    per_fill_lcb = (p_f - ep.z * o.p_se) - L - fee
    lcb = (f_lo if per_fill_lcb > 0 else f) * per_fill_lcb
    # sd of profit per submitted contract: mixture of {0 w.p. 1-f, win-L w.p. f}
    m2 = f * (p_f * (1 - L) ** 2 + (1 - p_f) * L ** 2)
    sd = math.sqrt(max(m2 - (f * (p_f - L)) ** 2, 0.0))
    notes = ("MODELLED_MAKER_FEE", "FILL_FROM_TAPE_SIMULATION") + (("ADVERSE_SELECTION_APPLIED",) if ep.adverse_selection else ())
    return ActionEval(LIMIT, L, ev, lcb, sd, ev - 0.5 * ep.risk_aversion * sd ** 2, f, notes)


def _eval_wait(o: Opportunity, ep: ExecParams, n=2001) -> ActionEval:
    # later ask ~ Normal(ask + drift_mean, drift_sd); at the later point you buy iff EV>0 (option value), p unchanged (martingale)
    rng = np.random.default_rng(11)
    ask2 = np.clip(o.ask + ep.drift_mean + ep.drift_sd * rng.standard_normal(n), 0.01, 0.99)
    ev2 = o.p - ask2 - fees.fee_per_contract(ask2, o.contracts, "taker")
    take = ev2 > 0
    ev = float(np.mean(np.where(take, ev2, 0.0)))
    lcb = float(np.mean(np.where(ev2 - ep.z * o.p_se > 0, ev2 - ep.z * o.p_se, 0.0)))
    pnl_sd = float(np.sqrt(np.mean(np.where(take, o.p * (1 - o.p), 0.0))))
    return ActionEval(WAIT, None, ev, lcb, pnl_sd, ev - 0.5 * ep.risk_aversion * pnl_sd ** 2, None, ("OPTION_VALUE_ASSUMES_MARTINGALE_P",))


def decide(o: Opportunity, ep: ExecParams) -> Dict:
    """Ranked comparison. A non-PASS action is recommended only if its EV lower confidence bound exceeds ``min_lcb``."""
    evals: List[ActionEval] = [_eval_buy_now(o, ep)]
    for c in sorted(ep.fill_prob):
        e = _eval_limit(o, ep, c)
        if e:
            evals.append(e)
    evals.append(_eval_wait(o, ep))
    evals.append(ActionEval(PASS, None, 0.0, 0.0, 0.0, 0.0, None))
    eligible = [e for e in evals if e.action == PASS or e.ev_lcb > ep.min_lcb]
    best = max(eligible, key=lambda e: e.score)
    return dict(status=STATUS, recommended=best.action, limit=best.limit, best=asdict(best),
                ranked=[asdict(e) for e in sorted(evals, key=lambda e: -e.score)],
                reason=("no action clears the EV lower-confidence-bound gate" if best.action == PASS else "highest risk-adjusted fee-adjusted EV among actions with EV_LCB>min_lcb"))

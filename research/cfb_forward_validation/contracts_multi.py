"""Kalshi CFB contract semantics for every scored family (RESEARCH_ONLY). Pure functions; tests/test_cfb_forward_validation.py.

Ticker:  <SERIES>-<YYMONDD><AWAY><HOME>-<TAIL>     event key = date + AWAY + HOME (verified in PR #98)
  team markets   TAIL = <TEAM>[<N>]   (moneyline: TEAM; spread / team total: TEAM + N, floor_strike = N - 0.5)
  period winner  TAIL = TEAM or TIE   (a tied period settles NO for both teams and YES for TIE)
  totals         TAIL = N             (floor_strike = N - 0.5)
All ladder contracts settle YES iff the quantity is STRICTLY greater than floor_strike ("strike_type": "greater").
Full-game winner: no ties (overtime).  Second half includes overtime.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FEE_RATE = 0.07

#: series -> (period, kind); kind in {winner, spread, total, team_total}
SERIES = {
    "KXNCAAFGAME": ("FG", "winner"), "KXNCAAFSPREAD": ("FG", "spread"), "KXNCAAFTOTAL": ("FG", "total"), "KXNCAAFTEAMTOTAL": ("FG", "team_total"),
    "KXNCAAF1H": ("1H", "winner"), "KXNCAAF1HSPREAD": ("1H", "spread"), "KXNCAAF1HTOTAL": ("1H", "total"), "KXNCAAF1HTEAMTOTAL": ("1H", "team_total"),
    "KXNCAAF2H": ("2H", "winner"), "KXNCAAF2HSPREAD": ("2H", "spread"), "KXNCAAF2HTOTAL": ("2H", "total"),
    "KXNCAAF1Q": ("1Q", "winner"), "KXNCAAF1QSPREAD": ("1Q", "spread"), "KXNCAAF1QTOTAL": ("1Q", "total"),
}


@dataclass(frozen=True)
class Contract:
    ticker: str
    period: str
    kind: str
    side: str | None  # "home", "away", "tie" or None (totals)
    strike: float | None

    @property
    def family(self) -> str:
        return f"{self.period}_{self.kind}"


def side_of(key: str, abbr: str) -> str | None:
    """home / away from the event key (AWAY then HOME after the 7-char date); None if undecidable."""
    teams = key[7:]
    end, start = teams.endswith(abbr), teams.startswith(abbr)
    if end == start:
        return None
    return "home" if end else "away"


def parse(ticker: str, floor_strike: float | None) -> Contract | None:
    series, key, tail = ticker.split("-", 2)
    if series not in SERIES:
        return None
    period, kind = SERIES[series]
    if kind == "total":
        n = int(tail)
        if floor_strike is not None and abs(floor_strike - (n - 0.5)) > 1e-9:
            return None
        return Contract(ticker, period, kind, None, n - 0.5)
    if kind == "winner":
        if tail == "TIE":
            return Contract(ticker, period, kind, "tie", None) if period != "FG" else None
        s = side_of(key, tail)
        return None if s is None else Contract(ticker, period, kind, s, None)
    abbr = tail.rstrip("0123456789"); n = tail[len(abbr):]
    s = side_of(key, abbr)
    if s is None or not n:
        return None
    if floor_strike is not None and abs(floor_strike - (int(n) - 0.5)) > 1e-9:
        return None
    return Contract(ticker, period, kind, s, int(n) - 0.5)


def quantity(c: Contract) -> str:
    """Which projected quantity drives the contract."""
    if c.kind in ("winner", "spread"):
        return "margin"
    if c.kind == "total":
        return "total"
    return "home_pts" if c.side == "home" else "away_pts"


def settle(c: Contract, home: float, away: float) -> bool:
    """YES outcome from the period's home and away points."""
    m = home - away
    if c.kind == "winner":
        if c.side == "tie":
            return m == 0
        return (m if c.side == "home" else -m) > 0
    if c.kind == "spread":
        return (m if c.side == "home" else -m) > c.strike
    if c.kind == "total":
        return home + away > c.strike
    return (home if c.side == "home" else away) > c.strike


def _phi(z):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z, float) / math.sqrt(2)))


def p_greater(mu, sigma, k, resid_q=None):
    """P(X > k) for X = mu + e. Normal e ~ N(0, sigma) or, with resid_q, the empirical residual quantiles (equal weight)."""
    mu = np.asarray(mu, float); k = np.asarray(k, float)
    if resid_q is None:
        return 1 - _phi((k - mu) / sigma)
    r = np.asarray(resid_q, float)
    return ((mu[..., None] + r) > k[..., None]).mean(axis=-1)


def yes_prob(c: Contract, mu_quantity: float, sigma: float, resid_q=None) -> float:
    """Model P(YES). `mu_quantity` is the mean of quantity(c) on the HOME orientation for margins."""
    if c.kind == "winner":
        if c.period == "FG":  # no ties: renormalise P(m > 0) against P(m < 0)
            ph = float(p_greater(mu_quantity, sigma, 0.0, resid_q)); pa = 1 - float(p_greater(mu_quantity, sigma, -1e-9, resid_q)) if resid_q is not None else 1 - ph
            ph = ph / (ph + pa) if (ph + pa) > 0 else 0.5
            return ph if c.side == "home" else 1 - ph
        p_home = float(p_greater(mu_quantity, sigma, 0.5, resid_q)); p_away = 1 - float(p_greater(mu_quantity, sigma, -0.5, resid_q))
        return {"home": p_home, "away": p_away, "tie": max(0.0, 1 - p_home - p_away)}[c.side]
    if c.kind == "spread":
        mu = mu_quantity if c.side == "home" else -mu_quantity
        if resid_q is not None and c.side == "away":  # -(m) = -mu - e: flip the residual distribution
            resid_q = -np.asarray(resid_q, float)
        return float(p_greater(mu, sigma, c.strike, resid_q))
    return float(p_greater(mu_quantity, sigma, c.strike, resid_q))


def fee_per_order(price: float, contracts: int) -> float:
    """Kalshi taker fee for one order: 0.07 * C * P * (1 - P), rounded UP to the next cent."""
    return math.ceil(FEE_RATE * contracts * price * (1 - price) * 100 - 1e-9) / 100


def fee_unrounded(price: float) -> float:
    return FEE_RATE * price * (1 - price)

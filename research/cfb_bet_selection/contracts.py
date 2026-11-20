"""Kalshi CFB contract semantics used by the bet-selection study (RESEARCH_ONLY). Pure functions, unit-tested in tests/test_cfb_bet_selection.py.

Verified against Kalshi official settlements (sift-data-vault archives/CFB/kalshi_official_settlements): 6,575 of 6,575 quoted 2026 tickers agree.
  event key   = YYMONDD + AWAY + HOME            e.g. 26SEP19MSUND  -> Michigan State at Notre Dame
  WIN ticker  = KXNCAAFGAME-<key>-<TEAM>          YES iff TEAM wins
  SPREAD      = KXNCAAFSPREAD-<key>-<TEAM><N>     floor_strike = N - 0.5; YES iff TEAM wins by MORE than floor_strike (strike_type "greater")
"""
from __future__ import annotations
import math

FEE_RATE = 0.07


def parse_ticker(market_ticker: str) -> dict:
    series, key, tail = market_ticker.split("-", 2)
    fam = {"KXNCAAFGAME": "WIN", "KXNCAAFSPREAD": "SPREAD"}[series]
    abbr = tail.rstrip("0123456789") if fam == "SPREAD" else tail
    n = tail[len(abbr):]
    return {"fam": fam, "key": key, "abbr": abbr, "thr": (int(n) - 0.5) if fam == "SPREAD" else -0.5}


def side_is_home(key: str, abbr: str):
    """True if abbr is the HOME (second) team of the event key, False if away, None if it cannot be decided from the key alone."""
    teams = key[7:]
    end, start = teams.endswith(abbr), teams.startswith(abbr)
    return None if end == start else end


def yes_wins(side_home: bool, home_score: float, away_score: float, thr: float) -> bool:
    """YES settles iff the contract team's margin is strictly greater than thr (WIN contracts use thr = -0.5)."""
    m = home_score - away_score
    return (m if side_home else -m) > thr


def yes_prob(side_home: bool, home_margin_mean: float, sigma: float, thr: float) -> float:
    """P(contract team margin > thr) under home margin ~ Normal(home_margin_mean, sigma)."""
    if thr == -0.5: thr = 0.0  # WIN: continuous equivalent of "margin > 0"; -0.5 on both sides double counts P(|margin| < 0.5)
    tm = home_margin_mean if side_home else -home_margin_mean
    return 1 - 0.5 * (1 + math.erf((thr - tm) / sigma / math.sqrt(2)))


def fee(price: float, round_up_cent: bool = False) -> float:
    """Kalshi taker fee per contract. PR #97 used the unrounded formula; a single-contract order actually pays the next whole cent."""
    f = FEE_RATE * price * (1 - price)
    return math.ceil(f * 100 - 1e-9) / 100 if round_up_cent else f


def pnl(won: bool, ask: float, fee_paid: float) -> float:
    return (1 - ask if won else -ask) - fee_paid

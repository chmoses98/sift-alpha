"""Kalshi fee model (general schedule), float implementation for vectorised research.

taker: ceil_to_cent(0.07 * C * P * (1-P)); maker: ceil_to_cent(0.0175 * C * P * (1-P)).
Agrees with ``sift_clv.canonical.estimate_fee`` (tested). HYPOTHETICAL entries only: real wagers carry exchange-reported fees.
The maker rate is an assumption (some series charge no maker fee); every maker result is labelled MODELLED_FEE.
"""
from __future__ import annotations
import math
import numpy as np

TAKER, MAKER = 0.07, 0.0175


def fee_dollars(price, contracts=1, role="taker"):
    """Total fee in dollars for ``contracts`` filled at ``price`` (dollars, 0-1). Vectorised."""
    rate = TAKER if role == "taker" else MAKER
    p = np.asarray(price, dtype=float)
    c = np.asarray(contracts, dtype=float)
    raw = rate * c * p * (1 - p) * 100.0
    return np.ceil(np.round(raw, 9)) / 100.0


def fee_per_contract(price, contracts=1, role="taker"):
    return fee_dollars(price, contracts, role) / np.asarray(contracts, dtype=float)


def net_pnl_per_contract(price, win, role="taker", contracts=1):
    """Settlement P&L per contract of buying at ``price``: (win - price) - fee/contract. Held to settlement, no exit fee."""
    return np.asarray(win, dtype=float) - np.asarray(price, dtype=float) - fee_per_contract(price, contracts, role)

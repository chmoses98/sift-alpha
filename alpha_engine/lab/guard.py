"""Market-free guarantee for the independent track.  Kalshi prices, sportsbook lines/odds and anything derived from them are evaluation inputs only."""
from __future__ import annotations
import re

FORBIDDEN = re.compile(r"(spread_line|total_line|moneyline|spread_odds|over_odds|under_odds|^mkt_|_mkt_|implied|closing|consensus|kalshi|bid$|ask$|^ix_spread_x|^ix_pace_x_total)", re.I)
# post-game quantities: valid only as TARGETS
POSTGAME = re.compile(r"^(home_score|away_score|result|total|overtime)$")


class MarketLeak(AssertionError):
    pass


def assert_market_free(columns, *, allow_targets=()):
    bad = [c for c in columns if (FORBIDDEN.search(str(c)) or (POSTGAME.match(str(c)) and c not in allow_targets))]
    if bad:
        raise MarketLeak(f"market or post-game columns reached a model: {bad}")
    return True

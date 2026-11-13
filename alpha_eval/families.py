"""Contract classification for evaluation. Reuses ``alpha_engine.taxonomy.classify`` (already pinned against the 275-family
master inventory) and maps its kinds onto the standard's families + the scoring types each may legally use.
Anything it cannot place is UNCLASSIFIED/UNSUPPORTED with a reason - never guessed, never dropped."""
from __future__ import annotations

from alpha_engine.taxonomy import classify

from .schema import (ALT_SPREAD, ALT_TEAM_TOTAL, ALT_TOTAL, ALTERNATE, BINARY, CATEGORICAL, COMBO, CONTINUOUS, FUTURE,
                     LADDER_RUNG, MONEYLINE, OFF_FIELD, ORDINAL_PMF, OTHER_EVENT, PERIOD, PLAYER_PROP, R, SPORTS,
                     SPREAD, TEAM_TOTAL, TOTAL, UNCLASSIFIED, LADDER, MAIN)

_NUMERIC = (BINARY, ORDINAL_PMF, CONTINUOUS)
# taxonomy kind -> (base family, allowed scoring types)
_KIND = {
    "winner": (MONEYLINE, (BINARY, CATEGORICAL)),          # 3-way soccer result is CATEGORICAL, not binary
    "spread": (SPREAD, _NUMERIC), "total": (TOTAL, _NUMERIC), "team_total": (TEAM_TOTAL, _NUMERIC),
    "period_result": (PERIOD, _NUMERIC + (CATEGORICAL,)),
    "player_stat": (PLAYER_PROP, _NUMERIC), "player_scorer": (PLAYER_PROP, (BINARY,)), "player_h2h": (PLAYER_PROP, (BINARY,)),
    "lineup_role": (PLAYER_PROP, (BINARY,)),
    "margin_bucket": (OTHER_EVENT, (CATEGORICAL, ORDINAL_PMF)), "exact_score": (OTHER_EVENT, (CATEGORICAL,)),
    "btts": (OTHER_EVENT, (BINARY,)), "overtime": (OTHER_EVENT, (BINARY,)),
    "first_event": (OTHER_EVENT, (BINARY, CATEGORICAL)), "team_stat": (OTHER_EVENT, _NUMERIC), "game_stat": (OTHER_EVENT, _NUMERIC),
    "season_outcome": (FUTURE, (BINARY, CATEGORICAL)), "season_award": (FUTURE, (BINARY, CATEGORICAL)),
    "season_stat": (FUTURE, _NUMERIC + (CATEGORICAL,)),
    "combo": (COMBO, ()), "off_field": (OFF_FIELD, ()), "unclassified": (UNCLASSIFIED, ()),
}
_GAME_KINDS = ("winner", "spread", "total", "team_total")


def classify_contract(sport: str, native_family: str, ticker: str = "", line_role: str = MAIN) -> dict:
    """-> {family, base_kind, period, allowed_scoring, support: SCORABLE|UNSUPPORTED, reason}."""
    if sport not in SPORTS:
        return dict(family=UNCLASSIFIED, base_kind="unclassified", period="FULL", allowed_scoring=(), support="UNSUPPORTED",
                    reason=R.UNKNOWN_SPORT)
    c = classify(sport, native_family, ticker)
    if native_family:
        # A producer-declared family beats substring hits in the ticker (alpha_engine's season_award rule matches "hart"
        # inside player codes such as NYKJHART3). The ticker is then used only for period detection.
        n = classify(sport, native_family, "")
        if n["kind"] != "unclassified":
            c = dict(n, period=c["period"])
    kind, period = c["kind"], c["period"]
    family, allowed = _KIND.get(kind, (UNCLASSIFIED, ()))
    if kind in _GAME_KINDS and period != "FULL":
        family = PERIOD                                     # period contracts keep their own family (base_kind retained)
    elif line_role == ALTERNATE:
        family = {SPREAD: ALT_SPREAD, TOTAL: ALT_TOTAL, TEAM_TOTAL: ALT_TEAM_TOTAL}.get(family, family)
    elif line_role == LADDER_RUNG and family in (TOTAL, TEAM_TOTAL, SPREAD, PLAYER_PROP):
        family = LADDER if family != PLAYER_PROP else PLAYER_PROP
    reason = {COMBO: R.COMBO, OFF_FIELD: R.OFF_FIELD, UNCLASSIFIED: R.UNCLASSIFIED}.get(family)
    return dict(family=family, base_kind=kind, period=period, allowed_scoring=allowed,
                support="UNSUPPORTED" if reason else "SCORABLE", reason=reason or R.OK)

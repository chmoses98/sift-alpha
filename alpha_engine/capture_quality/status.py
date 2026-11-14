"""Verified-vs-projected starter classifier (CFB QB, NHL goalie, NBA starters, NFL QB).

Principle: only an observation made BEFORE the game starts, from a source that itself says the starter is confirmed,
counts as VERIFIED_PREGAME. A projection (prior-game passer, depth chart, 'Likely'/'Expected' label) is PROJECTED.
A box-score row observed at/after the start is the actual starter (POSTGAME_ACTUAL) - useful as a label, never a pregame input.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

VERIFIED_PREGAME = "VERIFIED_PREGAME"
PROJECTED = "PROJECTED"
POSTGAME_ACTUAL = "POSTGAME_ACTUAL"
UNKNOWN = "UNKNOWN"

_CONFIRMED = {"confirmed", "starting", "official"}
_PROJECTED_WORDS = {"projected", "probable", "likely", "expected", "unconfirmed", "possible", "depth_chart"}
_POSTGAME_SOURCES = ("boxscore",)
_PROJECTION_SOURCES = ("prior_game_passer", "depth_chart", "projection")
_GENERIC_ACTIVE = {"active", "available", ""}


def _t(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def classify_lineup_status(row: Mapping[str, Any], game_start_utc: Any) -> dict[str, Any]:
    """Classify one observation. Row keys used: source, status, certainty, observed_at_utc, source_reported_at_utc."""
    source = str(row.get("source") or "").lower()
    status = str(row.get("status") or "").strip().lower()
    certainty = str(row.get("certainty") or "").strip().lower()
    obs = _t(row.get("observed_at_utc"))
    start = _t(game_start_utc)
    reported = _t(row.get("source_reported_at_utc"))
    flags: list[str] = []
    if obs is None or start is None:
        return {"class": UNKNOWN, "reason": "missing observed_at or game start", "flags": ["NO_TIMESTAMP"]}
    pregame = obs < start
    if reported is not None and reported > obs:
        flags.append("SOURCE_TIME_AFTER_OBSERVATION")
    if reported is None:
        flags.append("NO_SOURCE_REPORTED_TIME")
    if any(s in source for s in _POSTGAME_SOURCES):
        return {"class": POSTGAME_ACTUAL if not pregame else UNKNOWN,
                "reason": "box score row" if not pregame else "box score observed before start (not a starter report)", "flags": flags}
    if any(s in source for s in _PROJECTION_SOURCES) or certainty == "projected":
        return {"class": PROJECTED, "reason": "source is a projection", "flags": flags}
    if status in _CONFIRMED or certainty in _CONFIRMED:
        if not pregame:
            return {"class": POSTGAME_ACTUAL, "reason": "confirmed but observed at/after start", "flags": flags}
        if "SOURCE_TIME_AFTER_OBSERVATION" in flags:
            return {"class": UNKNOWN, "reason": "source time later than our observation (clock anomaly)", "flags": flags}
        return {"class": VERIFIED_PREGAME, "reason": "source-confirmed before start",
                "minutes_to_start": round((start - obs).total_seconds() / 60, 1), "flags": flags}
    if status in _PROJECTED_WORDS:
        return {"class": PROJECTED, "reason": f"status '{status}'", "flags": flags}
    if status in _GENERIC_ACTIVE:
        return {"class": UNKNOWN, "reason": "generic Active/available is not a starter report", "flags": flags}
    return {"class": UNKNOWN, "reason": f"unrecognised status '{status}'", "flags": flags}

"""Versioned shared evaluation schema (``sift-alpha-eval/1``).

Edge Finders export READ-ONLY JSONL rows of four kinds: forecast, outcome, quote, fill. Alpha never imports their
engines. Every row carries ``schema``. Unknown versions are refused, not coerced.

Status vocabulary (every forecast ends in exactly one, with a reason code - nothing is silently dropped):
  GRADED       scored against a valid outcome with all integrity checks passed
  PENDING      outcome not yet final (event not over / no outcome row yet)
  UNSUPPORTED  Alpha has no valid scoring rule for this contract/forecast shape (explicit reason)
  BLOCKED      a rule could score it, but an integrity or data requirement failed (explicit reason)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "sift-alpha-eval/1"
SPORTS = ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS")

GRADED, PENDING, UNSUPPORTED, BLOCKED = "GRADED", "PENDING", "UNSUPPORTED", "BLOCKED"
STATUSES = (GRADED, PENDING, UNSUPPORTED, BLOCKED)

# market families (user-facing list in the standard)
MONEYLINE, SPREAD, ALT_SPREAD, TOTAL, ALT_TOTAL = "MONEYLINE", "SPREAD", "ALT_SPREAD", "TOTAL", "ALT_TOTAL"
TEAM_TOTAL, ALT_TEAM_TOTAL, PERIOD, PLAYER_PROP, LADDER = "TEAM_TOTAL", "ALT_TEAM_TOTAL", "PERIOD", "PLAYER_PROP", "LADDER"
FUTURE, OTHER_EVENT, COMBO, OFF_FIELD, UNCLASSIFIED = "FUTURE", "OTHER_EVENT", "COMBO", "OFF_FIELD", "UNCLASSIFIED"
FAMILIES = (MONEYLINE, SPREAD, ALT_SPREAD, TOTAL, ALT_TOTAL, TEAM_TOTAL, ALT_TEAM_TOTAL, PERIOD, PLAYER_PROP, LADDER,
            FUTURE, OTHER_EVENT, COMBO, OFF_FIELD, UNCLASSIFIED)

# scoring types: the forecast payload decides the score; a binary Brier is never applied to a non-binary payload
BINARY, CONTINUOUS, ORDINAL_PMF, CATEGORICAL = "BINARY", "CONTINUOUS", "ORDINAL_PMF", "CATEGORICAL"
SCORING_TYPES = (BINARY, CONTINUOUS, ORDINAL_PMF, CATEGORICAL)

# evidence classes: never pooled
HISTORICAL, BACKTEST, PROSPECTIVE = "HISTORICAL", "BACKTEST", "PROSPECTIVE"
EVIDENCE_CLASSES = (HISTORICAL, BACKTEST, PROSPECTIVE)
SPORTS_ONLY, MARKET_INFORMED = "sports_only", "market_informed"

MAIN, ALTERNATE, LADDER_RUNG = "MAIN", "ALTERNATE", "LADDER_RUNG"
LINE_ROLES = (MAIN, ALTERNATE, LADDER_RUNG)

# reason codes
R = type("R", (), dict(
    OK="OK", NO_OUTCOME="NO_OUTCOME_ROW", EVENT_NOT_FINAL="EVENT_NOT_FINAL", VOID="OUTCOME_VOID_OR_POSTPONED",
    NOT_FROZEN="FORECAST_NOT_FROZEN_BEFORE_EVENT_START", AFTER_OUTCOME="FORECAST_FROZEN_AFTER_OUTCOME_OBSERVED",
    NO_MODEL_VERSION="MODEL_VERSION_MISSING", TYPE_MISMATCH="SCORING_TYPE_NOT_ALLOWED_FOR_CONTRACT",
    BAD_PAYLOAD="FORECAST_PAYLOAD_INVALID", BAD_OUTCOME="OUTCOME_PAYLOAD_INVALID_FOR_SCORING_TYPE",
    INDEPENDENCE="SPORTS_ONLY_MODEL_DECLARES_MARKET_INPUT", NO_INDEPENDENCE="MODEL_INDEPENDENCE_UNDECLARED",
    COMBO="COMBO_REQUIRES_JOINT_DISTRIBUTION", OFF_FIELD="OFF_FIELD_NO_SPORTS_OUTCOME_SOURCE",
    UNCLASSIFIED="UNCLASSIFIED_FAMILY", UNKNOWN_SPORT="UNSUPPORTED_SPORT", NO_QUOTE="NO_PIT_QUOTE_AT_FORECAST_TIME",
    STALE_QUOTE="PIT_QUOTE_TOO_OLD", ONE_SIDED="PIT_QUOTE_ONE_SIDED_OR_CROSSED", NO_CLOSE="NO_VALID_CLOSING_QUOTE",
    NO_FILL="NO_VERIFIED_FILL", DUPLICATE="DUPLICATE_FORECAST_ID", NOT_APPLICABLE="NOT_APPLICABLE_NONBINARY",
    MULTI_FREEZE="OUTCOME_OBSERVED_BEFORE_FREEZE_TIMESTAMP_UNVERIFIABLE",
))


class SchemaError(ValueError):
    pass


def parse_ts(v: Any, desc: str = "timestamp") -> datetime:
    """Strict, timezone-aware UTC. Naive timestamps are refused (point-in-time joins need an unambiguous clock)."""
    if isinstance(v, datetime):
        d = v
    else:
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError as e:
            raise SchemaError(f"{desc}: unparseable {v!r}") from e
    if d.tzinfo is None:
        raise SchemaError(f"{desc}: naive timestamp {v!r}")
    return d.astimezone(timezone.utc)


def opt_ts(v: Any, desc: str = "timestamp") -> Optional[datetime]:
    return None if v in (None, "") else parse_ts(v, desc)


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    sport: str
    event_id: str
    market_id: str                      # exchange ticker / contract identity (threshold included)
    model_id: str
    model_version: str
    model_independence: Optional[str]   # sports_only | market_informed | None (undeclared => BLOCKED for comparisons)
    frozen_at: datetime
    event_start: datetime
    evidence_class: str
    scoring_type: str
    payload: dict
    native_family: str = ""
    line_role: str = MAIN
    line: Optional[float] = None
    market_inputs_used: tuple = ()
    group_id: str = ""                  # correlation cluster (defaults to event_id)
    meta: dict = field(default_factory=dict)

    @property
    def horizon_hours(self) -> float:
        return (self.event_start - self.frozen_at).total_seconds() / 3600.0


@dataclass(frozen=True)
class Outcome:
    market_id: str
    event_id: str
    state: str                          # final | void | pending
    observed_at: Optional[datetime]
    source: str                         # sports | market_settlement
    value: Any = None                   # bool/0-1 | number | category label


@dataclass(frozen=True)
class QuoteRow:
    market_id: str
    observed_at: datetime
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    source: str = "archive"


@dataclass(frozen=True)
class FillRow:
    forecast_id: str
    market_id: str
    side: str
    price: float                        # FEE-EXCLUSIVE exchange fill price on the purchased side
    count: float
    fee: Optional[float]
    is_taker: Optional[bool]
    filled_at: datetime


def _need(row: dict, keys: tuple, kind: str) -> None:
    missing = [k for k in keys if row.get(k) in (None, "")]
    if missing:
        raise SchemaError(f"{kind}: missing {missing}")
    if row.get("schema") != SCHEMA_VERSION:
        raise SchemaError(f"{kind}: schema {row.get('schema')!r} != {SCHEMA_VERSION!r}")


def forecast_from_row(row: dict) -> Forecast:
    """Parses structure only; semantic integrity (freeze, independence, payload shape) is judged in grading so the row
    can still be COUNTED with a reason instead of vanishing at parse time."""
    _need(row, ("forecast_id", "sport", "event_id", "market_id", "model_id", "frozen_at", "event_start",
                "evidence_class", "scoring_type", "payload"), "forecast")
    if row["sport"] not in SPORTS:
        raise SchemaError(f"forecast: sport {row['sport']!r} not in {SPORTS}")
    if row["evidence_class"] not in EVIDENCE_CLASSES:
        raise SchemaError(f"forecast: evidence_class {row['evidence_class']!r}")
    if row["scoring_type"] not in SCORING_TYPES:
        raise SchemaError(f"forecast: scoring_type {row['scoring_type']!r}")
    if not isinstance(row["payload"], dict):
        raise SchemaError("forecast: payload must be an object")
    ind = row.get("model_independence")
    if ind not in (None, SPORTS_ONLY, MARKET_INFORMED):
        raise SchemaError(f"forecast: model_independence {ind!r}")
    role = row.get("line_role", MAIN)
    if role not in LINE_ROLES:
        raise SchemaError(f"forecast: line_role {role!r}")
    return Forecast(
        forecast_id=str(row["forecast_id"]), sport=row["sport"], event_id=str(row["event_id"]),
        market_id=str(row["market_id"]), model_id=str(row["model_id"]), model_version=str(row.get("model_version") or ""),
        model_independence=ind, frozen_at=parse_ts(row["frozen_at"], "frozen_at"),
        event_start=parse_ts(row["event_start"], "event_start"), evidence_class=row["evidence_class"],
        scoring_type=row["scoring_type"], payload=row["payload"], native_family=str(row.get("native_family") or ""),
        line_role=role, line=row.get("line"), market_inputs_used=tuple(row.get("market_inputs_used") or ()),
        group_id=str(row.get("group_id") or row["event_id"]), meta=dict(row.get("meta") or {}))


def outcome_from_row(row: dict) -> Outcome:
    _need(row, ("market_id", "event_id", "state", "source"), "outcome")
    if row["state"] not in ("final", "void", "pending"):
        raise SchemaError(f"outcome: state {row['state']!r}")
    if row["source"] not in ("sports", "market_settlement"):
        raise SchemaError(f"outcome: source {row['source']!r}")
    return Outcome(str(row["market_id"]), str(row["event_id"]), row["state"], opt_ts(row.get("observed_at"), "observed_at"),
                   row["source"], row.get("value"))


def quote_from_row(row: dict) -> QuoteRow:
    _need(row, ("market_id", "observed_at"), "quote")
    f = lambda k: None if row.get(k) is None else float(row[k])  # noqa: E731
    return QuoteRow(str(row["market_id"]), parse_ts(row["observed_at"], "observed_at"), f("yes_bid"), f("yes_ask"),
                    str(row.get("source") or "archive"))


def fill_from_row(row: dict) -> FillRow:
    _need(row, ("forecast_id", "market_id", "side", "price", "count", "filled_at"), "fill")
    return FillRow(str(row["forecast_id"]), str(row["market_id"]), str(row["side"]).upper(), float(row["price"]),
                   float(row["count"]), None if row.get("fee") is None else float(row["fee"]),
                   row.get("is_taker"), parse_ts(row["filled_at"], "filled_at"))

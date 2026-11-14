"""Usable-availability classifier (CBB and any roster-derived availability archive).

Measured motivation (2026-11-10, cbb-edge-finder availability-archive): every row of every capture is
status=available / native_status=Active / confidence=no_report with all injury_* fields null, and every raw
league_injuries payload is an empty list. A roster row with no report is the ABSENCE of information, not evidence that
the player is healthy, so such a report must never count as a usable availability observation.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

NO_INFO_CONFIDENCE = {None, "", "no_report", "none", "unknown"}
INJURY_FIELDS = ("injury_status", "injury_comment", "injury_type", "injury_date")
ROSTER_DEFAULT_NATIVE = {None, "", "active"}


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def is_placeholder_availability_row(row: Mapping[str, Any]) -> bool:
    """True when the row carries no availability evidence (default 'available' filled in from a roster)."""
    if any(not _blank(row.get(k)) for k in INJURY_FIELDS):
        return False
    conf = row.get("confidence")
    conf = conf.strip().lower() if isinstance(conf, str) else conf
    if conf not in NO_INFO_CONFIDENCE:
        return False
    native = row.get("native_status")
    native = native.strip().lower() if isinstance(native, str) else native
    if native not in ROSTER_DEFAULT_NATIVE:
        return False  # a non-default native status (e.g. 'Out', 'Questionable') is evidence
    if row.get("status_changed") is True:
        return False
    adj = row.get("expected_minutes_adjustment")
    if adj not in (None, 0, 0.0):
        return False
    return True


def classify_availability_capture(rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
                                  raw_injuries_payload: Mapping[str, Any] | Sequence[Any] | None = None) -> dict[str, Any]:
    """Return {'usable': bool, 'reason': str, counts...}.

    Reasons (usable only for EVIDENCE_PRESENT):
      EMPTY_CAPTURE         no rows at all
      EMPTY_SOURCE_PAYLOAD  raw payload supplied and carries no injuries, and no row carries evidence
      PLACEHOLDER_ONLY      rows exist but every one is a no_report/Active/available default
      EVIDENCE_PRESENT      at least one row carries injury/status evidence
    """
    rows = list(rows)
    n = len(rows)
    evidence = [r for r in rows if not is_placeholder_availability_row(r)]
    payload_n: int | None = None
    if raw_injuries_payload is not None:
        inj = raw_injuries_payload.get("injuries") if isinstance(raw_injuries_payload, Mapping) else raw_injuries_payload
        payload_n = len(inj) if isinstance(inj, (list, tuple)) else None
    out = {"rows": n, "placeholder_rows": n - len(evidence), "evidence_rows": len(evidence), "raw_payload_injuries": payload_n}
    if n == 0:
        return {"usable": False, "reason": "EMPTY_CAPTURE", **out}
    if not evidence:
        reason = "EMPTY_SOURCE_PAYLOAD" if payload_n == 0 else "PLACEHOLDER_ONLY"
        return {"usable": False, "reason": reason, **out}
    return {"usable": True, "reason": "EVIDENCE_PRESENT", **out}

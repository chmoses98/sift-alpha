"""Independent calculation of audited fields; reject altered research summaries."""
from __future__ import annotations

from typing import Any
from .audits import audit_cfb, audit_mlb


def independent_review(report: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Separate reference calculation runs before the audit can be published.

    The report is still exploratory; equality with source-derived descriptive
    metrics does NOT establish external source accuracy or profitable edge.
    """
    if report.get("version") != 1 or report.get("authority") != "RESEARCH_ONLY":
        return {"passed": False, "reason": "Invalid authority or report version"}
    expected = {
        "cfb_prospective_settlements": audit_cfb(inputs["cfb_prospective_settlements"]),
        "mlb_replay_status": audit_mlb(inputs["mlb_replay_status"]),
    }
    if report.get("studies") != expected:
        return {"passed": False, "reason": "Reported data do not reproduce from raw inputs"}
    if any(study["promotion_eligible"] for study in expected.values()):
        return {"passed": False, "reason": "Retroactive data may not grant trading authority"}
    return {"passed": True, "reason": "Historical descriptives reproduced, research-only"}

"""Fail-closed research coordination primitives for SIFT Alpha.

No paid APIs, no remote requests, no wagering, and no claims of discovery.
Python standard library only. This selects research/data-audit *work*, not bets.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_PROJECT = (
    "id", "sport", "question", "mechanism", "null_hypothesis",
    "target", "unit", "confounders", "sources", "priority",
)
REQUIRED_SOURCE = (
    "id", "provider", "source_url", "access_class", "charge_mode",
    "license_status", "temporal_status", "schema_status",
)


def utc_time(value: str) -> datetime:
    """Require explicit UTC for every point-in-time checkpoint."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Time must be an explicit UTC ISO-8601 timestamp ending in Z")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if result.tzinfo != timezone.utc:
        raise ValueError("UTC timestamps required")
    return result


def reject_cost(source: dict[str, Any]) -> list[str]:
    """Fail closed if free-use terms or possible billing are unknown."""
    faults = []
    if source.get("access_class") != "public_free":
        faults.append("access not certified free")
    if source.get("charge_mode") != "none":
        faults.append("source could generate charges")
    if source.get("estimated_usd") != 0:
        faults.append("source cost is not explicitly zero")
    if source.get("cost_verified") is not True:
        faults.append("zero-cost terms not verified")
    return faults


def audit_source(source: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_SOURCE if key not in source]
    faults = ["missing field: " + key for key in missing] + reject_cost(source)
    if source.get("license_status") != "reviewed":
        faults.append("data rights/terms not reviewed")
    if source.get("temporal_status") != "verified":
        faults.append("point-in-time availability not verified")
    if source.get("schema_status") != "verified":
        faults.append("identity, completeness and schema not verified")
    return {
        "source_id": source.get("id", "unknown"),
        "ready": not faults,
        "faults": sorted(set(faults)),
    }


def audit_project(project: dict[str, Any], source_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    faults = ["missing project field: " + key for key in REQUIRED_PROJECT if key not in project]
    for key in ("confounders", "sources"):
        if not isinstance(project.get(key), list) or not project.get(key):
            faults.append(key + " must be a nonempty list")
    if not isinstance(project.get("priority"), int) or not 0 <= project["priority"] <= 100:
        faults.append("priority must be 0..100")
    missing_sources = [sid for sid in project.get("sources", []) if sid not in source_map]
    faults += ["unregistered source: " + str(sid) for sid in missing_sources]
    audits = [audit_source(source_map[sid]) for sid in project.get("sources", []) if sid in source_map]
    cost_faults = any(reject_cost(source_map[sid]) for sid in project.get("sources", []) if sid in source_map)
    if faults or cost_faults:
        kind = "BLOCKED"
    elif any(not audit["ready"] for audit in audits):
        kind = "QUALIFY_DATA"
    else:
        # This does not mean an experiment is approved. A protocol and data snapshot
        # must separately pass independent checks before execution.
        kind = "DESIGN_PROTOCOL"
    return {
        "project_id": project.get("id", "unknown"),
        "sport": project.get("sport", "unknown"),
        "action": kind,
        "faults": faults,
        "source_audits": audits,
    }


def decide_next(queue: dict[str, Any], registry: dict[str, Any], history: dict[str, int] | None = None) -> dict[str, Any]:
    """Choose a defensible next *research task* with repeatable sport rotation.

    Priorities are registered ex ante; this planner does NOT inspect future
    scores, choose contracts, or manufacture exploratory findings.
    """
    if queue.get("schema_version") != 1 or registry.get("schema_version") != 1:
        raise ValueError("Unsupported queue/registry version")
    projects = queue.get("projects")
    sources = registry.get("sources")
    if not isinstance(projects, list) or not isinstance(sources, list):
        raise ValueError("Projects and sources must be arrays")
    if len({row.get("id") for row in sources}) != len(sources):
        raise ValueError("Duplicate source IDs")
    if len({row.get("id") for row in projects}) != len(projects):
        raise ValueError("Duplicate project IDs")
    source_map = {row["id"]: row for row in sources}
    history = history or {}
    candidates = []
    blocked = []
    for project in projects:
        audit = audit_project(project, source_map)
        if audit["action"] == "BLOCKED":
            blocked.append(audit)
            continue
        visited = max(0, min(100, int(history.get(project["id"], 0))))
        # Reward readiness and unexplored sports. No result quality/EV is inferred.
        score = project["priority"] + (25 if audit["action"] == "DESIGN_PROTOCOL" else 0) - 10 * visited
        candidates.append((score, project["id"], audit, project))
    if not candidates:
        return {"status": "NO_ELIGIBLE_WORK", "next": None, "blocked": blocked}
    _, _, audit, project = sorted(candidates, key=lambda x: (-x[0], x[1]))[0]
    if audit["action"] == "QUALIFY_DATA":
        required = [entry for entry in audit["source_audits"] if not entry["ready"]]
        next_text = "Verify free access, data rights, historical coverage, identity, and point-in-time integrity of listed sources."
    else:
        required = []
        next_text = "Register baseline, leakage-safe split, independent outcome and validation protocol before running any experiment."
    return {
        "status": "WORK_PLANNED_NOT_EXECUTED",
        "next": {
            "project_id": audit["project_id"],
            "sport": audit["sport"],
            "question": project["question"],
            "action": audit["action"],
            "reason": next_text,
            "sources_requiring_qualification": required,
        },
        "blocked": blocked,
    }


def audit_prediction_rows(rows: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    """Boundary check: features existed before the decision and before event start.

    This is one necessary integrity check, not proof of unbiased sampling,
    reproducibility, independent labels, or profitable predictions.
    """
    faults = []
    seen = set()
    if not isinstance(rows, list) or len(rows) < minimum:
        faults.append("insufficient rows for registered sample requirement")
    for index, row in enumerate(rows):
        try:
            identity = (row["event_id"], row["entity_id"], row["cutoff_at"])
            if identity in seen:
                faults.append(f"row {index}: duplicate decision identity")
            seen.add(identity)
            cutoff = utc_time(row["cutoff_at"])
            event = utc_time(row["event_start_at"])
            observed = utc_time(row["feature_observed_at"])
            if not observed <= cutoff < event:
                faults.append(f"row {index}: feature leakage or non-pregame cutoff")
            if "label_observed_at" in row and utc_time(row["label_observed_at"]) < event:
                faults.append(f"row {index}: label timestamp precedes event")
        except (KeyError, TypeError, ValueError) as exc:
            faults.append(f"row {index}: invalid decision record ({type(exc).__name__})")
    return {"passed": not faults, "count": len(rows), "faults": faults}


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be object")
    return data


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

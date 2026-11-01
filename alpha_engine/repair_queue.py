"""Bounded research queue controller: a blocked case cannot monopolize the queue.

This orchestrates verified task results; it does not pretend to fix source data.
"""
from __future__ import annotations

ALLOWED = {"REPAIRED_VERIFIED", "BLOCKED", "FAILED", "PENDING"}
def choose_next(cases, results, max_attempts=2):
    """Select next actionable defect, preserving blocked cases and denominators."""
    if not isinstance(cases, list) or not isinstance(results, dict) or not 1 <= max_attempts <= 10:
        raise ValueError("Invalid queue")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] or case["id"] in seen:
            raise ValueError("Duplicate or invalid defect")
        seen.add(case["id"])
        history = results.get(case["id"], [])
        if not isinstance(history, list):
            raise ValueError("Invalid history")
        if any(not isinstance(item, dict) or item.get("status") not in ALLOWED for item in history):
            raise ValueError("Invalid result")
        if any(item["status"] in ("REPAIRED_VERIFIED", "BLOCKED") for item in history):
            continue
        if sum(item["status"] == "FAILED" for item in history) >= max_attempts:
            continue
        return {"next_id": case["id"], "status": "ACTION_REQUIRED", "attempt": len(history)+1}
    return {"next_id": None, "status": "NO_ACTIONABLE_CASE", "attempt": None}

"""Integrity-first audits for actual (pinned) retrospective data.

These are diagnostics, NOT calibrated models, independent out-of-sample
studies, or evidence of executable bet returns.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any


def stamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Explicit Z timestamp required")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("UTC timestamp required")
    return parsed


def wilson(wins: int, trials: int, z: float = 1.96) -> list[float]:
    p = wins / trials
    denominator = 1 + (z * z) / trials
    middle = (p + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [round(middle - half, 6), round(middle + half, 6)]


def audit_cfb(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """All-source-game audit with explicit price eligibility and exclusions.

    Every record must have valid identity, pregame state and settlement.
    Status PRICE_1_00 (no usable entry) stays in coverage with a reason
    and is not silently added to price-model calibration denominators.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("CFB source must contain records")
    seen: set[str] = set()
    prices: list[float] = []
    results: list[int] = []
    qualities: Counter[str] = Counter()
    captures: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    for index, row in enumerate(rows):
        try:
            if row["schema"] != "cfb_control_prospective_settlement/1.0.0":
                raise ValueError("Unrecognized CFB settlement version")
            game = str(row["event_id"])
            if game in seen:
                raise ValueError("Duplicate event in independent game sample")
            seen.add(game)
            kickoff = stamp(row["kickoff_utc"])
            pregame = stamp(row["final_pregame"]["recorded_at"])
            settled = stamp(row["settled_at"])
            if not pregame < kickoff < settled:
                raise ValueError("Pregame publication or settlement leakage")
            if row["settlement"]["status"] != "SETTLED":
                raise ValueError("Unsettled game in purported final archive")
            y = row["settlement"]["control_won"]
            if type(y) is not bool:
                raise ValueError("Outcome must be a known boolean")
            pts = row["settlement"]["control_points"]
            opponent = row["settlement"]["opponent_points"]
            if type(pts) not in (int, float) or type(opponent) not in (int, float):
                raise ValueError("Invalid official score")
            if pts == opponent or (pts > opponent) is not y:
                raise ValueError("Outcome/score mismatch")
            capture = row["capture"]
            captures[capture["status"]] += 1
            if capture["status"] == "PRICE_1_00":
                if capture.get("entry") is not None:
                    raise ValueError("Excluded PRICE_1_00 must have no valid entry")
                exclusions["no_usable_pregame_quote"] += 1
                continue
            if capture["status"] != "CAPTURE_OK":
                raise ValueError("Unknown capture status")
            if not isinstance(capture.get("entry"), dict):
                raise ValueError("Capture-OK without price observation")
            first = stamp(capture["entry"]["captured_at"])
            open_at = stamp(capture["window_opens_at"])
            close_at = stamp(capture["window_closes_at"])
            if not open_at <= first <= close_at < kickoff:
                raise ValueError("Capture outside valid pregame window")
            p = capture["entry"]["price"]
            if type(p) not in (int, float) or not math.isfinite(p) or not 0 < p < 1:
                raise ValueError("Invalid contemporaneous quote")
            qualities[str(row["final_pregame"]["data_quality"])] += 1
            prices.append(float(p))
            results.append(int(y))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"CFB row {index}: {exc}") from exc
    n = len(prices)
    if not n:
        raise ValueError("No price-eligible CFB rows; cannot score market quotes")
    wins = sum(results)
    return {
        "sport": "CFB",
        "kind": "point_in_time_market_vs_outcome_descriptive_audit",
        "n_source_games": len(rows),
        "n_independent_games": n,
        "n_excluded": len(rows) - n,
        "exclusion_counts": dict(sorted(exclusions.items())),
        "capture_status_counts": dict(sorted(captures.items())),
        "n_wins": wins,
        "brier_market_price": round(sum((p - y) ** 2 for p, y in zip(prices, results)) / n, 6),
        "mean_captured_quote": round(sum(prices) / n, 6),
        "observed_win_fraction": round(wins / n, 6),
        "observed_win_wilson_95": wilson(wins, n),
        "quality_counts": dict(sorted(qualities.items())),
        "evaluation_population": "All price-eligible distinct games; excluded source games and reasons included",
        "statistical_conclusion": "DESCRIPTIVE_ONLY",
        "promotion_eligible": False,
        "reason": "No independent reserved holdout, no proof of executable asks/depth, small selected control sample. Retrospective summary cannot establish trading advantage.",
    }


def audit_mlb(records: dict[str, Any]) -> dict[str, Any]:
    """Real MLB research eligibility archive, not pitch-level or model data."""
    if not isinstance(records, dict) or not records:
        raise ValueError("Missing MLB replay archive")
    outcomes: Counter[str] = Counter()
    eligible = 0
    for key, item in records.items():
        if not isinstance(item, dict) or item.get("date") != key:
            raise ValueError("MLB replay date/record identity mismatch")
        try:
            stamp(item["recordedAt"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid MLB recordedAt for {key}") from exc
        state = item.get("outcome")
        if state not in ("completed", "rejected_ineligible", "not_applicable_no_decision", "no_snapshot"):
            raise ValueError(f"Unrecognized MLB status for {key}")
        if state == "completed":
            if item.get("eligibilityStatus") != "ELIGIBLE_LEVEL_2" or item.get("runStatus") != "COMPLETED":
                raise ValueError("Completed replay missing explicit eligibility")
            eligible += 1
        if state == "rejected_ineligible" and item.get("eligibilityStatus") != "INELIGIBLE_MISSING_INPUT":
            raise ValueError("Missing-input status mismatch")
        outcomes[state] += 1
    return {
        "sport": "MLB",
        "kind": "historical_replay_input_coverage_audit",
        "n_archived_dates": len(records),
        "n_eligible_completed_replays": eligible,
        "outcome_counts": dict(sorted(outcomes.items())),
        "statistical_conclusion": "DATA_COVERAGE_ONLY",
        "promotion_eligible": False,
        "reason": "Replay status is not pitch-level tracking, game outcomes, player projections, or executable trading returns. Missing-input days cannot be counted as valid forecasts.",
    }

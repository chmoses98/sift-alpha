"""Scientific input-integrity gates for game context and model forecasts.

Checks internal consistency, provenance, time availability and distribution
invariants. It is deliberately *not* an independent certification that any
third-party statistic, team roster or event clock is factually correct.

No remote calls, betting, external inference or paid services.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

SHA = re.compile(r"^[a-f0-9]{64}$")
SPORTS = {"NFL", "CFB", "NBA", "NHL", "MLB", "CBB", "SOCCER", "TENNIS"}


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Explicit UTC timestamp ending in Z required")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if dt.tzinfo != timezone.utc:
        raise ValueError("Non-UTC timestamp")
    return dt


def status(issues: list[str], limitations: list[str], domain: str) -> dict[str, Any]:
    issues = sorted(set(issues))
    limitations = sorted(set(limitations))
    return {
        "domain": domain,
        "state": "QUARANTINED" if issues else "LIMITED" if limitations else "STRUCTURE_PASS_UNCERTIFIED",
        "blocking_errors": issues,
        "unverified_or_missing_evidence": limitations,
        "scientific_certification": "NOT_INDEPENDENTLY_ESTABLISHED",
        "promotion_allowed": False,
    }


def context(record: dict[str, Any], decision_at: str) -> dict[str, Any]:
    """Reject contradictory identities and any future-observed pregame inputs.

    Actual game start can be a bounded interval from independent observation,
    but unknown start or overlap must NOT be silently certified pregame.
    """
    bad, limits = [], []
    try:
        decision = utc(decision_at)
    except (ValueError, TypeError):
        return status(["invalid decision timestamp"], [], "GAME_CONTEXT")
    if not isinstance(record, dict):
        return status(["context record missing"], [], "GAME_CONTEXT")
    if not isinstance(record.get("sport"), str) or record["sport"] not in SPORTS or not isinstance(record.get("event_id"), str) or not record["event_id"]:
        bad.append("unknown sport or physical-event identity")
    home, away = record.get("home_team_id"), record.get("away_team_id")
    if not isinstance(home, str) or not home or not isinstance(away, str) or not away or home == away:
        bad.append("invalid home/away physical-team mapping")
    try:
        scheduled = utc(record["scheduled_start_at"])
        # Scheduled start alone is NEVER proof of actual start.
        if scheduled.year < 2000:
            bad.append("implausible scheduled time")
    except (KeyError, ValueError, TypeError):
        bad.append("invalid scheduled start")
    bracket = record.get("actual_start_bracket")
    if bracket is None:
        limits.append("actual event start unverified; scheduled time insufficient")
    else:
        try:
            lower = utc(bracket["lower_bound_utc"])
            upper = utc(bracket["upper_bound_utc"])
            if lower > upper:
                bad.append("actual start bracket reversed")
            elif decision < lower:
                pass
            elif decision >= upper:
                bad.append("decision observation at/after actual game start")
            else:
                limits.append("decision lies inside uncertain game-start bracket")
            if not bracket.get("independent_evidence_id"):
                limits.append("actual start bounds lack independent proof")
        except (ValueError, TypeError, KeyError):
            bad.append("invalid game-start evidence interval")
    sources = record.get("sources", [])
    roots = set()
    source_by_id = {}
    if not isinstance(sources, list) or not sources:
        limits.append("source provenance missing")
        sources = []
    for i, source in enumerate(sources):
        if not isinstance(source, dict):
            bad.append(f"source {i}: malformed provenance")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id.strip():
            bad.append(f"source {i}: missing source identity")
        elif source_id in source_by_id:
            bad.append(f"source {i}: duplicate source identity")
        else:
            source_by_id[source_id] = source
        root = source.get("original_provider")
        if not isinstance(root, str) or not root.strip():
            limits.append(f"source {i}: underlying provider not identified")
        else:
            roots.add(root.strip().lower())
        if source.get("rights_checked") is not True:
            limits.append(f"source {i}: data usage rights unverified")
        observed = source.get("observed_at")
        try:
            if utc(observed) > decision:
                bad.append(f"source {i}: future-observed source")
        except (ValueError, TypeError):
            bad.append(f"source {i}: missing/invalid observation clock")
        available = source.get("available_at")
        if available is None:
            limits.append(f"source {i}: independent availability clock missing")
        else:
            try:
                if utc(available) > decision:
                    bad.append(f"source {i}: source not available by decision cutoff")
            except (ValueError, TypeError):
                bad.append(f"source {i}: invalid availability clock")
    if len(roots) < 2:
        limits.append("independent original-provider corroboration not established")
    facts = record.get("facts", [])
    if not isinstance(facts, list):
        bad.append("facts must be a list")
        facts = []
    seen = {}
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict) or not isinstance(fact.get("name"), str):
            bad.append(f"fact {i}: invalid fact descriptor")
            continue
        source_key = fact.get("source_id")
        source = source_by_id.get(source_key) if isinstance(source_key, str) else None
        if source is None:
            bad.append(f"fact {i}: unregistered source")
        try:
            fact_observed = utc(fact.get("observed_at"))
            if fact_observed > decision:
                bad.append(f"fact {i}: observed after decision cutoff")
            if source is not None and fact_observed > utc(source.get("observed_at")):
                bad.append(f"fact {i}: observation newer than its source capture")
        except (ValueError, TypeError):
            bad.append(f"fact {i}: invalid observation or source clock")
        fact_available = fact.get("available_at")
        if fact_available is None:
            limits.append(f"fact {i}: fact availability clock missing")
        else:
            try:
                available = utc(fact_available)
                if available > decision:
                    bad.append(f"fact {i}: unavailable by decision cutoff")
                if available < utc(fact.get("observed_at")):
                    bad.append(f"fact {i}: availability precedes observation")
            except (ValueError, TypeError):
                bad.append(f"fact {i}: invalid availability clock")
        if fact.get("status") not in ("OBSERVED", "CONFIRMED", "ESTIMATED", "UNKNOWN"):
            bad.append(f"fact {i}: unsupported confidence descriptor")
        if fact.get("status") in ("ESTIMATED", "UNKNOWN"):
            limits.append(f"fact {i}: estimate/unknown cannot be treated as observed truth")
        subject_id = fact.get("subject_id")
        if subject_id is not None and not isinstance(subject_id, str):
            bad.append(f"fact {i}: invalid subject identity")
        identity = (fact["name"], subject_id if isinstance(subject_id, str) else None)
        current = (fact.get("value"), fact.get("observed_at"))
        if identity in seen and seen[identity][1] == current[1] and seen[identity][0] != current[0]:
            bad.append(f"fact {i}: conflicting values at identical observation timestamp")
        seen[identity] = current
        if fact["name"] in ("player_roster_membership", "starter_team_id", "lineup_team_id"):
            if fact.get("value") not in (home, away):
                bad.append(f"fact {i}: participant assigned to team outside matchup")
            if fact.get("status") != "CONFIRMED":
                limits.append(f"fact {i}: roster/starter not independently confirmed")
        if fact["name"] in ("injury_status", "confirmed_lineup", "projected_starter") and fact.get("status") != "CONFIRMED":
            limits.append(f"fact {i}: availability or lineup is not confirmed")
    return status(bad, limits, "GAME_CONTEXT")


def projection(record: dict[str, Any], context_record: dict[str, Any], decision_at: str) -> dict[str, Any]:
    """Audit point-in-time publication, immutable model identity and probabilities.

    Passing a structural gate does NOT establish calibration, predictive
    accuracy, truthful roster information or provenance independence.
    """
    bad, limits = [], []
    try:
        decision = utc(decision_at)
    except (ValueError, TypeError):
        return status(["invalid decision timestamp"], [], "PROJECTION")
    if not isinstance(record, dict):
        return status(["projection record missing"], [], "PROJECTION")
    if record.get("event_id") != context_record.get("event_id") or record.get("sport") != context_record.get("sport"):
        bad.append("projection targets wrong physical game or sport")
    if not isinstance(record.get("model_version"), str) or not record["model_version"]:
        bad.append("missing versioned model")
    for field in ("model_sha256", "input_snapshot_sha256"):
        if not SHA.fullmatch(record.get(field, "")):
            bad.append("missing immutable " + field)
    if record.get("target_definition_verified") is not True:
        limits.append("target/statistic definition not independently verified")
    for field in ("published_at", "model_fit_at", "last_training_label_at", "latest_input_observed_at"):
        try:
            at = utc(record.get(field))
            if at > decision:
                bad.append(field + " is after decision cutoff")
        except (ValueError, TypeError):
            bad.append("missing/invalid " + field)
    # Observation and availability are distinct: an input or corrected label
    # may have been observed historically but unavailable to the model then.
    for available_field, observed_field, latest_allowed in (
        ("latest_input_available_at", "latest_input_observed_at", "published_at"),
        ("last_training_label_available_at", "last_training_label_at", "model_fit_at"),
    ):
        value = record.get(available_field)
        if value is None:
            limits.append(available_field + " missing; feature/label availability unverified")
        else:
            try:
                at = utc(value)
                if at > decision or at > utc(record.get(latest_allowed)):
                    bad.append(available_field + " after decision or model cutoff")
                if at < utc(record.get(observed_field)):
                    bad.append(available_field + " precedes observation")
            except (ValueError, TypeError):
                bad.append("invalid " + available_field)
    try:
        if utc(record.get("last_training_label_at")) > utc(record.get("model_fit_at")):
            bad.append("training outcome observed after model fit")
        if utc(record.get("latest_input_observed_at")) > utc(record.get("published_at")):
            bad.append("feature used from after forecast was published")
        if utc(record.get("model_fit_at")) > utc(record.get("published_at")):
            bad.append("forecast published before its model was fit")
    except (ValueError, TypeError):
        pass
    person = record.get("player_id")
    if person is not None:
        if not isinstance(person, str) or not person:
            bad.append("invalid player id")
        assigned = record.get("player_team_id")
        if assigned not in (context_record.get("home_team_id"), context_record.get("away_team_id")):
            bad.append("projected player assigned to team outside game")
        relevant = [f for f in context_record.get("facts", []) if isinstance(f, dict)
                    and f.get("name") in ("player_roster_membership", "lineup_team_id")
                    and f.get("subject_id") == person and f.get("status") == "CONFIRMED"]
        if not relevant:
            limits.append("player membership not confirmed at decision time")
        elif any(f.get("value") != assigned for f in relevant):
            bad.append("projection player-team conflicts with game-context evidence")
    forecast = record.get("distribution")
    if not isinstance(forecast, dict):
        bad.append("no probability distribution")
    elif forecast.get("kind") == "binary":
        p = forecast.get("p_yes")
        if type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1:
            bad.append("binary probability not finite in [0,1]")
    elif forecast.get("kind") == "categorical":
        values = forecast.get("probabilities")
        if not isinstance(values, dict) or len(values) < 2 or any(
            not isinstance(k, str) or not k or type(v) not in (float, int)
            or not math.isfinite(v) or v < 0 or v > 1 for k,v in values.items()
        ):
            bad.append("invalid categorical distribution")
        elif abs(sum(values.values()) - 1.0) > 0.000001:
            bad.append("categorical probabilities do not sum to 1")
    elif forecast.get("kind") == "quantiles":
        quantiles = forecast.get("values")
        try:
            parsed = [(float(q), float(v)) for q, v in quantiles.items()]
            if len(parsed) < 2 or any(not math.isfinite(q) or not math.isfinite(v) or q <= 0 or q >= 1 for q,v in parsed):
                raise ValueError("invalid quantile")
            parsed.sort()
            if any(b <= a for ((a, _), (b, _)) in zip(parsed, parsed[1:])):
                raise ValueError("duplicate quantile")
            if any(v2 < v1 for (_, v1),(_, v2) in zip(parsed, parsed[1:])):
                raise ValueError("quantile inversion")
        except (TypeError, ValueError, AttributeError):
            bad.append("invalid or nonmonotonic quantile distribution")
    else:
        bad.append("unknown distribution type")
    if record.get("backtest_holdout_verified") is not True:
        limits.append("independent holdout performance not established")
    if record.get("calibration_evidence_id") is None:
        limits.append("forecast calibration evidence not linked")
    context_gate = context(context_record, decision_at)
    if context_gate["state"] == "QUARANTINED":
        bad.append("underlying game context quarantined")
    elif context_gate["state"] == "LIMITED":
        limits.append("underlying game context limited or unverified")
    return status(bad, limits, "PROJECTION")


def research_eligibility(ctx_gate: dict[str, Any], pred_gate: dict[str, Any]) -> dict[str, Any]:
    """No unreviewed forecast gets elevated to a scientific or trading finding."""
    return {
        "eligible_for_research_claim": False,
        "eligible_for_live_trading": False,
        "data_ready_for_further_external_verification":
            all(g["state"] == "STRUCTURE_PASS_UNCERTIFIED" for g in (ctx_gate, pred_gate)),
        "reason": "Source accuracy, actual-game truth, holdout results and trade economics require independent certification beyond structural validation",
    }

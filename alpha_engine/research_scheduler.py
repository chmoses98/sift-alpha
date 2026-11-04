"""Evidence-gated eight-sport scheduler. Planning only; not a live collector.

Soft early-November weights never substitute for actual market observations.
A separately sourced *scheduled* start does not verify actual start/pregame status.
"""
from datetime import datetime, timezone
from math import log1p
import re

WEIGHTS = {"NFL": 24, "NBA": 22, "CFB": 20, "NHL": 12, "CBB": 12,
           "SOCCER": 5, "TENNIS": 3, "MLB": 2}
SPORTS = tuple(WEIGHTS)
HEX = re.compile(r"[0-9a-f]{64}\Z")
FAMILY = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")


def utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Explicit UTC timestamp required")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if result.tzinfo != timezone.utc:
        raise ValueError("UTC only")
    return result


def integer(x, low, high):
    return type(x) is int and low <= x <= high


def sha(x):
    return isinstance(x, str) and bool(HEX.fullmatch(x))


def plan(now_utc, observations, defects, *, completed_qa=None, limit=32):
    """Bounded tasks from *supplied evidence*, not invented live markets.

    Each observed family: sport, family, observed_contracts, captured_at_utc,
    source_sha256, optional scheduled_start_utc + start_source_sha256.
    Each defect: id, sport, family, severity (1..5), affected_rows, denominator,
    evidence_ready (bool), estimated_minutes (1..240), source_sha256.
    """
    now = utc(now_utc)
    if (not isinstance(observations, list) or len(observations) > 500
            or not isinstance(defects, list) or len(defects) > 500
            or not integer(limit, len(SPORTS), 64)):
        raise ValueError("Unbounded scheduler input")
    completed_qa = completed_qa or {}
    if not isinstance(completed_qa, dict) or any(
            s not in SPORTS or not integer(n, 0, 10000)
            for s, n in completed_qa.items()):
        raise ValueError("Invalid QA history")
    observed = {}
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("Invalid observation")
        sport, family = row.get("sport"), row.get("family")
        if sport not in SPORTS or not isinstance(family, str) or not FAMILY.fullmatch(family):
            raise ValueError("Unknown market family/sport")
        key = (sport, family)
        if (key in observed or not integer(row.get("observed_contracts"), 0, 1000000)
                or not sha(row.get("source_sha256"))):
            raise ValueError("Duplicate/unverified market observation")
        captured = utc(row.get("captured_at_utc"))
        if captured > now:
            raise ValueError("Future market evidence")
        start = row.get("scheduled_start_utc")
        if (start is None) != (row.get("start_source_sha256") is None):
            raise ValueError("Scheduled start needs independent source hash")
        if start is not None:
            utc(start)
            if not sha(row["start_source_sha256"]):
                raise ValueError("Unverified scheduled start")
        observed[key] = (row, captured)
    seen = set()
    for defect in defects:
        if not isinstance(defect, dict):
            raise ValueError("Invalid defect")
        ident = defect.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("Duplicate/invalid defect ID")
        seen.add(ident)
        if (defect.get("sport") not in SPORTS
                or not isinstance(defect.get("family"), str)
                or not FAMILY.fullmatch(defect["family"])
                or not integer(defect.get("severity"), 1, 5)
                or not integer(defect.get("affected_rows"), 0, 1000000000)
                or not integer(defect.get("denominator"), 1, 1000000000)
                or defect["affected_rows"] > defect["denominator"]
                or type(defect.get("evidence_ready")) is not bool
                or not integer(defect.get("estimated_minutes"), 1, 240)
                or not sha(defect.get("source_sha256"))):
            raise ValueError("Malformed defect evidence")
    tasks = []
    for sport in SPORTS:
        tasks.append({"id": "QA:" + sport, "sport": sport, "family": None,
                      "lane": "COLLECTION_QA", "score": 10 + 1/(1 + completed_qa.get(sport, 0)),
                      "observed_contracts": sum(v[0]["observed_contracts"]
                                                for k, v in observed.items() if k[0] == sport),
                      "authority": "AUDIT_ONLY"})
    for (sport, family), (row, captured) in observed.items():
        if row["observed_contracts"] == 0 or (now-captured).total_seconds() > 4*3600:
            continue
        start = row.get("scheduled_start_utc")
        if start is None:
            continue
        minutes = (utc(start)-now).total_seconds()/60
        if 0 <= minutes <= 180:
            tasks.append({"id": "CAPTURE:" + sport + ":" + family,
                          "sport": sport, "family": family, "lane": "PIT_CAPTURE",
                          "score": 1000000-minutes,
                          "source_sha256": row["source_sha256"],
                          "start_source_sha256": row["start_source_sha256"],
                          "authority": "CAPTURE_PRIORITY_NOT_PREGAME_CERTIFICATION"})
    for d in defects:
        key = (d["sport"], d["family"])
        item = observed.get(key)
        if not d["evidence_ready"]:
            lane, score = "SOURCE_GAP_AUDIT", 20+d["severity"]
        elif item is None or item[0]["observed_contracts"] == 0:
            lane, score = "ARCHIVAL_REPAIR", 30+d["severity"]
        elif (now-item[1]).total_seconds() > 24*3600:
            lane, score = "STALE_MARKET_AUDIT", 35+d["severity"]
        else:
            lane = "EVIDENCE_READY_REPAIR"
            score = (40 + 0.35*WEIGHTS[d["sport"]] + 5*d["severity"]
                     + 4*log1p(item[0]["observed_contracts"])
                     + 25*d["affected_rows"]/d["denominator"]
                     - 0.1*d["estimated_minutes"])
        tasks.append({"id": "REPAIR:" + d["id"], "sport": d["sport"],
                      "family": d["family"], "lane": lane, "score": round(score, 6),
                      "affected_rows": d["affected_rows"], "denominator": d["denominator"],
                      "source_sha256": d["source_sha256"],
                      "authority": "RESEARCH_ONLY_NO_MODEL_PROMOTION"})
    order = {"PIT_CAPTURE": 0, "EVIDENCE_READY_REPAIR": 1, "SOURCE_GAP_AUDIT": 2,
             "STALE_MARKET_AUDIT": 2, "ARCHIVAL_REPAIR": 2, "COLLECTION_QA": 3}
    tasks.sort(key=lambda t: (order[t["lane"]], -t["score"], t["id"]))
    qa = [t for t in tasks if t["lane"] == "COLLECTION_QA"]
    work = [t for t in tasks if t["lane"] != "COLLECTION_QA"]
    selected = work[:limit-len(qa)] + qa
    return {"schema_version": 1, "authority": "RESEARCH_ONLY_NOT_LIVE_COLLECTION",
            "asof_utc": now_utc, "soft_november_weights": dict(WEIGHTS),
            "observed_market_families": len(observed),
            "observed_contracts_by_sport": {s: sum(v[0]["observed_contracts"]
                                                  for k, v in observed.items() if k[0] == s)
                                            for s in SPORTS},
            "qa_lane_sports": list(SPORTS), "tasks": selected,
            "unselected_tasks": len(tasks)-len(selected),
            "next": selected[0] if selected else None,
            "actual_game_starts_or_pregame_eligibility_verified": False,
            "capture_daemon_running": False}

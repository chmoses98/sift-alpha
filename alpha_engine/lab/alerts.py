"""Alerts for the prospective capture system (RESEARCH_ONLY).  Pure functions over durable artifacts (heartbeats, observations, ingest results), so every alert is reproducible from the data branch.

HIGH   = data or decisions are being lost or the evidence chain is in doubt;  WARN = degraded but nothing lost yet.
Codes: STALE_HEARTBEAT, MISSED_FIRING, FIRING_FAILED, FIRING_PARTIAL, PUBLISH_FAILED, DECISION_UNCOVERED, SERIES_FAILURE, INCOMPLETE_BOOK, INGEST_REJECTED, UNMAPPED_EVENTS, MISSING_FIELDS,
LEASE_BUSY, FROZEN_MODEL_ABORT, SETTLEMENT_MISMATCH."""
from __future__ import annotations
import pandas as pd

CADENCE_MIN = 60.0
STALE_AFTER_MIN = 90.0


def _t(x):
    return pd.Timestamp(x)


def evaluate(heartbeats: list[dict], observations: list[dict], ingest: dict | None, now, coverage: pd.DataFrame | None = None, since=None, extra: list[dict] | None = None) -> list[dict]:
    now = _t(now); out: list[dict] = list(extra or [])
    cap = sorted((h for h in heartbeats if h.get("role") == "capture"), key=lambda h: h["started_utc"])
    if since is not None:
        cap = [h for h in cap if _t(h["started_utc"]) >= _t(since)]
    if cap:
        age = (now - _t(cap[-1]["started_utc"])).total_seconds() / 60
        if age > STALE_AFTER_MIN:
            out.append({"severity": "HIGH", "code": "STALE_HEARTBEAT", "detail": f"last capture heartbeat {age:.0f} min ago (limit {STALE_AFTER_MIN:.0f})"})
        for a, b in zip(cap, cap[1:]):
            gap = (_t(b["started_utc"]) - _t(a["started_utc"])).total_seconds() / 60
            if gap > STALE_AFTER_MIN:
                out.append({"severity": "HIGH", "code": "MISSED_FIRING", "detail": f"no heartbeat for {gap:.0f} min between {a['started_utc']} and {b['started_utc']}"})
        for h in cap:
            if h.get("status") == "failed":
                out.append({"severity": "HIGH", "code": "FIRING_FAILED", "detail": f"{h['run_id']}: {h.get('error', '')[:160]}"})
            elif h.get("status") == "partial":
                out.append({"severity": "WARN", "code": "FIRING_PARTIAL", "detail": f"{h['run_id']}: series_failures={h.get('series_failures')} publish_errors={len(h.get('publish_errors') or [])}"})
            if h.get("publish_errors"):
                out.append({"severity": "HIGH", "code": "PUBLISH_FAILED", "detail": f"{h['run_id']}: {h['publish_errors'][0][:160]}"})
            if h.get("missing_fields"):
                out.append({"severity": "WARN", "code": "MISSING_FIELDS", "detail": f"{h['run_id']}: {h['missing_fields']}"})
    elif heartbeats is not None:
        out.append({"severity": "WARN", "code": "STALE_HEARTBEAT", "detail": "no capture heartbeats published yet"})
    if coverage is not None and len(coverage):
        due = coverage[pd.to_datetime(coverage["decision_utc"]) <= now - pd.Timedelta(minutes=5)]
        if since is not None:
            due = due[pd.to_datetime(due["decision_utc"]) >= _t(since)]
        bad = due[~due["covered"]]
        for r in bad.itertuples():
            out.append({"severity": "HIGH", "code": "DECISION_UNCOVERED", "detail": f"{r.game_id} {r.horizon} decision {r.decision_utc}: last complete observation age {r.last_obs_age_min} min (> 30)"})
    for o in observations:
        if o.get("source") and o.get("series") and not o.get("complete", True):
            out.append({"severity": "HIGH", "code": "INCOMPLETE_BOOK", "detail": f"{o.get('run_id')} {o['series']}"})
        if o.get("unmapped_events"):
            out.append({"severity": "HIGH", "code": "UNMAPPED_EVENTS", "detail": f"{o.get('run_id')} {o['series']}: {o['unmapped_events'][:6]}"})
    if ingest:
        if ingest.get("rejected"):
            out.append({"severity": "HIGH", "code": "INGEST_REJECTED", "detail": f"{len(ingest['rejected'])} shard(s): {list(ingest['rejected'].items())[:2]}"})
        if ingest.get("series_failures"):
            out.append({"severity": "WARN", "code": "SERIES_FAILURE", "detail": f"{ingest['series_failures']} series failure(s) in newly ingested shards"})
    seen, uniq = set(), []
    for a in out:                                                        # one line per distinct (code, detail)
        k = (a["code"], a["detail"])
        if k not in seen:
            seen.add(k); uniq.append(a)
    return uniq


def summarize(alerts: list[dict]) -> dict:
    return {"high": sum(a["severity"] == "HIGH" for a in alerts), "warn": sum(a["severity"] == "WARN" for a in alerts), "codes": sorted({a["code"] for a in alerts}), "ok": not any(a["severity"] == "HIGH" for a in alerts)}

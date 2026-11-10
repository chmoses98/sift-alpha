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


REFRESH_STALE_H = 30.0
STALE_ACTIVE_MIN = 20.0            # inside an active capture window a tick is expected every 5 min: no tick for this long is stale data
WINDOW_GRACE_MIN = 5.0             # a window is judged only after it ended + this grace
# Findings dated before this instant (the hourly-Claude era: 504s, missed Claude firings, the seven Nov-8 T-90m cells, the Claude run killed 2026-11-09 22:37Z) are RETAINED in alerts.json as severity ACK with their
# original code, but they no longer count as HIGH -- otherwise every future refresh would be red forever for events that can never be repaired (nothing is backfilled).
ALERT_BASELINE_UTC = "2026-11-10T00:00:00+00:00"


def merged_windows(windows) -> list[tuple]:
    """Sorted, merged (start, end) intervals of the pre-registered capture windows (decision time -35/+5 min); overlapping windows are one capture need."""
    iv = sorted((_t(w["start"]), _t(w["end"])) for w in windows or [])
    out: list[list] = []
    for a, b in iv:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _ticked(h) -> bool:
    return int(h.get("ticks") or 0) > 0 and not h.get("no_window")


def _tick_span(h):
    a = h.get("first_tick_utc") or h.get("started_utc"); b = h.get("last_tick_utc") or h.get("ended_utc") or a
    return _t(a), _t(b)


def _window_alerts(allcap: list[dict], windows, now, since) -> list[dict]:
    """Capture health judged against the ACTUAL window schedule: quiet periods raise nothing.
    MISSED_FIRING = a window that has ended with no capture tick inside it; STALE_HEARTBEAT = a window that is open right now with no fresh tick."""
    out = []
    done = [h for h in allcap if h.get("status") != "started"]
    for a, b in merged_windows(windows):
        if since is not None and b < since:
            continue
        if b + pd.Timedelta(minutes=WINDOW_GRACE_MIN) < now:
            hit = [h for h in done if _ticked(h) and (lambda s, e: s <= b and e >= a)(*_tick_span(h))]
            if not hit:
                out.append({"severity": "HIGH", "code": "MISSED_FIRING", "at": a.isoformat(), "detail": f"capture window {a.isoformat()}..{b.isoformat()} had no capture tick (no heartbeat with ticks inside it)"})
        elif a <= now <= b and (now - a).total_seconds() / 60 > STALE_ACTIVE_MIN:
            fresh = any(_ticked(h) and _tick_span(h)[1] >= now - pd.Timedelta(minutes=STALE_ACTIVE_MIN) for h in done) or \
                any(h.get("status") == "started" and h["run_id"] not in {d["run_id"] for d in done} and (now - _t(h["started_utc"])).total_seconds() / 60 <= float(h.get("span_min") or 57) + 15 for h in allcap)
            if not fresh:
                out.append({"severity": "HIGH", "code": "STALE_HEARTBEAT", "at": now.isoformat(), "detail": f"capture window {a.isoformat()}..{b.isoformat()} is open but no capture tick in the last {STALE_ACTIVE_MIN:.0f} min"})
    return out


def evaluate(heartbeats: list[dict], observations: list[dict], ingest: dict | None, now, coverage: pd.DataFrame | None = None, since=None, extra: list[dict] | None = None, windows: list[dict] | None = None) -> list[dict]:
    now = _t(now); out: list[dict] = list(extra or [])
    allcap = [h for h in heartbeats if h.get("role") == "capture"]
    ended = {h["run_id"] for h in allcap if h.get("status") != "started"}
    for h in allcap:                                                   # a start heartbeat with no final one, long after the run should have ended
        if h.get("status") == "started" and h["run_id"] not in ended and (now - _t(h["started_utc"])).total_seconds() / 60 > float(h.get("span_min") or 57) + 15:
            out.append({"severity": "HIGH", "code": "RUN_UNFINISHED", "at": h["started_utc"], "detail": f"{h['run_id']} started {h['started_utc']} but never published a final heartbeat (killed or crashed)"})
    ref = sorted((h for h in heartbeats if h.get("role") == "refresh"), key=lambda h: h["started_utc"])
    if ref:                                                            # the LATEST refresh must have published and verified; a refresh older than REFRESH_STALE_H is itself an alert
        last = ref[-1]
        if last.get("status") == "failed" or last.get("publication_verified") is False:
            out.append({"severity": "HIGH", "code": "REFRESH_UNPUBLISHED", "detail": f"{last['run_id']}: status={last.get('status')} reasons={(last.get('publication') or {}).get('reasons')}"})
        okish = [h for h in ref if h.get("status") == "ok" and h.get("publication_verified") is not False]
        age_h = (now - _t(okish[-1]["started_utc"])).total_seconds() / 3600 if okish else None
        if age_h is None or age_h > REFRESH_STALE_H:
            out.append({"severity": "HIGH", "code": "REFRESH_STALE", "detail": f"last successful refresh {'never' if age_h is None else f'{age_h:.0f} h ago'} (limit {REFRESH_STALE_H:.0f} h)"})
    cap = sorted((h for h in allcap if h.get("status") != "started"), key=lambda h: h["started_utc"])
    if since is not None:
        cap = [h for h in cap if _t(h["started_utc"]) >= _t(since)]
    if windows is not None:                                            # window-driven schedule: no hourly-cadence assumption
        out.extend(_window_alerts(allcap, windows, now, _t(since) if since is not None else None))
    if cap:
        age = (now - _t(cap[-1]["started_utc"])).total_seconds() / 60
        if windows is None and age > STALE_AFTER_MIN:
            out.append({"severity": "HIGH", "code": "STALE_HEARTBEAT", "detail": f"last capture heartbeat {age:.0f} min ago (limit {STALE_AFTER_MIN:.0f})"})
        for a, b in zip(cap, cap[1:]):
            gap = (_t(b["started_utc"]) - _t(a["started_utc"])).total_seconds() / 60
            if windows is None and gap > STALE_AFTER_MIN:
                out.append({"severity": "HIGH", "code": "MISSED_FIRING", "detail": f"no heartbeat for {gap:.0f} min between {a['started_utc']} and {b['started_utc']}"})
        for h in cap:
            if h.get("status") == "failed":
                out.append({"severity": "HIGH", "code": "FIRING_FAILED", "at": h["started_utc"], "detail": f"{h['run_id']}: {h.get('error', '')[:160]}"})
            elif h.get("status") == "partial":
                out.append({"severity": "WARN", "code": "FIRING_PARTIAL", "at": h["started_utc"], "detail": f"{h['run_id']}: series_failures={h.get('series_failures')} publish_errors={len(h.get('publish_errors') or [])}"})
            if h.get("publish_errors"):
                out.append({"severity": "HIGH", "code": "PUBLISH_FAILED", "at": h["started_utc"], "detail": f"{h['run_id']}: {h['publish_errors'][0][:160]}"})
            if h.get("missing_fields"):
                out.append({"severity": "WARN", "code": "MISSING_FIELDS", "detail": f"{h['run_id']}: {h['missing_fields']}"})
    elif heartbeats is not None and windows is None:
        out.append({"severity": "WARN", "code": "STALE_HEARTBEAT", "detail": "no capture heartbeats published yet"})
    if coverage is not None and len(coverage):
        due = coverage[pd.to_datetime(coverage["decision_utc"]) <= now - pd.Timedelta(minutes=5)]
        if since is not None:
            due = due[pd.to_datetime(due["decision_utc"]) >= _t(since)]
        bad = due[~due["covered"]]
        for r in bad.itertuples():
            out.append({"severity": "HIGH", "code": "DECISION_UNCOVERED", "at": str(r.decision_utc), "detail": f"{r.game_id} {r.horizon} decision {r.decision_utc}: last complete observation age {r.last_obs_age_min} min (> 30)"})
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
    if windows is not None:                                              # retained-but-acknowledged: pre-baseline findings stay visible, they just stop failing every future run
        base = _t(ALERT_BASELINE_UTC)
        for a in uniq:
            if a.get("at") and a["severity"] in ("HIGH", "WARN") and _t(a["at"]) < base:
                a["severity"] = "ACK"; a["detail"] = "[pre-baseline, acknowledged] " + a["detail"]
    return uniq


def summarize(alerts: list[dict]) -> dict:
    return {"high": sum(a["severity"] == "HIGH" for a in alerts), "warn": sum(a["severity"] == "WARN" for a in alerts), "acknowledged": sum(a["severity"] == "ACK" for a in alerts), "codes": sorted({a["code"] for a in alerts if a["severity"] in ("HIGH", "WARN")}), "ok": not any(a["severity"] == "HIGH" for a in alerts)}

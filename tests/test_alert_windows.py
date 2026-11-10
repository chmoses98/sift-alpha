"""Window-driven capture alerts: quiet periods raise nothing, missed/stale windows and publication failures do (RESEARCH_ONLY)."""
import pandas as pd
from alpha_engine.lab import alerts as AL

T = pd.Timestamp


def hb(run, start, first, last, ticks=2, status="ok", **kw):
    return {"kind": "heartbeat", "role": "capture", "run_id": run, "started_utc": start, "first_tick_utc": first, "last_tick_utc": last, "ended_utc": last, "ticks": ticks, "status": status, "no_window": False, **kw}


W = [{"start": T("2026-12-06T16:55:00Z"), "end": T("2026-12-06T17:35:00Z")}]
SINCE = T("2026-12-01T00:00:00Z")


def codes(al, sev=("HIGH", "WARN")):
    return sorted({a["code"] for a in al if a["severity"] in sev})


def test_quiet_period_raises_nothing():
    h = [hb("a", "2026-12-06T17:00:00Z", "2026-12-06T17:00:05Z", "2026-12-06T17:30:00Z")]
    al = AL.evaluate(h, [], None, T("2026-12-09T08:40:00Z"), since=SINCE, windows=W)           # 3 days after the last heartbeat, no window open
    assert codes(al) == []


def test_old_hourly_logic_unchanged_without_windows():
    h = [hb("a", "2026-12-06T17:00:00Z", "2026-12-06T17:00:05Z", "2026-12-06T17:30:00Z")]
    assert "STALE_HEARTBEAT" in codes(AL.evaluate(h, [], None, T("2026-12-09T08:40:00Z"), since=SINCE))


def test_missed_window_is_high():
    al = AL.evaluate([], [], None, T("2026-12-07T08:40:00Z"), since=SINCE, windows=W)
    assert codes(al) == ["MISSED_FIRING"]


def test_zero_tick_or_nonoverlapping_heartbeat_does_not_cover():
    h = [hb("z", "2026-12-06T17:00:00Z", None, None, ticks=0, no_window=True), hb("late", "2026-12-06T18:00:00Z", "2026-12-06T18:00:05Z", "2026-12-06T18:30:00Z")]
    h[0]["first_tick_utc"] = h[0]["last_tick_utc"] = None
    assert codes(AL.evaluate(h, [], None, T("2026-12-07T08:40:00Z"), since=SINCE, windows=W)) == ["MISSED_FIRING"]


def test_overlapping_run_covers_window():
    h = [hb("a", "2026-12-06T16:37:00Z", "2026-12-06T16:37:05Z", "2026-12-06T17:20:00Z")]
    assert codes(AL.evaluate(h, [], None, T("2026-12-07T08:40:00Z"), since=SINCE, windows=W)) == []


def test_stale_data_during_active_window():
    h = [hb("a", "2026-12-06T16:10:00Z", "2026-12-06T16:10:05Z", "2026-12-06T16:50:00Z")]
    al = AL.evaluate(h, [], None, T("2026-12-06T17:25:00Z"), since=SINCE, windows=W)             # window open since 16:55, last tick 35 min ago
    assert "STALE_HEARTBEAT" in codes(al)
    h = [hb("a", "2026-12-06T16:37:00Z", "2026-12-06T16:37:05Z", "2026-12-06T17:20:00Z")]
    assert codes(AL.evaluate(h, [], None, T("2026-12-06T17:25:00Z"), since=SINCE, windows=W)) == []


def test_running_capture_is_not_stale():
    h = [{"kind": "heartbeat", "role": "capture", "run_id": "r", "started_utc": "2026-12-06T16:37:00Z", "status": "started", "span_min": 57}]
    assert codes(AL.evaluate(h, [], None, T("2026-12-06T17:25:00Z"), since=SINCE, windows=W)) == []


def test_publication_failure_in_heartbeat_is_high():
    h = [hb("a", "2026-12-06T16:37:00Z", "2026-12-06T16:37:05Z", "2026-12-06T17:20:00Z", publish_errors=["push rejected"], status="partial")]
    assert "PUBLISH_FAILED" in codes(AL.evaluate(h, [], None, T("2026-12-07T08:40:00Z"), since=SINCE, windows=W))


def test_pre_baseline_findings_are_acknowledged_not_omitted():
    w = [{"start": T("2026-11-08T16:00:00Z"), "end": T("2026-11-08T16:40:00Z")}]
    al = AL.evaluate([], [], None, T("2026-12-07T08:40:00Z"), since=T("2026-11-07T00:00:00Z"), windows=w)
    assert [a["severity"] for a in al] == ["ACK"] and al[0]["code"] == "MISSED_FIRING"
    s = AL.summarize(al)
    assert s["ok"] and s["high"] == 0 and s["acknowledged"] == 1 and s["codes"] == []


def test_overlapping_windows_merge():
    w = [{"start": T("2026-12-06T16:55:00Z"), "end": T("2026-12-06T17:35:00Z")}, {"start": T("2026-12-06T17:30:00Z"), "end": T("2026-12-06T18:10:00Z")}]
    assert len(AL.merged_windows(w)) == 1

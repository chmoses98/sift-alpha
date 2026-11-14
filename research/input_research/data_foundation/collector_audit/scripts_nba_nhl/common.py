"""Shared helpers for the read-only capture audit. Reads already-downloaded files only."""
import gzip, json, re, glob, statistics, collections, os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
TS_RE = re.compile(r"(\d{8}T\d{6})\d*Z")


def parse_iso(s):
    if s is None:
        return None
    s = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def fname_ts(path):
    m = TS_RE.findall(os.path.basename(path))
    if not m:
        return None
    return datetime.strptime(m[-1], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)


def read_rows(path):
    try:
        return [json.loads(l) for l in gzip.open(path, "rt") if l.strip()], None
    except Exception as e:  # truncated/corrupt
        return [], f"{type(e).__name__}: {e}"[:120]


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 2)


def dist(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(min(xs), 2), "median": pct(xs, .5), "p90": pct(xs, .9), "max": round(max(xs), 2)}


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def gap_report(times, sched_cadence_min, label=""):
    """times: list of datetimes (captures). Gaps between consecutive DISTINCT capture instants."""
    ts = sorted(set(times))
    gaps = [((b - a).total_seconds() / 60, a, b) for a, b in zip(ts, ts[1:])]
    g = [x[0] for x in gaps]
    big = sorted(gaps, key=lambda x: -x[0])[:10]
    return {
        "scheduled_cadence_min": sched_cadence_min,
        "n_captures": len(ts), "first_utc": iso(ts[0]) if ts else None, "last_utc": iso(ts[-1]) if ts else None,
        "distinct_capture_days_utc": len({t.date() for t in ts}),
        "gap_minutes": dist(g),
        "n_gaps_gt_2x_cadence": sum(1 for x in g if x > 2 * sched_cadence_min),
        "n_gaps_gt_2h": sum(1 for x in g if x > 120),
        "largest_10_gaps": [{"gap_min": round(x, 1), "start_utc": iso(a), "end_utc": iso(b)} for x, a, b in big],
    }


def completeness(rows):
    """% non-null and % non-empty per top-level field."""
    n = len(rows)
    keys = collections.Counter()
    nn = collections.Counter()
    ne = collections.Counter()
    for r in rows:
        for k, v in r.items():
            keys[k] += 1
            if v is not None:
                nn[k] += 1
            if v not in (None, "", [], {}):
                ne[k] += 1
    return {k: {"present_pct": round(100 * keys[k] / n, 1), "non_null_pct": round(100 * nn[k] / n, 1),
                "non_empty_pct": round(100 * ne[k] / n, 1)} for k in sorted(keys)} if n else {}


def schema_timeline(files_rows):
    """files_rows: list of (ts, rows). Returns key-set changes in time order."""
    out = []
    prev = None
    for ts, rows in files_rows:
        ks = frozenset(k for r in rows for k in r.keys())
        if not rows:
            continue
        if prev is None:
            out.append({"at_utc": iso(ts), "event": "first", "keys": sorted(ks)})
        elif ks != prev:
            out.append({"at_utc": iso(ts), "added": sorted(ks - prev), "removed": sorted(prev - ks)})
        prev = ks
    return out


def game_coverage(games, cap_times, window_h=6.0, near_cadence_min=10.0, lo=None, hi=None):
    """games: list of {id, tip(datetime)}. cap_times: sorted capture datetimes.
    Per game: captures in [tip-window, tip), latest capture before tip, max gap inside the window."""
    ct = sorted(set(cap_times))
    if not ct:
        return {"n_games_evaluated": 0}
    lo = lo or ct[0]
    hi = hi or ct[-1]
    rows = []
    for g in games:
        tip = g["tip"]
        # evaluate only games whose whole window lies inside the observed capture span
        if tip - timedelta(hours=window_h) < lo or tip > hi:
            continue
        w0 = tip - timedelta(hours=window_h)
        inw = [t for t in ct if w0 <= t < tip]
        before = [t for t in ct if t < tip]
        pts = [w0] + inw + [tip]
        mg = max((b - a).total_seconds() / 60 for a, b in zip(pts, pts[1:]))
        rows.append({"game_id": g["id"], "tip_utc": iso(tip), "n_caps_T-6h_to_T0": len(inw),
                     "latest_before_tip_min": round((tip - before[-1]).total_seconds() / 60, 1) if before else None,
                     "max_gap_in_window_min": round(mg, 1)})
    if not rows:
        return {"n_games_evaluated": 0}
    n = [r["n_caps_T-6h_to_T0"] for r in rows]
    lat = [r["latest_before_tip_min"] for r in rows if r["latest_before_tip_min"] is not None]
    mg = [r["max_gap_in_window_min"] for r in rows]
    step = max(1, len(rows) // 25)
    return {"n_games_evaluated": len(rows), "window_hours": window_h,
            "caps_in_window": dist(n), "latest_capture_before_start_min": dist(lat),
            "max_gap_in_window_min": dist(mg),
            "n_games_zero_caps_in_window": sum(1 for x in n if x == 0),
            "n_games_latest_gt_30min_before_start": sum(1 for x in lat if x > 30),
            "n_games_with_max_gap_gt_%dmin" % int(2 * near_cadence_min): sum(1 for x in mg if x > 2 * near_cadence_min),
            "sample_games_25": rows[::step][:25]}


def active_gap_report(times, games, cadence_min, pre_h=6.0, post_h=0.0):
    """Gaps (between consecutive distinct captures) whose START lies inside some game's [tip-pre_h, tip+post_h]:
    the cadence that actually matters for pregame use, excluding overnight/off-day idle."""
    ts = sorted(set(times))
    win = [(g["tip"] - timedelta(hours=pre_h), g["tip"] + timedelta(hours=post_h)) for g in games]
    def same(t0, t1):
        return any(a <= t0 < b and a <= t1 <= b for a, b in win)
    gaps = [((b - a).total_seconds() / 60, a, b) for a, b in zip(ts, ts[1:]) if same(a, b)]
    g = [x[0] for x in gaps]
    big = sorted(gaps, key=lambda x: -x[0])[:10]
    return {"definition": f"gaps whose BOTH endpoints lie inside the same game window T-{pre_h}h..T+{post_h}h (idle overnight/off-day excluded)", "scheduled_cadence_min": cadence_min,
            "gap_minutes": dist(g), "n_gaps": len(g), "n_gaps_gt_2x_cadence": sum(1 for x in g if x > 2 * cadence_min),
            "largest_10_gaps": [{"gap_min": round(x, 1), "start_utc": iso(a), "end_utc": iso(b)} for x, a, b in big]}

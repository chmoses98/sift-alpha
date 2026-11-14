import datetime as dt, statistics, json, gzip
UTC = dt.timezone.utc
def P(s):
    if s is None: return None
    s = str(s).strip().replace("Z", "+00:00")
    if len(s) == 16 and s[10] == "T": s += ":00+00:00"  # 2026-11-10T00:25 + Z
    try:
        d = dt.datetime.fromisoformat(s)
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)
def iso(d): return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
def pct(xs, q):
    xs = sorted(xs)
    if not xs: return None
    k = (len(xs) - 1) * q; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)
def gap_stats(times, sched_h=None, top=10):
    """times: list of datetimes. gaps in hours."""
    ts = sorted(times)
    gaps = [((b - a).total_seconds() / 3600, a, b) for a, b in zip(ts, ts[1:])]
    g = [x[0] for x in gaps]
    out = {"n_captures": len(ts), "distinct_days_utc": len({t.date() for t in ts}),
           "first_utc": iso(ts[0]) if ts else None, "last_utc": iso(ts[-1]) if ts else None}
    if g:
        out.update(gap_h_min=round(min(g), 3), gap_h_median=round(statistics.median(g), 3),
                   gap_h_p90=round(pct(g, .9), 3), gap_h_max=round(max(g), 3))
        if sched_h:
            out["scheduled_cadence_h"] = sched_h
            out["gaps_gt_2x_sched"] = sum(1 for x in g if x > 2 * sched_h)
        out["largest_10_gaps"] = [{"hours": round(h, 2), "from_utc": iso(a), "to_utc": iso(b)}
                                  for h, a, b in sorted(gaps, key=lambda x: -x[0])[:top]]
    return out
def jl(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt") as f:
        return [json.loads(l) for l in f if l.strip()]
def jload(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt") as f:
        return json.load(f)
def pregame(cap_times, kickoff, window_h=6):
    inw = [t for t in cap_times if kickoff - dt.timedelta(hours=window_h) <= t < kickoff]
    before = [t for t in cap_times if t < kickoff]
    last = max(before) if before else None
    return {"n_in_T-6h": len(inw), "latest_before_kickoff_lead_min": round((kickoff - last).total_seconds() / 60, 1) if last else None}
def flat(o, pre="", skip=("links", "logos", "headshot")):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in skip: continue
            yield from flat(v, pre + k + ".", skip)
    elif isinstance(o, list):
        if o and all(not isinstance(x, (dict, list)) for x in o): yield pre[:-1], o
        elif o:
            for x in o[:1]: yield from flat(x, pre + "[].", skip)
        else: yield pre[:-1], o
    else:
        yield pre[:-1], o

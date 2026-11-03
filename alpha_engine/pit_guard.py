"""Point-in-time guards for pregame research. Raw archives are never modified: the guard only partitions records
into (usable, quarantined) and every quarantined record carries a reason. Persist the quarantine ledger next to,
not instead of, the raw archive.

weather_pregame(): an observation is pregame only if captured_at <= kickoff_utc - min_lead. The archive's own
`hours_before_kickoff` is recomputed from the two timestamps; disagreement (> tol hours) is quarantined too,
because a mislabelled lead time would silently leak post-kickoff data."""
from datetime import datetime, timedelta


def _p(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("naive timestamp")
    return d


def weather_pregame(records, *, min_lead_minutes=0, tol_hours=0.1):
    ok, bad = [], []
    for r in records:
        try:
            cap, ko = _p(r["captured_at"]), _p(r["kickoff_utc"])
        except (KeyError, ValueError, TypeError):
            bad.append((r, "MISSING_OR_NAIVE_TIMESTAMP")); continue
        lead = (ko - cap).total_seconds() / 3600
        stated = r.get("hours_before_kickoff")
        if cap > ko - timedelta(minutes=min_lead_minutes):
            bad.append((r, "CAPTURED_AFTER_KICKOFF" if cap > ko else "INSIDE_MIN_LEAD")); continue
        if stated is not None and abs(stated - lead) > tol_hours:
            bad.append((r, "STATED_LEAD_DISAGREES_WITH_TIMESTAMPS")); continue
        ok.append(r)
    return ok, bad


def write_quarantine(bad, path):
    """Append-only ledger of excluded records (id + reason). The raw archive stays untouched."""
    import json
    with open(path, "a") as f:
        for r, why in bad:
            f.write(json.dumps({"reason": why, "espn_event_id": r.get("espn_event_id"), "captured_at": r.get("captured_at"), "kickoff_utc": r.get("kickoff_utc")}, sort_keys=True) + "\n")
    return len(bad)

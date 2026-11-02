"""Per-family historical coverage from archived daily snapshots (research/audit/snapshots/daily_series_coverage.json).

For each family: the first/last archived day any of its series had markets, days present, and the archive's own
calendar span - so `days_present < calendar_days` exposes archive gaps. Families whose series are absent from every
scanned day are 'NEVER_SEEN_IN_SCANNED_DAYS' (not 'nonexistent'). Sports without a scanned archive are
'NOT_SCANNED' (sport-level archive coverage lives in collection_status)."""
import json
from datetime import date, timedelta
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "research" / "audit" / "snapshots" / "daily_series_coverage.json"


def _d(s):
    s = s.replace("-", ""); return date(int(s[:4]), int(s[4:6]), int(s[6:]))


SOCCER_TOKENS = [("1HBTTS", "first_half_btts"), ("1HSPREAD", "first_half_handicap"), ("1HTOTAL", "first_half_total"), ("TEAMTOTAL", "team_total"), ("SPREAD", "handicap"),
                 ("TOTAL", "total_goals"), ("BTTS", "btts"), ("SCORE", "exact_score"), ("FTTS", "first_to_score"), ("GAME", "match_result_3way"), ("1H", "first_half_result")]


def soccer_family(ticker):
    return next((f for tok, f in SOCCER_TOKENS if ticker.endswith(tok) and len(ticker) > len(tok) + 3), None)


def attach(sport, rows):
    cov = json.loads(P.read_text()) if P.exists() else {}
    c = cov.get(sport)
    if sport == "SOCCER" and c:   # inventory has no series lists: derive them from archived tickers by suffix grammar (titles unconfirmed)
        seen = {t for d in c["days"].values() for t in d}
        for r in rows:
            if not r["series"]:
                r["series"] = [{"ticker": t, "title": None, "markets_now": None, "status": {}, "family_by": "ticker-suffix grammar"} for t in sorted(seen) if soccer_family(t) == r["native_family"]]
    for r in rows:
        if not c:
            r["historical"] = {"state": "NOT_SCANNED", "note": "no per-day archived market snapshot scanned for this sport"}; continue
        days = sorted(c["days"]); tick = {s["ticker"] for s in r["series"]}
        span = (_d(days[-1]) - _d(days[0])).days + 1
        present = [(d, sum(n for t, n in c["days"][d].items() if t in tick)) for d in days]
        present = [(d, n) for d, n in present if n]
        missing_cal = sorted({(_d(days[0]) + timedelta(i)).isoformat() for i in range(span)} - {_d(d).isoformat() for d in days})
        if not tick:
            h = {"state": "NO_SERIES_LISTED"}
        elif not present:
            other = {k: r.get(k) for k in ("markets_historical_archived_tier", "markets_prior_snapshot", "markets_prior_registry_snapshot") if r.get(k)}
            h = {"state": "NEVER_SEEN_IN_SCANNED_DAYS", "exists_per_other_evidence": bool(other), "other_evidence": other,
                 "absence_meaning": "no market in the scanned daily snapshots (basis below); NOT evidence the market does not exist" + ("; other sources show it existed" if other else "")}
        else:
            h = {"state": "OBSERVED", "first_seen": _d(present[0][0]).isoformat(), "last_seen": _d(present[-1][0]).isoformat(), "days_present": len(present),
                 "markets_peak": max(n for _, n in present), "markets_latest_day": present[-1][1]}
        h.update({"archive_first_day": _d(days[0]).isoformat(), "archive_last_day": _d(days[-1]).isoformat(), "snapshot_days": len(days),
                  "calendar_days_in_span": span, "calendar_days_without_snapshot": len(missing_cal), "basis": c["basis"], "branch": c["branch"], "commit": c["commit"]})
        r["historical"] = h
    return rows

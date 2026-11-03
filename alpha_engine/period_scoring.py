"""Per-period scoring history from the ESPN scoreboard (free, public JSON) for NFL / CFB / NBA / CBB / NHL.

Why: the quarter/half/period market families (e.g. CFB 1Q total, NBA 1Q, NHL period totals) need empirical scoring
distributions by period, and no sport repo archives per-period points (cfb-edge-finder only counts linescore periods).

Discipline
* POST-GAME data: only usable as a lagged feature for LATER games; every row carries observed_at (fetch time, stamped
  after the response) and game start. Join with research_eval.asof_join - never for the same game.
* Nothing is fabricated: games without a complete linescore are counted under `rejected` with a reason, not imputed.
* Reconciliation: sum(periods) must equal the reported final score; otherwise the row is kept but flagged
  SCORE_UNRECONCILED (excluded from distributions by default).
* Append-only: per (league, date) JSONL; an existing event_id is never overwritten.
Usage: python -m alpha_engine.period_scoring collect LEAGUE START END OUT_DIR   (dates YYYY-MM-DD)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LEAGUES = {  # path, query, regulation periods, period label
    "nfl": ("football/nfl", "", 4), "cfb": ("football/college-football", "groups=80&limit=400", 4),
    "nba": ("basketball/nba", "", 4), "cbb": ("basketball/mens-college-basketball", "groups=50&limit=400", 2),
    "nhl": ("hockey/nhl", "", 3),
}
URL = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}&{q}"


def now_utc():
    return datetime.now(timezone.utc)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else None


def parse_scoreboard(body, league, observed_at, source_url):
    """-> (rows, rejected_counter). Only COMPLETED regulation-structure games with full linescores become rows."""
    reg = LEAGUES[league][2]
    rows, rej = [], Counter()
    for ev in (body or {}).get("events") or []:
        try:
            comp = ev["competitions"][0]
            if not (comp.get("status") or ev.get("status") or {}).get("type", {}).get("completed"):
                rej["NOT_COMPLETED"] += 1
                continue
            sides = {c.get("homeAway"): c for c in comp["competitors"]}
            if set(sides) != {"home", "away"}:
                rej["SIDES_UNRESOLVED"] += 1
                continue
            per, final = {}, {}
            for k, c in sides.items():
                ls = c.get("linescores")
                vals = [_num(x.get("value")) for x in ls] if isinstance(ls, list) else None
                if not vals or any(v is None for v in vals):
                    raise KeyError("linescores")
                per[k], final[k] = vals, _num(c.get("score"))
            if len(per["home"]) != len(per["away"]):
                rej["PERIOD_COUNT_MISMATCH"] += 1
                continue
            n = len(per["home"])
            if n < reg:
                rej["FEWER_THAN_REGULATION_PERIODS"] += 1
                continue
            rec = all(final[k] is not None and sum(per[k]) == final[k] for k in per)
            rows.append({
                "league": league, "event_id": str(ev["id"]), "start_time_utc": ev.get("date") or comp.get("date"),
                "home": sides["home"]["team"].get("abbreviation"), "away": sides["away"]["team"].get("abbreviation"),
                "home_team_id": str(sides["home"]["team"].get("id")), "away_team_id": str(sides["away"]["team"].get("id")),
                "neutral_site": comp.get("neutralSite"), "regulation_periods": reg, "n_periods": n, "overtime": n > reg,
                "home_periods": per["home"], "away_periods": per["away"], "home_final": final["home"], "away_final": final["away"],
                "reconciliation": "RECONCILED" if rec else "SCORE_UNRECONCILED",
                "observed_at": observed_at.isoformat().replace("+00:00", "Z"), "source": "espn_scoreboard", "source_url": source_url,
            })
        except (KeyError, IndexError, TypeError):
            rej["MALFORMED_OR_NO_LINESCORES"] += 1
    return rows, rej


def collect(league, start, end, out_dir, fetch=None, sleep_s=0.4):
    path, q, _ = LEAGUES[league]
    throttle = fetch is None                           # only throttle real network fetches (injected fetchers are tests)
    fetch = fetch or (lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "sift-alpha-period-scoring/1"}), timeout=30).read()))
    out_dir = Path(out_dir)
    stats = {"days": 0, "rows_new": 0, "rows_existing": 0, "rejected": Counter(), "failed_days": []}
    d = start
    while d <= end:
        f = out_dir / league / f"{d.isoformat()}.jsonl"
        url = URL.format(path=path, d=d.strftime("%Y%m%d"), q=q)
        try:
            body = fetch(url)
            observed = now_utc()                       # stamped AFTER the response returned
        except Exception as e:                         # record, never fabricate
            stats["failed_days"].append(f"{d}: {str(e)[:80]}")
            d += timedelta(days=1)
            continue
        rows, rej = parse_scoreboard(body, league, observed, url)
        have = set()
        if f.exists():
            have = {json.loads(l)["event_id"] for l in f.read_text().splitlines() if l.strip()}
        new = [r for r in rows if r["event_id"] not in have]
        if new:
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "a") as fh:
                for r in new:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
        stats["days"] += 1
        stats["rows_new"] += len(new)
        stats["rows_existing"] += len(rows) - len(new)
        stats["rejected"].update(rej)
        d += timedelta(days=1)
        time.sleep(sleep_s) if throttle else None
    stats["rejected"] = dict(stats["rejected"])
    return stats


def load(out_dir, league):
    rows = []
    for f in sorted((Path(out_dir) / league).glob("*.jsonl")):
        rows += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return rows


def period_distribution(rows, period_index, *, kind="combined", include_unreconciled=False, include_overtime_games=True):
    """Empirical distribution of points in regulation period `period_index` (0-based). kind: combined | team.
    Returns {n, mean, pmf:{points:prob}, p_zero}. Overtime periods are never mixed into regulation periods."""
    vals = []
    for r in rows:
        if r["reconciliation"] != "RECONCILED" and not include_unreconciled:
            continue
        if r["overtime"] and not include_overtime_games:
            continue
        h, a = r["home_periods"][period_index], r["away_periods"][period_index]
        vals += [h + a] if kind == "combined" else [h, a]
    if not vals:
        return {"n": 0}
    c = Counter(vals)
    return {"n": len(vals), "mean": round(sum(vals) / len(vals), 3), "p_zero": round(c[0] / len(vals), 4),
            "pmf": {str(k): round(v / len(vals), 4) for k, v in sorted(c.items())}}


def manifest(out_dir):
    out = {}
    for f in sorted(Path(out_dir).rglob("*.jsonl")):
        out[str(f.relative_to(out_dir))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def main(argv=None):
    a = list(argv or sys.argv[1:])
    if len(a) != 5 or a[0] != "collect":
        raise SystemExit(__doc__)
    league, s, e, out = a[1], date.fromisoformat(a[2]), date.fromisoformat(a[3]), a[4]
    st = collect(league, s, e, out)
    print(json.dumps(st))
    (Path(out) / "MANIFEST.sha256.json").write_text(json.dumps(manifest(out), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()

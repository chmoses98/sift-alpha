"""Consumer check: read ONLY the built index.json and say what SIFT projects for a team.

    python -m sift_feed.say Celtics [--sport NBA] [--index feed/v1/index.json | --index https://...]
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone

from .schema import parse_ts


def load(index):
    if index.startswith("http"):
        with urllib.request.urlopen(index, timeout=30) as r:
            return json.loads(r.read())
    with open(index) as f:
        return json.load(f)


def score(team, q):
    """3 = abbreviation, 2 = whole words of the name ("Duke" -> Duke Blue Devils), 1 = substring, 0 = none."""
    q, name = q.lower().strip(), (team.get("name") or "").lower()
    if (team.get("abbr") or "").lower() == q:
        return 3
    if f" {q} " in f" {name} ":
        return 2
    return 1 if q and q in name else 0


def find(rows, q, sport=None):
    out = []
    for g in rows:
        if sport and g["sport"] != sport.upper():
            continue
        for side, other in (("home", "away"), ("away", "home")):
            sc = score(g[side], q)
            if sc:
                out.append((sc, g, side, other))
    best = max((x[0] for x in out), default=0)
    return [x[1:] for x in sorted((x for x in out if x[0] == best), key=lambda x: x[1]["start_time"])]


def _name(t):
    return t.get("name") or t.get("abbr")


def _hours(sec):
    return "age unknown" if sec is None else f"{sec / 3600:.1f}h old"


def sentence(idx, g, side, other):
    me, opp = g[side], g[other]
    hs = g.get("home_spread")
    line = None if hs is None else (hs if side == "home" else -hs)
    line_s = "n/a" if line is None else ("PK" if line == 0 else f"{line:+.1f}")
    wp = (g.get("win_probability") or {}).get(side)
    total = g.get("projected_total")
    where = "vs" if side == "home" else "at"
    parts = [f"SIFT projects {_name(me)} {line_s} {where} {_name(opp)}"]
    parts.append(f"total {total}" if total is not None else "total not published")
    lead = ", ".join(parts)
    if wp is not None:
        pct = round(wp * 100)
        lead += f", with {'an' if str(pct).startswith('8') or pct in (11, 18) else 'a'} {pct}% win probability."
    else:
        lead += ", win probability not published."
    tt = g.get("team_totals") or {}
    if tt.get(side) is not None and tt.get(other) is not None:
        lead += f" Projected score {_name(me)} {tt[side]}, {_name(opp)} {tt[other]} (book line: {g.get('spread')})."
    stale = "STALE - " if g.get("stale") else ""
    return (f"{stale}{lead} Forecast {g['model_version']} made {g['projected_at']} ({_hours(g.get('data_age_seconds'))} "
            f"at feed time); game starts {g['start_time']}; feed generated {idx['generated_at']}; "
            f"status {g['status']}/{g['approval_status']}; source {g['source']}.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("team")
    ap.add_argument("--sport")
    ap.add_argument("--index", default="feed/v1/index.json")
    a = ap.parse_args(argv)
    idx = load(a.index)
    now = datetime.now(timezone.utc)
    hits = [h for h in find(idx.get("games", []), a.team, a.sport) if h[0]["status"] == "production"]
    upcoming = [h for h in hits if parse_ts(h[0]["start_time"]) > now] or hits
    if upcoming:
        print(sentence(idx, *upcoming[0]))
        return 0
    res = find(idx.get("research", []), a.team, a.sport)
    sports = idx.get("sports", {})
    if res:
        g, side, other = res[0]
        s = sports.get(g["sport"], {})
        print(f"No SIFT production forecast for {_name(g[side])} ({g['sport']} status {s.get('status')}: {s.get('reason')}). "
              f"A research-only model ({g['model_version']}, {g['approval_status']}) exists; it is NOT a SIFT production "
              f"forecast and is not quoted here. Feed generated {idx['generated_at']}.")
        return 2
    notes = "; ".join(f"{k} {v['status']}" + (f" ({v['reason']})" if v.get("reason") else "") for k, v in sports.items()
                      if not a.sport or k == a.sport.upper())
    print(f"No upcoming SIFT production forecast matches '{a.team}'. Sports: {notes}. Feed generated {idx['generated_at']}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

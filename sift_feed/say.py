"""Consumer check: read ONLY the built index.json and say what SIFT projects for a team.
Phrasing follows source_class; age and staleness are computed against the current time.

    python -m sift_feed.say Celtics [--sport NBA] [--research] [--index feed/v1/index.json | --index https://...]
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone

from .schema import OPERATING, PRODUCTION, RESEARCH, parse_ts


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


def _age_h(now, ts):
    t = parse_ts(ts)
    return None if t is None else (now - t).total_seconds() / 3600


def _decl(d):
    return "; ".join(f"{k}={v!r}" for k, v in (d or {}).items()) or "none"


def freshness(idx, g, now):
    """Warnings computed against `now` (the moment of the answer), never the build time."""
    limit = (idx.get("stale_after_hours") or {}).get(g["sport"])
    age, feed_age = _age_h(now, g.get("projected_at")), _age_h(now, idx.get("generated_at"))
    warn = []
    if parse_ts(g["start_time"]) <= now:
        warn.append(f"WARNING: this game already started at {g['start_time']}; this is a pre-game forecast, not live")
    if age is None or limit is None or age > limit:
        lim = "?" if limit is None else limit
        warn.append(f"STALE: forecast is {'?' if age is None else f'{age:.1f}'}h old now (limit {lim}h)")
    if feed_age is not None and limit is not None and feed_age > limit:
        warn.append(f"the feed itself was generated {feed_age:.1f}h ago ({idx['generated_at']})")
    return age, warn


def sentence(idx, g, side, other, now=None):
    now = now or datetime.now(timezone.utc)
    me, opp = g[side], g[other]
    hs = g.get("home_spread")
    line = None if hs is None else (hs if side == "home" else -hs)
    line_s = "n/a" if line is None else ("PK" if line == 0 else f"{line:+.1f}")
    wp = (g.get("win_probability") or {}).get(side)
    total = g.get("projected_total")
    where = "vs" if side == "home" else "at"
    cls = g.get("source_class")
    who = "SIFT" if cls == PRODUCTION else f"SIFT's operating (not production-approved) {g['sport']} model"
    parts = [f"{who} projects {_name(me)} {line_s} {where} {_name(opp)}"]
    parts.append(f"total {total}" if total is not None else "total not published")
    lead = ", ".join(parts)
    if wp is not None:
        pct = round(wp * 100)
        lead += f", with {'an' if str(pct).startswith('8') or pct in (11, 18) else 'a'} {pct}% win probability."
    else:
        lead += ", win probability not published."
    tt = g.get("team_totals") or {}
    if tt.get(side) is not None and tt.get(other) is not None:
        lead += f" Projected score {_name(me)} {tt[side]}, {_name(opp)} {tt[other]} (model spread in sportsbook notation: {g.get('spread')}; not a market line)."
    age, warn = freshness(idx, g, now)
    tail = (f" Forecast {g['model_version']} made {g['projected_at']} ({'?' if age is None else f'{age:.1f}'}h ago); "
            f"game starts {g['start_time']}; feed generated {idx['generated_at']}; source_class {cls}.")
    if cls != PRODUCTION:
        tail += f" The source declares: {_decl(g.get('source_declaration'))}."
    return ("; ".join(warn) + ". " if warn else "") + lead + tail


def research_sentence(idx, g, side, other, now):
    pts = g.get("team_points_mean") or {}
    nums = (f"mean points {_name(g[side])} {pts.get(side)}, {_name(g[other])} {pts.get(other)}"
            if pts.get(side) is not None and pts.get(other) is not None else "no game-level numbers published")
    _, warn = freshness(idx, g, now)
    return (("; ".join(warn) + ". " if warn else "") +
            f"RESEARCH ONLY - not a SIFT production or operating forecast: research model {g['model_version']} "
            f"({_decl(g.get('source_declaration'))}) has {nums} for {_name(g['away'])} at {_name(g['home'])}, "
            f"made {g['projected_at']}; game starts {g['start_time']}; feed generated {idx['generated_at']}.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("team")
    ap.add_argument("--sport")
    ap.add_argument("--index", default="feed/v1/index.json")
    ap.add_argument("--research", action="store_true", help="explicitly ask for research rows (labelled research)")
    a = ap.parse_args(argv)
    idx = load(a.index)
    now = datetime.now(timezone.utc)
    hits = [h for h in find(idx.get("games", []), a.team, a.sport) if h[0].get("source_class") in (PRODUCTION, OPERATING)]
    upcoming = [h for h in hits if parse_ts(h[0]["start_time"]) > now] or hits[-1:]
    if upcoming:
        print(sentence(idx, *upcoming[0], now=now))
        return 0
    res = [h for h in find(idx.get("research", []), a.team, a.sport) if h[0].get("source_class") == RESEARCH]
    sports = idx.get("sports", {})
    if res and a.research:
        up = [h for h in res if parse_ts(h[0]["start_time"]) > now] or res[-1:]
        print(research_sentence(idx, *up[0], now))
        return 3
    if res:
        g, side, other = res[0]
        s = sports.get(g["sport"], {})
        print(f"No SIFT operating forecast for {_name(g[side])} ({g['sport']} status {s.get('status')}: {s.get('reason')}). "
              f"Only a research model ({g['model_version']}) exists; it is NOT a SIFT forecast and is not quoted here "
              f"(ask with --research to see it, labelled research). Feed generated {idx['generated_at']}.")
        return 2
    notes = "; ".join(f"{k} {v['status']}" + (f" ({v['reason']})" if v.get("reason") else "") for k, v in sports.items()
                      if not a.sport or k == a.sport.upper())
    print(f"No upcoming SIFT forecast matches '{a.team}'. Sports: {notes}. Feed generated {idx['generated_at']}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

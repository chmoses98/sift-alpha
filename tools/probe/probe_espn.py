"""Read-only ESPN payload probe (runs on a GitHub runner). Prints STRUCTURAL facts as 'PROBE {json}' lines; no bodies are stored."""
import json, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (SIFT-Alpha probe)"}
B = "https://site.api.espn.com/apis/site/v2/sports"


def get(url):
    t0 = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r), t0, datetime.now(timezone.utc), r.status
    except Exception as e:
        return None, t0, datetime.now(timezone.utc), str(e)[:120]


def P(kind, **kw):
    print("PROBE", json.dumps({"kind": kind, **kw}, default=str, separators=(",", ":")), flush=True)


def walk_keys(o, pat, path="", out=None, depth=0):
    out = {} if out is None else out
    if depth > 6:
        return out
    if isinstance(o, dict):
        for k, v in o.items():
            if re.search(pat, k, re.I):
                out[path + "/" + k] = out.get(path + "/" + k, 0) + 1
            walk_keys(v, pat, path + "/" + k, out, depth + 1)
    elif isinstance(o, list):
        for v in o[:50]:
            walk_keys(v, pat, path + "[]", out, depth + 1)
    return out


now = datetime.now(timezone.utc)
P("start", utc=now.isoformat())
# ---------------- NBA
seen = 0
for off in (0, 1):
    d = (now + timedelta(days=off)).strftime("%Y%m%d")
    sb, t0, t1, st = get(f"{B}/basketball/nba/scoreboard?dates={d}")
    P("nba_scoreboard", date=d, status=st, events=len((sb or {}).get("events", [])))
    for ev in (sb or {}).get("events", []):
        comp = ev["competitions"][0]; state = comp["status"]["type"]["state"]
        tip = ev.get("date")
        body, f0, f1, st2 = get(f"{B}/basketball/nba/summary?event={ev['id']}")
        if body is None:
            P("nba_summary", id=ev["id"], state=state, tip=tip, status=st2); continue
        players = (body.get("boxscore") or {}).get("players") or []
        n_ath = n_start = 0
        for tp in players:
            for g in tp.get("statistics") or []:
                for a in g.get("athletes") or []:
                    n_ath += 1; n_start += a.get("starter") is True
        mins = None
        try:
            mins = round((datetime.fromisoformat(tip.replace("Z", "+00:00")) - f1).total_seconds() / 60, 1)
        except Exception:
            pass
        P("nba_summary", id=ev["id"], state=state, tip=tip, fetched_utc=f1.isoformat(), minutes_to_tip=mins, top_keys=sorted(body), boxscore_keys=sorted(body.get("boxscore") or {}),
          n_box_players=len(players), n_athletes=n_ath, n_starters_flagged=n_start, rosters_present="rosters" in body, lineup_like_keys=walk_keys(body, r"starter|lineup|probable|projected"))
        # core API roster (competition competitors)
        if state == "pre" and seen < 3:
            seen += 1
            for c in comp.get("competitors", [])[:2]:
                core = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{ev['id']}/competitions/{ev['id']}/competitors/{c['team']['id']}/roster"
                rb, _, c1, st3 = get(core)
                ents = (rb or {}).get("entries") or []
                P("nba_core_roster", id=ev["id"], team=c["team"].get("abbreviation"), status=st3, n=len(ents), keys=sorted(ents[0]) if ents else None,
                  starters=sum(1 for e in ents if e.get("starter") is True))
# ---------------- SOCCER: completed matches, cross-check cards/shots/corners
yd = (now - timedelta(days=1)).strftime("%Y%m%d"); n_done = 0
for lg in ("eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "usa.1", "mex.1", "bra.1", "arg.1", "uefa.champions"):
    sb, _, _, st = get(f"{B}/soccer/{lg}/scoreboard?dates={yd}")
    for ev in (sb or {}).get("events", []):
        comp = ev["competitions"][0]
        if comp["status"]["type"]["state"] != "post" or n_done >= 8:
            continue
        details = comp.get("details") or []
        sb_cards = {}
        for d in details:
            if d.get("yellowCard") or d.get("redCard"):
                k = ("red" if d.get("redCard") else "yellow", (d.get("team") or {}).get("id"))
                sb_cards[f"{k[0]}:{k[1]}"] = sb_cards.get(f"{k[0]}:{k[1]}", 0) + 1
        body, f0, f1, st2 = get(f"{B}/soccer/{lg}/summary?event={ev['id']}")
        if body is None:
            P("soc_summary", league=lg, id=ev["id"], status=st2); continue
        teams = (body.get("boxscore") or {}).get("teams") or []
        P("soc_summary", league=lg, id=ev["id"], fetched_utc=f1.isoformat(), kickoff=ev.get("date"), scoreboard_details=len(details), scoreboard_cards=sb_cards,
          home_away_scoreboard=[(c.get("homeAway"), c["team"]["id"], c.get("score")) for c in comp["competitors"]],
          boxscore_teams=[{"team": (t.get("team") or {}).get("id"), "homeAway": t.get("homeAway"), "stats": {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}} for t in teams],
          keyEvents_cards=sum(1 for k in body.get("keyEvents") or [] if re.search("card", ((k.get("type") or {}).get("text") or ""), re.I)), top_keys=sorted(body),
          lineup_like_keys=walk_keys(body, r"xg|expectedgoal"))
        n_done += 1
P("done", utc=datetime.now(timezone.utc).isoformat())

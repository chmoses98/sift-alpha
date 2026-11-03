"""Read-only runner probe v2: POPULATED VALUES, timestamps and historical depth (v1 recorded key presence only).
Archives raw summaries (gzip) verbatim next to a per-field verdict. No inference, no projection."""
import gzip, json, sys, time, urllib.request
from datetime import date, timedelta
from pathlib import Path

H = {"User-Agent": "sift-alpha-value-probe/1"}
out = Path(sys.argv[1]); (out / "raw").mkdir(parents=True, exist_ok=True)
NOW = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
res = {"started": NOW(), "espn": {}, "soccer_missing_box": [], "nhl_web": [], "mlb_statsapi": [], "tennis": {}}


def get(u):
    t = NOW()
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40)
        raw = r.read()
        return json.loads(raw), raw, {"url": u, "status": r.status, "fetched_at": t, "bytes": len(raw)}
    except Exception as e:  # noqa: BLE001
        return None, b"", {"url": u, "error": str(e)[:150], "fetched_at": t}


def save(name, raw):
    (out / "raw" / (name + ".json.gz")).write_bytes(gzip.compress(raw))


def num(v):
    if v is None: return None
    s = str(v).replace("%", "").replace("--", "").strip()
    if s in ("", "-"): return None
    try: return float(s.split("-")[0].split("/")[0].replace(":", "."))
    except ValueError: return None


def verdict(summary):
    """Per team-stat and per player-label: populated count / total and numeric-parse count."""
    teams, players = {}, {}
    for t in summary.get("boxscore", {}).get("teams", []):
        for s in t.get("statistics", []):
            d = teams.setdefault(s.get("name"), {"n": 0, "populated": 0, "numeric": 0, "sample": None})
            d["n"] += 1
            v = s.get("displayValue", s.get("value"))
            if v not in (None, "", "--"): d["populated"] += 1
            if num(v) is not None: d["numeric"] += 1
            if d["sample"] is None: d["sample"] = v
    for pl in summary.get("boxscore", {}).get("players", []):
        for cat in pl.get("statistics", []):
            key = cat.get("name") or cat.get("type") or "?"
            labels = cat.get("labels") or []
            for a in cat.get("athletes", []):
                for lab, v in zip(labels, a.get("stats") or []):
                    d = players.setdefault(key + "." + lab, {"n": 0, "populated": 0, "numeric": 0, "sample": None})
                    d["n"] += 1
                    if v not in (None, "", "--"): d["populated"] += 1
                    if num(v) is not None: d["numeric"] += 1
                    if d["sample"] is None: d["sample"] = v
    return {"team": teams, "player": players}


def completed_ids(path, d, q=""):
    b, _, m = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}&{q}")
    out_ = []
    for ev in (b or {}).get("events", []):
        c = ev["competitions"][0]
        if c["status"]["type"].get("completed"):
            out_.append({"id": ev["id"], "scoreboard_date": ev.get("date"), "status": c["status"]["type"].get("name")})
    return out_


ESPN = {"nfl": ("football/nfl", ""), "cfb": ("football/college-football", "groups=80&limit=100"), "nba": ("basketball/nba", ""),
        "cbb": ("basketball/mens-college-basketball", ""), "nhl": ("hockey/nhl", ""), "mlb": ("baseball/mlb", "")}
today = date.today()
# recent = latest 3 completed; historical = same calendar window 1, 2 and 3 seasons back (does the endpoint still serve full box scores?)
OFFSETS = {"recent": [1, 2, 3, 4, 5, 6, 7, 10, 14], "1y": [365, 366, 367], "2y": [730, 731, 732], "3y": [1095, 1096, 1097]}
for lg, (path, q) in ESPN.items():
    res["espn"][lg] = {}
    for era, offs in OFFSETS.items():
        picked = []
        for o in offs:
            d = (today - timedelta(days=o)).strftime("%Y%m%d")
            for e in completed_ids(path, d, q):
                picked.append({**e, "date_queried": d})
            time.sleep(0.25)
            if len(picked) >= (3 if era == "recent" else 1): break
        games = []
        for e in picked[: 3 if era == "recent" else 1]:
            b, raw, m = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={e['id']}")
            rec = {**e, **{k: m.get(k) for k in ("url", "status", "error", "fetched_at", "bytes")}}
            if b:
                save(f"{lg}_{era}_{e['id']}", raw)
                hd = (b.get("header", {}).get("competitions") or [{}])[0]
                rec["header_date"] = hd.get("date"); rec["header_status"] = (hd.get("status") or {}).get("type", {}).get("name")
                rec["n_players_listed"] = sum(len(c.get("athletes", [])) for pl in b.get("boxscore", {}).get("players", []) for c in pl.get("statistics", []))
                rec["n_plays"] = len(b.get("plays") or []) or len((b.get("drives") or {}).get("previous") or [])
                plays = b.get("plays") or []
                rec["last_play_wallclock"] = plays[-1].get("wallclock") if plays and isinstance(plays[-1], dict) else None
                rec["first_play_wallclock"] = plays[0].get("wallclock") if plays and isinstance(plays[0], dict) else None
                rec["wallclockAvailable"] = b.get("wallclockAvailable")
                rec["officials"] = [o.get("displayName") for o in (b.get("gameInfo", {}).get("officials") or [])][:6]
                rec["venue"] = (b.get("gameInfo", {}).get("venue") or {}).get("fullName")
                rec["attendance"] = b.get("gameInfo", {}).get("attendance")
                rec["pickcenter_n"] = len(b.get("pickcenter") or []); rec["pickcenter_first"] = (b.get("pickcenter") or [None])[0]
                rec["injuries_teams"] = [(t.get("team", {}).get("displayName"), len(t.get("injuries", []))) for t in b.get("injuries", []) or []]
                rec["verdict"] = verdict(b)
            games.append(rec); time.sleep(0.25)
        res["espn"][lg][era] = games

# soccer: the 11 finished matches whose box-score stats were NOT populated by PR #39 (why?) + 3 populated controls
SOC = [("bra.1", "401841288"), ("bra.1", "401841292"), ("bra.1", "401841290"), ("eng.league_cup", "401921844"), ("ita.1", "401874976"),
       ("ita.1", "401874969"), ("ksa.1", "401900882"), ("ksa.1", "401900881"), ("ksa.1", "401900880"), ("ksa.1", "401900885"),
       ("ksa.1", "401900877"), ("arg.1", "401841655")]
for lg, ev in SOC:
    b, raw, m = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={ev}")
    rec = {"league": lg, "event": ev, **{k: m.get(k) for k in ("status", "error", "fetched_at", "bytes")}}
    if b:
        save(f"soccer_{lg}_{ev}", raw)
        bx = b.get("boxscore", {})
        rec["boxscore_keys"] = sorted(bx.keys()); rec["n_team_blocks"] = len(bx.get("teams", []))
        rec["team_stats"] = [{s.get("name"): s.get("displayValue") for s in t.get("statistics", [])} for t in bx.get("teams", [])]
        rec["header_status"] = ((b.get("header", {}).get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("name")
        rec["summary_top_keys"] = sorted(b.keys())
    res["soccer_missing_box"].append(rec); time.sleep(0.25)

# NHL api-web: populated values + TOI + timestamps
d0 = None
for k in range(1, 10):
    d = (today - timedelta(days=k)).isoformat()
    b, _, m = get(f"https://api-web.nhle.com/v1/schedule/{d}")
    gs = [g for w in (b or {}).get("gameWeek", []) if w.get("date") == d for g in w.get("games", []) if g.get("gameState") in ("OFF", "FINAL")]
    if gs: break
for g in gs[:3]:
    pb, raw, m1 = get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/play-by-play")
    bx, raw2, m2 = get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/boxscore")
    rec = {"game": g["id"], "pbp": m1.get("status") or m1.get("error"), "box": m2.get("status") or m2.get("error"), "pbp_fetched_at": m1["fetched_at"]}
    if pb:
        save(f"nhlweb_pbp_{g['id']}", raw)
        shots = [p for p in pb["plays"] if p.get("typeDescKey") in ("shot-on-goal", "goal", "missed-shot", "blocked-shot")]
        rec["shot_sample"] = shots[0] if shots else None
        rec["xy_populated_numeric"] = sum(1 for p in shots if isinstance(p.get("details", {}).get("xCoord"), (int, float)) and isinstance(p.get("details", {}).get("yCoord"), (int, float)))
        rec["n_shots"] = len(shots); rec["gameDate"] = pb.get("gameDate"); rec["startTimeUTC"] = pb.get("startTimeUTC")
        rec["officials"] = (pb.get("summary") or {}).get("gameInfo") if isinstance(pb.get("summary"), dict) else None
    if bx:
        save(f"nhlweb_box_{g['id']}", raw2)
        sk = [p for side in ("homeTeam", "awayTeam") for grp in ("forwards", "defense") for p in bx.get("playerByGameStats", {}).get(side, {}).get(grp, [])]
        rec["n_skaters"] = len(sk); rec["toi_populated"] = sum(1 for p in sk if p.get("toi") not in (None, "", "00:00")); rec["sample_skater"] = sk[0] if sk else None
        gl = [p for side in ("homeTeam", "awayTeam") for p in bx.get("playerByGameStats", {}).get(side, {}).get("goalies", [])]
        rec["sample_goalie"] = gl[0] if gl else None
    res["nhl_web"].append(rec); time.sleep(0.25)

# MLB statsapi: populated pitcher/hitter values, starter flag, game start time (+ older seasons for depth)
for era, off in (("recent", 7), ("1y", 365), ("2y", 730), ("3y", 1095)):
    got = None
    for k in range(off, off + 12):
        d = (today - timedelta(days=k)).isoformat()
        b, _, m = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}&hydrate=probablePitcher")
        pks = [g for dt in (b or {}).get("dates", []) for g in dt.get("games", []) if g.get("status", {}).get("abstractGameState") == "Final"]
        if pks: got = (d, pks[0]); break
        time.sleep(0.2)
    if not got: res["mlb_statsapi"].append({"era": era, "found": False}); continue
    d, g = got; pk = g["gamePk"]
    bx, raw, m = get(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore")
    rec = {"era": era, "date": d, "gamePk": pk, "gameDate": g.get("gameDate"), "boxscore": m.get("status") or m.get("error"), "fetched_at": m["fetched_at"],
           "probable_home": ((g.get("teams", {}).get("home", {}).get("probablePitcher")) or {}).get("fullName")}
    if bx:
        save(f"mlb_box_{era}_{pk}", raw)
        for side in ("home", "away"):
            t = bx["teams"][side]
            pit = [p for p in t["players"].values() if p.get("stats", {}).get("pitching") and p["stats"]["pitching"].get("inningsPitched") not in (None, "0.0")]
            rec[side] = {"pitchers_used": len(pit), "pitchingOrder": t.get("pitchers"), "battingOrder": t.get("battingOrder"),
                         "sample_pitching": pit[0]["stats"]["pitching"] if pit else None, "season_stats_sample": (pit[0].get("seasonStats") or {}).get("pitching") if pit else None,
                         "n_batters": len([p for p in t["players"].values() if p.get("stats", {}).get("batting")])}
    res["mlb_statsapi"].append(rec); time.sleep(0.25)

# Tennis ESPN: are competitor.statistics populated for completed matches?
for tour in ("atp", "wta"):
    found = []
    for k in range(1, 8):
        d = (today - timedelta(days=k)).strftime("%Y%m%d")
        b, raw, m = get(f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={d}")
        for e in (b or {}).get("events", []):
            for gr in e.get("groupings", []) or []:
                for c in gr.get("competitions", []):
                    if (c.get("status", {}).get("type") or {}).get("completed"):
                        found.append({"scoreboard_date": d, "tournament": e.get("name"), "grouping": (gr.get("grouping") or {}).get("displayName"), "startDate": c.get("startDate") or c.get("date"), "round": (c.get("round") or {}).get("displayName"),
                                      "competitors": [{"name": (x.get("athlete") or {}).get("displayName"), "winner": x.get("winner"), "linescores": x.get("linescores"), "statistics": x.get("statistics"), "curatedRank": x.get("curatedRank")} for x in c.get("competitors", [])]})
        if len(found) >= 6: break
        time.sleep(0.25)
    res["tennis"][tour] = {"completed_matches_seen": len(found), "sample": found[:4],
                           "with_statistics": sum(1 for f in found if any(c["statistics"] for c in f["competitors"])),
                           "with_linescores": sum(1 for f in found if any(c["linescores"] for c in f["competitors"]))}

res["finished"] = NOW()
(out / "value_probe.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
print(json.dumps({"espn": {lg: {e: len(v) for e, v in eras.items()} for lg, eras in res["espn"].items()}, "soccer": len(res["soccer_missing_box"]), "nhl": len(res["nhl_web"]), "mlb": len(res["mlb_statsapi"])}))

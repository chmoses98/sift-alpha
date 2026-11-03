"""Read-only runner probe: which statistical fields do free public endpoints actually return for completed games?
Records presence/absence only (stat names, label sets, counts per sampled game). No inference, no projection."""
import json, sys, time, urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

H = {"User-Agent": "sift-alpha-field-probe/1"}
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
res = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": {}}


def get(u):
    t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40)
        return json.loads(r.read()), {"url": u, "status": r.status, "fetched_at": t}
    except Exception as e:  # noqa: BLE001
        return None, {"url": u, "error": str(e)[:150], "fetched_at": t}


def recent_completed(path, q="", n=3, back=10):
    ids = []
    for k in range(1, back + 1):
        d = (date.today() - timedelta(days=k)).strftime("%Y%m%d")
        b, meta = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}&{q}")
        for ev in (b or {}).get("events", []):
            if ev["competitions"][0]["status"]["type"].get("completed"):
                ids.append(ev["id"])
        if len(ids) >= n: break
        time.sleep(0.3)
    return ids[:n]


ESPN = {"nfl": "football/nfl", "cfb": "football/college-football", "nba": "basketball/nba", "cbb": "basketball/mens-college-basketball",
        "nhl": "hockey/nhl", "mlb": "baseball/mlb", "tennis_atp": "tennis/atp", "tennis_wta": "tennis/wta"}
for lg, path in ESPN.items():
    if lg.startswith("tennis"):
        ev = []
        for k in range(1, 8):
            d = (date.today() - timedelta(days=k)).strftime("%Y%m%d")
            b, meta = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}")
            for e in (b or {}).get("events", []):
                ev.append(e)
            if ev: break
        keys = Counter()
        for e in ev[:3]:
            for g in e.get("groupings", []) or []:
                for c in g.get("competitions", [])[:3]:
                    keys.update(c.keys())
                    for cp in c.get("competitors", [])[:2]: keys.update("competitor." + k for k in cp.keys())
        res["sources"][lg] = {"scoreboard_events": len(ev), "competition_keys": dict(keys), "sample_competitor_linescore": (((ev[0].get("groupings") or [{}])[0].get("competitions") or [{}])[0].get("competitors") or [{}])[0].get("linescores") if ev else None}
        continue
    ids = recent_completed(path, "groups=80&limit=100" if lg == "cfb" else "")
    stats, plabels, topkeys, per = Counter(), defaultdict(set), Counter(), []
    for i in ids:
        b, meta = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={i}")
        rec = {"event": i, **{k: meta.get(k) for k in ("status", "error", "url")}}
        if b:
            topkeys.update(b.keys())
            names = set()
            for t in b.get("boxscore", {}).get("teams", []):
                for s in t.get("statistics", []):
                    names.add(s.get("name"))
            stats.update(names)
            for pl in b.get("boxscore", {}).get("players", []):
                for cat in pl.get("statistics", []):
                    plabels[cat.get("name") or cat.get("type") or "?"].update(cat.get("labels") or [])
            rec["team_stat_names"] = sorted(n for n in names if n)
            rec["n_plays"] = len(b.get("plays") or []); rec["n_scoring_plays"] = len(b.get("scoringPlays") or []); rec["n_drives"] = len((b.get("drives") or {}).get("previous") or [])
            rec["has_officials"] = bool(b.get("gameInfo", {}).get("officials")); rec["has_pickcenter"] = bool(b.get("pickcenter"))
        per.append(rec); time.sleep(0.3)
    res["sources"][lg] = {"games": len(ids), "team_stat_names_count_of_games": dict(stats), "summary_top_keys": dict(topkeys), "player_stat_labels": {k: sorted(v) for k, v in plabels.items()}, "per_game": per}

# NHL official API: boxscore + play-by-play (shot coordinates, penalties, shootout period type)
nh = {}
for k in range(1, 8):
    d = (date.today() - timedelta(days=k)).isoformat()
    b, meta = get(f"https://api-web.nhle.com/v1/schedule/{d}")
    gs = [g for w in (b or {}).get("gameWeek", []) if w.get("date") == d for g in w.get("games", []) if g.get("gameState") in ("OFF", "FINAL")]
    if gs: break
nh["schedule_probe"] = meta; nh["games"] = []
for g in gs[:3]:
    pb, m1 = get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/play-by-play")
    bx, m2 = get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/boxscore")
    rec = {"game": g["id"], "pbp": m1.get("status") or m1.get("error"), "boxscore": m2.get("status") or m2.get("error")}
    if pb:
        types = Counter(p.get("typeDescKey") for p in pb.get("plays", []))
        shots = [p for p in pb.get("plays", []) if p.get("typeDescKey") in ("shot-on-goal", "goal", "missed-shot", "blocked-shot")]
        rec["event_types"] = dict(types); rec["shot_events"] = len(shots)
        rec["shot_with_xy"] = sum(1 for p in shots if "xCoord" in p.get("details", {}) and "yCoord" in p.get("details", {}))
        rec["period_types"] = sorted({p.get("periodDescriptor", {}).get("periodType") for p in pb.get("plays", [])})
        rec["penalty_events"] = types.get("penalty", 0)
        rec["has_shootout_events"] = any(p.get("periodDescriptor", {}).get("periodType") == "SO" for p in pb.get("plays", []))
    if bx:
        rec["boxscore_keys"] = sorted(bx.keys()); ptg = bx.get("playerByGameStats", {})
        rec["team_player_stat_keys"] = {side: {grp: sorted((lst[0].keys() if lst else [])) for grp, lst in ptg.get(side, {}).items()} for side in ("homeTeam",)}
    nh["games"].append(rec); time.sleep(0.3)
res["sources"]["nhl_api_web"] = nh

# MLB Stats API: boxscore + live feed for first-three-innings split, TTO (batters faced), SB, total bases
ml = {}
for k in range(1, 8):
    d = (date.today() - timedelta(days=k)).isoformat()
    b, meta = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}")
    pks = [g["gamePk"] for dt in (b or {}).get("dates", []) for g in dt.get("games", []) if g.get("status", {}).get("abstractGameState") == "Final"]
    if pks: break
ml["schedule_probe"] = meta; ml["games"] = []
for pk in pks[:3]:
    bx, m = get(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore")
    ls, m2 = get(f"https://statsapi.mlb.com/api/v1/game/{pk}/linescore")
    rec = {"gamePk": pk, "boxscore": m.get("status") or m.get("error"), "linescore": m2.get("status") or m2.get("error")}
    if bx:
        t = bx["teams"]["home"]
        pl = next(iter(t["players"].values()))
        pit = [p for p in t["players"].values() if p.get("stats", {}).get("pitching")]
        bat = [p for p in t["players"].values() if p.get("stats", {}).get("batting")]
        rec["pitching_keys"] = sorted(pit[0]["stats"]["pitching"].keys()) if pit else []
        rec["batting_keys"] = sorted(bat[0]["stats"]["batting"].keys()) if bat else []
    if ls: rec["innings_listed"] = len(ls.get("innings", [])); rec["inning_has_runs"] = all("runs" in i.get("home", {}) for i in ls.get("innings", []))
    ml["games"].append(rec); time.sleep(0.3)
res["sources"]["mlb_statsapi"] = ml
res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
(out / "field_probe.json").write_text(json.dumps(res, indent=1, sort_keys=True))
print(json.dumps({k: ({"games": v.get("games") if isinstance(v.get("games"), int) else len(v.get("games", []))} if isinstance(v, dict) else 0) for k, v in res["sources"].items()}))

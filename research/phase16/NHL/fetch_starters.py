"""Historical starting-goalie table from the public NHL api-web boxscore (playerByGameStats.*.goalies[].starter).

One row per (regular-season game, team). Provenance per row: endpoint URL, fetch time, sha256 of the response body.
Usage: python fetch_starters.py OUT_DIR SEASON_START [SEASON_END]   (season = first year, e.g. 2005 -> 2005-06)
"""
import concurrent.futures as cf, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests

UA = {"User-Agent": "nhl-edge-finder-research/0.1"}
URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"
S = requests.Session(); S.headers.update(UA)

def toi_min(s):
    if not s: return 0.0
    m, sec = s.split(":"); return int(m) + int(sec) / 60

def fetch(gid):
    url = URL.format(gid=gid)
    for attempt in range(4):
        try:
            r = S.get(url, timeout=20)
            if r.status_code == 404: return gid, None, url, None
            if r.status_code == 200: return gid, r.content, url, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except requests.RequestException:
            pass
        time.sleep(1.5 * (attempt + 1))
    return gid, "ERR", url, None

def rows_for(gid, body, url, ts):
    d = json.loads(body)
    if d.get("gameState") not in ("OFF", "FINAL"): return []
    pb = d.get("playerByGameStats") or {}
    sha = hashlib.sha256(body).hexdigest()
    out = []
    for side, opp in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
        gl = (pb.get(side) or {}).get("goalies") or []
        st = [g for g in gl if g.get("starter")]
        played = [g for g in gl if toi_min(g.get("toi")) > 0]
        s = st[0] if st else None
        out.append({
            "game_id": gid, "season": d.get("season"), "game_date": d.get("gameDate"), "start_time_utc": d.get("startTimeUTC"),
            "team_id": d[side]["id"], "team": d[side]["abbrev"], "opp_team_id": d[opp]["id"], "is_home": side == "homeTeam",
            "starter_id": s["playerId"] if s else None, "starter_name": (s.get("name") or {}).get("default") if s else None,
            "starter_toi_min": round(toi_min(s.get("toi")), 3) if s else None, "starter_shots_against": s.get("shotsAgainst") if s else None,
            "starter_goals_against": s.get("goalsAgainst") if s else None, "starter_decision": s.get("decision") if s else None,
            "n_starter_flags": len(st), "n_goalies_dressed": len(gl), "n_goalies_played": len(played),
            "relieved": len(played) > 1, "dressed_goalie_ids": ",".join(str(g["playerId"]) for g in gl),
            "source": "api-web.nhle.com boxscore playerByGameStats.goalies.starter", "source_url": url, "fetched_at_utc": ts, "response_sha256": sha,
        })
    return out

def season(year, out_dir, workers=6):
    path = Path(out_dir) / f"starters_{year}.jsonl"
    if path.exists() and path.stat().st_size > 0 and year < 2026: return
    rows, missing, errs, n = [], 0, [], 1
    with cf.ThreadPoolExecutor(workers) as ex:
        while missing < 3:
            batch = [int(f"{year}02{i:04d}") for i in range(n, n + 60)]
            n += 60
            for gid, body, url, ts in ex.map(fetch, batch):
                if body is None: missing += 1; continue
                if body == "ERR": errs.append(gid); continue
                missing = 0
                rows += rows_for(gid, body, url, ts)
            if missing >= 3: break
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(json.dumps({"season": year, "rows": len(rows), "errors": errs[:20], "n_err": len(errs)}), flush=True)

if __name__ == "__main__":
    out = sys.argv[1]; a = int(sys.argv[2]); b = int(sys.argv[3]) if len(sys.argv) > 3 else a
    Path(out).mkdir(parents=True, exist_ok=True)
    for y in range(b, a - 1, -1): season(y, out)

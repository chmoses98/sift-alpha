"""Verify free data sources against what the catalog claims (RESEARCH_ONLY). Records MEASURED facts: HTTP status, year coverage probed, fields present, completeness.

Not verified here (stated, not assumed): licence/terms, accuracy against an independent provider, and point-in-time vintage. A live snapshot endpoint (e.g. injury lists) is marked
SNAPSHOT_ONLY: its history cannot be reconstructed, so point-in-time use requires prospective archiving.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/input_research/source_verification.json"
UA = {"User-Agent": "sift-alpha-research/1"}
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
NFL_ASSETS = {  # tag -> (filename template, years probed, catalog inputs it can serve)
    "pbp_participation": ("pbp_participation_{y}.parquet", [2015, 2016, 2018, 2022, 2024, 2025], ["nfl.coverage_scheme", "nfl.formation", "nfl.pressure_qb", "nfl.def_personnel", "nfl.routes"]),
    "ftn_charting": ("ftn_charting_{y}.parquet", [2021, 2022, 2023, 2025], ["nfl.formation", "nfl.routes", "nfl.cb_coverage_matchup"]),
    "pfr_advstats": ("advstats_week_pass_{y}.csv", [2017, 2018, 2020, 2025], ["nfl.pressure_qb", "nfl.ol", "nfl.pass_rush", "nfl.catch_rate_oe"]),
    "nextgen_stats": ("ngs_{y}_passing.csv.gz", [2015, 2016, 2018, 2023], ["nfl.ngs", "nfl.air_yards_adot"]),
    "depth_charts": ("depth_charts_{y}.csv", [2000, 2001, 2010, 2025], ["nfl.depth_chart_pit"]),
    "snap_counts": ("snap_counts_{y}.csv", [2011, 2012, 2025], ["nfl.snaps"]),
    "injuries": ("injuries_{y}.csv", [2008, 2009, 2025], ["nfl.injuries_pit", "nfl.inactives_pit"]),
    "rosters": ("roster_{y}.csv", [1999, 2024, 2025], ["nfl.roster_continuity"]),
    "stats_player": ("stats_player_week_{y}.csv", [2011, 2012, 2025], ["nfl.targets", "nfl.carries"]),
}


def head(url: str, timeout=30):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=timeout).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return type(e).__name__


def get(url: str, timeout=40):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        return r.status, json.load(r)
    except Exception as e:
        return str(e)[:80], None


def nflverse() -> dict:
    out = {}
    for tag, (tpl, years, serves) in NFL_ASSETS.items():
        st = {y: head(f"{NFLVERSE}/{tag}/{tpl.format(y=y)}") for y in years}
        ok = [y for y, s in st.items() if s == 200]
        out[tag] = {"status_by_year": st, "earliest_ok_probed": min(ok) if ok else None, "latest_ok_probed": max(ok) if ok else None, "serves_catalog_inputs": serves}
    st = head(f"{NFLVERSE}/officials/officials.csv")
    out["officials"] = {"status": st, "serves_catalog_inputs": ["nfl.officials_crew"]}
    return out


def football_data(cache: Path) -> dict:
    import pandas as pd
    cols = ["Referee", "HS", "AS", "HST", "AST", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]
    rows = {}
    for f in sorted(cache.glob("*.csv")):
        lg, yr = f.stem.split("_")
        d = pd.read_csv(f, encoding="utf-8-sig", usecols=lambda c: c in cols or c in ("FTHG",), on_bad_lines="skip").dropna(subset=["FTHG"])
        for c in cols:
            rows.setdefault(c, {}).setdefault(yr, []).append(float(d[c].notna().mean()) if c in d else 0.0)
    comp = {c: {yr: round(sum(v) / len(v), 3) for yr, v in by.items()} for c, by in rows.items()}
    ref = {}
    for f in sorted(cache.glob("*.csv")):
        lg, yr = f.stem.split("_")
        d = pd.read_csv(f, encoding="utf-8-sig", usecols=lambda c: c in ("Referee", "FTHG"), on_bad_lines="skip").dropna(subset=["FTHG"])
        ref.setdefault(lg, []).append(float(d["Referee"].notna().mean()) if "Referee" in d else 0.0)
    referee_by_league = {lg: round(sum(v) / len(v), 3) for lg, v in ref.items()}
    return {"leagues": ["E0", "SP1", "D1", "I1", "F1"], "files": len(list(cache.glob("*.csv"))), "column_completeness_by_season_mean_over_leagues": comp, "referee_name_completeness_by_league": referee_by_league,
            "serves_catalog_inputs": ["soc.corners", "soc.fouls_cards", "soc.referee", "soc.shots", "soc.keeper_workload"],
            "note": "team-level counts and referee name only; no player-level data, no xG, no lineups; odds columns exist in the files and are never read"}


def mlb() -> dict:
    out = {"sampled_games": {}}
    for date in ("2008-07-15", "2015-07-20", "2023-07-15", "2025-09-20"):
        s, d = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}&hydrate=probablePitcher,lineups,weather,officials")
        if not d or not d.get("dates"):
            out["sampled_games"][date] = {"status": s}; continue
        gm = d["dates"][0]["games"][0]
        rec = {"status": s, "schedule_has": [k for k in ("lineups", "officials", "weather") if k in gm], "probable_pitcher_home": bool((gm["teams"]["home"] or {}).get("probablePitcher"))}
        s2, f = get(f"https://statsapi.mlb.com/api/v1.1/game/{gm['gamePk']}/feed/live")
        if f:
            plays = f["liveData"]["plays"]["allPlays"]
            pit = [e for p in plays for e in p["playEvents"] if "pitchData" in e]
            rec.update({"plays": len(plays), "pitches_with_pitchData": len(pit), "pitchData_keys": sorted(pit[0]["pitchData"].keys())[:12] if pit else [], "has_hitData": any("hitData" in e for p in plays for e in p["playEvents"]),
                        "weather_in_gameData": bool(f["gameData"].get("weather")), "umpires_in_boxscore": len(f["liveData"]["boxscore"].get("officials", []))})
        out["sampled_games"][date] = rec
    out["serves_catalog_inputs"] = ["mlb.pitch_mix", "mlb.velo_trend", "mlb.pitch_type_whiff", "mlb.hitter_contact_profile", "mlb.lineup_pit", "mlb.umpire", "mlb.weather_pit", "mlb.sp_workload", "mlb.bullpen"]
    out["note"] = "weather is the recorded game-time observation, not a forecast vintage; lineups in the schedule hydrate are the posted lineup (timestamp of posting not recorded)"
    return out


def nhl() -> dict:
    out = {"sampled_games": {}}
    for gid in ("2015020001", "2020020001", "2024020001"):
        s, x = get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play")
        out["sampled_games"][gid] = {"status": s, "plays": len(x["plays"]) if x else None, "play_keys": sorted(x["plays"][5].keys())[:10] if x else None, "has_xy_coordinates": bool(x and "xCoord" in str(x["plays"][5].get("details", {})))}
    out["serves_catalog_inputs"] = ["nhl.shot_location", "nhl.score_state", "nhl.pace", "nhl.period_split", "nhl.first_goal_hazard", "nhl.empty_net"]
    out["not_available_on_allowlisted_hosts"] = "shift charts and goalie-start confirmations are on other hosts (api.nhle.com, dailyfaceoff.com), not reachable from this runner"
    return out


def espn() -> dict:
    s, d = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries")
    snap = {"status": s, "top_keys": list(d)[:5] if d else None, "timestamp": d.get("timestamp") if d else None}
    return {"nba_injuries": snap, "classification": "SNAPSHOT_ONLY", "implication": "A live injury list has no history endpoint: injury-timing research requires archiving this feed prospectively. Past vintages cannot be reconstructed from it.",
            "serves_catalog_inputs": ["nba.injuries_pit", "cbb.injuries", "cfb.injuries"]}


def blocked() -> dict:
    return {u: head(u) for u in ("https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json", "https://www.tennis-data.co.uk/2025/2025.xlsx", "https://tennisabstract.com", "https://www.baseball-reference.com", "https://fbref.com", "https://www.pro-football-reference.com")}


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    res = {"schema_version": "source-verification-1.0", "status": "RESEARCH_ONLY", "verified_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "nflverse": nflverse(), "mlb_statsapi": mlb(), "nhl_api": nhl(), "espn": espn(),
           "football_data": football_data(cache) if cache and cache.exists() else {"status": "not run (no cache dir given)"}, "reachability_from_runner": blocked(),
           "not_verified": ["licence/terms of use", "agreement with an independent provider", "point-in-time vintage of any historical file (files are final snapshots unless stated)"]}
    OUT.write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps({"nflverse": {k: (v.get("earliest_ok_probed"), v.get("latest_ok_probed")) for k, v in res["nflverse"].items() if "earliest_ok_probed" in v}, "blocked": res["reachability_from_runner"]}, indent=0))


if __name__ == "__main__":
    main()

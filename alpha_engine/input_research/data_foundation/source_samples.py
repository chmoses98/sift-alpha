"""Measured samples from FREE, already-reachable sources (RESEARCH_ONLY, $0).

    python -m alpha_engine.input_research.data_foundation.source_samples GROUP SCRATCH_DIR

Downloads real files/pages into SCRATCH_DIR only (never the repo), profiles them and writes a compact JSON under research/input_research/data_foundation/source_samples/<GROUP>.json:
columns with non-null share, row counts, season/date coverage, event-time (timestamp) fields and how they relate to the game time, per-season missingness. Nothing here creates accounts, uses keys,
scrapes websites or touches a host that is not already reachable. A source existing is NOT an implemented input: this module measures raw availability only.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUTD = ROOT / "research/input_research/data_foundation/source_samples"
UA = "sift-alpha-research/1.0 (research-only source measurement)"
REL = "https://github.com/nflverse/nflverse-data/releases/download"


def get(url: str, dest: Path, tries: int = 2) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sS", "-L", "--max-time", "300", "-A", UA, "-o", str(dest), "-w", "%{http_code}|%{size_download}", url], capture_output=True, text=True)
    code, size = (r.stdout.split("|") + ["0", "0"])[:2]
    return {"url": url, "http": int(code or 0), "bytes": int(size or 0)}


def jget(url: str, timeout: int = 40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except Exception as e:
        return getattr(e, "code", 0), None


def profile(df: pd.DataFrame, time_cols=(), season_col=None, key=None) -> dict:
    out = {"rows": int(len(df)), "columns": {c: round(float(df[c].notna().mean()), 3) for c in df.columns}}
    if season_col and season_col in df:
        out["seasons"] = [int(df[season_col].min()), int(df[season_col].max())]
        out["rows_by_season"] = {str(k): int(v) for k, v in df.groupby(season_col).size().items()}
    for c in time_cols:
        if c in df:
            t = pd.to_datetime(df[c], errors="coerce", utc=True)
            out.setdefault("time_fields", {})[c] = {"nonnull": round(float(t.notna().mean()), 3), "min": str(t.min()), "max": str(t.max())}
    if key:
        out["rows_per_key"] = {"key": list(key), "max": int(df.groupby(list(key)).size().max()), "mean": round(float(df.groupby(list(key)).size().mean()), 3)}
    return out


def nflverse(scratch: Path) -> dict:
    sc = scratch / "nflverse"; res = {"group": "nflverse", "source_host": "github.com release assets (already reachable)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "datasets": {}}
    games = pd.read_csv(scratch.parent / "replay/nfl/games.csv", usecols=["season", "week", "gameday", "gametime", "home_team", "away_team", "game_type"]) if (scratch.parent / "replay/nfl/games.csv").exists() else None
    specs = [("injuries", "injuries", [2009, 2012, 2016, 2020, 2024, 2025]), ("depth_charts", "depth_charts", [2001, 2010, 2016, 2024, 2025]), ("snap_counts", "snap_counts", [2012, 2018, 2024, 2025]),
             ("pbp_participation", "pbp_participation", [2016, 2020, 2024, 2025]), ("ftn_charting", "ftn_charting", [2022, 2024, 2025]), ("pfr_advstats", "pfr_advstats", None), ("rosters", "rosters", [1999, 2012, 2024]),
             ("weekly_rosters", "weekly_rosters", [2018, 2024]), ("player_stats", "player_stats", [2011, 2024]), ("nextgen_stats", "nextgen_stats", None)]
    for name, tag, years in specs:
        ent = {"files": []}; frames = []
        files = []
        if name == "pfr_advstats":
            files = [("advstats_week_pass_2024.parquet", 2024), ("advstats_week_rush_2024.parquet", 2024), ("advstats_week_rec_2024.parquet", 2024), ("advstats_week_def_2024.parquet", 2024)]
        elif name == "nextgen_stats":
            files = [("ngs_passing.parquet", None), ("ngs_rushing.parquet", None), ("ngs_receiving.parquet", None)]
        elif name == "weekly_rosters":
            files = [(f"roster_weekly_{y}.parquet", y) for y in years]
        elif name == "rosters":
            files = [(f"roster_{y}.parquet", y) for y in years]
        elif name == "player_stats":
            files = [(f"player_stats_{y}.parquet", y) for y in years]
        elif name == "pbp_participation":
            files = [(f"pbp_participation_{y}.parquet", y) for y in years]
        else:
            files = [(f"{name}_{y}.parquet", y) for y in years]
        tagdir = {"weekly_rosters": "weekly_rosters", "rosters": "rosters", "player_stats": "player_stats", "pbp_participation": "pbp_participation", "pfr_advstats": "pfr_advstats", "nextgen_stats": "nextgen_stats"}.get(name, tag)
        for fn, y in files:
            d = sc / tagdir / fn; g = get(f"{REL}/{tagdir}/{fn}", d); g["file"] = fn
            if g["http"] == 200 and g["bytes"] > 2000:
                try:
                    df = pd.read_parquet(d); frames.append((y, df)); g["rows"] = int(len(df))
                except Exception as e:
                    g["error"] = type(e).__name__
            ent["files"].append(g)
        if frames:
            allc = {}
            for y, df in frames:
                for c in df.columns:
                    allc.setdefault(c, []).append(round(float(df[c].notna().mean()), 3))
            ent["columns_nonnull_by_file"] = {c: v for c, v in allc.items()}
            ent["first_file_profile"] = None
            big = frames[-1][1]
            tcols = [c for c in big.columns if any(k in c.lower() for k in ("date", "time", "dt", "modified", "gameday"))]
            ent["time_like_columns"] = tcols
            ent["profile_last_file"] = profile(big, time_cols=[c for c in tcols if big[c].dtype == object or "date" in str(big[c].dtype)][:4], season_col="season" if "season" in big else None)
        res["datasets"][name] = ent
    # injuries: do vintages exist, and are they before kickoff?
    try:
        inj = pd.read_parquet(sc / "injuries" / "injuries_2024.parquet")
        e = res["datasets"]["injuries"]["pit_analysis_2024"] = {"rows": int(len(inj)), "rows_per_player_week": float(inj.groupby(["season", "week", "gsis_id"]).size().mean()) if "gsis_id" in inj else None}
        if "date_modified" in inj and games is not None:
            m = inj.copy(); m["mod"] = pd.to_datetime(m.date_modified, errors="coerce", utc=True)
            g = games[games.season == 2024].copy(); g["kick"] = pd.to_datetime(g.gameday + " " + g.gametime.fillna("13:00"), errors="coerce", utc=True)
            rows = []
            for side in ("home_team", "away_team"):
                rows.append(g.rename(columns={side: "team"})[["season", "week", "team", "kick"]])
            kk = pd.concat(rows); mm = m.merge(kk, on=["season", "week", "team"], how="left")
            ok = mm["mod"].notna() & mm["kick"].notna()
            e["date_modified_nonnull"] = round(float(m["mod"].notna().mean()), 3); e["share_modified_before_kickoff_assuming_ET_as_UTC"] = round(float((mm.loc[ok, "mod"] <= mm.loc[ok, "kick"] + pd.Timedelta(hours=5)).mean()), 3)
            e["date_modified_range"] = [str(m["mod"].min()), str(m["mod"].max())]
            e["distinct_modified_timestamps_per_week"] = {str(k): int(v) for k, v in m.groupby("week")["mod"].nunique().head(6).items()}
    except Exception as ex:
        res["datasets"]["injuries"]["pit_analysis_error"] = type(ex).__name__
    return res



SDV = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
SDV_ASSETS = [("cfb_pbp_espn", "espn_cfb_pbp", "play_by_play_{y}.parquet"), ("cfb_pbp_cfbd", "cfbfastR_cfb_pbp", "play_by_play_{y}.parquet"), ("cfb_schedule", "espn_cfb_schedules", "cfb_schedule_{y}.parquet"),
              ("mbb_pbp", "espn_mens_college_basketball_pbp", "play_by_play_{y}.parquet"), ("mbb_player_box", "espn_mens_college_basketball_player_boxscores", "player_box_{y}.parquet"),
              ("mbb_team_box", "espn_mens_college_basketball_team_boxscores", "team_box_{y}.parquet"), ("mbb_schedule", "espn_mens_college_basketball_schedules", "mbb_schedule_{y}.parquet"),
              ("nba_pbp", "espn_nba_pbp", "play_by_play_{y}.parquet"), ("nba_player_box", "espn_nba_player_boxscores", "player_box_{y}.parquet"),
              ("nhl_schedule", "nhl_schedules", "nhl_schedule_{y}.parquet"), ("nhl_rosters", "nhl_rosters", "rosters_{y}.parquet"), ("nhl_shifts", "nhl_shifts", "shifts_{y}.parquet"), ("nhl_officials", "nhl_officials", "officials_{y}.parquet")]


def sportsdataverse(scratch: Path) -> dict:
    sc = scratch / "sportsdataverse"; res = {"group": "sportsdataverse", "source_host": "github.com release assets of sportsdataverse/sportsdataverse-data (already reachable; release PAGES are denied, assets are not)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"),
                                            "terms_note": "licence/terms pages for hoopR-data, cfbfastR-data and wehoop-data were not found; upstream (ESPN, CollegeFootballData, NHL) terms were not verified: ingestion beyond this measurement needs the owner's decision", "datasets": {}}
    years = [2002, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, 2023, 2024, 2025, 2026]
    for name, tag, pat in SDV_ASSETS:
        ent = {"tag": tag, "asset_pattern": pat, "exists_by_year": {}}
        for y in years:
            r = subprocess.run(["curl", "-sS", "-L", "--max-time", "25", "-r", "0-255", "-A", UA, "-o", "/dev/null", "-w", "%{http_code}", f"{SDV}/{tag}/{pat.format(y=y)}"], capture_output=True, text=True)
            ent["exists_by_year"][str(y)] = r.stdout.strip() in ("200", "206")
        have = [int(y) for y, ok in ent["exists_by_year"].items() if ok]
        ent["first_year_probed_present"] = min(have) if have else None; ent["last_year_probed_present"] = max(have) if have else None
        samples = []
        for y in ([max(have)] if have else []) + ([min(y for y in have if y >= 2008)] if any(y >= 2008 for y in have) and min(have) != max(have) else []):
            fn = pat.format(y=y); d = sc / tag / fn; g = get(f"{SDV}/{tag}/{fn}", d); g["season_file"] = y
            if g["http"] == 200 and g["bytes"] > 2000:
                try:
                    df = pd.read_parquet(d); g["profile"] = profile(df, time_cols=[c for c in df.columns if any(k in c.lower() for k in ("date", "time", "wallclock", "clock"))][:6])
                    g["profile"]["rows_per_game"] = (round(float(len(df) / df[[c for c in df.columns if c in ("game_id", "gameId", "game_pk", "id")][0]].nunique()), 1) if any(c in df.columns for c in ("game_id", "gameId", "game_pk", "id")) else None)
                except Exception as e:
                    g["error"] = type(e).__name__ + ": " + str(e)[:80]
            samples.append(g)
        ent["samples"] = samples; res["datasets"][name] = ent
    return res


def nflverse_coverage(scratch: Path) -> dict:
    """Season-by-season rows and key-column non-null shares for the nflverse weekly datasets (event-time and missingness evidence)."""
    sc = scratch / "nflverse_cov"; res = {"group": "nflverse_coverage", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "datasets": {}}
    plan = {"injuries": ("injuries", range(2009, 2026), ["date_modified", "report_status", "practice_status", "report_primary_injury", "gsis_id"]),
            "depth_charts": ("depth_charts", range(2001, 2026), ["dt", "depth_team", "gsis_id", "depth_position"]),
            "snap_counts": ("snap_counts", range(2012, 2026), ["offense_snaps", "defense_snaps", "offense_pct", "pfr_player_id"]),
            "pbp_participation": ("pbp_participation", range(2016, 2026), ["offense_personnel", "defense_personnel", "defense_coverage_type", "defense_man_zone_type", "was_pressure", "time_to_throw", "offense_formation", "route"]),
            "ftn_charting": ("ftn_charting", range(2022, 2026), ["is_play_action", "is_rpo", "n_blitzers", "is_screen_pass", "is_no_huddle"]),
            "rosters": ("rosters", range(1999, 2026), ["status", "gsis_id", "position", "birth_date"]),
            "player_stats": ("player_stats", range(1999, 2026), ["passing_epa", "carries", "targets"])}
    for name, (tag, yrs, keys) in plan.items():
        per = {}
        for y in yrs:
            fn = f"{name}_{y}.parquet" if name not in ("rosters",) else f"roster_{y}.parquet"
            if name == "player_stats":
                fn = f"player_stats_{y}.parquet"
            d = sc / tag / fn; g = get(f"{REL}/{tag}/{fn}", d)
            if g["http"] != 200 or g["bytes"] < 1500:
                per[str(y)] = {"http": g["http"]}; continue
            try:
                df = pd.read_parquet(d); per[str(y)] = {"rows": int(len(df)), **{k: round(float(df[k].notna().mean()), 3) for k in keys if k in df.columns}}
            except Exception as e:
                per[str(y)] = {"error": type(e).__name__}
        res["datasets"][name] = per
    for fn, tag in (("officials.parquet", "officials"), ("draft_picks.parquet", "draft_picks"), ("combine.parquet", "combine"), ("historical_contracts.parquet", "contracts")):
        d = sc / tag / fn; g = get(f"{REL}/{tag}/{fn}", d)
        if g["http"] == 200 and g["bytes"] > 1500:
            df = pd.read_parquet(d); res["datasets"][tag] = {"rows": int(len(df)), "columns": {c: round(float(df[c].notna().mean()), 3) for c in df.columns}, **({"seasons": [int(df.season.min()), int(df.season.max())]} if "season" in df else {})}
        else:
            res["datasets"][tag] = {"http": g["http"]}
    return res


def _keys(d, depth=0, maxd=2):
    if not isinstance(d, dict) or depth >= maxd:
        return None
    return {k: _keys(v, depth + 1, maxd) for k, v in d.items()}


def espn(scratch: Path) -> dict:
    res = {"group": "espn", "source_host": "site.api.espn.com (already reachable; unofficial public JSON; terms not verified)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "sports": {}}
    sports = {"NFL": "football/nfl", "CFB": "football/college-football", "CBB": "basketball/mens-college-basketball", "NBA": "basketball/nba", "NHL": "hockey/nhl", "MLB": "baseball/mlb"}
    dates = {"NFL": ["20051113", "20101114", "20151108", "20201108", "20241110"], "CFB": ["20051015", "20101016", "20151017", "20201107", "20241109"], "CBB": ["20060114", "20110115", "20160116", "20210116", "20250118"],
             "NBA": ["20040114", "20100113", "20150114", "20200115", "20250114"], "NHL": ["20050301", "20100114", "20150114", "20200115", "20250114"], "MLB": ["20050715", "20100715", "20150715", "20200815", "20250715"]}
    for sp, path in sports.items():
        out = []
        for d in dates[sp]:
            st, sb = jget(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}" + ("&groups=50&limit=50" if sp == "CBB" else "") + ("&groups=80&limit=50" if sp == "CFB" else ""))
            rec = {"date": d, "scoreboard_http": st}
            ev = [e for e in (sb or {}).get("events", []) if (e.get("status", {}).get("type", {}) or {}).get("completed")]
            rec["completed_events_on_date"] = len(ev)
            if ev:
                eid = ev[0]["id"]; st2, sm = jget(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={eid}", timeout=60)
                rec["summary_http"] = st2
                if sm:
                    bx = sm.get("boxscore") or {}
                    rec.update({"top_keys": sorted(sm.keys()), "boxscore_team_stats": len((bx.get("teams") or [{}])[0].get("statistics", [])) if bx.get("teams") else 0, "boxscore_players_groups": len(bx.get("players") or []),
                                "plays": len(sm.get("plays") or []), "drives": len((sm.get("drives") or {}).get("previous", [])) if isinstance(sm.get("drives"), dict) else 0, "officials": len((sm.get("gameInfo") or {}).get("officials") or []),
                                "injuries_block": bool(sm.get("injuries")), "winprobability": len(sm.get("winprobability") or []), "has_attendance_venue": bool((sm.get("gameInfo") or {}).get("venue")), "weather_in_gameInfo": bool((sm.get("gameInfo") or {}).get("weather"))})
            out.append(rec)
        res["sports"][sp] = out
    return res


def mlb(scratch: Path) -> dict:
    res = {"group": "mlb_statsapi", "source_host": "statsapi.mlb.com (already reachable; unofficial public API; terms not verified)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "games": [], "other": {}}
    for y in (2008, 2010, 2012, 2015, 2017, 2019, 2021, 2023, 2025):
        st, sc = jget(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={y}-07-15&hydrate=probablePitcher,lineups,weather,officials")
        games = [g for d in (sc or {}).get("dates", []) for g in d["games"] if g.get("status", {}).get("abstractGameState") == "Final"]
        rec = {"year": y, "schedule_http": st, "final_games_that_day": len(games)}
        if games:
            g = games[0]; rec["schedule_has"] = {"lineups": bool(g.get("lineups")), "officials": bool(g.get("officials")), "weather": bool(g.get("weather")), "probable_home": bool(g["teams"]["home"].get("probablePitcher"))}
            st2, fd = jget(f"https://statsapi.mlb.com/api/v1.1/game/{g['gamePk']}/feed/live", timeout=90)
            rec["feed_http"] = st2
            if fd:
                plays = fd["liveData"]["plays"]["allPlays"]; ev = [e for p in plays for e in p.get("playEvents", []) if e.get("isPitch")]
                pdat = [e.get("pitchData") or {} for e in ev]
                n = max(len(ev), 1)
                rec.update({"pitches": len(ev), "share_startSpeed": round(sum("startSpeed" in x for x in pdat) / n, 3), "share_spinRate": round(sum("spinRate" in (e.get("pitchData", {}).get("breaks") or {}) for e in ev) / n, 3),
                            "share_plate_coordinates": round(sum("coordinates" in x and "pX" in x["coordinates"] for x in pdat) / n, 3), "share_strike_zone": round(sum("strikeZoneTop" in x for x in pdat) / n, 3),
                            "share_hitData_on_balls_in_play": round(sum(1 for p in plays for e in p.get("playEvents", []) if e.get("hitData")) / max(sum(1 for p in plays if p["result"].get("eventType") not in ("strikeout", "walk")), 1), 3),
                            "has_officials": bool(fd["liveData"]["boxscore"].get("officials")), "has_weather": bool(fd["gameData"].get("weather")), "has_batting_orders": bool(fd["liveData"]["boxscore"]["teams"]["home"].get("battingOrder")), "gameData_keys": sorted(fd["gameData"].keys())[:12]})
        res["games"].append(rec)
    st, tr = jget("https://statsapi.mlb.com/api/v1/transactions?startDate=2015-04-06&endDate=2015-04-12"); res["other"]["transactions_2015"] = {"http": st, "n": len((tr or {}).get("transactions", [])), "fields": sorted(((tr or {}).get("transactions") or [{}])[0].keys())}
    for y in (2012, 2018, 2024):
        st, r = jget(f"https://statsapi.mlb.com/api/v1/teams/119/roster?rosterType=injuredList&season={y}"); res["other"][f"il_roster_{y}"] = {"http": st, "n": len((r or {}).get("roster", []))}
    return res


def nhl(scratch: Path) -> dict:
    res = {"group": "nhl_api_web", "source_host": "api-web.nhle.com (already reachable; unofficial public API; terms not verified)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "games": []}
    for y in (2009, 2010, 2011, 2013, 2015, 2017, 2019, 2021, 2023, 2024, 2025):
        gid = f"{y}020500"; st, pb = jget(f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play", timeout=60)
        rec = {"season_start": y, "game_id": gid, "pbp_http": st}
        if pb:
            pl = pb.get("plays") or []; det = [p.get("details") or {} for p in pl]
            rec.update({"plays": len(pl), "share_xy": round(sum("xCoord" in d for d in det) / max(len(det), 1), 3), "has_situationCode": bool(pl and "situationCode" in pl[0]), "roster_spots": len(pb.get("rosterSpots") or []), "top_keys": sorted(pb.keys())[:20],
                        "has_period_clock": bool(pl and "timeInPeriod" in pl[0]), "home_defending_side": bool(pl and "homeTeamDefendingSide" in pl[0])})
        st2, lc = jget(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", timeout=60); rec["landing_http"] = st2
        if lc:
            rec["landing_keys"] = sorted(lc.keys())[:25]; gi = (lc.get("summary") or {}).get("gameInfo") or {}; rec["landing_gameInfo_keys"] = sorted(gi.keys()); rec["scratches_present"] = "scratches" in (lc.get("summary") or {}) or "scratches" in gi; rec["referees_present"] = bool(gi.get("referees"))
        st3, bx = jget(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore", timeout=60); rec["boxscore_http"] = st3
        if bx:
            rec["boxscore_keys"] = sorted(bx.keys())[:20]; rec["player_by_game_stats"] = "playerByGameStats" in bx
        res["games"].append(rec)
    return res


def statsbomb(scratch: Path) -> dict:
    base = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
    st, comps = jget(f"{base}/competitions.json", timeout=60)
    res = {"group": "statsbomb_open", "source_host": "raw.githubusercontent.com (already reachable)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "terms_note": "README: attribute StatsBomb and use their logo; free 'for research projects and genuine interest in football analytics'; LICENSE.pdf text was not readable; commercial use not addressed",
           "competitions_http": st, "n_competition_seasons": len(comps or [])}
    if comps:
        res["competitions"] = [{"competition": c["competition_name"], "season": c["season_name"], "gender": c.get("competition_gender"), "has_360": bool(c.get("match_available_360")), "last_updated": str(c.get("match_updated"))[:10]} for c in comps]
        c0 = [c for c in comps if c["competition_name"] == "Premier League"][:1] or comps[:1]
        sst, ms = jget(f"{base}/matches/{c0[0]['competition_id']}/{c0[0]['season_id']}.json", timeout=60); res["sample_matches_http"] = sst; res["sample_competition"] = c0[0]["competition_name"] + " " + c0[0]["season_name"]; res["sample_matches"] = len(ms or [])
        if ms:
            mid = ms[0]["match_id"]; est, evs = jget(f"{base}/events/{mid}.json", timeout=90); lst, lu = jget(f"{base}/lineups/{mid}.json", timeout=60)
            res["sample_events_http"] = est; res["sample_lineups_http"] = lst
            if evs:
                import collections as _c
                res["sample_event_types"] = dict(_c.Counter(e["type"]["name"] for e in evs).most_common(12)); res["sample_event_keys"] = sorted(evs[5].keys()); res["sample_shot_has_xg"] = any("statsbomb_xg" in (e.get("shot") or {}) for e in evs)
            if lu:
                res["sample_lineup_fields"] = sorted((lu[0].get("lineup") or [{}])[0].keys())
    return res


def archives(scratch: Path) -> dict:
    """The owner's NBA/NHL archive tables that earlier verdicts could only judge from ledger schemas: measured now from the authorized read-only checkouts."""
    import glob
    R = scratch.parent / "replay"; res = {"group": "owner_archives", "source": "chmoses98/nba-edge-finder and NHL-edge-finder (authorized read-only; files read from scratch checkouts)", "measured_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"), "datasets": {}}
    pats = {"nba_pbp_events": R / "nba_src/data/history/espn_pbp/pbp_events_*.parquet", "nba_pbp_games": R / "nba_src/data/history/espn_pbp/pbp_games_*.parquet", "nba_pbp_box": R / "nba_src/data/history/espn_pbp/pbp_box_*.parquet",
            "nba_stints": R / "nba_src/data/history/espn_pbp/stints_*.parquet", "nhl_shots_2021_2026": R / "nhl_src/data/history/players/shots_*.parquet", "nhl_shots_extension_2008_2020": R / "nhl_src/data/history/shots_extension/shots_*.parquet",
            "nhl_goals": R / "nhl_src/data/history/players/goals_*.parquet", "nhl_coice": R / "nhl_src/data/history/players/coice_*.parquet"}
    for name, pat in pats.items():
        files = sorted(glob.glob(str(pat))); ent = {"files": [Path(f).name for f in files]}
        if files:
            df = pd.concat([pd.read_parquet(f).assign(_f=Path(f).name) for f in files], ignore_index=True)
            tcols = [c for c in df.columns if any(k in c.lower() for k in ("date", "time", "wallclock", "clock", "utc"))][:6]
            ent["profile"] = profile(df.drop(columns=["_f"]), time_cols=tcols); ent["profile"]["rows_by_file"] = {k: int(v) for k, v in df.groupby("_f").size().items()}
        res["datasets"][name] = ent
    return res


GROUPS = {"archives": archives, "espn": espn, "mlb": mlb, "nhl": nhl, "statsbomb": statsbomb, "nflverse_coverage": nflverse_coverage, "nflverse": nflverse, "sportsdataverse": sportsdataverse}


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    g, scratch = a[0], Path(a[1]); OUTD.mkdir(parents=True, exist_ok=True)
    r = GROUPS[g](scratch)
    (OUTD / f"{g}.json").write_text(json.dumps(r, indent=0, sort_keys=True, default=str) + "\n")
    print(g, "written", list(r)[:8])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

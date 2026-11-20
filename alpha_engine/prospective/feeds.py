"""Feed definitions for the highest-value prospective gaps (RESEARCH_ONLY, DISABLED by default; see vintage.activation_check).

Each feed normalizes a payload into entity rows with stable identifiers and keeps the source's own publication time when the payload carries one. The parsers are tested
against SYNTHETIC fixtures shaped like the public payloads (tests/test_prospective_capture.py); no live payload was fetched for this module, so a parser must be re-checked
against one real response, under the owner's activation, before any capture is trusted.

| feed                          | source_id (rights_registry)        | collection_allowed today | P1 inputs it would feed                                     |
|-------------------------------|------------------------------------|--------------------------|-------------------------------------------------------------|
| nfl.injury_report_vintages    | espn_scoreboard_and_archives       | false                    | nfl.qb, nfl.skill_avail (intra-week), with_without targets  |
| cbb.availability_snapshots    | espn_scoreboard_and_archives       | false                    | cbb.injuries (7 P1), cbb.player_minutes, cbb.starters       |
| mlb.probable_pitchers         | mlb_stats_api                      | false                    | mlb.sp_quality, mlb.f5_starter_change_risk, candidate match |
| mlb.lineups                   | mlb_stats_api                      | false                    | mlb.lineup_pit (4 P1), lineup_strength_delta                |
| nhl.starting_goalies          | nhl_api_moneypuck                  | false                    | nhl.goalie_quality, nhl.lineup_impact_delta                 |
| env.weather_forecast_pit      | nws_api_weather_gov (UNREGISTERED) | false (not registered)   | nfl/mlb/cfb.weather_pit, nfl.weather_total_response        |
The MLB feeds duplicate what chmoses98/edge-finder-api already captures (prospective_capture_plan: VERIFY_THEN_EXTEND_EXISTING); they are defined here only so the vintage
schema is shared and must not be activated in parallel with that supplier.
"""
from __future__ import annotations

from .vintage import Feed


def _espn_injuries(p: dict) -> list[dict]:
    rows = []
    for team in p.get("injuries") or p.get("teams") or []:
        tid = (team.get("team") or {}).get("id") or team.get("id")
        for it in team.get("injuries") or []:
            a = it.get("athlete") or {}
            rows.append({"entity_id": a.get("id"), "team_id": tid, "status": it.get("status") or (it.get("type") or {}).get("description"),
                         "reported_utc": it.get("date"), "detail": (it.get("details") or {}).get("type"), "position": (a.get("position") or {}).get("abbreviation")})
    return [r for r in rows if r["entity_id"] is not None]


def _espn_published(p: dict) -> str | None:
    ds = [it.get("date") for t in (p.get("injuries") or p.get("teams") or []) for it in (t.get("injuries") or []) if it.get("date")]
    return max(ds) if ds else None


def _mlb_probables(p: dict) -> list[dict]:
    rows = []
    for d in p.get("dates") or []:
        for g in d.get("games") or []:
            for side in ("home", "away"):
                t = (g.get("teams") or {}).get(side) or {}
                pp = t.get("probablePitcher") or {}
                rows.append({"entity_id": f"{g.get('gamePk')}:{side}", "game_pk": g.get("gamePk"), "team_id": (t.get("team") or {}).get("id"), "pitcher_id": pp.get("id"),
                             "game_date_utc": g.get("gameDate"), "status": (g.get("status") or {}).get("detailedState")})
    return rows


def _mlb_lineups(p: dict) -> list[dict]:
    rows = []
    for side in ("home", "away"):
        t = ((p.get("teams") or {}).get(side)) or {}
        for i, pid in enumerate(t.get("battingOrder") or []):
            rows.append({"entity_id": f"{p.get('gamePk')}:{side}:{i + 1}", "game_pk": p.get("gamePk"), "side": side, "slot": i + 1, "batter_id": pid})
    return rows


def _nhl_goalies(p: dict) -> list[dict]:
    rows = []
    for g in p.get("games") or []:
        for side in ("homeTeam", "awayTeam"):
            t = g.get(side) or {}
            rows.append({"entity_id": f"{g.get('id')}:{side}", "game_id": g.get("id"), "team": t.get("abbrev"), "goalie_id": (t.get("startingGoalie") or {}).get("playerId"),
                         "confirmed": (t.get("startingGoalie") or {}).get("confirmed")})
    return rows


def _nws_hourly(p: dict) -> list[dict]:
    props = p.get("properties") or {}
    return [{"entity_id": per.get("startTime"), "start_utc": per.get("startTime"), "temp_f": per.get("temperature"), "wind_speed": per.get("windSpeed"), "wind_dir": per.get("windDirection"),
             "precip_prob": (per.get("probabilityOfPrecipitation") or {}).get("value")} for per in props.get("periods") or []]


FEEDS = {
    "nfl.injury_report_vintages": Feed("nfl.injury_report_vintages", "espn_scoreboard_and_archives",
                                       "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", _espn_injuries, _espn_published,
                                       ["team_id", "status", "reported_utc", "position"], notes="every 3 h Wed-Sun in season; the inactive list ~90 min before kickoff"),
    "cbb.availability_snapshots": Feed("cbb.availability_snapshots", "espn_scoreboard_and_archives",
                                       "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/injuries", _espn_injuries, _espn_published,
                                       ["team_id", "status", "reported_utc", "position"], notes="hourly on game days; coverage of college injury listings is sparse and must be measured first"),
    "mlb.probable_pitchers": Feed("mlb.probable_pitchers", "mlb_stats_api", "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}&hydrate=probablePitcher",
                                  _mlb_probables, lambda p: None, ["pitcher_id", "game_date_utc", "status"], notes="do NOT activate in parallel with edge-finder-api slate captures"),
    "mlb.lineups": Feed("mlb.lineups", "mlb_stats_api", "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live?fields=gamePk,liveData,boxscore,teams,home,away,battingOrder",
                        lambda p: _mlb_lineups({"gamePk": p.get("gamePk"), "teams": ((p.get("liveData") or {}).get("boxscore") or {}).get("teams")}), lambda p: None, ["batter_id"]),
    "nhl.starting_goalies": Feed("nhl.starting_goalies", "nhl_api_moneypuck", "https://api-web.nhle.com/v1/schedule/{date}", _nhl_goalies, lambda p: None, ["goalie_id", "confirmed"],
                                 notes="api-web.nhle.com carries an ai-train=no reservation (Phase 13): research only"),
    "env.weather_forecast_pit": Feed("env.weather_forecast_pit", "nws_api_weather_gov", "https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly", _nws_hourly,
                                     lambda p: (p.get("properties") or {}).get("updateTime") or (p.get("properties") or {}).get("generatedAt"),
                                     ["temp_f", "wind_speed", "wind_dir", "precip_prob"], notes="source not in the rights registry: needs an owner rights entry before any activation; venue coordinates (env.venue_geo) are also not built"),
}

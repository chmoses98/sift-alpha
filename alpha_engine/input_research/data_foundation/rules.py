"""Draft mapping of catalog inputs to raw-data NEEDS and then to registry datasets (RESEARCH_ONLY).

This is the deterministic first pass: auditable (the matched triggers are stored per input) and deliberately conservative. It is NOT the final word: per-sport reviewers read every draft
row and record corrections in `review/<SPORT>.json`, which `audit.py` merges and validates. A NEED is an abstract kind of raw data ("pregame availability", "play-level events");
each sport maps a need to an ordered list of ALTERNATIVE datasets (the best-available one satisfies it). An input needs ALL of its needs.
"""
from __future__ import annotations

import re

SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"]
# (need, regex). Applied to raw_data + label when the input has a raw-data definition, else label + measurement[:500].
NEED_RX = [
    ("TRACKING", r"tracking|separation|defender distance|sprint speed|bat speed|swing (speed|length|path)|time to throw|cushion|next gen|\bngs\b|rim protection|second spectrum|hawk-?eye|serve speed|exit velocity|launch angle|spin rate|release extension|hit ?data|plate ?time|catch probability|bat tracking|biomechan|player (speed|movement)"),
    ("SCHEME", r"coverage|formation|personnel|man/zone|\bshell\b|\broutes?\b|play.?action|blitz|pitch (mix|type|sequenc)|whiff|chase rate|zone rate|scheme|pressing|shot (quality|location|profile|zone|type)|play type|set.?piece|tactic|\brpo\b|charting|point.?by.?point|shot.?by.?shot|rally|serve (direction|placement)|strike.?zone|defensive (alignment|rotation)|pick.and.roll|synergy|hustle"),
    ("LINEUP", r"lineup|on/off|five.?man|stint|linemate|line combination|pairing|minutes distribution|with/without|batting order|platoon|rotation pattern|depth chart"),
    ("AVAIL", r"injur|availab|inactive|questionable|scratch|starter status|starting (lineup|goalie|pitcher|qb|eleven|xi|five)|confirmed (lineup|starter)|load management|return from|suspension|withdraw|retire(d|ment)? (rate|risk)|participation status|resting|probable pitcher|lineup news|game.?day status|\bstatus\b|\bdnp\b|\bout\b designation"),
    ("OFFICIALS", r"referee|umpire|officiat|\bcrew\b|chair umpire|linesm"),
    ("WEATHER_FCST", r"forecast"),
    ("WEATHER_OBS", r"weather|wind\b|temperature|humidity|precip|\brain\b|heat index|lightning"),
    ("VENUE", r"\bdome\b|\broof\b|surface|court speed|conditions|altitude|elevation|venue|ballpark|\bpark\b|stadium|arena|neutral|home.?(court|field|ice) advantage|home advantage|time zone|travel|dimensions|\bwall\b|\bcapacity\b|crowd|attendance"),
    ("EVENT", r"play.?by.?play|possession|\bepa\b|win probability|\bdrives?\b|first (basket|goal|score|td|bucket|to score)|hazard|score state|game state|garbage|late.?game|\bfouls?\b|free.?throw|empty.?net|tempo|\bpace\b|\bshots?\b|\bpitch(es)?\b|plate appearance|\binning|power.?play|penalt|timeout|\brally|break point|overtime|extra time|quarter|period|\bhalf\b|play.?level|event.?level|per.?play|run expectancy|leverage"),
    ("PLAYER_BOX", r"usage|minutes|touches|rebound|assist|steal|\bblocks?\b|three|points per|per 90|share|target|carr(y|ies)|snap|\btoi\b|time on ice|strikeout|\bwalks?\b|\bhits?\b|home run|\brbi\b|\baces?\b|double fault|player|goalie|pitcher|hitter|batter|quarterback|\bqb\b|receiver|\bstats?\b|prop|scorer"),
    ("TEAM_BOX", r"team|rating|efficiency|offen[sc]e|defen[sc]e|scoring|goals|total|margin|\belo\b|\bform\b|strength|record|standings|expected goals|\bxg\b"),
    ("RATINGS_EXT", r"\belo\b|\bepm\b|darko|rapm|kenpom|t-?rank|torvik|\bnet (rank|rating)|sp\+|power rating|massey|\bbpi\b|composite rating|external rating|public rating"),
    ("POLLS", r"\bpoll\b|polls\b|\bap top|coaches poll|cfp (committee|rank)|committee rank|quadrant|bracketolog|selection (show|committee)|seed(ing)? (line|projection)"),
    ("RULES", r"\brules?\b|regulation|\bformat\b|tiebreak|bylaw|eligib|selection principle|qualification|rulebook|slot|coefficient|criteria|\bcba\b|\bcut line"),
    ("AWARDS", r"award|voting|voter|ballot|\bmvp\b|rookie of|heisman|naismith|ballon|all-star|all-nba|all-pro|pro bowl|hall of fame|cy young|\bhart\b|norris|vezina|\bderby\b|contest|honou?rs?"),
    ("DRAFT", r"\bdraft|prospect|mock|big board|lottery|combine|pick (ownership|trade)|early.?entry|draft order"),
    ("CONTRACTS", r"contract|salary|\bcap\b|payroll|luxury tax|valuation|finance|buyout|extension"),
    ("NEWS", r"\bnews|rumou?r|transaction|\btrades?\b|\bhire|\bfire[sd]?\b|coach(ing)? (change|hot|candidate|search|carousel)|manager (change|sack)|announce|insider|\breports?\b|narrative|social|\bbeat\b|broadcast|labou?r|lockout|work stoppage|relocation|franchise|expansion|\bsale\b|media"),
    ("RECRUITING", r"recruit|transfer portal|portal|returning production|roster continuity|roster churn"),
    ("MARKET_RULES", r"kalshi|contract (wording|rules|text)|settlement|rules text|resolution|void|rounding|strike construction|\bsettle"),
    ("PROJECTIONS", r"projection|steamer|zips|pecota|\bros\b|preseason (rating|projection)|win total (projection|prior)"),
]
PIT_SENSITIVE = {"AVAIL", "LINEUP", "WEATHER_FCST", "RATINGS_EXT", "POLLS", "DRAFT", "NEWS", "CONTRACTS", "RECRUITING", "PROJECTIONS"}
# cross-sport datasets
X = {"WEATHER_OBS": ["env.weather_observed"], "WEATHER_FCST": ["env.weather_forecast_pit"], "VENUE": ["env.venue_geo"], "MARKET_RULES": ["mkt.kalshi_rules"], "RULES": ["xx.rules_reference"], "NEWS": ["xx.news_timestamped"],
     "AWARDS": ["xx.awards_results"], "DRAFT": ["xx.draft_boards_vintaged"], "CONTRACTS": ["xx.contracts_finance"], "PROJECTIONS": ["xx.projection_vintages"], "RECRUITING": ["xx.news_timestamped"], "POLLS": ["xx.news_timestamped"],
     "RATINGS_EXT": [], "OFFICIALS": [], "LINEUP": [], "TRACKING": [], "SCHEME": [], "AVAIL": [], "EVENT": [], "PLAYER_BOX": [], "TEAM_BOX": [], "RESULTS": []}
M = {
 "NFL": {"RESULTS": ["nfl.schedule_results"], "TEAM_BOX": ["nfl.pbp", "nfl.schedule_results"], "PLAYER_BOX": ["nfl.player_stats_weekly", "nfl.snap_counts"], "EVENT": ["nfl.pbp"], "LINEUP": ["nfl.participation", "nfl.depth_charts"],
        "TRACKING": ["nfl.nextgen_stats", "nfl.raw_tracking"], "SCHEME": ["nfl.participation", "nfl.ftn_charting"], "AVAIL": ["nfl.injuries_weekly", "nfl.depth_charts", "nfl.inactives_game_day", "nfl.injury_report_vintages"], "OFFICIALS": ["nfl.officials"],
        "WEATHER_OBS": ["nfl.schedule_results", "env.weather_observed"], "RATINGS_EXT": ["nfl.pbp"], "AWARDS": ["nfl.awards_results"], "DRAFT": ["nfl.draft_combine"], "CONTRACTS": ["nfl.contracts_cap"], "NEWS": ["nfl.transactions_news"]},
 "CFB": {"RESULTS": ["cfb.games_espn"], "TEAM_BOX": ["cfb.games_espn", "cfb.pbp_cfbd"], "PLAYER_BOX": ["cfb.box_player", "cfb.pbp_cfbd"], "EVENT": ["cfb.pbp_cfbd"], "LINEUP": ["cfb.availability_snapshots"], "TRACKING": ["cfb.raw_tracking_scheme"], "SCHEME": ["cfb.raw_tracking_scheme", "cfb.pff_charting"],
         "AVAIL": ["cfb.availability_snapshots"], "OFFICIALS": ["cfb.raw_tracking_scheme"], "RATINGS_EXT": ["cfb.pbp_cfbd", "cfb.rankings_polls"], "POLLS": ["cfb.rankings_polls"], "RULES": ["cfb.rules_formats"], "RECRUITING": ["cfb.recruiting_portal"], "CONTRACTS": ["cfb.coaching_finance"]},
 "NBA": {"RESULTS": ["nba.team_games", "nba.schedule_arena"], "TEAM_BOX": ["nba.team_games"], "PLAYER_BOX": ["nba.player_games"], "EVENT": ["nba.pbp", "nba.shots_xy"], "LINEUP": ["nba.lineup_stints"], "TRACKING": ["nba.tracking"], "SCHEME": ["nba.playtype_scheme"],
         "AVAIL": ["nba.injury_report_vintages"], "OFFICIALS": ["nba.referees"], "RATINGS_EXT": ["nba.advanced_ratings"], "AWARDS": ["nba.awards_allstar"], "DRAFT": ["nba.transactions_draft"], "NEWS": ["nba.transactions_draft"], "CONTRACTS": ["nba.transactions_draft"], "RULES": ["nba.awards_allstar", "xx.rules_reference"]},
 "CBB": {"RESULTS": ["cbb.games_espn"], "TEAM_BOX": ["cbb.games_espn", "cbb.ratings_barttorvik"], "PLAYER_BOX": ["cbb.box_player"], "EVENT": ["cbb.box_player"], "LINEUP": ["cbb.shot_tracking_scheme"], "TRACKING": ["cbb.shot_tracking_scheme"], "SCHEME": ["cbb.shot_tracking_scheme"],
         "AVAIL": ["cbb.availability_snapshots"], "OFFICIALS": ["cbb.shot_tracking_scheme"], "RATINGS_EXT": ["cbb.ratings_barttorvik", "cbb.ratings_kenpom"], "POLLS": ["cbb.polls", "cbb.net_bracket"], "RULES": ["cbb.rules_formats"], "RECRUITING": ["cbb.recruiting_portal"], "CONTRACTS": ["cbb.coaching_finance"]},
 "NHL": {"RESULTS": ["nhl.games"], "TEAM_BOX": ["nhl.team_states", "nhl.games"], "PLAYER_BOX": ["nhl.player_games", "nhl.goalie_games"], "EVENT": ["nhl.shots_xy"], "LINEUP": ["nhl.shifts_lines"], "TRACKING": ["nhl.shifts_lines"], "SCHEME": ["nhl.shots_xy"],
         "AVAIL": ["nhl.lineup_goalie_pregame", "nhl.goalie_games", "nhl.injuries"], "OFFICIALS": ["nhl.officials"], "RATINGS_EXT": ["nhl.ratings_external", "nhl.shots_xy"], "AWARDS": ["nhl.awards"], "DRAFT": ["nhl.transactions_draft"], "CONTRACTS": ["nhl.transactions_draft"], "NEWS": ["nhl.transactions_draft"]},
 "MLB": {"RESULTS": ["mlb.schedule_games"], "TEAM_BOX": ["mlb.schedule_games"], "PLAYER_BOX": ["mlb.boxscore_player", "mlb.pitch_pa_events"], "EVENT": ["mlb.pitch_pa_events", "mlb.retrosheet"], "LINEUP": ["mlb.lineup_il_vintages", "mlb.schedule_games"], "TRACKING": ["mlb.pitch_pa_events", "mlb.statcast_bulk"],
         "SCHEME": ["mlb.pitch_pa_events"], "AVAIL": ["mlb.lineup_il_vintages", "mlb.transactions"], "OFFICIALS": ["mlb.umpire_stats", "mlb.schedule_games"], "RATINGS_EXT": ["mlb.leaderboards_external", "mlb.pitch_pa_events"], "AWARDS": ["mlb.awards_allstar_derby"], "DRAFT": ["mlb.draft_prospects"],
         "CONTRACTS": ["mlb.contracts_labor"], "NEWS": ["mlb.transactions", "mlb.contracts_labor"], "PROJECTIONS": ["mlb.projections_vintages"]},
 "SOCCER": {"RESULTS": ["soc.results_shots_cards", "soc.fixtures_intl"], "TEAM_BOX": ["soc.results_shots_cards"], "PLAYER_BOX": ["soc.player_stats_lineups"], "EVENT": ["soc.xg_events"], "LINEUP": ["soc.lineups_pregame"], "TRACKING": ["soc.opta_commercial"], "SCHEME": ["soc.xg_events"],
            "AVAIL": ["soc.lineups_pregame", "soc.injuries_suspensions"], "OFFICIALS": ["soc.referee_stats"], "RATINGS_EXT": ["soc.ratings_elo"], "RULES": ["soc.competition_rules"], "AWARDS": ["soc.awards_history"], "CONTRACTS": ["soc.transfers_values"], "NEWS": ["soc.transfers_values"], "DRAFT": ["soc.transfers_values"]},
 "TENNIS": {"RESULTS": ["ten.matches"], "TEAM_BOX": ["ten.matches"], "PLAYER_BOX": ["ten.matches"], "EVENT": ["ten.point_charting", "ten.tracking_commercial"], "LINEUP": ["ten.matches"], "TRACKING": ["ten.tracking_commercial"], "SCHEME": ["ten.point_charting"],
            "AVAIL": ["ten.withdrawals_injuries"], "OFFICIALS": ["ten.matches"], "RATINGS_EXT": ["ten.elo_external", "ten.matches", "ten.rankings_history"], "POLLS": ["ten.rankings_history"], "RULES": ["ten.rules_formats_awards"], "AWARDS": ["ten.rules_formats_awards"],
            "VENUE": ["ten.court_speed_env", "env.venue_geo"], "WEATHER_OBS": ["ten.court_speed_env", "env.weather_observed"], "NEWS": ["ten.withdrawals_injuries"]},
}
SPORT_CORE_RESULTS = {s: M[s]["RESULTS"] for s in SPORTS}


def need_map(sport: str, need: str) -> list[str]:
    return list(M[sport].get(need) or X.get(need) or SPORT_CORE_RESULTS[sport])


def needs_for(sport: str, label: str, raw_data: list[str] | None, measurement: str, mechanism: str) -> tuple[list[tuple[str, str]], str]:
    """-> ([(need, matched trigger)], basis) where basis says which text the needs came from."""
    if raw_data:
        text, basis = " ; ".join(raw_data) + " ; " + label, "raw_data+label"
    else:
        text, basis = label + " ; " + (measurement or "")[:500], "label+measurement"
    t = text.lower(); hits = []
    for need, rx in NEED_RX:
        m = re.search(rx, t)
        if m:
            hits.append((need, m.group(0)))
    return hits, basis

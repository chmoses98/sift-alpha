"""Shared cross-sport market taxonomy: every native Kalshi family maps to (kind, scope, period, stat).

Rules are transparent keyword rules. Anything they cannot place becomes kind="unclassified" and is listed in the
inventory's `unclassified` section - it is never dropped and never guessed.
"""
from __future__ import annotations

import re

SCOPES = ("game", "player", "team_season", "season", "other")
KINDS = {
    "winner": "Who wins (moneyline / match winner / 3-way result)",
    "spread": "Margin / handicap ladder",
    "total": "Combined score ladder (goals, points, runs, games, sets)",
    "team_total": "One team's score ladder",
    "margin_bucket": "Winning-margin bucket / exact margin",
    "exact_score": "Exact final or set score",
    "btts": "Both teams to score / score in every period",
    "first_event": "First/next scorer, first basket, first TD, early goal, race-to-N",
    "overtime": "Overtime / shootout / extra-time occurrence",
    "period_result": "Winner/spread/total of a half, quarter, period or inning block",
    "player_stat": "Player statistic threshold ladder (yards, assists, shots, hits, aces...)",
    "player_scorer": "Player to score / anytime scorer / double-double style events",
    "player_h2h": "Head-to-head player comparison",
    "team_stat": "Team non-score statistic (sacks, FGs, first downs, etc.)",
    "game_stat": "Game-level event/count (touchdowns in game, turnovers, specials)",
    "lineup_role": "Starter / availability / depth-chart / participation",
    "combo": "Parlay / multivariate combination",
    "season_outcome": "Championship, division, playoff, seed, win totals, relegation",
    "season_award": "Awards, selections, draft position",
    "season_stat": "Season statistical leaders / records / fantasy",
    "off_field": "Transactions, coaching, business, schedule, media",
    "unclassified": "Rules could not place this family",
}
_RULES = [  # (kind, scope, regex over native-family+series text) - first match wins
    ("combo", "other", r"parlay|combo|multigame|multi_game|prepack|mve|multivariate"),
    ("season_award", "season", r"award|mvp|rookie|roy\b|dpoy|all_nba|all_pro|selection|trophy|hart|calder|norris|vezina|conn_smythe|ballon|cy_young|heisman|draft"),
    ("off_field", "other", r"transaction|coach|business|franchise|retire|schedule_ann|stadium|expansion|contract|manager|joinclub|non_basketball|non_hockey|non_soccer|office|exhibition|all_star|media|halftime|super_bowl_event|primetime|special_event|novelty|career|nationality|participation"),
    ("lineup_role", "player", r"starting|lineup|depth|compete|availability|role_event|starter"),
    ("player_h2h", "player", r"h2h|head_to_head|matchup_player"),
    ("season_stat", "season", r"leader|season_stat|season_player|fantasy|streak|record|stat_leader|week_leader|high_score|season_special|season_matchup|team_points|points_margin|season_team"),
    ("season_outcome", "season", r"champion|champ\b|super_bowl|stanley|cup\b|world_series|conference|division|seed|playoff|wins|qualif|relegat|promotion|top_n|last_place|futures|round|advance|series_winner|series_|tournament|winner_outright|competition_|host|nba_cup|summer_league_season|march|final_four|bracket|future"),
    ("player_scorer", "player", r"scorer|anytime|double_double|triple_double|brace"),
    ("player_stat", "player", r"^(player_|hitter_|pitcher_|goalie_|batter_)"),
    ("margin_bucket", "game", r"win_margin|winning_margin|margin_bucket|margin_of_victory"),
    ("exact_score", "game", r"exact_score|correct_score|exact_set|set_score|exact_match"),
    ("btts", "game", r"btts|both_teams|score_in_every"),
    ("overtime", "game", r"overtime|shootout|extra_time|\bot\b"),
    ("first_event", "game", r"first_|next_|race|early_goal|last_to|anytime_first|ftts|points_leader"),
    ("team_total", "game", r"team_total|teamtotal"),
    ("spread", "game", r"spread|handicap|set_spread|game_spread"),
    ("total", "game", r"total|over_under|total_goals|total_games|total_sets|total_td|total_runs"),
    ("player_scorer", "player", r"scorer|anytime|double_double|triple_double|td_scorer|touchdown_scorer|brace|player_goals_any"),
    ("player_stat", "player", r"player|hitter|pitcher|goalie|batter|props?\b|aces|hit\b|strikeout|rbi|hrr|total_bases|stolen|ks\b"),
    ("team_stat", "game", r"team_stat|team_prop|team_.*(sack|fg|down)|bench_points"),
    ("game_stat", "game", r"game_stat|game_event|stat_prop|game_special|dst|turnover"),
    ("winner", "game", r"winner|moneyline|game_winner|match_result|3way|match_winner|result|\bgame\b|1x2|tie"),
]
_PERIOD = [("1H", r"first_half|1h\b|(?<![a-z])1h(?![a-z])"), ("2H", r"second_half|2h"),
           ("Q1", r"1q"), ("Q2", r"2q"), ("Q3", r"3q"), ("Q4", r"4q"),
           ("F3", r"f3\b|first_3"), ("F5", r"f5\b|first_5"), ("F7", r"f7\b|first_7"),
           ("INNING", r"inning|rfi|yrfi|nrfi"), ("SET", r"set_|setwinner|set\b"), ("PERIOD_PATTERN", r"period_|quarter_|half_")]


def detect_period(sport: str, native: str, ticker: str = "") -> str:
    n = f"{native} {ticker}".lower()
    t = ticker.upper()
    toks = "1H|2H|1Q|2Q|3Q|4Q" + ("|F3|F5|F7" if sport == "MLB" else "")
    m = re.match(rf"KX[A-Z]*?({toks})(?![A-Z0-9]*[0-9])", t) if ticker else None
    if m and not t.startswith(("KXNFL2PT",)):
        return {"1H": "1H", "2H": "2H", "1Q": "Q1", "2Q": "Q2", "3Q": "Q3", "4Q": "Q4"}.get(m.group(1), m.group(1))
    if sport == "NHL" and re.match(r"KXNHL[1-3]P", t):
        return "P" + t[5]
    for p, rx in _PERIOD:
        if re.search(rx, native.lower()):
            return p
    return "FULL"


OVERRIDES = {  # explicit (sport, native_family) -> (kind, scope) where keyword rules mislead
    ("NFL", "DRAFT"): ("off_field", "other"), ("NFL", "SEASON_TEAM_H2H"): ("season_outcome", "season"), ("NFL", "TOTAL_TD"): ("game_stat", "game"),
    ("NFL", "PERIOD_TD"): ("game_stat", "game"), ("NFL", "FIRST_TD_SCORER"): ("player_scorer", "player"), ("NFL", "NEXT_TD_SCORER"): ("player_scorer", "player"),
    ("CFB", "game_stat_prop"): ("game_stat", "game"), ("CFB", "team_stat_prop"): ("team_stat", "game"), ("CFB", "season_level_events"): ("season_outcome", "season"),
    ("CBB", "PLAYER_PROP"): ("player_stat", "player"), ("CBB", "HALF"): ("period_result", "game"), ("NBA", "game_points_leader"): ("first_event", "game"),
    ("NBA", "h2h_team_stat"): ("game_stat", "game"), ("NBA", "summer_league_game"): ("winner", "game"), ("NBA", "series_player_stat"): ("player_stat", "player"),
    ("MLB", "SERIES_LISTED_NOT_QUERIED"): ("unclassified", "other"), ("TENNIS", "TIEBREAK_OCCURS"): ("game_stat", "game"), ("TENNIS", "SET_SWEEP"): ("game_stat", "game"),
    ("TENNIS", "SEASON_RANKING"): ("season_stat", "season"), ("TENNIS", "SEASON_MAJORS"): ("season_stat", "season"), ("TENNIS", "NATIONALITY_WINNER"): ("season_outcome", "season"),
    ("TENNIS", "NATIONALITY_STAGE_COUNT"): ("season_outcome", "season"), ("SOCCER", "soccer_special"): ("off_field", "other"),
    ("SOCCER", "first_to_score"): ("first_event", "game"), ("SOCCER", "competition_outright"): ("season_outcome", "season"),
    ("MLB", "announcer_mentions"): ("off_field", "other"), ("MLB", "extra_innings"): ("overtime", "game"), ("MLB", "game_delay"): ("game_stat", "game"), ("MLB", "non_baseball"): ("off_field", "other"), ("MLB", "non_baseball_esports"): ("off_field", "other"),
    ("MLB", "postseason_series"): ("season_outcome", "season"), ("MLB", "season_specials"): ("season_stat", "season"), ("MLB", "business_other"): ("off_field", "other"),
    ("MLB", "other_league_game_result"): ("winner", "game"), ("MLB", "team_season_records"): ("season_stat", "season"), ("MLB", "player_participation"): ("lineup_role", "player"),
    ("MLB", "first5_total"): ("total", "game"), ("MLB", "first5_spread"): ("spread", "game"), ("MLB", "first_inning_runs"): ("total", "game"), ("MLB", "game_spread"): ("spread", "game"), ("SOCCER", "season_player_total"): ("season_stat", "season"),
}


def classify(sport: str, native: str, ticker: str = "", title: str = "") -> dict:
    ov = OVERRIDES.get((sport, native))
    if ov:
        return {"kind": ov[0], "scope": ov[1], "period": detect_period(sport, native, ticker)}
    text = f"{native.replace('first_half','').replace('second_half','')} {ticker}".lower().replace("-", "_")
    kind, scope = "unclassified", "other"
    for k, s, rx in _RULES:
        if re.search(rx, text):
            kind, scope = k, s
            break
    period = detect_period(sport, native, ticker)
    if kind in ("winner", "spread", "total", "team_total", "margin_bucket", "btts", "first_event") and period != "FULL":
        kind_out = kind
    else:
        kind_out = kind
    return {"kind": kind_out, "scope": scope, "period": period}

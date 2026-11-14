"""Reconcile the live Kalshi sports listing with the catalog's market archetypes, by CONTRACT TYPE (RESEARCH_ONLY).

A series is classified into a generic contract type from its title/ticker (rules below), then (sport, type) is looked up in COVERAGE (the archetype whose inputs model that
type) or recorded as NO_ARCHETYPE. Unknown/unclassified titles are kept as ``unclassified`` and counted, never dropped. League fan-out (the same type listed for 40 soccer
leagues) is reported separately from genuinely new contract types: 1,144 unregistered soccer series are mostly the former.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from . import market_universe as MU

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "research/input_research/market_universe/live_series_snapshot.json"
OUT = ROOT / "research/input_research/market_universe/reconciliation.json"
PROP = {"goalscorer": r"\bgoal(s)? ?scorer|anytime|\bgoal\b(?! (kick|line))|hat trick", "shots": r"\bshots?\b|\bsot\b", "saves": r"\bsaves?\b", "cards": r"\bcards?\b|yellow|red card",
        "passing_yards": r"pass(ing)? yards?|pass yds", "receiving_yards": r"receiving yards?|rec yds", "rushing_yards": r"rushing yards?|rush yds", "receptions": r"receptions?",
        "passing_tds_ints": r"passing (touchdowns?|tds?|interceptions?|completions?|attempts?)|pass (td|int|comp|att)", "touchdowns": r"touchdowns?|\btds?\b|first td|anytime td",
        "points": r"\bpoints?\b(?! total)", "rebounds": r"rebounds?", "assists": r"assists?", "threes": r"threes|3-?pointers?|3pt", "steals_blocks": r"steals?|blocks?|turnovers?",
        "strikeouts": r"strikeouts?", "hits_tb": r"\bhits?\b|total bases", "home_runs": r"home runs?|\bhr\b", "rbi_runs": r"\brbis?\b|runs scored", "aces": r"aces?|double faults?",
        "sacks_tackles": r"sacks?|tackles?", "fantasy": r"fantasy", "corners": r"corners?"}
TYPES = [("test_junk", r"^(test|testing|delete|play again|testing series)\b|kxtennisssss"),
         ("business_off_field", r"franchise|sale\b|sold|stadium|relocat|expansion|owner|governor|white house|apology|\brule\b|redzone ads|sellouts?|badge|weather delay|practice field|ads\b|cost\b|exec|specials?\b"),
         ("outright_futures", r"champion|winner of|to win the|\bwinner\b.*(league|cup|conference|division|tournament|series|open)|outright|\btitle\b|pennant|super bowl|world series|stanley cup|finals?\b(?! (half|quarter))"),
         ("season_totals", r"\bwins\b|exact wins|win total|season (record|total)|points total|final points|winning streak"),
         ("playoff_advancement", r"advance|qualif|playoff|make the|bracket|seed|group (winner|qual|bottom|points)|furthest stage|relegat|promotion|top \d|top four|finishers?"),
         ("awards_leaders", r"mvp|rookie|award|coach of|defensive player|leader|golden boot|heisman|draft|all-?star|all-?pro|player of the|executive of|sixth man|most improved|all-nba|all-defensive|first team|hall of fame|silver slugger|gold glove|month|naismith|ballon|triple crown|teammate of|ranked #1|#1 ranked|top pick|pitcher of"),
         ("player_move", r"next team|player to return|\breturn\b|debut|first start|to play|to compete|to make|club change|leave|acquire|pull\b|player to pitch|starting lineup|starter\b|\bstarting\b"),
         ("team_stat_special", r"team stat|season stat|player stat|stat average|1st downs|field goals?|interceptions?|safeties|\bties\b|largest lead|stolen bases|outs recorded|\bwalks\b|earned runs|\bpasses\b|1 yard pass|triple double|one three|games played|undefeated|streak|win record|losses|\.500|best record|divisions?|series (comeback|sweep|exact)|upsets|season (point )?totals|goals scored in season|opening day|fastest pitch|matchups?|combo|first opponent|stage of elimination|round of elimination|reach round|major\b|grand slam|group goals|season stats|top x"),
         ("off_field", r"manager|coach (out|hire|fired)|transfer|trade|sign|retire|announce|host|contract|mention|say|sanction|stripped|ban|join|next (coach|manager)"),
         ("first_team_or_event", r"first team to score|first to score|first (td|touchdown|basket|goal|score)|method of (finish|victory)|overtime|tie\b|safety|longest|hat trick"),
         ("btts", r"both teams to score|\bbtts\b"), ("correct_score", r"correct score|exact score|score\b(?! total)"),
         ("team_total", r"team total|team points|team goals|team runs"),
         ("spread", r"spread|handicap|win margin|margin of victory"), ("total", r"\btotal\b|over/under|\bo/u\b"),
         ("winner", r"\bgame\b|moneyline|match\b|winner|to win\b|vs\.?|head[- ]to[- ]head|h2h"),
         ("outright_futures", r"\b(cup|championship|league|open|trophy|tournament|nations|asian)\b")]
PERIOD = [("first_half", r"1st half|first half|\b1h\b"), ("second_half", r"2nd half|second half|\b2h\b"), ("quarter", r"[1-4](st|nd|rd|th) quarter|\b[1-4]q\b|quarter"),
          ("period", r"[1-3](st|nd|rd) period|\b[1-3]p\b"), ("inning", r"inning|first 5|\bf5\b|first five|\bf3\b|first three|\brfi\b|nrfi"), ("set", r"\bset\b|\bsets\b")]
# archetype that models (sport, type[, period]); None = recorded gap. Looked up most-specific first.
COVERAGE = {
 "NFL": {"team_stat_special": "unreg:team_and_event_counting_specials", "player_move": "player_availability", "business_off_field": "off_field_events", "test_junk": "EXCLUDED_JUNK", "winner": "game_moneyline_spread", "spread": "game_moneyline_spread", "total": "game_total", "team_total": "team_total", "first_half": "first_half_and_quarter_totals", "quarter": "first_half_and_quarter_totals",
         "second_half": "first_half_and_quarter_totals", "passing_yards": "qb_passing_yards", "passing_tds_ints": "qb_passing_tds_and_ints", "rushing_yards": "rushing_yards", "receiving_yards": "receiving_yards_and_receptions",
         "receptions": "receiving_yards_and_receptions", "touchdowns": "anytime_first_td_scorer", "goalscorer": "anytime_first_td_scorer", "first_team_or_event": "game_events", "outright_futures": "season_win_totals_and_futures",
         "season_totals": "season_win_totals_and_futures", "playoff_advancement": "season_win_totals_and_futures", "awards_leaders": "season_awards", "off_field": "off_field_events",
         "fantasy": None, "sacks_tackles": "unreg:team_and_event_counting_specials", "points": "unreg:team_and_event_counting_specials", "btts": None, "correct_score": None},
 "CFB": {"team_stat_special": None, "player_move": None, "business_off_field": None, "test_junk": "EXCLUDED_JUNK", "winner": "game_moneyline_spread", "spread": "game_moneyline_spread", "total": "game_total", "team_total": "team_total", "total|first_half": "quarter_and_half_totals", "total|second_half": "quarter_and_half_totals",
         "total|quarter": "quarter_and_half_totals", "team_total|first_half": "quarter_and_half_totals", "first_half": "quarter_and_half_sides", "second_half": "quarter_and_half_sides", "quarter": "quarter_and_half_sides",
         "touchdowns": "touchdown_scorer", "receiving_yards": "game_stat_props", "rushing_yards": "game_stat_props", "receptions": "game_stat_props", "first_team_or_event": "overtime", "outright_futures": "season_futures",
         "season_totals": "season_futures", "playoff_advancement": "season_futures", "awards_leaders": "unreg:awards_and_honors", "off_field": None, "btts": None, "points": None, "sacks_tackles": None, "steals_blocks": None, "goalscorer": None, "correct_score": None},
 "NBA": {"team_stat_special": "unreg:team_and_player_counting_specials", "player_move": "player_availability", "business_off_field": "off_court_events", "test_junk": "EXCLUDED_JUNK", "winner": "game_moneyline_spread", "spread": "game_moneyline_spread", "total": "game_total", "team_total": "team_total", "first_half": "quarter_and_half_markets", "second_half": "quarter_and_half_markets",
         "quarter": "quarter_and_half_markets", "points": "player_points", "rebounds": "player_rebounds", "assists": "player_assists", "threes": "player_threes", "steals_blocks": "steals_blocks_turnovers",
         "first_team_or_event": "first_basket", "outright_futures": "season_futures_team", "season_totals": "season_futures_team", "playoff_advancement": "series_and_cup", "awards_leaders": "awards_draft",
         "off_field": "off_court_events", "correct_score": None},
 "CBB": {"team_stat_special": None, "player_move": None, "business_off_field": None, "test_junk": "EXCLUDED_JUNK", "winner": "game_moneyline_spread", "spread": "game_moneyline_spread", "total": "game_total", "team_total": "team_total", "first_half": "first_half", "second_half": "first_half", "points": "player_points",
         "outright_futures": "futures_champion", "playoff_advancement": "futures_conference", "season_totals": "futures_conference", "awards_leaders": "unreg:polls_and_awards", "off_field": None, "first_team_or_event": None, "goalscorer": None},
 "NHL": {"team_stat_special": "unreg:team_and_player_season_counting", "player_move": None, "business_off_field": "offfield_markets", "test_junk": "EXCLUDED_JUNK", "winner": "game_moneyline_puckline", "spread": "game_moneyline_puckline", "total": "game_total_and_team_total", "team_total": "game_total_and_team_total", "period": "period_markets", "btts|period": "period_markets",
         "goalscorer": "player_points_goals_assists", "points": "player_points_goals_assists", "assists": "player_points_goals_assists", "saves": "goalie_saves", "shots": "player_shots_on_goal", "first_team_or_event": "game_events",
         "outright_futures": "season_futures", "season_totals": "season_futures", "playoff_advancement": "season_futures", "awards_leaders": "season_awards_and_stats", "off_field": "offfield_markets", "correct_score": None, "aces": None},
 "MLB": {"team_stat_special": "unreg:player_and_team_counting_specials", "player_move": "player_participation", "business_off_field": "offfield_markets", "test_junk": "EXCLUDED_JUNK", "winner": "game_moneyline", "spread": "game_moneyline", "total": "game_total_and_team_total", "team_total": "game_total_and_team_total", "inning": "first_inning_and_inning_markets", "strikeouts": "pitcher_strikeouts",
         "hits_tb": "hitter_hits_and_total_bases", "home_runs": "hitter_home_runs", "rbi_runs": "hitter_rbis_runs_sb", "first_team_or_event": "extras_and_delay", "outright_futures": "season_futures", "season_totals": "season_futures",
         "playoff_advancement": "season_futures", "awards_leaders": "season_leaders_and_awards", "off_field": "offfield_markets", "correct_score": None},
 "TENNIS": {"team_stat_special": None, "player_move": "retirement_walkover_participation", "business_off_field": None, "test_junk": "EXCLUDED_JUNK", "winner": "match_winner", "winner|set": "set_winner_and_any_set", "set": "set_winner_and_any_set", "spread": "set_and_game_spreads", "total": "total_games_and_sets", "correct_score": "exact_set_score", "aces": "player_aces_and_double_faults",
            "outright_futures": "tournament_winner_futures", "playoff_advancement": "tournament_winner_futures", "off_field": None},
 "SOCCER": {"team_stat_special": None, "player_move": "soccer_special_and_host", "business_off_field": "soccer_special_and_host", "test_junk": "EXCLUDED_JUNK", "winner": "match_result_3way", "spread": "handicap_and_exact_score", "total": "total_goals", "team_total": "total_goals", "btts": "btts_and_clean_sheet", "correct_score": "handicap_and_exact_score",
            "first_half": "first_half_and_period", "second_half": "first_half_and_period", "first_team_or_event": "first_to_score_event", "outright_futures": "competition_winner_and_top_n", "season_totals": "team_points_and_margin",
            "playoff_advancement": "relegation_qualification_advancement", "awards_leaders": "player_season_leader_and_awards", "off_field": "soccer_special_and_host", "goalscorer": "unreg:player_goal_assist_props", "shots": "unreg:player_shots_saves_props", "saves": "unreg:player_shots_saves_props", "cards": "unreg:corners_and_cards_team_events",
            "corners": "unreg:corners_and_cards_team_events", "assists": "unreg:player_goal_assist_props", "points": None},
}


def classify(r: dict) -> dict:
    t = f"{r['title']} {r['ticker']}".lower()
    ttl = (r["title"] or "").lower()
    period = next((p for p, rx in PERIOD if re.search(rx, ttl)), "full")
    prop = next((p for p, rx in PROP.items() if re.search(rx, ttl)), None)
    typ = next((k for k, rx in TYPES if re.search(rx, ttl)), None)
    if prop and not (typ in ("total", "spread", "team_total", "btts", "correct_score") and prop in ("points", "goalscorer") and "player" not in ttl):
        typ = "player_prop:" + prop
    return {"type": typ or "unclassified", "period": period}


def covering_archetype(sport: str, c: dict):
    """Most specific first: type|period, then period, then type. Missing from the authored table = recorded as UNAUTHORED (a gap in this map, not a verdict)."""
    table = COVERAGE.get(sport)
    if table is None:
        return "NOT_AUTHORED"
    key = c["type"].split(":")[1] if c["type"].startswith("player_prop:") else c["type"]
    for k in (f"{key}|{c['period']}", c["period"], key):
        if k in table:
            return table[k]
    return "UNAUTHORED" if c["type"] != "unclassified" else None


def reconcile() -> dict:
    rows = json.loads(SNAP.read_text())
    known = MU.known_series()
    out = collections.defaultdict(lambda: collections.Counter())
    detail = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        sp = MU.sport_of(r)
        if sp not in ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"):
            continue
        c = classify(r)
        arch = covering_archetype(sp, c)
        key = f"{c['type']}|{c['period']}"
        out[sp][key] += 1
        detail[sp][key].append({"ticker": r["ticker"], "title": r["title"], "registered": r["ticker"] in known, "archetype": arch})
    res = {"schema_version": "universe-reconcile-1.0", "status": "RESEARCH_ONLY", "sports": {}}
    for sp, cnt in out.items():
        rec = []
        for k, n in cnt.most_common():
            d = detail[sp][k]
            rec.append({"type_period": k, "series": n, "registered": sum(x["registered"] for x in d), "unregistered": sum(not x["registered"] for x in d),
                        "archetype": d[0]["archetype"], "examples": [x["title"] for x in d[:3]]})
        res["sports"][sp] = rec
    return res


if __name__ == "__main__":
    r = reconcile()
    OUT.write_text(json.dumps(r, indent=0, sort_keys=True))
    for sp, rec in r["sports"].items():
        un = sum(x["series"] for x in rec if x["archetype"] in (None, "NOT_AUTHORED", "UNAUTHORED") or x["type_period"].startswith("unclassified"))
        print(sp, sum(x["series"] for x in rec), "series;", un, "without archetype/unclassified")

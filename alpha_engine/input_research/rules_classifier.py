"""Classify Kalshi series from their ACTUAL contract rules text (rules_primary of one sampled market), not title keywords (RESEARCH_ONLY).

Ordered regex rules over the rules text (lowercase) map a series to (contract type, archetype). The result overrides title-based classification in series_ledger via
classification_overrides.json, and disagreements between rules text and the title-based classification are reported (the review of provisional archetypes).
Series with no listed market have no rules text: they stay NO_LISTED_MARKETS, an explicit gap, never guessed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MUD = ROOT / "research/input_research/market_universe"

# (regex on rules text, type) ordered; first match wins
RULES = [
    (r"if (over|under) [\d.]+ points? scored wins against|wins against .*(over|under) [\d.]+ points", "combo_mve"),
    (r"fantasy|finishes top \d+ in scoring among", "fantasy_points"),
    (r"plays a game before", "nonsport_business"),
    (r"first non-own goal .* wins the match|scores the first .* goal", "soccer_goal_combo"),
    (r"each record at least \d+ points", "team_total_joint"),
    (r"win at least \d+ games in a row", "team_streak"),
    (r"ballon d'or|best (men's|women's) player|player of the year", "player_award"),
    (r"qualifies for the .* round|reach the .*round of|round of \d+", "tournament_advance"),
    (r"one of the teams to reach the college football playoff national championship", "season_future"),
    (r"(competes|competes in)|qualifies for the final|wins the .* singles title|reach the final", "tennis_tournament"),

    (r"stadium|franchise|board of governors|collective bargaining|\bcba\b|expansion|relocat|reboot|apolog|governor|white house|sold|sale of|ownership", "nonsport_business"),
    (r"conference (leave|join)|leaves the .* before|joins the .* before|cfp .*(expand|approved)|college football playoff \(cfp\) has officially approved", "governance"),
    (r"head coach .* leaves|next permanent head coach|next head coach|leaves his role as the manager|manager of|general manager", "coach_change"),
    (r"next team is|next club|transfers out|announced to be joining|joins .* before|is announced to|performs as an on-air|broadcast|analyst|53-man|top 100 list|walter payton|protector of the year|man of the year|pro bowl|hall of fame", "person_event"),
    (r"announces (his|her) retirement", "retirement_announcement"),
    (r"major (grand slam )?(tournament|title)|wins a tennis major|wins his \d+th career major|grand slam", "tennis_major"),
    (r"ranked #?\d+ on the .*(atp|wta)|#1 ranked (player )?on the .*(atp|wta)|top \d+ ranked .*(atp|wta)|#1 ranked player on the", "tennis_ranking"),
    (r"professional tennis match|wins the .* vs .* (professional )?tennis", "tennis_match"),
    (r"ranked .*(ap |cfp|poll|pomeroy|kenpom|top 25|college football playoff rankings)|ranked #1 .*any week|teams are ranked #1", "poll_rank"),
    (r"is the result of the .* soccer game|wins the .* professional .* soccer game|soccer game originally scheduled", "soccer_game"),
    (r"both (.* )?score a goal|both teams to score", "soccer_btts"),
    (r"(over|under) [\d.]+ goals are scored", "soccer_total"),
    (r"wins by more than [\d.]+ goals", "soccer_spread"),
    (r"finishes in last place|last place in the league", "league_last"),
    (r"top \d+ (finisher|finishers)|finishes in the top|is a top \d+ finisher", "league_top_n"),
    (r"champion|wins .* trophies|golden boot", "outright_champion"),
    (r"undefeated|selected to play in a bowl|reach the college football playoff national championship|#1 seed|worst regular season record|win conference|make a bowl", "season_future"),
    (r"winning margin|point differential of between|wins the game by|point differential of over", "game_margin"),
    (r"double double|triple double", "player_milestone"),
    (r"combined points, rebounds, and assists|pts \+ reb", "nba_combo"),
    (r"overtime periods are played|weather delay|delay due to weather", "game_event"),
    (r"records? (at least |\d+\+? )?(\d+\+? )?(defensive interceptions|sacks|turnovers gained|total yards|rushing attempts|made field goals|2-point)|collectively record|highest scoring team in week|primetime games|lead changes|least penalized", "team_event_count"),
    (r"scores at least \d+ goals during|scores at least \d+ points in any game|records \d+\+? goals across all games|highest scoring performance", "season_player_count"),
    (r"each yes contract pays|ppr", "fantasy_points"),
    (r"\bamericans?\b|\bamerican (woman|man)\b", "tennis_nationality"),
    (r"earned runs|walks allowed|outs recorded|stolen bases?|strikeouts thrown|107\+? mph|50 home runs|100 losses|best record|losing streak|opening day|games played|series score", "mlb_stat_or_season"),
]
# (sport, type) -> (status, archetype). status COVERED means an archetype models it; EXCLUDED_* are explicit exclusions with a reason.
MAP = {
    ("*", "combo_mve"): ("EXCLUDED_COMBO", "combo of other contracts; modelled through its legs and their correlation (future work), not a distinct outcome mechanism"),
    ("*", "nonsport_business"): ("EXCLUDED_NONSPORT", "corporate, political or facility event; outcome not determined by sporting mechanisms (no input list can be justified)"),
    ("NFL", "fantasy_points"): ("COVERED", "unreg:fantasy_points_markets"), ("NFL", "person_event"): ("COVERED", "off_field_events"), ("NFL", "coach_change"): ("COVERED", "off_field_events"),
    ("NFL", "team_event_count"): ("COVERED", "unreg:team_and_event_counting_specials"), ("NFL", "game_event"): ("COVERED", "game_events"), ("NFL", "season_future"): ("COVERED", "season_win_totals_and_futures"),
    ("NFL", "season_player_count"): ("COVERED", "unreg:team_and_event_counting_specials"), ("NFL", "game_margin"): ("COVERED", "game_moneyline_spread"),
    ("CFB", "poll_rank"): ("COVERED", "unreg:polls_and_cfp_rankings"), ("CFB", "team_event_count"): ("COVERED", "unreg:team_event_counting_specials"), ("CFB", "game_event"): ("COVERED", "unreg:team_event_counting_specials"),
    ("CFB", "coach_change"): ("COVERED", "unreg:coaching_and_governance_events"), ("CFB", "governance"): ("COVERED", "unreg:coaching_and_governance_events"), ("CFB", "person_event"): ("COVERED", "unreg:coaching_and_governance_events"),
    ("CFB", "season_future"): ("COVERED", "season_futures"), ("CFB", "game_margin"): ("COVERED", "game_moneyline_spread"),
    ("CBB", "poll_rank"): ("COVERED", "unreg:polls_and_awards"), ("CBB", "coach_change"): None, ("CBB", "season_future"): ("COVERED", "futures_conference"),
    ("CBB", "game_margin"): ("COVERED", "game_moneyline_spread"), ("CBB", "game_event"): ("COVERED", "game_total"),
    ("NBA", "player_milestone"): ("COVERED", "player_milestones"), ("NBA", "nba_combo"): ("COVERED", "combo_props"), ("NBA", "season_player_count"): ("COVERED", "unreg:team_and_player_counting_specials"),
    ("NBA", "person_event"): ("COVERED", "off_court_events"), ("NBA", "coach_change"): ("COVERED", "off_court_events"), ("NBA", "game_margin"): ("COVERED", "game_win_margin"),
    ("NHL", "season_player_count"): ("COVERED", "unreg:team_and_player_season_counting"), ("NHL", "season_future"): ("COVERED", "season_futures"), ("NHL", "person_event"): ("COVERED", "offfield_markets"), ("NHL", "coach_change"): ("COVERED", "offfield_markets"),
    ("MLB", "person_event"): ("COVERED", "offfield_markets"), ("MLB", "mlb_stat_or_season"): ("COVERED", "unreg:player_and_team_counting_specials"), ("MLB", "season_player_count"): ("COVERED", "unreg:player_and_team_counting_specials"),
    ("TENNIS", "tennis_match"): ("COVERED", "match_winner"), ("TENNIS", "tennis_major"): ("COVERED", "season_ranking_and_majors"), ("TENNIS", "tennis_ranking"): ("COVERED", "season_ranking_and_majors"),
    ("TENNIS", "retirement_announcement"): ("COVERED", "retirement_walkover_participation"), ("TENNIS", "tennis_tournament"): ("COVERED", "tournament_winner_futures"), ("TENNIS", "tennis_nationality"): ("COVERED", "nationality_and_team_futures"),
    ("NFL", "team_total_joint"): ("COVERED", "team_total"), ("SOCCER", "team_streak"): ("COVERED", "team_points_and_margin"), ("SOCCER", "player_award"): ("COVERED", "player_award"), ("SOCCER", "soccer_goal_combo"): ("COVERED", "unreg:player_goal_assist_props"),
    ("CBB", "tournament_advance"): ("COVERED", "futures_champion"), ("CFB", "tournament_advance"): ("COVERED", "season_futures"),
    ("SOCCER", "soccer_game"): ("COVERED", "match_result_3way"), ("SOCCER", "soccer_btts"): ("COVERED", "btts_and_clean_sheet"), ("SOCCER", "soccer_total"): ("COVERED", "total_goals"), ("SOCCER", "soccer_spread"): ("COVERED", "handicap_and_exact_score"),
    ("SOCCER", "league_last"): ("COVERED", "relegation_qualification_advancement"), ("SOCCER", "league_top_n"): ("COVERED", "competition_winner_and_top_n"), ("SOCCER", "outright_champion"): ("COVERED", "competition_winner_and_top_n"),
    ("SOCCER", "person_event"): ("COVERED", "soccer_special_and_host"), ("SOCCER", "coach_change"): ("COVERED", "soccer_special_and_host"), ("SOCCER", "season_player_count"): ("COVERED", "player_season_leader_and_awards"),
}


def classify(sport: str, rules: str, secondary: str = ""):
    """Primary rules text first (the contract definition); secondary text only as a fallback, because its boilerplate mentions unrelated words ('champion', 'American')."""
    for text in (rules, secondary):
        t = (text or "").lower()
        if not t:
            continue
        for rx, typ in RULES:
            if re.search(rx, t):
                hit = MAP.get((sport, typ)) or MAP.get(("*", typ))
                return typ, hit
    return None, None


# Corrections found by reading the rules text of series where the title-based archetype disagreed (rules text = the contract definition). Keyed by exact series title.
CORRECTIONS = {
    "Pro Football Player Fantasy Points": ("unreg:fantasy_points_markets", "rules: full-PPR fantasy points, not a team/event count"),
    "Team to go undefeated in division": ("season_win_totals_and_futures", "rules: season outcome (division record), not a game/event count"),
    "Will player be ranked on Pro Football Top 100 List": ("off_field_events", "rules: rank on a published list (narrative/voting), not a counting stat"),
    "NBA Player Triple Double": ("player_milestones", "rules: single-game triple double by a named player = milestone archetype"),
    "College Football Team Total Yards": ("unreg:team_event_counting_specials", "rules: team yards count in a game, not team points"),
    "Nationality of Tennis Tournament Winner": ("nationality_and_team_futures", "rules: nationality of a tournament winner, not a match winner"),
    "Top 5 Ranked Player ATP": ("season_ranking_and_majors", "rules: year-end ranking position, not a tournament title"),
    "Ballon d'Or awards": ("player_award", "rules: a named panel award, the more specific archetype"),
    "When will team end streak": ("season_win_totals_and_futures", "rules: streak length over the season, not a corporate event (rules classifier false positive on 'sale/ownership' words)"),
    "Liga Expansion Game": ("match_result_3way", "'Expansion' is a league name (Liga de Expansion), not a franchise expansion: a normal 3-way match result"),
}


def build() -> dict:
    sample = json.loads((MUD / "contract_rules_sample.json").read_text())
    from . import series_ledger as SL
    led = SL.build(use_overrides=False)          # title-based status, independent of any previous override (no circular dependency)
    by = {r["ticker"]: r for r in led["rows"]}
    over, nolist, unmatched, dis = {}, [], [], []
    UNRESOLVED = ("UNCLASSIFIED", "CLASSIFIED_NO_ARCHETYPE")
    for t, q in sample.items():
        r = by.get(t)
        if not r or r["sport"] == "OUT_OF_SCOPE_SPORT":
            continue
        if "basketball" in (q.get("rules_primary") or "").lower() and r["sport"] == "SOCCER":
            over[t] = {"type": "basketball_misassigned", "period": "full", "archetype": "OUT_OF_SCOPE_BASKETBALL", "reason": "contract rules say basketball: a non-NBA/CBB basketball league wrongly sport-tagged as soccer by the ticker heuristic"}; continue
        if r["status"] == "EXCLUDED_TEST":
            continue                               # test/placeholder series stay excluded (they also list no market)
        if q.get("status") in ("NO_MARKETS_LISTED", None):
            nolist.append(t); over[t] = {"type": "no_listed_market", "period": "full", "archetype": "NO_LISTED_MARKETS", "reason": "series has no listed market, so no contract rules can be read"}; continue
        typ, hit = classify(r["sport"], q.get("rules_primary", ""), (q.get("rules_secondary") or "")[:200])
        if typ is None:
            unmatched.append(t); continue
        if hit is None:
            unmatched.append(t); continue
        status, arch = hit
        # rules text overrides the title-based status ONLY where that was unresolved; where the title-based archetype exists, disagreements are logged (rules text is often coarser than the title: e.g. every soccer stat series says "soccer game")
        if r["status"] not in UNRESOLVED:
            if r.get("archetype") != (arch if status == "COVERED" else status):
                dis.append({"ticker": t, "title": r["title"], "title_based": r.get("archetype"), "rules_based": arch if status == "COVERED" else status, "rules_type": typ})
            continue
        if arch.endswith("_PLACEHOLDER"):
            unmatched.append(t); continue
        entry = {"type": typ, "period": "full", "reason": f"contract rules: {typ}"}
        if status == "COVERED":
            entry["archetype"] = arch
        else:
            entry["archetype"] = status; entry["reason"] = arch
        over[t] = entry
    corrected = []
    for t, r in by.items():
        c = CORRECTIONS.get(r["title"])
        if c and r["sport"] != "OUT_OF_SCOPE_SPORT" and t not in nolist:
            over[t] = {"type": "rules_review_correction", "period": "full", "archetype": c[0], "reason": c[1]}; corrected.append(t)
    dis = [d for d in dis if d["ticker"] not in corrected]
    return {"overrides": over, "no_listed_market": nolist, "unmatched": unmatched, "disagreements": dis, "corrected": corrected}


if __name__ == "__main__":
    b = build()
    (MUD / "classification_overrides.json").write_text(json.dumps(b["overrides"], indent=0, sort_keys=True))
    (MUD / "classification_review.json").write_text(json.dumps({"disagreements_with_title_based": b["disagreements"], "unmatched_by_rules": b["unmatched"], "no_listed_market": b["no_listed_market"], "corrected_after_rules_review": b["corrected"]}, indent=0, sort_keys=True))
    print(len(b["overrides"]), "overrides;", len(b["no_listed_market"]), "no listed market;", len(b["unmatched"]), "unmatched;", len(b["disagreements"]), "disagreements")

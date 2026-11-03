"""Family -> input links for the 43 overnight-discovered candidate inputs (+ cross-sport market inputs).

Before this module the 43 ids existed in the registry but were attached to NO market family, so they contributed nothing to
per-market coverage. Each rule: (sport, native_family regex [fullmatch, case-insensitive], input id, tier E/C/X, why).
Tier = hypothesised relevance (E essential, C important/contextual, X exploratory), NOT validated value. Existing blueprint
tokens are never changed or downgraded: a link only ADDS an input, or raises an input that is currently lower tier.
Anticipated-but-unobserved classes (soccer corners/cards/shots, MLB first-three-innings) are deliberately NOT linked to
unrelated observed families; they are reported as `unlinked` with the reason."""
import re

PER = "period"   # pseudo-regex marker: matches families that list any non-FULL period and are winner/spread/total/team_total/btts/game_stat/period_result
RULES = [
 # --- NFL
 ("NFL", PER, "nfl.q_scoring", "E", "quarter/half markets settle on per-period points"),
 ("NFL", r"PERIOD_TD", "nfl.q_scoring", "E", "period TD markets"),
 ("NFL", r"TEAM_TOTAL", "nfl.team_total_split", "E", "team total = team share of game total"),
 ("NFL", r"TEAM_STAT", "nfl.team_total_split", "C", "team stat markets"),
 ("NFL", r"SPREAD|TOTAL|TEAM_TOTAL|GAME_STAT|GAME_EVENT", "nfl.kicker", "C", "FG/XP/touchback outcomes move totals and scoring margins"),
 ("NFL", r"FIRST_TD_TEAM|FIRST_TD_TIME", "nfl.opening_script", "E", "first-TD timing/team depends on opening drives"),
 ("NFL", r"FIRST_TD_SCORER|RACE_TO_N|BOTH_TEAMS_SCORE", "nfl.opening_script", "C", "early-scoring script"),
 ("NFL", r"FIRST_TD_SCORER|NEXT_TD_SCORER", "nfl.td_rates", "E", "scorer markets depend on role/red-zone share"),
 ("NFL", r"PLAYER_STAT|TOTAL_TD", "nfl.td_rates", "C", "TD props"),
 # --- CFB
 ("CFB", r"quarter_.*|first_half_.*|second_half_.*", "cfb.q_scoring", "E", "quarter/half markets settle on per-period points"),
 ("CFB", r"touchdown_scorer", "cfb.td_rates", "E", "scorer market"),
 ("CFB", r"quarter_.*|touchdown_scorer", "cfb.first_drive", "C", "opening-drive script"),
 ("CFB", r"game_.*|team_total|first_half_.*|overtime", "cfb.kicker", "C", "FG range decides totals/margins"),
 ("CFB", r"game_moneyline|game_spread|game_total|team_total|first_half_.*", "cfb.qb_status_pit", "E", "QB status moves the whole game line; no reliable official feed"),
 # --- NBA
 ("NBA", PER, "nba.q_scoring", "E", "quarter/half markets settle on per-period points"),
 ("NBA", r"game_race_to|game_points_leader", "nba.q_scoring", "C", "early-game scoring path"),
 ("NBA", r"player_threes", "nba.three_volume", "E", "3PM = 3PA x 3P%"),
 ("NBA", r"player_points|player_pra|team_total|game_total", "nba.three_volume", "C", "three-point variance"),
 ("NBA", r"player_steals|player_blocks|player_stocks", "nba.steal_block_rates", "E", "stat prop"),
 ("NBA", r"player_turnovers", "nba.steal_block_rates", "C", "opponent steal pressure"),
 ("NBA", r"first_basket", "nba.tip_first_shot", "E", "first-basket depends on tip winner and first-shot usage"),
 ("NBA", r"game_race_to|period_winner", "nba.tip_first_shot", "C", "early scoring"),
 ("NBA", r"player_free_throws", "nba.ft_attempts", "E", "FT made = FTA x FT%"),
 ("NBA", r"player_points|player_pra|player_pr|player_pa", "nba.ft_attempts", "C", "FT share of points"),
 ("NBA", r"player_free_throws|player_points|player_rebounds|player_assists|player_pra|player_pr|player_pa|player_ra|player_steals|player_blocks|player_threes", "nba.foul_rates", "C", "foul trouble cuts minutes"),
 ("NBA", r"team_bench_points", "nba.bench_scoring", "E", "bench points market"),
 # --- CBB
 ("CBB", r"GAME_WINNER|SPREAD|TOTAL|TEAM_TOTAL|HALF", "cbb.neutral_site", "E", "home-court/neutral-site adjustment to every game line"),
 ("CBB", r"GAME_WINNER|SPREAD|TOTAL|TEAM_TOTAL|HALF", "cbb.three_pt_dist", "C", "high single-game 3P variance"),
 ("CBB", r"GAME_WINNER|SPREAD|TOTAL|HALF", "cbb.free_throw", "C", "late-game FT effects"),
 ("CBB", r"PLAYER_PROP", "cbb.player_foul", "C", "foul trouble cuts minutes"),
 # --- NHL
 ("NHL", r"goalie_saves", "nhl.goalie_workload", "E", "saves depend on goalie identity/rest"),
 ("NHL", r"goalie_saves", "nhl.shots_against", "E", "saves = shots against - goals"),
 ("NHL", r"goalie_saves|player_shots", "nhl.shot_location", "C", "shot quality/location"),
 ("NHL", r"game_total|team_total|period_total", "nhl.shots_against", "C", "pace/volume"),
 ("NHL", r"game_total|period_total|period_btts|game_early_goal", "nhl.penalty_rates", "C", "power-play volume"),
 ("NHL", r"game_winner|game_total", "nhl.goalie_workload", "C", "starter vs backup"),
 ("NHL", r"game_shootout|game_overtime|game_multi_overtime", "nhl.shootout_record", "E", "shootout/OT markets"),
 ("NHL", r"game_winner", "nhl.shootout_record", "C", "tie-break outcome"),
 ("NHL", PER, "nhl.penalty_rates", "C", "period scoring depends on power plays"),
 # --- MLB
 ("MLB", r"pitcher_strikeouts", "mlb.k_rates", "E", "strikeout rate vs lineup"),
 ("MLB", r"pitcher_outs", "mlb.k_rates", "C", "efficiency"),
 ("MLB", r"pitcher_strikeouts|pitcher_outs|pitcher_earned_runs|pitcher_hits_allowed|pitcher_walks_allowed", "mlb.tto", "E", "pull rate and times-through-order penalty set the workload"),
 ("MLB", r"first5_.*|inning_.*|first_inning_runs", "mlb.tto", "C", "starter length"),
 ("MLB", r"first5_.*|inning_.*|first_inning_runs", "mlb.f3_split", "C", "early-innings run split (no dedicated first-three-innings family observed)"),
 ("MLB", r"hitter_stolen_bases", "mlb.sb_context", "E", "SB attempt rate, hold time, catcher pop time"),
 ("MLB", r"hitter_hits|hitter_total_bases|hitter_rbis|hitter_hits_runs_rbis|hitter_home_runs", "mlb.contact_dist", "E", "count distributions given PA count and lineup slot"),
 # --- SOCCER (corners/cards/shots/anytime-scorer classes have NO observed Kalshi family: not linked)
 ("SOCCER", r"match_result_3way|match_winner_2way|total_goals|btts|handicap", "soc.formation", "C", "tactical matchup"),
 ("SOCCER", r"match_result_3way|total_goals|exact_score|btts", "soc.penalty_rate", "X", "penalty frequency/referee tendency"),
 # --- TENNIS
 ("TENNIS", r"TIEBREAK_OCCURS", "ten.tiebreak", "E", "tiebreak market"),
 ("TENNIS", r"TOTAL_GAMES|GAME_SPREAD|EXACT_SET_SCORE|SET_WINNER|ANY_SET_WINNER", "ten.tiebreak", "C", "tiebreak frequency shapes games/sets"),
 ("TENNIS", r"MATCH_WINNER|SET_WINNER|GAME_SPREAD|TOTAL_GAMES|GAME_WINNER_INPLAY", "ten.break_points", "C", "break-point creation/conversion"),
 ("TENNIS", r"TOTAL_SETS|SET_SWEEP|EXACT_SET_SCORE", "ten.decider_record", "E", "deciding-set behaviour"),
 ("TENNIS", r"MATCH_WINNER", "ten.decider_record", "C", "match closure"),
 ("TENNIS", r"ROUND_ADVANCE|ROUND_OF_ELIMINATION", "ten.round_context", "E", "bracket-path difficulty"),
 ("TENNIS", r"TOURNAMENT_WINNER|MATCH_WINNER", "ten.round_context", "C", "round/seed context"),
 ("TENNIS", r"PLAYER_ACES", "ten.first_serve", "E", "ace count"),
 ("TENNIS", r"TOTAL_GAMES|MATCH_WINNER", "ten.first_serve", "C", "serve dominance"),
]
PERIOD_KINDS = {"winner", "spread", "total", "team_total", "btts", "game_stat", "period_result", "margin_bucket"}
RANK = {"E": 3, "C": 2, "X": 1}
# cross-sport market inputs: every family gets the tape; ladder-structured families get strike hit rates
COMMON_LINKS = {"all": ("m.trade_tape", "C"), "ladder": ("m.strike_hit_rates", "C")}
UNLINKED = {"soc.corners": "no Kalshi soccer corners family observed in the 48 ambiguous series examined", "soc.shots": "no shots/SOT family observed",
            "soc.fouls_cards": "no cards/fouls family observed"}


def links_for(fam):
    """fam: master_inventory family dict -> {input_id: (tier, why)} (highest tier wins)."""
    sp, nat, kind, periods = fam["sport"], fam["native_family"], fam["canonical"]["kind"], fam["canonical"]["periods"]
    out = {}
    for s, rx, iid, tier, why in RULES:
        if s != sp:
            continue
        hit = (kind in PERIOD_KINDS and any(p != "FULL" for p in periods)) if rx == PER else re.fullmatch(rx, nat, re.I) is not None
        if hit and (iid not in out or RANK[tier] > RANK[out[iid][0]]):
            out[iid] = (tier, why)
    return out

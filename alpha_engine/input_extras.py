"""Market-specific candidate inputs added after the first catalog pass (overnight expansion).

Same discipline as input_catalog: every entry is a candidate hypothesis, NOT a claim of predictive value or of
collection. Newly added ids start UNKNOWN until audited against repo code (code_evidence) and archives.
Format: "id|label|category" ; KW maps id -> case-insensitive regex used for static code-reference search."""

EXTRA = {
"NFL": """nfl.kicker|Kicker accuracy by distance, effective range, kickoff touchback rate|specialized
nfl.q_scoring|Historical scoring by quarter/half (team and game), opponent-adjusted|distribution
nfl.opening_script|Opening-drive play-calling and first-drive points/yards by team|specialized
nfl.td_rates|Anytime/first-TD scoring rates by role, red-zone and goal-line touch share|usage_role
nfl.team_total_split|Team-points share model (implied total x spread -> team means)|distribution""",
"CFB": """cfb.kicker|Kicker accuracy by distance, effective range, FG attempt rate by field position|specialized
cfb.q_scoring|Historical scoring distribution by quarter (Q1-Q4) and half, opponent-adjusted|distribution
cfb.first_drive|Opening-drive tendencies (script, tempo, punt/FG/TD outcome rate)|specialized
cfb.td_rates|Anytime/first-TD rates by role and red-zone/goal-line usage|usage_role
cfb.qb_status_pit|Confirmed QB/starter status with timestamped vintages (no reliable official feed)|personnel""",
"NBA": """nba.foul_rates|Personal fouls per minute, foul-out and foul-trouble minute loss|usage_role
nba.three_volume|3PA rate, catch-and-shoot share, 3P% shrinkage and opponent 3PA allowed|usage_role
nba.steal_block_rates|Steals/blocks per minute, opponent turnover and rim-attempt rates|usage_role
nba.tip_first_shot|Tip-off winner tendencies and first-shot/first-basket usage|specialized
nba.q_scoring|Historical scoring by quarter/half, first-quarter pace and starter minutes|distribution
nba.ft_attempts|Free-throw attempt rate and FT% (for FT-made props), opponent foul-rate allowed|usage_role
nba.bench_scoring|Bench scoring share and rotation depth by team|usage_role""",
"CBB": """cbb.three_pt_dist|3PA rate and 3P% variance (single-game volatility) by team|distribution
cbb.free_throw|Free-throw rate and FT% (late-game and foul-game effects)|specialized
cbb.neutral_site|Neutral/tournament-site effects and travel distance|venue_weather_schedule
cbb.player_foul|Player foul rate and foul-trouble minute risk|usage_role""",
"NHL": """nhl.shots_against|Team shots-on-goal against, shot quality, score-effects adjusted|pace_volume
nhl.penalty_rates|Penalties taken/drawn per 60 and referee crew tendencies|venue_weather_schedule
nhl.goalie_workload|Goalie rest, consecutive starts, recent save-pct and backup identity|personnel
nhl.shootout_record|Shootout/OT record and shooter/goalie shootout talent|specialized
nhl.shot_location|Shot location/danger-zone mix for and against|specialized""",
"MLB": """mlb.f3_split|First-three-innings run split and top-of-order exposure by lineup|distribution
mlb.tto|Times-through-the-order penalty and starter pull rates|usage_role
mlb.k_rates|Pitcher K%/whiff/CSW and opposing-lineup K% (platoon-split)|usage_role
mlb.sb_context|Stolen-base attempt rate, pitcher hold time, catcher pop time|specialized
mlb.contact_dist|Hit/TB/RBI count distributions given PA count and lineup slot|distribution""",
"SOCCER": """soc.corners|Team corners for/against, wing play, crossing volume, possession-state effects|pace_volume
soc.shots|Shots and shots-on-target for/against by team and player, shot volume by game state|pace_volume
soc.fouls_cards|Fouls, yellow/red card rates by team/player and referee card tendencies|specialized
soc.formation|Formation/tactical system and expected pressing matchup|matchup
soc.penalty_rate|Penalty awarded rate, designated taker, referee penalty tendency|specialized""",
"TENNIS": """ten.tiebreak|Tiebreak win rate and hold-under-pressure (break-point saved/converted)|distribution
ten.break_points|Break points created/converted/saved|team_strength
ten.decider_record|Deciding-set record, first-set-winner conversion|distribution
ten.round_context|Round, seeding and bracket-path difficulty|team_strength
ten.first_serve|1st-serve in%, 1st/2nd-serve points won by surface|specialized""",
}

COMMON_EXTRA = """m.strike_hit_rates|Historical realized frequency by strike/rung per family (from settlements)|distribution
m.trade_tape|Executed trades (price, size, taker side, time) for slippage and flow|market_structure"""

KW_EXTRA = {
"nfl.kicker": r"kicker|field_goal|fg_pct|touchback", "nfl.q_scoring": r"quarter_scor|q1_points|points_by_quarter|first_quarter",
"nfl.opening_script": r"opening_drive|first_drive|script", "nfl.td_rates": r"anytime_td|first_td|td_rate|td_share", "nfl.team_total_split": r"team_total|implied_total",
"cfb.kicker": r"kicker|field_goal|fg_pct|fg_range", "cfb.q_scoring": r"quarter_scor|q1_points|first_quarter|points_by_quarter", "cfb.first_drive": r"opening_drive|first_drive|opening_poss",
"cfb.td_rates": r"anytime_td|first_td|td_rate", "cfb.qb_status_pit": r"qb_status|starting_qb|qb_out",
"nba.foul_rates": r"foul_rate|pf_per|fouls_per|foul_trouble|fouled_out", "nba.three_volume": r"fg3a|three_pa|3pa|threes_attempt|catch_and_shoot", "nba.steal_block_rates": r"steal|block|stl_per|blk_per",
"nba.tip_first_shot": r"tip_?off|first_basket|first_shot", "nba.q_scoring": r"quarter_scor|q1_points|first_quarter|period_points", "nba.ft_attempts": r"fta|free_throw|ft_rate", "nba.bench_scoring": r"bench_points|bench_scor",
"cbb.three_pt_dist": r"three_pt|3pa|fg3|3p_pct", "cbb.free_throw": r"free_throw|ft_rate|ft_pct", "cbb.neutral_site": r"neutral", "cbb.player_foul": r"foul",
"nhl.shots_against": r"shots_against|sog_against|shots_allowed|sa_per", "nhl.penalty_rates": r"penalt|pim", "nhl.goalie_workload": r"goalie_rest|back_to_back|consecutive_starts|backup",
"nhl.shootout_record": r"shootout", "nhl.shot_location": r"shot_location|danger|high_danger|shot_zone",
"mlb.f3_split": r"first_three|f3_|first3", "mlb.tto": r"times_through|tto|order_penalty", "mlb.k_rates": r"k_rate|k_pct|whiff|csw|strikeout_rate", "mlb.sb_context": r"stolen_base|pop_time|sb_attempt", "mlb.contact_dist": r"total_bases|tb_dist|hits_dist|rbi",
"soc.corners": r"corner", "soc.shots": r"shots_on_target|shots_total|\bsot\b|shot_volume", "soc.fouls_cards": r"yellow|red_card|cards?_rate|foul", "soc.formation": r"formation", "soc.penalty_rate": r"penalt",
"ten.tiebreak": r"tiebreak|tie_break", "ten.break_points": r"break_?point|bp_", "ten.decider_record": r"decid|third_set|fifth_set", "ten.round_context": r"round|seed|bracket", "ten.first_serve": r"first_serve|1st_serve|svpt|1stIn",
"m.strike_hit_rates": r"hit_rate|strike_dist|calibration", "m.trade_tape": r"trades?\.jsonl|trade_tape|taker_side|executed",
}

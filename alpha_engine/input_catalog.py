"""Candidate-input catalog per sport + blueprints per market kind.

IMPORTANT: every entry is a *candidate hypothesis*. Tier is ESSENTIAL (the outcome cannot be projected sensibly
without it), CONTEXTUAL (plausibly moves the projection), EXPLORATORY (speculative / advanced). Nothing here
claims predictive value; validation lives in collection_status / future experiments.
Format: "id|label|category" ; blueprint: "id:E|C|X".
"""
CATS = ("team_strength", "pace_volume", "personnel", "usage_role", "matchup", "venue_weather_schedule",
        "distribution", "market_structure", "specialized", "settlement")

COMMON = """m.quote_history|Kalshi bid/ask/last time series (pre-game through close)|market_structure
m.orderbook_depth|Order-book depth and spread|market_structure
m.volume_oi|Volume and open interest|market_structure
m.ladder_structure|Cross-rung consistency of the threshold ladder (monotonicity, implied distribution)|market_structure
m.settlement_truth|Settled result, settlement value and timestamp|settlement
m.rules_text|Versioned rules_primary / settlement wording (OT, ties, postponement, void)|settlement
m.external_lines|Sportsbook / exchange reference prices with timestamps|market_structure
m.fees|Fee schedule and maker/taker rules in force|market_structure
m.lifecycle|Open/close/halt/postponement lifecycle events|settlement"""
COMMON_BP = "m.quote_history:E m.settlement_truth:E m.rules_text:E m.orderbook_depth:C m.volume_oi:C m.external_lines:C m.fees:C m.lifecycle:C"
LADDER_BP = "m.ladder_structure:C"

INPUTS = {
"NFL": """nfl.off_epa|Offensive EPA/play, opponent-adjusted, recency-weighted|team_strength
nfl.def_epa|Defensive EPA/play, opponent-adjusted|team_strength
nfl.success_rate|Success rate / early-down efficiency|team_strength
nfl.pace|Neutral-situation pace (sec/play) and plays per game|pace_volume
nfl.drives|Expected drives per team (incl. clock-killing style)|pace_volume
nfl.proe|Pass rate over expected, neutral and script-adjusted|pace_volume
nfl.explosive|Explosive-play rate / yards per play allowed|team_strength
nfl.redzone|Red-zone and goal-to-go TD conversion|team_strength
nfl.turnovers|Turnover rate and takeaway luck regression|team_strength
nfl.field_pos|Starting field position, special teams, return units|team_strength
nfl.penalties|Penalty rates and officials crew tendencies|venue_weather_schedule
nfl.qb|Starting QB status and QB-specific performance/regime|personnel
nfl.injuries_pit|Injury report with practice status, timestamped vintages|personnel
nfl.depth_chart_pit|Depth chart vintages (starter/rotation)|personnel
nfl.ol|Offensive-line continuity, pass-block/pressure rates, run-block|personnel
nfl.skill_avail|WR/TE/RB availability and replacement quality|personnel
nfl.def_personnel|Defensive injuries (pass rush, secondary) and coverage scheme|matchup
nfl.coaching|Coach tendencies (4th-down aggression, tempo, run/pass)|matchup
nfl.weather_pit|Kickoff-hour weather forecast vintages (wind, temp, precip)|venue_weather_schedule
nfl.venue|Roof, surface, altitude, home-field effect|venue_weather_schedule
nfl.rest_travel|Rest, bye, short week, travel/time zone|venue_weather_schedule
nfl.score_resid|Historical score residual distribution around market lines (key numbers)|distribution
nfl.ot_model|Overtime / tie model|distribution
nfl.script|Game-script lattice (lead/trail pass-rate and pace shifts)|distribution
nfl.corr|Within-game correlations across stats and teams|distribution
nfl.snaps|Snap share and role by game state|usage_role
nfl.routes|Route participation / alignment (pbp_participation)|usage_role
nfl.targets|Target share, air yards, TPRR, aDOT|usage_role
nfl.carries|Carry share, goal-line and passing-down role|usage_role
nfl.rz_share|Red-zone and goal-line usage shares|usage_role
nfl.dvp|Defense vs position/coverage matchup (shadow coverage, CB assignment)|matchup
nfl.pressure_qb|QB pressure/sack rate faced, time to throw|matchup
nfl.formation|Formation/personnel grouping and motion/play-action rates (FTN)|specialized
nfl.ngs|Next Gen: separation, cushion, YAC over expected, CPOE|specialized
nfl.standings_sim|Season simulation with tiebreakers and remaining schedule|team_strength
nfl.ratings|Power ratings / market-implied team strength history|team_strength
nfl.news|Beat-writer / news events (suspensions, trades, retirement)|personnel
nfl.award_stats|Award-candidate production and voting-narrative features|specialized
nfl.draft_board|Draft order, prospect rankings, team needs|specialized""",
"CFB": """cfb.off_ppa|Opponent-adjusted offensive PPA/EPA, success rate|team_strength
cfb.def_ppa|Opponent-adjusted defensive PPA/EPA|team_strength
cfb.sp_plus|SP+/FPI-style composite ratings|team_strength
cfb.talent|Recruiting talent composite, portal gains/losses|team_strength
cfb.pace|Plays per game, tempo, no-huddle rate|pace_volume
cfb.drives|Drives per game, explosiveness, finishing drives|pace_volume
cfb.pass_rate|Pass rate / script behaviour|pace_volume
cfb.field_pos|Field position, special teams, kicking|team_strength
cfb.redzone|Red-zone efficiency, FG vs TD|team_strength
cfb.qb|Starting QB status, QB performance/regime|personnel
cfb.injuries|Injury/availability news (no reliable official feed)|personnel
cfb.depth_chart|Depth chart / starters (ESPN)|personnel
cfb.ol|Offensive/defensive line quality and continuity|personnel
cfb.transfer_roster|Transfers, roster churn, eligibility|personnel
cfb.coaching|Coaching change, scheme, tempo tendencies|matchup
cfb.weather_pit|Kickoff weather forecast vintages|venue_weather_schedule
cfb.venue|Venue, altitude, home-field and crowd effect|venue_weather_schedule
cfb.rest_travel|Rest, travel, bye, short week, rivalry/lookahead|venue_weather_schedule
cfb.motivation|Bowl/CFP eligibility, rivalry and standings stakes|venue_weather_schedule
cfb.score_resid|Score residual distribution around lines (key numbers)|distribution
cfb.script|Opening-script, early-game scripting, blowout/garbage-time|distribution
cfb.ot_model|Overtime rules and tie/OT model|distribution
cfb.opening_poss|Opening possession (coin toss/deferral) and first-quarter pace|specialized
cfb.half_split|First/second-half scoring split and adjustments|specialized
cfb.player_usage|Player target/carry/snap share (ESPN/CFBD)|usage_role
cfb.standings|Conference standings, tiebreakers, CFP ranking model|team_strength
cfb.polls|Poll/ranking dynamics and committee behaviour|specialized
cfb.officials|Officiating crew penalty tendencies|venue_weather_schedule""",
"NBA": """nba.off_rtg|Opponent-adjusted offensive rating, lineup-adjusted|team_strength
nba.def_rtg|Opponent-adjusted defensive rating|team_strength
nba.pace|Pace/possessions, opponent-adjusted, lineup-aware|pace_volume
nba.minutes|Projected minutes (role, blowout risk, foul trouble)|usage_role
nba.starters_pit|Starting lineups / confirmed starters timestamped|personnel
nba.injuries_pit|Injury report (official + ESPN) vintages, status changes|personnel
nba.rotation|Rotation patterns, minutes distribution by lineup/scoreboard margin|usage_role
nba.usage|Usage rate, shot attempts, creation share|usage_role
nba.touches|Touches, time of possession, ball-handling load|usage_role
nba.pot_ast|Potential assists, passes, secondary assists|usage_role
nba.teammate_conv|Teammate shot conversion / shooting quality|matchup
nba.reb_chances|Rebound chances and contested rebounds|usage_role
nba.shot_profile|Shot location/profile (rim/mid/3), zone defense allowed|specialized
nba.tracking|Tracking data (speed, defender distance, rim protection)|specialized
nba.onoff|On/off and lineup combination efficiency|specialized
nba.matchup_def|Individual defensive matchup / scheme (drop, switch)|matchup
nba.opp_def_pos|Opponent defense vs position / stat allowed|matchup
nba.fouls_ft|Foul drawing, free-throw rate and officials/referee crew|venue_weather_schedule
nba.rest_travel|Rest, back-to-back, travel, altitude|venue_weather_schedule
nba.venue|Arena/home-court effect|venue_weather_schedule
nba.garbage|Blowout / garbage-time probability from spread|distribution
nba.score_resid|Score residual distribution around lines|distribution
nba.ot_model|Overtime probability and minutes|distribution
nba.stat_dist|Per-stat count distributions (overdispersion, correlation)|distribution
nba.ratings|Team ratings / schedule strength for season markets|team_strength
nba.standings_sim|Season/playoff simulation, tiebreakers, play-in|team_strength
nba.load_mgmt|Load management / return-from-injury minutes restrictions|personnel
nba.award_stats|Award-candidate production, voting narrative|specialized
nba.news|Transactions, trades, coaching news|personnel""",
"CBB": """cbb.adj_off|Adjusted offensive efficiency (opponent/venue-adjusted)|team_strength
cbb.adj_def|Adjusted defensive efficiency|team_strength
cbb.tempo|Adjusted tempo / possessions|pace_volume
cbb.four_factors|Four factors (eFG, TO, ORB, FT rate)|team_strength
cbb.shot_zones|Shot quality and rim/mid/3 mix|specialized
cbb.roster_minutes|Roster, minutes distribution, transfer portal changes|personnel
cbb.injuries|Availability / injury / suspension information|personnel
cbb.lineups|Lineups, stints, on-floor efficiency|specialized
cbb.starters|Starter/rotation status|personnel
cbb.player_usage|Player usage, shooting, rebound/assist rates|usage_role
cbb.venue|Home court, neutral site, altitude|venue_weather_schedule
cbb.rest_travel|Rest, travel, schedule density|venue_weather_schedule
cbb.motivation|Conference/tournament stakes, rivalry|venue_weather_schedule
cbb.score_resid|Score residual distribution (key numbers, halves)|distribution
cbb.half_split|First/second-half scoring split|specialized
cbb.fouls_officials|Fouls/free throws and officials crew|venue_weather_schedule
cbb.ratings|Power ratings (Torvik/KenPom-style) + market-implied|team_strength
cbb.bracket_sim|Tournament/bracket/seed/conference simulation|team_strength
cbb.recruit_exp|Experience, recruiting and returning minutes|specialized
cbb.news|Coaching, award, ranking-poll news|personnel""",
"NHL": """nhl.xg_for|Expected goals for (all strengths), shot quality|team_strength
nhl.xg_against|Expected goals against, shot suppression|team_strength
nhl.pace|Shot attempt rate / event pace|pace_volume
nhl.special_teams|PP/PK rates, penalty rates, referee tendencies|team_strength
nhl.goalie_start|Confirmed starting goalie (timestamped)|personnel
nhl.goalie_quality|Goalie save-percentage above expected, workload|team_strength
nhl.lines|Line combinations and defence pairings|personnel
nhl.toi|Projected time on ice by strength state|usage_role
nhl.pp_role|Power-play unit role and PP time|usage_role
nhl.shot_rate|Individual shot attempt/SOG rates, shot location|usage_role
nhl.finishing|Shooting percentage / finishing talent (regressed)|usage_role
nhl.assist_rate|Primary/secondary assist involvement|usage_role
nhl.injuries_pit|Injury/scratch status vintages|personnel
nhl.opp_supp|Opponent shot suppression / goals-against by position|matchup
nhl.rest_travel|Rest, back-to-back, travel|venue_weather_schedule
nhl.venue|Rink effects (shot counting bias), home advantage|venue_weather_schedule
nhl.score_state|Game-script / score effects on shots|distribution
nhl.ot_so|Overtime/shootout model and rules|distribution
nhl.empty_net|Empty-net goals and pulled-goalie timing|distribution
nhl.period_split|Period-level scoring distribution|distribution
nhl.stat_dist|Per-stat count distributions and correlations|distribution
nhl.ratings|Team ratings/standings simulation|team_strength
nhl.award_stats|Awards/season-stat candidate production|specialized
nhl.officials|Referee penalty-call tendencies|venue_weather_schedule
nhl.news|Trades, coaching, transactions|personnel""",
"MLB": """mlb.sp_quality|Starting-pitcher quality (xFIP/SIERA/Stuff+, projections)|team_strength
mlb.sp_workload|Expected innings / batters faced / pitch count|pace_volume
mlb.pitch_mix|Pitch mix, velocity, whiff and chase rates|specialized
mlb.bullpen|Bullpen availability, fatigue, leverage ordering|team_strength
mlb.lineup_pit|Confirmed batting order timestamped (and platoon splits)|personnel
mlb.hitter_quality|Hitter xwOBA/contact quality, projections|team_strength
mlb.platoon|Handedness matchup and platoon splits|matchup
mlb.batter_vs_pitch|Batter vs pitch-type matchup|matchup
mlb.park|Park factors (run, HR, hit types) and dimensions|venue_weather_schedule
mlb.weather_pit|Game-time weather (wind direction/speed, temp, humidity)|venue_weather_schedule
mlb.umpire|Plate-umpire strike-zone tendencies|venue_weather_schedule
mlb.defense|Team/fielder defense (OAA), catcher framing|team_strength
mlb.baserunning|Baserunning/steal rates, catcher arm|specialized
mlb.rest_travel|Rest, travel, doubleheaders|venue_weather_schedule
mlb.run_dist|Run-scoring distribution (inning-level, negative binomial), correlations|distribution
mlb.pa_sim|Plate-appearance outcome simulation|distribution
mlb.first_inning|First-inning scoring distribution (RFI/YRFI)|distribution
mlb.f5_split|First-N-innings vs bullpen split|distribution
mlb.injuries_pit|Injury/IL and late scratches vintages|personnel
mlb.opp_strength|Opponent-adjusted offense/defense|team_strength
mlb.extra_innings|Extra-innings/ghost-runner rules|distribution
mlb.season_sim|Season/playoff simulation, awards candidates|team_strength
mlb.news|Trades, call-ups, news|personnel""",
"SOCCER": """soc.xg|Team xG for/against, shot quality, set-piece xG|team_strength
soc.ratings|Elo/rating, opponent-adjusted goal models (Dixon-Coles)|team_strength
soc.pace_press|Tempo, pressing intensity, possession style|pace_volume
soc.lineups_pit|Confirmed lineups timestamped|personnel
soc.injuries|Injuries/suspensions/availability|personnel
soc.gk|Goalkeeper quality and PSxG-GA|team_strength
soc.player_xg|Player shot/xG/xA rates and minutes|usage_role
soc.set_pieces|Set-piece takers and aerial strength|usage_role
soc.rest_travel|Rest, congestion, travel, European fixtures|venue_weather_schedule
soc.motivation|Competition stakes, relegation/title incentives, rotation|venue_weather_schedule
soc.weather|Weather/pitch/altitude|venue_weather_schedule
soc.referee|Referee card/penalty tendencies|venue_weather_schedule
soc.goal_dist|Goal-count distributions, correlation (Poisson/bivariate)|distribution
soc.score_state|Game state effects, red cards, substitutions|distribution
soc.period_split|1H vs 2H scoring split|distribution
soc.market_odds|Closing and live bookmaker odds (1X2, AH, O/U)|market_structure
soc.comp_sim|League/cup simulation, tiebreakers, qualification|team_strength
soc.transfers|Transfers/manager changes news|personnel
soc.player_awards|Awards/leaders production|specialized""",
"TENNIS": """ten.surface_rating|Surface-adjusted player rating (Elo/serve-return)|team_strength
ten.serve_return|Serve/return point-win probabilities by surface|team_strength
ten.h2h_style|Head-to-head and style matchup (serve vs return, lefties)|matchup
ten.form|Recent form and match-load|team_strength
ten.fitness|Fitness/injury/withdrawal and in-match retirement risk|personnel
ten.fatigue|Fatigue (match length, back-to-back days, travel)|venue_weather_schedule
ten.format|Match format (best-of-3/5, tiebreak, ad scoring)|distribution
ten.hold_break|Hold/break probabilities and game-level Markov model|distribution
ten.set_dist|Set/score distribution and correlations|distribution
ten.aces_df|Aces/double-fault rates, serve speed, court speed|specialized
ten.court_cond|Court speed, altitude, balls, indoor/outdoor, weather|venue_weather_schedule
ten.draw|Draw/bracket structure and round-by-round simulation|team_strength
ten.schedule|Start times, order of play, delays|venue_weather_schedule
ten.motivation|Tournament stakes, ranking points, tanking risk|venue_weather_schedule
ten.market_odds|Closing bookmaker odds (Pinnacle etc.)|market_structure
ten.in_play|Point-level/in-play state|specialized
ten.rankings|ATP/WTA rankings and race points|team_strength
ten.news|Coaching, retirement, participation news|personnel""",
}

# blueprints: key -> "id:E id:C id:X ..." (market kinds map to keys in registry.bp_keys)
BP = {
"NFL": {
 "game_side": "nfl.off_epa:E nfl.def_epa:E nfl.qb:E nfl.injuries_pit:E nfl.ratings:C nfl.success_rate:C nfl.rest_travel:C nfl.weather_pit:C nfl.venue:C nfl.field_pos:C nfl.turnovers:C nfl.coaching:C nfl.score_resid:E nfl.ot_model:C nfl.ol:C nfl.script:X nfl.dvp:X",
 "game_total": "nfl.pace:E nfl.drives:E nfl.proe:C nfl.off_epa:E nfl.def_epa:E nfl.explosive:C nfl.redzone:C nfl.qb:E nfl.injuries_pit:E nfl.ol:C nfl.weather_pit:E nfl.script:C nfl.score_resid:E nfl.ot_model:C nfl.penalties:X nfl.coaching:C nfl.field_pos:C nfl.corr:C",
 "period": "nfl.script:E nfl.pace:E nfl.drives:C nfl.coaching:E nfl.field_pos:C nfl.corr:C",
 "player_pass": "nfl.qb:E nfl.proe:E nfl.pace:E nfl.targets:C nfl.pressure_qb:C nfl.ol:C nfl.weather_pit:C nfl.dvp:C nfl.injuries_pit:E nfl.script:C nfl.ngs:X nfl.formation:X",
 "player_rush": "nfl.carries:E nfl.snaps:E nfl.script:E nfl.ol:C nfl.injuries_pit:E nfl.rz_share:C nfl.dvp:C nfl.depth_chart_pit:E nfl.weather_pit:X",
 "player_rec": "nfl.routes:E nfl.targets:E nfl.snaps:E nfl.injuries_pit:E nfl.proe:C nfl.dvp:C nfl.qb:C nfl.script:C nfl.pressure_qb:X nfl.ngs:X nfl.formation:X nfl.rz_share:C",
 "player_td": "nfl.rz_share:E nfl.snaps:E nfl.script:C nfl.redzone:C nfl.injuries_pit:E nfl.depth_chart_pit:C nfl.pace:C",
 "player_other": "nfl.snaps:E nfl.injuries_pit:E nfl.depth_chart_pit:C nfl.script:C",
 "first_event": "nfl.redzone:C nfl.coaching:C nfl.pace:C nfl.script:C nfl.rz_share:E nfl.field_pos:C",
 "game_event": "nfl.coaching:C nfl.penalties:C nfl.turnovers:C nfl.weather_pit:C nfl.corr:C",
 "lineup_role": "nfl.injuries_pit:E nfl.depth_chart_pit:E nfl.news:E nfl.coaching:C",
 "season_outcome": "nfl.ratings:E nfl.standings_sim:E nfl.injuries_pit:C nfl.news:C",
 "season_stat": "nfl.snaps:E nfl.targets:C nfl.carries:C nfl.injuries_pit:C nfl.standings_sim:C",
 "season_award": "nfl.award_stats:E nfl.standings_sim:C nfl.news:C",
 "off_field": "nfl.news:E nfl.draft_board:C",
 "combo": "nfl.corr:E nfl.score_resid:E nfl.script:C"},
"CFB": {
 "game_side": "cfb.off_ppa:E cfb.def_ppa:E cfb.sp_plus:E cfb.qb:E cfb.injuries:E cfb.talent:C cfb.transfer_roster:C cfb.depth_chart:C cfb.venue:C cfb.rest_travel:C cfb.motivation:C cfb.coaching:C cfb.score_resid:E cfb.ot_model:C cfb.weather_pit:C cfb.officials:X",
 "game_total": "cfb.pace:E cfb.drives:E cfb.off_ppa:E cfb.def_ppa:E cfb.pass_rate:C cfb.redzone:C cfb.qb:E cfb.injuries:E cfb.weather_pit:E cfb.script:C cfb.score_resid:E cfb.ot_model:C cfb.field_pos:C cfb.coaching:C",
 "period": "cfb.opening_poss:E cfb.pace:E cfb.script:E cfb.half_split:E cfb.coaching:C cfb.field_pos:C cfb.off_ppa:C cfb.def_ppa:C",
 "player_other": "cfb.player_usage:E cfb.injuries:E cfb.depth_chart:C cfb.pass_rate:C cfb.script:C",
 "first_event": "cfb.opening_poss:E cfb.redzone:C cfb.pace:C cfb.coaching:C cfb.player_usage:C",
 "game_event": "cfb.coaching:C cfb.script:C cfb.weather_pit:C cfb.officials:X",
 "lineup_role": "cfb.injuries:E cfb.depth_chart:E cfb.transfer_roster:C",
 "season_outcome": "cfb.sp_plus:E cfb.standings:E cfb.polls:C cfb.injuries:C",
 "season_stat": "cfb.player_usage:C cfb.standings:C",
 "season_award": "cfb.standings:C cfb.polls:C cfb.player_usage:E",
 "off_field": "cfb.coaching:E cfb.transfer_roster:C",
 "combo": "cfb.score_resid:E cfb.script:C"},
"NBA": {
 "game_side": "nba.off_rtg:E nba.def_rtg:E nba.injuries_pit:E nba.starters_pit:E nba.rotation:C nba.minutes:C nba.rest_travel:E nba.venue:C nba.load_mgmt:C nba.onoff:X nba.garbage:C nba.score_resid:E nba.ot_model:C nba.fouls_ft:X",
 "game_total": "nba.pace:E nba.off_rtg:E nba.def_rtg:E nba.injuries_pit:E nba.starters_pit:E nba.rest_travel:C nba.garbage:C nba.fouls_ft:C nba.score_resid:E nba.ot_model:C nba.shot_profile:X nba.onoff:X",
 "period": "nba.starters_pit:E nba.rotation:E nba.pace:E nba.off_rtg:C nba.def_rtg:C nba.garbage:C nba.onoff:X",
 "player_pts": "nba.minutes:E nba.usage:E nba.injuries_pit:E nba.starters_pit:E nba.pace:C nba.opp_def_pos:C nba.shot_profile:C nba.fouls_ft:C nba.garbage:C nba.stat_dist:E nba.matchup_def:X nba.tracking:X",
 "player_reb": "nba.minutes:E nba.reb_chances:E nba.injuries_pit:E nba.starters_pit:E nba.pace:C nba.opp_def_pos:C nba.shot_profile:C nba.garbage:C nba.stat_dist:E nba.tracking:X",
 "player_ast": "nba.minutes:E nba.pot_ast:E nba.touches:E nba.usage:C nba.teammate_conv:C nba.injuries_pit:E nba.starters_pit:E nba.pace:C nba.opp_def_pos:C nba.garbage:C nba.stat_dist:E nba.onoff:X nba.tracking:X",
 "player_other": "nba.minutes:E nba.usage:C nba.injuries_pit:E nba.starters_pit:E nba.stat_dist:E nba.pace:C nba.opp_def_pos:C nba.shot_profile:X",
 "first_event": "nba.starters_pit:E nba.usage:C nba.pace:C nba.shot_profile:X",
 "game_event": "nba.score_resid:C nba.garbage:C nba.ot_model:C",
 "lineup_role": "nba.starters_pit:E nba.injuries_pit:E nba.load_mgmt:C nba.rotation:C",
 "season_outcome": "nba.ratings:E nba.standings_sim:E nba.injuries_pit:C nba.load_mgmt:C nba.news:C",
 "season_stat": "nba.minutes:C nba.usage:C nba.injuries_pit:C nba.standings_sim:C",
 "season_award": "nba.award_stats:E nba.standings_sim:C nba.news:C",
 "off_field": "nba.news:E",
 "combo": "nba.stat_dist:E nba.score_resid:E"},
"CBB": {
 "game_side": "cbb.adj_off:E cbb.adj_def:E cbb.ratings:E cbb.roster_minutes:C cbb.injuries:E cbb.starters:C cbb.venue:E cbb.rest_travel:C cbb.motivation:C cbb.score_resid:E cbb.lineups:X",
 "game_total": "cbb.tempo:E cbb.adj_off:E cbb.adj_def:E cbb.four_factors:C cbb.injuries:E cbb.starters:C cbb.roster_minutes:C cbb.fouls_officials:C cbb.venue:C cbb.score_resid:E cbb.shot_zones:X",
 "period": "cbb.half_split:E cbb.tempo:E cbb.starters:C cbb.adj_off:C cbb.adj_def:C",
 "player_other": "cbb.player_usage:E cbb.injuries:E cbb.starters:E cbb.roster_minutes:E cbb.tempo:C",
 "first_event": "cbb.tempo:C cbb.player_usage:C",
 "game_event": "cbb.tempo:C cbb.score_resid:C",
 "lineup_role": "cbb.starters:E cbb.injuries:E cbb.roster_minutes:C",
 "season_outcome": "cbb.ratings:E cbb.bracket_sim:E cbb.injuries:C cbb.news:C",
 "season_stat": "cbb.player_usage:C",
 "season_award": "cbb.ratings:C cbb.news:C",
 "off_field": "cbb.news:E",
 "combo": "cbb.score_resid:E"},
"NHL": {
 "game_side": "nhl.xg_for:E nhl.xg_against:E nhl.goalie_start:E nhl.goalie_quality:E nhl.injuries_pit:E nhl.lines:C nhl.special_teams:C nhl.rest_travel:C nhl.venue:C nhl.ot_so:E nhl.score_state:C nhl.ratings:C",
 "game_total": "nhl.pace:E nhl.xg_for:E nhl.xg_against:E nhl.goalie_start:E nhl.goalie_quality:E nhl.special_teams:C nhl.injuries_pit:E nhl.lines:C nhl.rest_travel:C nhl.empty_net:C nhl.ot_so:E nhl.period_split:C nhl.officials:X",
 "period": "nhl.period_split:E nhl.goalie_start:E nhl.pace:C nhl.xg_for:C nhl.xg_against:C nhl.score_state:C",
 "player_shots": "nhl.toi:E nhl.shot_rate:E nhl.lines:E nhl.pp_role:E nhl.opp_supp:C nhl.score_state:C nhl.injuries_pit:E nhl.venue:C nhl.stat_dist:E",
 "player_points": "nhl.toi:E nhl.lines:E nhl.pp_role:E nhl.shot_rate:C nhl.finishing:C nhl.assist_rate:C nhl.goalie_start:C nhl.injuries_pit:E nhl.stat_dist:E",
 "goalie_saves": "nhl.goalie_start:E nhl.goalie_quality:E nhl.pace:E nhl.opp_supp:C nhl.score_state:C nhl.stat_dist:E",
 "player_other": "nhl.toi:E nhl.lines:E nhl.injuries_pit:E nhl.stat_dist:C",
 "first_event": "nhl.pace:C nhl.goalie_start:C nhl.lines:C nhl.period_split:C",
 "game_event": "nhl.ot_so:C nhl.score_state:C",
 "lineup_role": "nhl.goalie_start:E nhl.lines:E nhl.injuries_pit:E",
 "season_outcome": "nhl.ratings:E nhl.injuries_pit:C nhl.news:C",
 "season_stat": "nhl.toi:C nhl.shot_rate:C",
 "season_award": "nhl.award_stats:E nhl.news:C",
 "off_field": "nhl.news:E",
 "combo": "nhl.stat_dist:E"},
"MLB": {
 "game_side": "mlb.sp_quality:E mlb.lineup_pit:E mlb.bullpen:E mlb.hitter_quality:E mlb.park:C mlb.weather_pit:C mlb.platoon:C mlb.defense:C mlb.injuries_pit:C mlb.rest_travel:C mlb.run_dist:E mlb.umpire:X",
 "game_total": "mlb.sp_quality:E mlb.lineup_pit:E mlb.bullpen:E mlb.hitter_quality:E mlb.park:E mlb.weather_pit:E mlb.umpire:C mlb.defense:C mlb.run_dist:E mlb.extra_innings:C",
 "period": "mlb.sp_quality:E mlb.f5_split:E mlb.first_inning:C mlb.lineup_pit:E mlb.park:C mlb.weather_pit:C mlb.bullpen:C",
 "player_hit": "mlb.lineup_pit:E mlb.hitter_quality:E mlb.sp_quality:E mlb.platoon:E mlb.batter_vs_pitch:C mlb.park:C mlb.weather_pit:C mlb.umpire:X mlb.pa_sim:E mlb.bullpen:C",
 "player_pitch": "mlb.sp_workload:E mlb.sp_quality:E mlb.pitch_mix:E mlb.lineup_pit:E mlb.umpire:C mlb.park:C mlb.weather_pit:X mlb.pa_sim:E",
 "player_other": "mlb.lineup_pit:E mlb.hitter_quality:C mlb.baserunning:C mlb.pa_sim:E",
 "first_event": "mlb.first_inning:E mlb.sp_quality:E mlb.lineup_pit:E mlb.park:C",
 "game_event": "mlb.run_dist:C mlb.extra_innings:C",
 "lineup_role": "mlb.lineup_pit:E mlb.injuries_pit:E mlb.news:C",
 "season_outcome": "mlb.season_sim:E mlb.injuries_pit:C mlb.news:C",
 "season_stat": "mlb.hitter_quality:C mlb.season_sim:C",
 "season_award": "mlb.season_sim:C mlb.news:C",
 "off_field": "mlb.news:E",
 "combo": "mlb.run_dist:E"},
"SOCCER": {
 "game_side": "soc.ratings:E soc.xg:E soc.lineups_pit:E soc.injuries:E soc.gk:C soc.rest_travel:C soc.motivation:C soc.market_odds:E soc.goal_dist:E soc.weather:X soc.referee:X",
 "game_total": "soc.xg:E soc.ratings:E soc.lineups_pit:E soc.injuries:E soc.pace_press:C soc.gk:C soc.goal_dist:E soc.motivation:C soc.rest_travel:C soc.weather:X soc.referee:X soc.set_pieces:X",
 "period": "soc.period_split:E soc.xg:C soc.lineups_pit:E soc.goal_dist:E soc.pace_press:C",
 "player_other": "soc.player_xg:E soc.lineups_pit:E soc.injuries:E soc.set_pieces:C soc.rest_travel:C",
 "first_event": "soc.xg:C soc.goal_dist:E soc.lineups_pit:C",
 "game_event": "soc.referee:C soc.score_state:C",
 "lineup_role": "soc.lineups_pit:E soc.injuries:E",
 "season_outcome": "soc.comp_sim:E soc.ratings:E soc.injuries:C soc.transfers:C",
 "season_stat": "soc.player_xg:C soc.comp_sim:C",
 "season_award": "soc.player_awards:E soc.comp_sim:C",
 "off_field": "soc.transfers:E",
 "combo": "soc.goal_dist:E"},
"TENNIS": {
 "game_side": "ten.surface_rating:E ten.serve_return:E ten.fitness:E ten.form:C ten.h2h_style:C ten.fatigue:C ten.court_cond:C ten.format:E ten.market_odds:E ten.motivation:X ten.in_play:X",
 "game_total": "ten.hold_break:E ten.serve_return:E ten.format:E ten.set_dist:E ten.surface_rating:C ten.court_cond:C ten.fatigue:C ten.fitness:C",
 "period": "ten.hold_break:E ten.set_dist:E ten.serve_return:C",
 "player_other": "ten.aces_df:E ten.serve_return:E ten.court_cond:C ten.format:E ten.hold_break:C",
 "first_event": "ten.hold_break:C ten.set_dist:C",
 "game_event": "ten.hold_break:E ten.set_dist:E ten.format:E",
 "lineup_role": "ten.fitness:E ten.news:C",
 "season_outcome": "ten.draw:E ten.surface_rating:E ten.fitness:C ten.rankings:C",
 "season_stat": "ten.rankings:E ten.form:C",
 "season_award": "ten.rankings:C",
 "off_field": "ten.news:E",
 "combo": "ten.set_dist:E"}}

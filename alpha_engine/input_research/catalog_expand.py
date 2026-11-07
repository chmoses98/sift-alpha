"""Adjudication of the audit's 85 mechanism-category flags and the resulting catalog corrections (RESEARCH_ONLY).

Every (sport, archetype, missing category) flag from coverage_audit is resolved here with a verdict and a reason; where the mechanism is genuine the correction is applied to the
catalog (attach an existing sport input to the market with a market-specific "why", or add a new input). ``apply()`` is idempotent. Verdicts:
  ATTACHED_EXISTING   the mechanism existed in the sport catalog but was not linked to this market (a linkage gap, not a missing idea)
  NEW_INPUT_ADDED     no input modelled the mechanism: new candidate input defined and attached
  COVERED_OTHER_CAT   the mechanism is modelled by an input filed under a different category; why-text updated so the link is explicit
  FALSE_POSITIVE      the checklist does not apply to this contract (reason given)
Catalog text is a HYPOTHESIS inventory, not evidence. Market-derived inputs are never predictors (see market_dependency.json).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAT = ROOT / "research/input_research/catalog"
OUT = ROOT / "research/input_research/gap_adjudication.json"
A, C, N, F = "ATTACHED_EXISTING", "COVERED_OTHER_CAT", "NEW_INPUT_ADDED", "FALSE_POSITIVE"
ADJ: list[dict] = []


def adj(sport, arch, cat, verdict, reason, attach=()):
    ADJ.append({"sport": sport, "archetype": arch, "category": cat, "verdict": verdict, "reason": reason, "attach": [{"id": i, "role": r, "why": w} for i, r, w in attach]})


def many(sport, archs, cat, verdict, reason, attach):
    for a in archs:
        adj(sport, a, cat, verdict, reason, attach)


# ---------------------------------------------------------------- CBB
adj("CBB", "first_half", "variance_luck", A, "A 20-minute sample is dominated by three-point shooting variance.", [("cbb.three_pt_luck", "secondary", "In a 20-minute half a handful of threes swing the total; a team's 3P% well above its shot-quality expectation regresses, so first-half totals should be priced on shot quality, not the hot hand.")])
many("CBB", ["player_props", "player_points", "player_rebounds_assists", "player_threes"], "game_state", A, "Blowouts and foul-and-free-throw endgames change a player's minutes and shot volume; the blowout input existed but was not linked.",
     [("cbb.blowout_garbage", "secondary", "Lopsided games empty the starters' minutes early; rebuilt from the model's OWN margin forecast (never the spread), blowout probability is the main downside branch of every player counting stat.")])
adj("CBB", "player_points", "game_state", A, "Late-game fouling inflates free-throw points for ball handlers.", [("cbb.late_game_foul_script", "secondary", "Trailing teams foul and leaders' guards shoot the resulting free throws, adding points that a per-minute rate misses; the effect depends on who handles the ball in the final minutes.")])
# ---------------------------------------------------------------- CFB
adj("CFB", "game_moneyline_spread", "matchup", A, "Scheme-versus-scheme matchups were modelled at sport level but not attached to the side markets.",
    [("cfb.pass_rush", "secondary", "A dominant pass rush against a weak line ends drives and shortens the favourite's margin; the matchup term is the rush rate for versus the line's sack rate allowed."), ("cfb.secondary_coverage", "secondary", "Explosive pass offences against thin secondaries produce large margins that efficiency averages understate."),
     ("cfb.run_defense", "secondary", "Run-heavy favourites against weak fronts convert leads into clock; margin distributions skew toward key numbers."), ("cfb.offense_style", "secondary", "Option and tempo offences compress possessions and transfer variance to the underdog, changing cover probability at constant rating gap.")])
adj("CFB", "game_total", "variance_luck", A, "Turnover luck regresses and moves totals.", [("cfb.turnover_luck", "secondary", "Short fields from turnovers inflate points scored; a team's recent turnover margin beyond its fumble-recovery expectation regresses, so totals built on raw scoring carry a luck premium.")])
adj("CFB", "team_total", "matchup", A, "A team total depends on that offence against this defence, not league averages.", [("cfb.offense_style", "secondary", "Style clash sets how many possessions this offence gets and how explosive they are."), ("cfb.secondary_coverage", "secondary", "Explosive-pass allowed rate converts directly into this team's points when its quarterback is the strength.")])
adj("CFB", "quarter_and_half_totals", "availability", A, "Quarterback status changes early-game scripting.", [("cfb.qb_status_pit", "primary", "A backup quarterback changes the opening script and first-half pace; timestamped confirmation is the point-in-time input.")])
adj("CFB", "quarter_and_half_totals", "team_strength", A, "Period scoring is a team-strength problem too; the totals blueprint lacked rating inputs.", [("cfb.off_ppa", "primary", "Opponent-adjusted offence sets expected points per drive in the period."), ("cfb.def_ppa", "primary", "Opponent-adjusted defence sets the opposing points per drive in the period.")])
many("CFB", ["quarter_and_half_totals", "quarter_and_half_sides"], "variance_luck", A, "Short periods amplify turnover luck.", [("cfb.turnover_luck", "secondary", "One early turnover decides a quarter; regressing turnover luck separates repeatable offence from noise in 15-minute sample.")])
adj("CFB", "game_stat_props", "availability", A, "Skill-position availability was catalogued but unattached.", [("cfb.skill_avail", "primary", "A starting receiver or back out redistributes targets and carries; replacement quality sets the stat shift."), ("cfb.injuries", "secondary", "Injury news has no reliable official feed in college football, so timing and source matter more than the designation.")])
adj("CFB", "game_stat_props", "player_role", A, "Role share is the volume driver of every player stat.", [("cfb.player_usage", "primary", "Target, carry and snap share translate team volume into player volume; share changes after injuries are the main source of line error.")])
adj("CFB", "season_futures", "distribution", N, "No input described the distribution of season outcomes (CFP/conference) from schedule and rating uncertainty.", [("cfb.season_sim_distribution", "primary", "Season outcomes are order statistics over a schedule; the simulated distribution, not the point rating, prices playoff and conference markets.")])
# ---------------------------------------------------------------- MLB
adj("MLB", "pitcher_strikeouts", "game_state", C, "Score state affects strikeouts only through when the starter leaves; the hook input models that.", [("mlb.leash", "primary", "Run differential and pitch count drive the early hook that truncates strikeout opportunity.")])
adj("MLB", "pitcher_earned_runs_hits_walks", "distribution", A, "Count outcomes need a distribution, not a mean.", [("mlb.pa_sim", "primary", "A plate-appearance simulation produces the full distribution of hits, walks and earned runs from matchup probabilities."), ("mlb.contact_dist", "secondary", "Counts are over-dispersed; ignoring that mis-prices the tails of ladder thresholds.")])
adj("MLB", "pitcher_earned_runs_hits_walks", "game_state", C, "Same mechanism as strikeouts: the starter's exit time.", [("mlb.leash", "primary", "Exit time bounds the number of batters faced and therefore every count stat.")])
adj("MLB", "hitter_hits_and_total_bases", "game_state", C, "Score state matters through plate appearances and late substitutions.", [("mlb.expected_pa", "primary", "Lineup slot and game script set plate appearances; pinch-hitting and blowout substitution cut them.")])
adj("MLB", "hitter_home_runs", "distribution", A, "Home runs are rare events; the distribution and per-PA simulation matter.", [("mlb.pa_sim", "primary", "Per-PA home-run probability, compounded over expected PAs, gives the any-HR probability; park, wind and pitcher enter per PA."), ("mlb.contact_dist", "secondary", "Barrel-driven hitters have heavier tails than a constant per-PA rate implies.")])
adj("MLB", "hitter_rbis_runs_sb", "game_state", C, "RBI and run opportunities depend on lineup context and game script.", [("mlb.expected_pa", "primary", "Slot, teammates on base and score state set the opportunity count.")])
adj("MLB", "game_moneyline", "matchup", A, "Starter-versus-lineup matchups were catalogued but not attached to the winner market.",
    [("mlb.platoon", "secondary", "The lineup's handedness mix against the starter shifts run expectancy by several percent."), ("mlb.pitch_mix", "secondary", "Starter pitch mix against the lineup's pitch-type weaknesses changes strikeout and contact quality."), ("mlb.lineup_k_platoon", "secondary", "Confirmed-lineup strikeout rate by handedness is the market-free matchup summary available after lineups post.")])
adj("MLB", "first_inning_and_inning_markets", "game_state", C, "First-inning outcomes are batting-order and top-of-lineup exposure problems.", [("mlb.first_inning_splits", "primary", "The first three batters, not the whole lineup, decide the first inning.")])
adj("MLB", "first_inning_and_inning_markets", "variance_luck", A, "Single-inning outcomes are extremely noisy.", [("mlb.babip_luck", "secondary", "BABIP luck in the starter's recent first innings regresses; raw first-inning ERA overstates persistent skill.")])
adj("MLB", "first5_markets", "game_state", C, "First-five markets depend on how deep the starter goes and the times-through-order penalty.", [("mlb.tto", "primary", "Third time through the order raises run expectancy materially, so the starter's expected depth sets the first-five mean.")])
adj("MLB", "first5_markets", "variance_luck", A, "Starters' strand luck distorts small samples.", [("mlb.lob_strand_luck", "secondary", "ERA-minus-FIP gaps from stranding luck regress and mis-price first-five runs.")])
adj("MLB", "extras_and_delay", "variance_luck", F, "Extra-innings and delay markets are event-probability contracts: tie-after-nine distribution and weather timing, not a luck regression on skill.")
adj("MLB", "season_futures", "distribution", N, "No input described the season simulation distribution.", [("mlb.season_sim_distribution", "primary", "Division, wildcard and win-total markets are tails of a schedule simulation with injury and rating uncertainty.")])
adj("MLB", "season_leaders_and_awards", "distribution", N, "Leader races are max-of-N order statistics; none was catalogued for baseball.", [("mlb.leader_order_statistic", "primary", "The probability a player finishes first is the probability his final total exceeds every rival's; correlations and games remaining set it.")])
adj("MLB", "player_participation", "motivation", N, "Resting policy of clinched teams is a distinct mechanism for lineup-participation markets.", [("mlb.clinched_rest_policy", "primary", "Clinched or eliminated teams rest regulars and call up prospects; the policy is manager-specific and timestamped by announcement.")])
adj("MLB", "transactions", "distribution", A, "Reference-class base rates exist for off-field events.", [("mlb.offfield_base_rate", "primary", "Transaction markets are priced from historical frequency by calendar window; deadline proximity drives it.")])
# ---------------------------------------------------------------- NBA
many("NBA", ["player_points", "player_rebounds", "player_assists", "player_threes", "steals_blocks_turnovers", "player_h2h_series_stats"], "game_state", A, "Blowout/garbage time and late-game fouling change minutes and counting stats; both inputs existed.",
     [("nba.garbage", "secondary", "Blowout probability (rebuilt from the model's own margin forecast, not the spread) cuts starters' fourth-quarter minutes, the main downside branch of every counting stat."), ("nba.late_game_script", "secondary", "Close games add intentional-foul possessions and free throws that shift guards' and bigs' stat lines.")])
adj("NBA", "player_free_throws", "pace_volume", A, "Free-throw attempts scale with possessions.", [("nba.pace", "secondary", "More possessions mean more fouls drawn; opponent-adjusted pace scales attempts.")])
adj("NBA", "player_milestones", "game_state", A, "Milestones require sustained minutes.", [("nba.garbage", "secondary", "A blowout ends the chase for a double- or triple-double early.")])
adj("NBA", "player_milestones", "matchup", A, "Opponent stat allowance by position drives the thresholds.", [("nba.opp_def_pos", "secondary", "Opponent allowance by position shifts rebound and assist expectations toward or away from the milestone.")])
adj("NBA", "player_milestones", "pace_volume", A, "Possessions create rebound and assist chances.", [("nba.pace", "secondary", "Pace scales every component of a double-double.")])
adj("NBA", "game_moneyline_spread", "matchup", A, "Scheme matchups were catalogued but not linked to the side market.", [("nba.def_scheme", "secondary", "Drop versus switch schemes against pick-and-roll-heavy offences change efficiency at equal ratings."), ("nba.matchup_def", "secondary", "Star-versus-defender matchups matter more in the playoffs than in the regular season.")])
adj("NBA", "game_win_margin", "matchup", A, "Margin distributions depend on style clash.", [("nba.def_scheme", "secondary", "Scheme clashes widen or narrow the margin distribution around the same expected spread.")])
adj("NBA", "game_total", "matchup", A, "Totals depend on how shot profiles meet defensive schemes.", [("nba.def_scheme", "secondary", "Rim-protecting schemes against rim-heavy offences lower totals relative to ratings."), ("nba.shot_profile", "secondary", "Three-point-heavy offences against drop schemes raise expected points per possession.")])
adj("NBA", "game_overtime_and_team_events", "team_strength", A, "Team events (first to 10, overtime) still depend on team quality.", [("nba.off_rtg", "primary", "Offensive rating sets scoring pace for race-to markets."), ("nba.def_rtg", "primary", "Defensive rating sets the opposing pace.")])
adj("NBA", "game_overtime_and_team_events", "variance_luck", A, "Three-point variance drives close finishes.", [("nba.three_pt_luck", "secondary", "Close-game and overtime frequency is driven by shooting variance a rating cannot predict.")])
adj("NBA", "off_court_events", "distribution", N, "No base-rate input for NBA off-court events existed (other sports had one).", [("nba.offfield_base_rate", "primary", "Franchise-sale, relocation and rule-change markets are priced from reference-class frequencies and announcement calendars.")])
adj("NBA", "player_escalator_payout", "team_strength", A, "Team strength drives minutes and pace, which scale payout ladders.", [("nba.ratings", "secondary", "A strong team's blowout wins cap minutes; a weak team's lead role raises usage.")])
# ---------------------------------------------------------------- NFL
adj("NFL", "anytime_first_td_scorer", "pace_volume", A, "Scoring opportunities scale with plays and red-zone trips.", [("nfl.pace", "secondary", "Plays per game set the number of scoring chances."), ("nfl.proe", "secondary", "Pass rate over expected sets the split of scoring chances between receivers and rushers."), ("nfl.drives", "secondary", "Expected drives set red-zone trip counts.")])
adj("NFL", "game_moneyline_spread", "matchup", A, "Matchups were catalogued but not attached to the side market.", [("nfl.pass_rush", "secondary", "Pass-rush win rate against pass-block quality is the largest single matchup in the side market."), ("nfl.coverage_scheme", "secondary", "Coverage shell against the offence's route concepts shifts expected passing efficiency."), ("nfl.run_defense", "secondary", "Run defence against a run-led offence decides time of possession."), ("nfl.coaching", "secondary", "Fourth-down aggression and tempo tendencies change variance.")])
adj("NFL", "game_total", "matchup", A, "Total depends on how the two units meet.", [("nfl.pass_rush", "secondary", "Pressure shortens drives and lowers totals."), ("nfl.coverage_scheme", "secondary", "Soft shells concede completions and add scoring."), ("nfl.run_defense", "secondary", "Run defence controls clock and drive length.")])
adj("NFL", "team_total", "matchup", A, "A team total is one offence against one defence.", [("nfl.coverage_scheme", "secondary", "The opposing coverage shell sets this offence's passing efficiency."), ("nfl.run_defense", "secondary", "Run defence caps the ground game."), ("nfl.pass_rush", "secondary", "Pressure against this offensive line cuts scoring.")])
adj("NFL", "first_half_and_quarter_totals", "availability", A, "Starting quarterback and key availability change scripting.", [("nfl.qb", "primary", "A backup quarterback changes early scripting and pace."), ("nfl.injuries_pit", "primary", "Timestamped designations determine who is actually on the field.")])
adj("NFL", "first_half_and_quarter_totals", "team_strength", A, "Period scoring still needs team ratings.", [("nfl.off_epa", "primary", "Offensive efficiency per play."), ("nfl.def_epa", "primary", "Defensive efficiency per play.")])
adj("NFL", "first_half_and_quarter_totals", "variance_luck", A, "Short periods amplify touchdown luck.", [("nfl.td_luck", "secondary", "A quarter holds only a few scoring drives; touchdown conversion luck regresses and moves period totals.")])
adj("NFL", "player_availability", "schedule_context", A, "Rest and bye timing affect designations and participation.", [("nfl.rest_travel", "secondary", "Short weeks and byes change practice participation and the odds a questionable player plays.")])
adj("NFL", "season_win_totals_and_futures", "distribution", N, "No input described the schedule simulation distribution.", [("nfl.season_sim_distribution", "primary", "Win totals and division markets are tails of a 17-game schedule simulation with injury and rating uncertainty.")])
adj("NFL", "season_awards", "distribution", A, "Award races are order statistics.", [("nfl.leader_order_statistic", "primary", "The chance a candidate finishes first is the chance his final production plus narrative exceeds every rival's.")])
adj("NFL", "season_awards", "player_role", C, "Award candidates' production is the quarterback/skill efficiency stack.", [("nfl.qb_efficiency", "primary", "For quarterback-dominated awards, efficiency and volume to date are the production leg of voting."), ("nfl.fantasy_points_model", "secondary", "Translates role and volume into a comparable production score across positions.")])
adj("NFL", "game_events", "game_state", A, "Game events (safeties, ties, first scores) depend on script and state.", [("nfl.script", "primary", "Script lattices give the probability of each state a rare event needs."), ("nfl.opening_script", "secondary", "Scripted opening drives drive first-score events.")])
adj("NFL", "off_field_events", "distribution", N, "No base-rate input for NFL off-field events existed.", [("nfl.offfield_base_rate", "primary", "Coach firings, trades and announcements are priced from historical frequency by calendar window.")])
# ---------------------------------------------------------------- NHL
adj("NHL", "game_total_and_team_total", "matchup", A, "Shot-suppression and location matchups drive totals.", [("nhl.opp_supp", "secondary", "Opponent shot suppression sets expected attempts."), ("nhl.shot_location", "secondary", "Danger-zone mix converts attempts to goals.")])
adj("NHL", "period_markets", "variance_luck", A, "Period goal counts are dominated by finishing luck.", [("nhl.pdo_regression", "secondary", "A team's shooting and save percentage beyond expectation regress; period markets inherit the noise.")])
adj("NHL", "game_events", "variance_luck", A, "Rare events inherit finishing noise.", [("nhl.pdo_regression", "secondary", "Team PDO (shooting plus save percentage) luck regresses, so rare-event counts inherit noise a rating cannot predict."), ("nhl.finishing", "secondary", "Finishing talent versus luck separates repeatable shooting from variance in rare-event counts.")])
adj("NHL", "season_futures", "distribution", N, "No season simulation distribution input existed.", [("nhl.season_sim_distribution", "primary", "Points and playoff markets are tails of an 82-game simulation with overtime-point rules and injury uncertainty.")])
adj("NHL", "season_awards_and_stats", "distribution", A, "Season stats need count distributions.", [("nhl.stat_dist", "primary", "Season totals are sums of over-dispersed per-game counts.")])
adj("NHL", "player_h2h", "game_state", A, "Head-to-head player stats depend on score state and deployment.", [("nhl.score_state", "secondary", "Trailing teams shoot more; leading teams protect leads, shifting both players' volume.")])
# ---------------------------------------------------------------- SOCCER
adj("SOCCER", "match_result_3way", "game_state", F, "Pregame full-time result is not conditioned on in-play state; live markets are a separate contract type that this catalog does not yet model (recorded as a coverage gap).")
adj("SOCCER", "total_goals", "variance_luck", A, "Goal totals are dominated by finishing and goalkeeping variance.", [("soc.finishing_regression", "secondary", "Over- or under-performance against xG regresses, so totals should use xG not goals."), ("soc.keeper_shot_stopping_regression", "secondary", "Goalkeeper save luck regresses.")])
adj("SOCCER", "first_half_and_period", "variance_luck", A, "A 45-minute sample amplifies finishing luck.", [("soc.finishing_regression", "secondary", "First-half goals are rare events; finishing luck dominates.")])
adj("SOCCER", "soccer_special_and_host", "distribution", N, "No reference-class base-rate input for soccer announcements existed.", [("soc.offfield_base_rate", "primary", "Appointment, transfer and host markets are priced from historical frequency by calendar window.")])
adj("SOCCER", "player_award", "distribution", N, "Award votes need a distribution over candidates.", [("soc.award_vote_distribution", "primary", "Panel awards are decided by vote shares; narrative and team success set the distribution.")])
# ---------------------------------------------------------------- TENNIS
adj("TENNIS", "match_winner", "game_state", F, "Pregame winner is not conditioned on in-play state; in-play is a separate archetype (game_winner_inplay).")
adj("TENNIS", "set_winner_and_any_set", "availability", A, "Withdrawal and retirement risk change set markets.", [("ten.withdrawal_signals", "primary", "Practice and press signals precede in-match retirements that truncate sets.")])
adj("TENNIS", "set_winner_and_any_set", "pace_volume", A, "Expected number of service games drives set outcomes.", [("ten.match_length_expectation", "secondary", "More service games raise the chance a set reaches a tiebreak.")])
adj("TENNIS", "total_games_and_sets", "matchup", A, "Return style and rally length shape games per set.", [("ten.return_style_rally", "secondary", "Strong returners create breaks, shortening sets; rallying styles lengthen them.")])
adj("TENNIS", "total_games_and_sets", "pace_volume", A, "Serve volume sets games.", [("ten.match_length_expectation", "primary", "Expected service games per set sets the games count."), ("ten.first_serve", "secondary", "First-serve effectiveness drives hold rates.")])
adj("TENNIS", "total_games_and_sets", "variance_luck", A, "Break-point luck swings set lengths.", [("ten.break_point_luck", "secondary", "Break-point conversion beyond expectation regresses.")])
adj("TENNIS", "exact_set_score", "game_state", F, "Pregame exact set score depends on the set distribution, not in-play state.")
adj("TENNIS", "exact_set_score", "pace_volume", A, "Match length drives which exact score arises.", [("ten.match_length_expectation", "secondary", "Expected games per set shifts the mass between straight sets and deciders.")])
adj("TENNIS", "set_sweep_and_tiebreak_events", "game_state", C, "Sweep and tiebreak probabilities come from the within-match dependence model.", [("ten.within_match_dependence", "primary", "Momentum across sets sets sweep probability.")])
adj("TENNIS", "set_sweep_and_tiebreak_events", "variance_luck", A, "Break-point luck drives tiebreaks.", [("ten.break_point_luck", "secondary", "Break luck regresses and moves tiebreak counts.")])
adj("TENNIS", "player_aces_and_double_faults", "distribution", N, "Ace counts need an over-dispersed count distribution; none was catalogued.", [("ten.ace_count_distribution", "primary", "Aces are counts over service points with surface and opponent-return dependence; a negative-binomial with per-point probability prices the ladder.")])
adj("TENNIS", "player_aces_and_double_faults", "game_state", F, "Pregame ace counts are not conditioned on in-play state.")
adj("TENNIS", "season_ranking_and_majors", "distribution", N, "No simulation of ranking points existed.", [("ten.ranking_points_simulation", "primary", "Rank and major-count markets are tails of points accumulated over a tournament calendar.")])

NEW_INPUTS = {
 "CFB": {"cfb.season_sim_distribution": ("distribution", "Season simulation distribution (CFP, conference title, win totals)", "Season outcomes are order statistics of a simulated schedule with rating uncertainty, injury risk and committee rules.", "Point ratings answer who is better; futures markets ask for the probability of a rank or title, which needs the simulated distribution including tiebreakers, conference championship games and the committee's ranking behaviour. Subtle: correlated outcomes (two teams in one conference) matter for head-to-head and top-N markets.", "Monte Carlo of the remaining schedule using own power ratings with rating uncertainty (Bayesian updating after each game), conference tiebreaker rules and a committee-ranking model fitted to past rankings; report rank and title probabilities.", "yes", ["collegefootballdata.com API (schedule, results)", "Sports-reference CFB schedules"])},
 "MLB": {"mlb.season_sim_distribution": ("distribution", "Season simulation distribution (division, wildcard, win totals)", "Playoff and win-total markets are tails of a 162-game simulation with rating and injury uncertainty.", "A team's rating gives a mean win total; the market asks for tail probabilities that depend on schedule, correlation within divisions and injury attrition. Subtle: late-season motivation and resting change the last games.", "Monte Carlo of remaining games from own run-differential ratings (Pythagorean/BaseRuns shrunk), home advantage, starting-pitcher rotation uncertainty and tiebreaker rules; output win-total and playoff probabilities.", "yes", ["MLB StatsAPI schedule and standings (statsapi.mlb.com)", "Baseball-Reference standings"]),
         "mlb.leader_order_statistic": ("distribution", "Leader-race order statistic (home runs, strikeouts, batting titles)", "The probability of leading is the chance a player's final total exceeds every rival's.", "Season-leader markets are max-of-N problems; to-date totals, games remaining, per-game rate variance and rival correlations (same park/schedule) set the probability. A projection of the mean is not enough: variance and the gap to the second place decide.", "Simulate each contender's remaining games from rate × playing-time distributions with injury hazards; compute the share of simulations in which he finishes first including ties.", "yes", ["MLB StatsAPI leaderboards and game logs", "Baseball-Reference/FanGraphs splits"]),
         "mlb.clinched_rest_policy": ("motivation", "Clinched/eliminated rest and call-up policy", "Teams with nothing to play for rest regulars and give opportunities to prospects.", "Participation and counting-stat markets for regulars in the final weeks depend on the manager's historical behaviour once seeding is decided. The announcement is timestamped by lineup posting. Subtle: policy varies by manager and by whether a bye is at stake.", "Per manager and season-state: share of regular starters sitting after clinch/elimination, by days remaining and bye status; compare with the lineup posted at decision time.", "partial", ["MLB StatsAPI lineups and standings", "Baseball-Reference game logs by manager"])},
 "NBA": {"nba.offfield_base_rate": ("distribution", "Reference-class base rates for NBA off-court events", "Franchise, rule and personnel events occur at historical frequencies tied to the calendar.", "These contracts cannot be modelled from game data; the honest prior is the frequency of the event class by calendar window, updated by dated reporting. Subtle: markets often over-price dramatic events relative to base rates.", "Count events of the class per season and calendar window from news archives and league announcements; shrink with an empirical-Bayes prior; record the announcement timestamp.", "partial", ["NBA.com transactions and league announcements", "Wikipedia event timelines (as an index, verify against primary sources)"])},
 "NFL": {"nfl.season_sim_distribution": ("distribution", "Season simulation distribution (win totals, division, seeding)", "Season markets are tails of a 17-game schedule simulation with rating, injury and tiebreak uncertainty.", "The mean win total is not the market quantity: division and seed probabilities depend on schedule order, divisional correlation, tiebreakers and the chance of a key injury. Subtle: single games are high-variance so team ratings must carry uncertainty.", "Monte Carlo of remaining games from own ratings with posterior uncertainty, injury-state hazards for the starting quarterback, and full NFL tiebreaker rules; report win-total, division and seed distributions.", "yes", ["nflverse schedules and results", "Pro-Football-Reference tiebreaker documentation"]),
         "nfl.offfield_base_rate": ("distribution", "Reference-class base rates for NFL off-field events", "Coach firings, trades and announcements occur at historical frequencies by calendar window.", "Off-field markets (coach out, hire, trade) are not game-model problems; the prior is the historical frequency conditional on record, ownership and calendar, updated by dated reporting.", "Count event classes per season and week-of-year from transactions archives; condition on team record and tenure; shrink; store the announcement timestamp.", "partial", ["nflverse transactions-adjacent data (players/rosters)", "Pro-Football-Reference coaching records"])},
 "NHL": {"nhl.season_sim_distribution": ("distribution", "Season simulation distribution (points, playoffs, division)", "Season markets are tails of an 82-game simulation including overtime-point rules and injury uncertainty.", "NHL standings points are 2-1-0 with overtime-loss points, so points markets need a bivariate result model, not just win probability. Subtle: goalie injuries and back-to-back starts alter win probability game by game.", "Monte Carlo from own expected-goals ratings with goalie-state uncertainty, regulation/overtime split and wildcard tiebreakers; report points and playoff distributions.", "yes", ["NHL API schedule and standings (api-web.nhle.com)", "Natural Stat Trick / Moneypuck public tables"])},
 "SOCCER": {"soc.offfield_base_rate": ("distribution", "Reference-class base rates for soccer appointments, transfers and hosts", "Announcement markets are priced from historical frequency conditional on calendar windows.", "Manager, transfer and host markets depend on windows (transfer deadlines, tournament cycles) and club circumstances, which a base-rate model captures better than game data.", "Event counts per window and club state (position in table, tenure) from transfer and manager-change archives, shrunk, with announcement timestamps.", "partial", ["Transfermarkt public pages (check terms)", "Football-data.co.uk team results as context"]),
            "soc.award_vote_distribution": ("distribution", "Award vote-share distribution (Ballon d'Or, golden boot, panel awards)", "Panel awards are decided by vote shares driven by team success and narrative.", "Award markets need a distribution across candidates: production to date, team trophies and media narrative interact; prior-year voting predicts next year's ranking. Subtle: tournament years shift weight to international performance.", "Fit a conditional-logit on historical winners with production, team success and prior-vote features; output probabilities per candidate with uncertainty.", "partial", ["FBref player production tables", "Public voting results archives"])},
 "TENNIS": {"ten.ace_count_distribution": ("distribution", "Ace and double-fault count distribution", "Counts over service points are over-dispersed and depend on surface and the opponent's return.", "Ace ladder markets need the whole count distribution; per-point ace probability by surface and opponent, number of service points (set length) and within-match dependence set it. Subtle: tiebreaks add service points.", "Negative-binomial or beta-binomial over expected service points with per-point ace probability from opponent-adjusted serve and return data by surface.", "yes", ["Jeff Sackmann tennis_atp/tennis_wta match stats (w_ace, w_df, w_svpt)", "tennis-data.co.uk results"]),
            "ten.ranking_points_simulation": ("distribution", "Ranking-points simulation over the tournament calendar", "Rank and major-count markets are tails of points accumulated over a calendar of tournaments.", "A player's rank depends on points defended and available at each event; the calendar structure (points dropping off after 52 weeks) is deterministic, outcomes are not. Subtle: injuries and withdrawals dominate the lower tail.", "Simulate remaining tournaments from own rating, entry probability and draw difficulty; track points added and dropped; output rank and major-count distributions.", "partial", ["ATP/WTA rankings history (Sackmann rankings files)", "Official calendars"])},
}


# Corrections to catalog source claims found by source_verify (measured, not assumed)
SOURCE_CORRECTIONS = {
    ("SOCCER", "soc.referee"): ("football-data.co.uk", "football-data.co.uk historical CSVs: the Referee column is populated ONLY in the Premier League (E0) files (measured 2015/16-2025/26: E0 100%, La Liga, Bundesliga, Serie A and Ligue 1 0%); other leagues need another referee source (not yet found free)"),
    ("SOCCER", "soc.fouls_cards"): ("football-data.co.uk", "football-data.co.uk historical CSVs: team fouls and yellow/red cards are complete (measured 99.9-100% for all five leagues 2015/16-2025/26); referee attribution only for E0"),
}


def _load(sp):
    return json.loads((CAT / f"{sp}.json").read_text())


def _save(sp, d):
    (CAT / f"{sp}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")


def apply() -> dict:
    by_sport: dict[str, list] = {}
    for a in ADJ:
        by_sport.setdefault(a["sport"], []).append(a)
    added_inputs = added_links = 0
    for sp, items in by_sport.items():
        d = _load(sp)
        for iid, (cat, label, mech, rat, meas, pit, src) in NEW_INPUTS.get(sp, {}).items():
            if iid not in d["inputs"]:
                d["inputs"][iid] = {"label": label, "category": cat, "mechanism": mech, "rationale": rat, "measurement": meas, "pregame_knowable": pit, "free_sources": src, "registry_ids": []}
                added_inputs += 1
        for a in items:
            arch = d["archetypes"][a["archetype"]]
            have = {i["id"]: i for i in arch["inputs"]}
            for att in a["attach"]:
                assert att["id"] in d["inputs"], (sp, att["id"])
                if att["id"] in have:
                    if have[att["id"]]["why"] != att["why"] and a["verdict"] == C:
                        have[att["id"]]["why"] = att["why"]
                    continue
                arch["inputs"].append({"id": att["id"], "why": att["why"], "role": att["role"]}); added_links += 1
        for (csp, iid), (prefix, new) in SOURCE_CORRECTIONS.items():
            if csp == sp:
                fs = d["inputs"][iid]["free_sources"]
                d["inputs"][iid]["free_sources"] = [new if x.startswith(prefix) else x for x in fs] if any(x.startswith(prefix) for x in fs) else [new] + fs
        _save(sp, d)
    OUT.write_text(json.dumps({"schema_version": "gap-adjudication-1.0", "status": "RESEARCH_ONLY", "n_flags": len({(a["sport"], a["archetype"], a["category"]) for a in ADJ}), "n_adjudications": len(ADJ), "adjudications": ADJ}, indent=0))
    return {"inputs_added": added_inputs, "links_added": added_links, "flags": len(ADJ)}


if __name__ == "__main__":
    print(apply())

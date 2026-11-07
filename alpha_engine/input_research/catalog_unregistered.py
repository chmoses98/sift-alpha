"""Archetypes for contract types that are LISTED ON KALSHI but have no family in the registry (found by universe_reconcile). RESEARCH_ONLY hypotheses.

Stored under ``unregistered_archetypes`` in each sport catalog (not ``archetypes``, whose families must exist in the registry), with the contract titles they cover, so the
dashboard shows them as "listed, not yet registered" instead of hiding them. Registering the families and verifying contract rules remains open.
"""
from __future__ import annotations

import json

from .catalog_expand import CAT

I = lambda i, r, w: {"id": i, "role": r, "why": w}
X = lambda a, b, h: {"inputs": [a, b], "hypothesis": h}

NEW_INPUTS = {
 "SOCCER": {
  "soc.player_shot_share": ("player_role", "Player shot and shot-on-target share of team volume", "A player's shots are a share of team shots driven by role, set-piece duty and position in the attack.", "Shots, shots-on-target and goalscorer markets convert team volume into player volume through share; share is stable within a role but jumps when a teammate is absent or a penalty taker changes. Subtle: share must be measured per minute played and net of penalties.", "Shots and SOT per 90 and share of team shots, split open play / set pieces / penalties, with minutes-weighted shrinkage toward the position mean; recompute with the confirmed lineup.", "yes", ["FBref player shooting tables (Opta-sourced)", "football-data.co.uk team shots and shots on target (team level)"]),
  "soc.opp_shot_profile_by_zone": ("matchup", "Opponent shots and chances conceded by zone and position", "Defences concede shots in specific zones and to specific positions; a striker's chances depend on where the opponent is weak.", "A defence that concedes wide crosses favours target men; one that concedes through-balls favours runners. Matching player shot zones to the opponent's conceded zones sharpens player props beyond team strength.", "Shots and xG conceded per 90 by zone and by attacker position, opponent-adjusted, shrunk by matches played.", "partial", ["FBref team shot-creation and conceded tables", "Understat shot location data (check terms)"]),
  "soc.keeper_workload": ("pace_volume", "Expected shots-on-target faced by the goalkeeper", "Saves are shots on target faced times save probability.", "Goalkeeper saves markets are a count driven by opponent shot volume and quality and the keeper's own stopping skill, shrunk heavily because save percentage is noisy.", "Expected SOT faced from both teams' shot-on-target generation and game state; multiply by shrunk save probability (PSxG-based) to price the count distribution.", "yes", ["football-data.co.uk team shots on target (HST/AST)", "FBref goalkeeper tables"]),
 },
 "CFB": {"cfb.award_vote_distribution": ("distribution", "Award vote-share distribution (Heisman and conference awards)", "Awards are decided by voter shares driven by production, team success and narrative.", "Heisman-style markets need a probability distribution over candidates; quarterbacks on top-ranked teams dominate, and late-season games weigh more. Subtle: voting is regionally clustered and respects a candidate's bowl/CFP stage only in some years.", "Conditional-logit on historical winners and finalists with production percentile, team rank, prime-time exposure and position; calibrate by season.", "partial", ["Heisman Trust voting history (public)", "collegefootballdata.com player production"])},
 "CBB": {"cbb.poll_voter_behavior": ("other", "AP/coaches poll voter behaviour and rank-change dynamics", "Poll ranks move with results and narrative in patterned ways.", "Markets on who is ranked #1 or how many teams hold the top spot depend on voters' reactions to losses and ranking inertia; strong teams losing to unranked opponents drop less than weak ones. Subtle: ties in the poll and week-of-season effects.", "Historical week-over-week rank transitions conditional on result type, opponent rank and margin; fit an ordered-response model.", "partial", ["AP poll archives (public)", "Sports-reference CBB poll history"])},
}
ARCH = {
 "SOCCER": {
  "player_goal_assist_props": {"label": "Soccer player goals, assists, hat tricks and score-or-assist", "blueprint": "player_other", "contract_types": ["Anytime/First goalscorer", "Goals scored", "Hat trick", "Assists", "Score or assist"],
    "target": "A named player scores (or assists) at least once, or a count threshold, in a match; regulation per contract rules.",
    "mechanism": "Player scoring is team expected goals times the player's share of chances times minutes, adjusted for penalty duty and opponent defensive weaknesses. Lineup confirmation about an hour before kickoff is the decisive information: the same player's probability changes by multiples if he is dropped or moves position. Over-dispersion and correlation with team goals matter for hat tricks and multi-leg combinations.",
    "inputs": [I("soc.player_xg", "primary", "Per-90 xG and xA with minutes shrinkage is the base scoring rate."), I("soc.player_shot_share", "primary", "Share of team shots by role and set-piece duty converts team expected goals into player expected goals."),
              I("soc.lineups_pit", "primary", "Confirmed starters and positions about an hour before kickoff decide whether the player plays and where."), I("soc.player_minutes_expectation", "primary", "Expected minutes and substitution risk scale every count."),
              I("soc.penalty_taker_status", "primary", "Penalty duty adds roughly 0.76 expected goals per penalty awarded, concentrated in one player."), I("soc.penalty_rate", "secondary", "Team and referee penalty-award rates set how often penalty duty matters."),
              I("soc.xg_adjusted_ratings", "secondary", "Opponent- and venue-adjusted team xG sets the team's goal expectation."), I("soc.opp_shot_profile_by_zone", "secondary", "Opponent's conceded zones match the player's shot zones."),
              I("soc.gk", "secondary", "Opposing goalkeeper quality shifts conversion."), I("soc.finishing_regression", "secondary", "Finishing over-performance regresses, so use xG not goals."), I("soc.rotation_index", "secondary", "Predicted rotation changes starter probability before lineups are published.")],
    "interactions": [X("soc.penalty_taker_status", "soc.referee", "A penalty taker's goal probability rises when the referee awards penalties at a high rate."), X("soc.player_shot_share", "soc.formation", "Formation changes redistribute shot share among forwards and wingers."), X("soc.lineups_pit", "soc.opp_shot_profile_by_zone", "A positional move changes which conceded zone the player faces.")]},
  "player_shots_saves_props": {"label": "Soccer player shots, shots on target and goalkeeper saves", "blueprint": "player_other", "contract_types": ["Player shots", "Team shots", "Goalkeeper saves"],
    "target": "A player's shot or shot-on-target count, or a goalkeeper's saves, relative to a threshold.",
    "mechanism": "Shot counts are team shot volume times the player's share times minutes, shaped by game state (trailing teams shoot more) and the opponent's block and press profile. Goalkeeper saves are the opponent's shots on target times the keeper's save probability, which is noisy and must be shrunk. Both are over-dispersed counts and depend on the confirmed lineup.",
    "inputs": [I("soc.shots", "primary", "Team shots and SOT for and against set the volume to be shared."), I("soc.player_shot_share", "primary", "Player share by role converts team volume to player volume."), I("soc.lineups_pit", "primary", "Confirmed lineup fixes who plays and in which role."),
              I("soc.player_minutes_expectation", "primary", "Minutes scale counts."), I("soc.keeper_workload", "primary", "Expected SOT faced is the keeper-saves volume."), I("soc.gk", "secondary", "Keeper quality (PSxG minus goals allowed) shrunk toward average."),
              I("soc.pace_press", "secondary", "Pressing and tempo change shot volume."), I("soc.score_state", "secondary", "Trailing teams shoot more; leading teams concede more shots."), I("soc.opp_shot_profile_by_zone", "secondary", "Opponent block and zone profile changes shot conversion to SOT."),
              I("soc.formation", "secondary", "Formation changes who takes shots.")],
    "interactions": [X("soc.shots", "soc.score_state", "Shot volume is convex in expected deficit: heavy underdogs concede many shots while taking few, changing both player and keeper counts."), X("soc.keeper_workload", "soc.gk", "Keeper saves depend on volume times shrunk skill; volume dominates unless skill is extreme."), X("soc.player_shot_share", "soc.lineups_pit", "A teammate's absence raises shot share in a position-specific way.")]},
  "corners_and_cards_team_events": {"label": "Soccer corners, cards and fouls", "blueprint": "game_total", "contract_types": ["Team corners", "Total corners", "Cards", "Fouls"],
    "target": "Count of corners, cards or fouls in a match relative to a threshold.",
    "mechanism": "Corners follow territorial pressure, wing play and blocked shots; cards and fouls follow referee tendencies, derby intensity, tackle volume and score state. Both are over-dispersed counts that correlate with possession and game state. The referee appointment is announced days ahead and is the single most informative card input.",
    "inputs": [I("soc.corners", "primary", "Team corners for and against per 90, opponent-adjusted, are the base rate."), I("soc.fouls_cards", "primary", "Team and player foul and card rates are the base of card markets."), I("soc.referee", "primary", "Referee card and penalty tendencies are the largest known card driver and are published in advance."),
              I("soc.pace_press", "secondary", "Pressing intensity creates fouls and turnovers."), I("soc.formation", "secondary", "Wide formations generate corners and crosses."), I("soc.rivalry_intensity", "secondary", "Derbies raise fouls and cards."), I("soc.stakes_leverage", "secondary", "High-stakes matches raise cards."),
              I("soc.score_state", "secondary", "Trailing teams earn corners; late leads add time-wasting cards."), I("soc.set_piece_matchup", "secondary", "Set-piece attack versus defence shifts corner-to-goal conversion."), I("soc.var_intervention_rate", "secondary", "VAR reviews add stoppage and cards."), I("soc.added_time", "secondary", "Added time lengthens the window for corners and cards.")],
    "interactions": [X("soc.referee", "soc.rivalry_intensity", "A card-happy referee in a derby compounds the baseline."), X("soc.corners", "soc.score_state", "Corners cluster in the trailing team's spell, so the mean is conditional on the expected score path."), X("soc.pace_press", "soc.fouls_cards", "High-press teams commit tactical fouls that referees punish unevenly.")]},
 },
 "NFL": {"team_and_event_counting_specials": {"label": "NFL team and event counting specials", "blueprint": "game_event", "contract_types": ["Team 1st downs", "Field goals", "Interceptions", "Safeties", "Ties", "Largest lead", "Sacks", "Non-QB passes", "2-point conversions"],
    "target": "A team or game count (first downs, field goals, interceptions, sacks) or a rare event (safety, tie, largest lead) relative to a threshold.",
    "mechanism": "Team counts are plays times a rate: first downs follow plays and success rate, field goals follow stalled drives inside the kicker's range, interceptions follow dropbacks times interception rate under pressure, sacks follow dropbacks and the pass-rush/protection matchup. Rare events (safeties, ties, large leads) are tail probabilities of the score-path distribution and depend on weather, pace and variance rather than on mean efficiency.",
    "inputs": [I("nfl.pace", "primary", "Plays per game bound every count."), I("nfl.drives", "primary", "Expected drives set opportunities for field goals and turnovers."), I("nfl.success_rate", "primary", "Success rate drives first downs."), I("nfl.kicker", "primary", "Kicker range and accuracy price field-goal counts."),
              I("nfl.redzone", "secondary", "Red-zone conversion decides field goal versus touchdown."), I("nfl.int_rate", "primary", "Quarterback interception rate decomposition."), I("nfl.pass_rush", "primary", "Pressure drives sacks and interceptions."), I("nfl.turnovers", "secondary", "Turnover regression."),
              I("nfl.safety_risk", "primary", "Safety and special-play event risk."), I("nfl.script", "secondary", "Game script lattice sets pass volume and lead sizes."), I("nfl.garbage_time", "secondary", "Blowout mass drives largest-lead markets (rebuilt from own margin forecast)."), I("nfl.ot_model", "secondary", "Overtime and tie probability."),
              I("nfl.weather_pit", "secondary", "Wind and cold depress passing and kicking."), I("nfl.penalties", "secondary", "Flags extend drives and change first-down counts."), I("nfl.officials_crew", "secondary", "Crew tendencies change penalties and tempo.")],
    "interactions": [X("nfl.pass_rush", "nfl.int_rate", "Pressure raises interception rate most for quarterbacks with high pressure-to-sack conversion."), X("nfl.weather_pit", "nfl.kicker", "Wind compresses effective kicking range, shifting field-goal attempts to go-for-it decisions."), X("nfl.script", "nfl.pace", "Trailing teams pass more and run more plays, raising first downs and sacks together.")]}},
 "NBA": {"team_and_player_counting_specials": {"label": "NBA player/team counting specials (triple doubles, stat averages, one-off thresholds)", "blueprint": "player_other", "contract_types": ["Player triple double", "Player stat average", "Highest-scoring performance", "Players to make one three", "Combo ladders"],
    "target": "A player or team reaching a single-game milestone or a season average threshold.",
    "mechanism": "Milestones are joint events across stat components driven by minutes, usage and role; their probability is a tail of a covariance-aware distribution, not a product of marginals. Season-average and extreme-performance markets add a long-horizon component: availability, minutes trajectory and the variance of single-game performance.",
    "inputs": [I("nba.milestone_rates", "primary", "Base rates for double- and triple-doubles by role and minutes."), I("nba.stat_dist", "primary", "Per-stat count distributions with overdispersion."), I("nba.combo_covariance", "primary", "Covariance between stat components shapes joint events."), I("nba.minutes", "primary", "Minutes distribution is the common driver."),
              I("nba.usage", "secondary", "Usage drives scoring and assist components."), I("nba.pace", "secondary", "Possessions scale every component."), I("nba.garbage", "secondary", "Blowout risk truncates milestone chases (rebuilt market-free)."), I("nba.opp_def_pos", "secondary", "Opponent allowance by position."),
              I("nba.three_volume", "secondary", "Three-point attempts for make-one-three thresholds."), I("nba.player_shooting_regression", "secondary", "Shooting luck regresses."), I("nba.injuries_pit", "secondary", "Availability and minutes restrictions."), I("nba.rotation", "secondary", "Rotation patterns shape minutes.")],
    "interactions": [X("nba.minutes", "nba.usage", "Usage matters only with minutes; the product drives all components together."), X("nba.combo_covariance", "nba.pace", "Higher pace raises all components but correlates rebounds and assists with scoring, widening the joint tail."), X("nba.garbage", "nba.milestone_rates", "Blowout probability cuts milestone completion for stars more than for role players.")]}},
 "MLB": {"player_and_team_counting_specials": {"label": "MLB player/team counting specials (stolen bases, walks, outs recorded, earned runs, next home run)", "blueprint": "player_hit", "contract_types": ["Stolen bases", "Walks", "Outs recorded", "Earned runs", "Games played", "Next homerun", "Team stats"],
    "target": "A counting stat for a player or team over a game or season relative to a threshold, or which player does an event next.",
    "mechanism": "Counts are plate appearances (or batters faced) times per-PA probabilities with matchup adjustments; stolen bases add catcher and pitcher hold-time effects, walks add umpire zone and plate discipline, outs recorded depends on the starter's hook. Season-level counts add playing-time and availability risk.",
    "inputs": [I("mlb.expected_pa", "primary", "Plate appearances by slot and script."), I("mlb.plate_discipline", "primary", "Walk drivers on both sides."), I("mlb.sb_context", "primary", "Steal attempt rate, pitcher hold time and catcher arm."), I("mlb.baserunning", "secondary", "Baserunning and sprint speed."),
              I("mlb.sp_workload", "primary", "Expected innings and batters faced."), I("mlb.leash", "primary", "Manager hook tendencies."), I("mlb.run_dist", "secondary", "Run-scoring distribution."), I("mlb.bullpen", "secondary", "Bullpen availability decides outs after the starter."),
              I("mlb.lineup_pit", "primary", "Confirmed batting order timestamped."), I("mlb.playing_time_role", "secondary", "Starter versus platoon role."), I("mlb.umpire", "secondary", "Umpire zone changes walks."), I("mlb.pa_sim", "secondary", "PA simulation gives count distributions.")],
    "interactions": [X("mlb.sb_context", "mlb.lineup_pit", "A speedster's steal probability depends on batting slot and the hitters behind him."), X("mlb.plate_discipline", "mlb.umpire", "A tight zone inflates walks most for patient hitters."), X("mlb.sp_workload", "mlb.leash", "Outs recorded is the starter's pitch efficiency times the hook rule.")]}},
 "NHL": {"team_and_player_season_counting": {"label": "NHL season point/goal totals and counting leaders", "blueprint": "season_stat", "contract_types": ["Season point totals", "Player goals scored in season", "All-NHL team"],
    "target": "A player's season total (goals, points) or team points relative to a threshold.",
    "mechanism": "Season totals are games played times per-game rates, where rates depend on ice time, power-play role, linemates and shot quality, and games played depend on injury hazard. Over-dispersion and age curves matter; early-season to-date totals are weak evidence relative to talent priors.",
    "inputs": [I("nhl.stat_dist", "primary", "Count distributions over a season."), I("nhl.toi", "primary", "Time on ice by strength state."), I("nhl.pp_role", "primary", "Power-play unit role."), I("nhl.ixg_player", "primary", "Individual expected goals rate."),
              I("nhl.finishing", "secondary", "Finishing talent versus luck."), I("nhl.lines", "secondary", "Line combinations."), I("nhl.linemate_quality", "secondary", "Linemate quality."), I("nhl.career_trajectory", "secondary", "Age curve."), I("nhl.shot_rate", "secondary", "Shot attempt rate.")],
    "interactions": [X("nhl.pp_role", "nhl.toi", "Power-play share multiplies even-strength time on ice into points."), X("nhl.finishing", "nhl.ixg_player", "Expected goals with shrunk finishing talent beats raw goals for season totals."), X("nhl.career_trajectory", "nhl.toi", "Age declines show first in ice time, then production.")]}},
 "CFB": {"awards_and_honors": {"label": "College football awards (Heisman and conference awards)", "blueprint": "player_other", "contract_types": ["Heisman", "Defensive Heisman", "Conference player awards"],
    "target": "Winner of a voted individual award.",
    "mechanism": "Voted awards follow production percentile, team success and narrative; quarterbacks on top teams dominate and late-season prime-time games weigh more. The distribution across candidates, not a single mean, prices the market, and vote clustering by region and position matters.",
    "inputs": [I("cfb.award_narrative", "primary", "Narrative and production to date."), I("cfb.award_vote_distribution", "primary", "Historical vote-share distribution."), I("cfb.player_usage", "secondary", "Usage and volume."), I("cfb.pass_efficiency", "secondary", "Passing efficiency for quarterbacks."),
              I("cfb.qb", "secondary", "Quarterback status."), I("cfb.qb_rushing", "secondary", "Rushing production adds to quarterback narrative."), I("cfb.td_rates", "secondary", "Touchdown rates."), I("cfb.standings", "secondary", "Team success and CFP position."), I("cfb.schedule_strength", "secondary", "Schedule strength discounts production.")],
    "interactions": [X("cfb.standings", "cfb.award_narrative", "Team rank multiplies a candidate's production in voter perception."), X("cfb.pass_efficiency", "cfb.schedule_strength", "Efficiency against weak schedules is discounted by voters."), X("cfb.player_usage", "cfb.qb", "Quarterback status changes the candidate's late-season production.")]}},
 "CBB": {"polls_and_awards": {"label": "College basketball polls, #1 rank and awards", "blueprint": "season_outcome", "contract_types": ["Teams to be ranked #1", "Naismith and player awards", "Poll churn"],
    "target": "Which teams hold a poll rank or how many distinct teams hold #1, or an individual award winner.",
    "mechanism": "Poll position follows results, opponent rank and voter inertia; the number of distinct #1 teams is driven by upset probability among the top teams and voter reactions to losses. Player awards follow production, team success and narrative. Markets here are driven by schedule structure and voter behaviour, not game-level models alone.",
    "inputs": [I("cbb.ratings", "primary", "Team strength for upset probability."), I("cbb.poll_voter_behavior", "primary", "Voter behaviour and inertia."), I("cbb.resume_metrics", "secondary", "Resume metrics."), I("cbb.conf_strength", "secondary", "Conference strength."),
              I("cbb.sos_remaining", "secondary", "Remaining schedule decides loss risk."), I("cbb.single_game_variance", "secondary", "Single-game upset variance."), I("cbb.rating_uncertainty", "secondary", "Rating uncertainty."), I("cbb.player_usage", "secondary", "Production for awards."), I("cbb.news", "secondary", "News and injuries.")],
    "interactions": [X("cbb.ratings", "cbb.single_game_variance", "Upset probability is rating gap scaled by team-style variance."), X("cbb.poll_voter_behavior", "cbb.sos_remaining", "Voter reaction to a loss depends on opponent rank and timing."), X("cbb.resume_metrics", "cbb.conf_strength", "Resume strength is discounted by weak conferences.")]}},
}


WHY_FIX = {
 "nfl.turnovers": "Team turnover rates regress toward the mean, so interception and takeaway counts should not extrapolate recent luck.",
 "nfl.ot_model": "Overtime and tie probability is a tail of the score-path distribution; it bounds tie markets and adds possessions to counts.",
 "cfb.player_usage": "Usage and volume determine the production totals voters actually see for each candidate.",
 "cfb.qb": "Quarterback status (injury, benching) can end a candidacy abruptly, so confirmed availability is a hard filter.",
 "cfb.td_rates": "Touchdown rates by role translate usage into the headline numbers voters weight most.",
 "nba.player_shooting_regression": "Shooting luck regresses: a hot start in 3P% or FG% inflates season-average thresholds and should be shrunk toward talent.",
 "cbb.poll_voter_behavior": "Voter inertia and reaction to losses decide how far a team falls after an upset, which determines whether #1 changes hands.",
 "cbb.resume_metrics": "Resume metrics (quality wins, bad losses) are what voters reward beyond efficiency ratings.",
 "cbb.conf_strength": "Conference strength discounts or boosts a team's results in voters' eyes.",
 "cbb.single_game_variance": "Single-game upset variance by team style sets the per-game chance the top team loses.",
 "cbb.rating_uncertainty": "Rating uncertainty widens the probability a ranked team is really weaker than its poll slot.",
 "cbb.player_usage": "Production and usage form the statistical case for individual awards.",
 "cbb.news": "Injury and eligibility news can remove an award candidate or a top team without a game being played.",
 "nhl.pp_role": "Power-play unit role multiplies even-strength ice time into points; PP1 players earn a large share of their totals there.",
 "nhl.finishing": "Finishing talent versus luck: shrunk shooting percentage predicts goals better than raw totals over a season.",
 "nhl.lines": "Line combinations determine linemates and ice time, so a promotion or demotion shifts the whole scoring rate.",
 "nhl.linemate_quality": "Playing with elite centres or wingers raises assist and goal rates independent of the player's own talent.",
 "nhl.career_trajectory": "Age curves set the expected change in rate from last season: young players rise and veterans decline on average.",
 "nhl.shot_rate": "Shot-attempt rate per 60 is the most stable component of goal scoring and anchors the projection.",
 "mlb.plate_discipline": "Walk rate depends on the hitter's patience and the pitcher's control; both set the per-PA walk probability.",
 "mlb.baserunning": "Sprint speed and baserunning aggressiveness set the steal attempt rate and success probability.",
 "mlb.leash": "Manager hook rules (pitch counts, times through the order) determine how many outs the starter records.",
 "mlb.run_dist": "The run-scoring distribution gives the tail probabilities for earned runs and team-count thresholds.",
 "mlb.playing_time_role": "Starter versus platoon role sets plate appearances and games played over a season.",
 "mlb.umpire": "Umpire strike-zone size changes walk and strikeout rates and therefore walks and outs recorded.",
 "soc.player_minutes_expectation": "Expected minutes and substitution risk scale every shot and save count.",
}


def apply() -> dict:
    n_in = n_arch = 0
    for sp, archs in ARCH.items():
        d = json.loads((CAT / f"{sp}.json").read_text())
        for iid, (cat, label, mech, rat, meas, pit, src) in NEW_INPUTS.get(sp, {}).items():
            if iid not in d["inputs"]:
                d["inputs"][iid] = {"label": label, "category": cat, "mechanism": mech, "rationale": rat, "measurement": meas, "pregame_knowable": pit, "free_sources": src, "registry_ids": []}; n_in += 1
        d.setdefault("unregistered_archetypes", {})
        for name, rec in archs.items():
            for i in rec["inputs"]:
                assert i["id"] in d["inputs"], (sp, name, i["id"])
                if len(i["why"]) < 30:
                    i["why"] = WHY_FIX[i["id"]]
            d["unregistered_archetypes"][name] = rec; n_arch += 1
        (CAT / f"{sp}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    return {"new_inputs": n_in, "unregistered_archetypes": n_arch}


if __name__ == "__main__":
    print(apply())

# Blind re-implementation brief: NFL pbp batch 2 (team-game features, strictly pre-game)

Data (read-only): play-by-play parquet files `/tmp/claude-0/data/nfl/pbp/pbp_<season>.parquet` (nflverse, seasons 2010-2025) and schedule `/tmp/claude-0/data/nfl/games.csv`.
Use only pandas/numpy. Do NOT look at any code under /home/user/sift-alpha/alpha_engine/ ; implement from this text alone. Where this text is ambiguous, choose the most literal reading and RECORD the choice in your ambiguities list.

## Universe and common rules
* Games: rows of games.csv with season >= 2009 and non-null home_score (completed games). Team keys: map OAK->LV, SD->LAC, STL->LA on every team column. One output row per (game_id, team) for both home_team and away_team of each such game. date = gameday.
* Drop plays with play_deleted==1 or aborted_play==1. Order plays by (game_id, play_id). Plays with null posteam are not usable for offence-side quantities.
* If a game has no pbp rows at all (after the deletions above), every raw quantity of both teams is NaN (never 0). If it has pbp rows: all COUNTS (ds, xp_att, xp_made, tp_att, tp_conv, td_n, kneel, fg, go, late_n) are 0 when there are no events, while means/shares are NaN when their set is empty.
* "_pre" feature for a team-game G = value computed ONLY from that team's strictly earlier games (sorted by date, game_id): either
  (E) EWMA: take the per-game raw series r_1..r_n of the team's games in chronological order (NaN allowed), shift by one game so G sees only earlier games, then pandas ewm(halflife=8, min_periods=3).mean() (ignore_na=False default; min_periods counts non-NaN observations; adjust=True default); or
  (S) shrunk cumulative: (A + k*L) / (B + k), with A, B the team's cumulative numerator/denominator summed over ALL strictly earlier games (missing counts treated as 0), and L the league ratio sum(num)/sum(den) over all team-games dated STRICTLY BEFORE the date of G (NaN if no denominator yet -> result NaN).
* Drives: take plays with non-null fixed_drive and posteam; a drive = unique (game_id, posteam, fixed_drive); read drive attributes from the FIRST play row (by play_id) of the drive. drive seconds = drive_time_of_possession "M:SS" -> 60*M+S (NaN if absent). Only drives with drive_quarter_start <= 4 are used ("regulation drives"). Drive index = dense rank of fixed_drive within (game, team) over all of the team's drives in that game (computed BEFORE the quarter filter). Drive outcome class from fixed_drive_result: 'Touchdown'->td, 'Field goal'->fg, 'Punt'->punt, 'Turnover' or 'Opp touchdown'->to, anything else->other.

## Inputs and columns
### nfl.drive_outcome_by_index  -> o3_td_pre, o3_fg_pre, o3_punt_pre, o3_to_pre, o3_def_td_pre, o3_def_fg_pre
Raw per game for team T: among T's regulation drives with index <=3, the share ending in td / fg / punt / to (o3_td, o3_fg, o3_punt, o3_to). Defence versions: o3_def_td / o3_def_fg for T in game G = the OPPONENT's o3_td / o3_fg in the same game G. Feature = (E) of each.
### nfl.drive_duration_by_outcome -> dur_td_pre, dur_fg_pre, dur_punt_pre, dur_to_pre
Raw per game: mean drive seconds (skipping NaN seconds) of T's regulation drives of class td / fg / punt / to (NaN if none). Feature = (E).
### nfl.period_drive_scoring_rates -> pq{q}_td_pre, pq{q}_fg_pre for q=1..4
Raw per game: among T's regulation drives with drive_quarter_start == q, the share with class td, the share with class fg (NaN if T has no such drive). Feature = (E).
### nfl.drive_clock_allocation -> ds{q}_pre, dsec{q}_pre, q=1..4
Raw per game: ds{q} = number of T's regulation drives with drive_quarter_start==q (0 if none but the game has usable pbp for T; see rule above); dsec{q} = mean seconds of those drives (NaN if none). Feature = (E).
### nfl.period_zero_tie_mass -> qs{q}_pre, qtie{q}_pre, qbtts{q}_pre, q=1..4
Points scored in regulation quarter q by a team = (team's cumulative score at the START of the first play of quarter q+1) - (at start of first play of quarter q), using total_home_score / total_away_score (score at start of play); for q=4 the "start of quarter 5" score is the start of the first overtime play if any, else the game's final home_score/away_score. Use the first play (lowest play_id) of each quarter with non-null total_home_score. Raw: qs = 1 if team's quarter points >0 else 0; qtie = 1 if team's and opponent's quarter points are equal (incl 0-0); qbtts = 1 if both >0. (NaN when the needed quarter points are NaN.) Feature = (E).
### nfl.opening_kick_field_position -> kr_tb_pre, kr_td_pre, kk_tb_pre, kr_start_pre
Kickoff plays: kickoff_attempt==1 (the kicking team is posteam, the receiving team is defteam). Raw per game for T: kr_tb = mean of touchback over kickoffs T received; kr_td = share of kickoffs T received where return_touchdown==1; kk_tb = mean of touchback over kickoffs T kicked; kr_start = mean yardline_100 of T's drives whose first row has drive_start_transition == 'KICKOFF' (case-insens.), computed from drive_start_yard_line: '<TEAM> n' (TEAM normalised as above) means n yards from TEAM's own goal line: if TEAM == T then yardline_100 = 100 - n else n; a bare '50' is 50. (Drives are taken over all quarters here.) Feature = (E).
### nfl.scoring_event_point_values -> xp_make_pre, twopt_share_pre, twopt_conv_pre
xp_att = count of plays by posteam T with extra_point_attempt==1; xp_made = of those, extra_point_result=='good'. tp_att = plays by posteam T with two_point_attempt==1; tp_conv = of those two_point_conv_result=='success'. td_n = count of plays with touchdown==1 whose td_team is T. Features (S): xp_make_pre num=xp_made den=xp_att k=50; twopt_share_pre num=tp_att den=td_n k=15; twopt_conv_pre num=tp_conv den=tp_att k=15.
### nfl.late_tie_game_management -> late_kneel_pre, late_fg_pre, late_go_pre
Occasion plays by posteam T: qtr==4, game_seconds_remaining<=120, score_differential (posteam minus defteam at start of play) between -3 and 0 inclusive. kneel = qb_kneel==1; fg = field_goal_attempt==1; go = (pass_attempt==1 or rush_attempt==1 or sack==1 or qb_scramble==1) and qb_kneel==0 and qb_spike==0. late_n = kneel+fg+go counts (per game). Features (S): late_kneel_pre num=kneel den=late_n k=10, likewise late_fg_pre, late_go_pre.

## Output
Write `/tmp/claude-0/out/blind_pbp2.csv` with columns game_id, team, then every *_pre column listed above (54 columns), for every (game_id, team) in the universe (NaN allowed). Also write `/tmp/claude-0/out/blind_pbp2_notes.json` {"ambiguities": [...]}. Report back only a short summary of ambiguities you resolved; do not try to obtain or compare against any other implementation's output.

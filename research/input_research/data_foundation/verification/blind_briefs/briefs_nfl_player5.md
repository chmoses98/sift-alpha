# Blind brief: NFL batch 5 (play-by-play player usage), six pre-game player inputs (19 value columns)

You get `data/games.csv` (nflverse schedule) and `data/pbp/*.parquet` (nflverse play-by-play, one file per season). Write your own implementation from this text only and
write `out.csv` with one row per (game_id, player) and exactly the columns listed under Output (empty cell = missing). Use float64 throughout. Do not look for any other implementation.

## 1. Schedule
* Rows of games.csv with season >= 2010, all game types (REG, WC, DIV, CON, SB). If a game_id occurs twice keep the first. date = gameday (a calendar date).
* played = home_score is present (not missing). Unplayed games are kept (they can be output rows) but are never history.
* Replace team codes OAK -> LV, SD -> LAC, STL -> LA in home_team and away_team, and in play-by-play `posteam`. Every team code below is the replaced code.
* Each game has two team slots: (home_team, opponent away_team) and (away_team, opponent home_team).
* Output games: schedule games with season >= 2011 (played or unplayed). Season 2010 is history only and has no output rows.

## 2. Plays (history)
Use play-by-play rows whose game_id is a PLAYED schedule game (season >= 2010). Ignore the play-by-play `season` column; a play's date is its game's schedule date.
A play qualifies only if `posteam` is present and two_point_attempt != 1 (missing two_point_attempt counts as 0). Its team T = posteam (code replaced).
* Target: qualifying play with play_type == "pass" and receiver_player_id present. The player is receiver_player_id.
* Run: qualifying play with play_type == "run" and rusher_player_id present. The player is rusher_player_id.
* Carry: a run with qb_scramble != 1 (missing qb_scramble counts as 0). (Scrambles are runs but not carries; kneels and spikes have other play_types and are ignored.)
* Goal-line carry: carry with yardline_100 <= 5. Red-zone carry: carry with yardline_100 <= 20. Passing-down carry: carry with down == 3 or down == 4.
  Red-zone target: target with yardline_100 <= 20. (A missing yardline_100 or down makes the condition false.)
* Air: a target with air_yards present contributes air_yards to "air" and 1 to "n_air"; other targets contribute 0 to both.
* Receiving yards of a target = receiving_yards (missing -> 0). Rushing yards of a run (scrambles included) = rushing_yards (missing -> 0).
* TD play of its player: a target with pass_touchdown == 1, or a run with rush_touchdown == 1.
* First TD of a game: among ALL play-by-play rows of the game (no filter at all), the row with touchdown == 1 and the smallest play_id (play_id as a number). A target or run (as
  defined above) is a first-TD play of its player if it is a TD play of its player AND its play_id equals that smallest play_id. A game with no touchdown == 1 row has no first-TD play.

Team-game totals, per (game_id, T) over that team's targets and runs: n_tgt = targets, n_car = carries, n_gl = goal-line carries, n_pd = passing-down carries, n_rzt = red-zone
targets, n_rzc = red-zone carries, air_tot = sum of air over its targets.
Player-game values, per (game_id, T, player) over the player's targets and runs for team T in that game: tgt, car, gl, pd, rzt, rzc (counts as above), air, n_air (sums),
recy = sum of receiving yards of his targets, rushy = sum of rushing yards of his runs (scrambles included), td = 1 if he has at least one TD play else 0,
ftd = 1 if he has a first-TD play else 0.
**Involvement game**: a player-game with tgt + car >= 1 (a player-game with only scrambles is NOT an involvement game and is not used anywhere).
A player's **history** = all his involvement games (for any team), ordered by (date, game_id, T).

## 3. Row universe
For each output game g (date d) and each of its two team slots T:
* prev(T, d) = T's last 4 PLAYED schedule games (season >= 2010) dated strictly before d, by (date, game_id) (fewer if T has fewer).
* Candidates: every player with an involvement game for team T in one of the games of prev(T, d). For a candidate, q = the latest date among those involvement games.
* A player who is a candidate for both teams of g is kept only for the team with the larger q (if equal, the alphabetically smaller team code).
* One output row per remaining (g, player): game_id = g, team = the player id, pteam = T.
Nothing of game g itself (or any game dated >= d) is used, neither for the universe nor for any value.

## 4. Conventions for every value of a row (g, player p, date d)
* H(d) = p's history games dated strictly before d (non-empty by construction). Index k = 0 for the most recent of them, 1 for the one before, and so on.
* EWM with half-life h of a per-game value x: sum over games in H(d) where x is defined of 0.5 ** (k / h) * x, divided by the sum over the same games of 0.5 ** (k / h).
  Games where x is undefined are skipped in both sums but still occupy their index k. Missing if no game in H(d) has x defined.
  (Equivalent to pandas ewm(halflife=h, adjust=True, ignore_na=False).mean() taken at the last game of H(d).)
* Share a / b for a player-game: a / b if b > 0, otherwise undefined. a is the player-game value and b the team-game total of the same (game_id, T).

## 5. Columns
nfl.carries (h = 4):
* pcr_carry_share_pre = EWM of car / n_car.
* pcr_gl_carry_share_pre = EWM of gl / n_gl.
* pcr_pd_carry_share_pre = EWM of pd / n_pd.

nfl.targets (h = 4):
* ptg_target_share_pre = EWM of tgt / n_tgt.
* ptg_air_share_pre = EWM of air / air_tot (undefined when air_tot <= 0; the share itself may be negative or > 1).
* ptg_adot_pre = [sum over ALL games in H(d) of 0.5 ** (k / 4) * air] / [sum over ALL games in H(d) of 0.5 ** (k / 4) * n_air]; missing if the denominator is 0.

nfl.rz_share (h = 4):
* prz_rz_target_share_pre = EWM of rzt / n_rzt.
* prz_rz_carry_share_pre = EWM of rzc / n_rzc.

nfl.td_rates (h = 8; x always defined):
* ptd_anytime_rate_pre = EWM of td.
* ptd_first_td_rate_pre = EWM of ftd.

nfl.player_stat_variance: W = the last min(16, |H(d)|) games of H(d). If W has fewer than 4 games, all six columns are missing. Otherwise, with y = recy (rec) or rushy (rush):
* psv_rec_yds_mean_pre / psv_rush_yds_mean_pre = mean of y over W.
* psv_rec_yds_sd_pre / psv_rush_yds_sd_pre = sample standard deviation of y over W (denominator |W| - 1).
* psv_rec_yds_cv_pre / psv_rush_yds_cv_pre = sd / mean if mean > 0, else missing.

nfl.target_competition: within the output rows of the same (game_id, pteam), let s_i = ptg_target_share_pre of row i (missing -> 0) and S = sum of s over those rows.
* ptc_teammate_share_sum_pre = S - s_i.
* ptc_share_rank_pre = 1 + the number of rows j of the same (game_id, pteam) with s_j > s_i (1 = highest share; ties share the smaller rank).
* ptc_team_hhi_pre = sum of s_j ** 2 over those rows divided by S ** 2; missing if S == 0.

## Output
`out.csv`: game_id, team (= player id), then the 19 value columns
pcr_carry_share_pre, pcr_gl_carry_share_pre, pcr_pd_carry_share_pre, ptg_target_share_pre, ptg_air_share_pre, ptg_adot_pre, prz_rz_target_share_pre, prz_rz_carry_share_pre,
ptd_anytime_rate_pre, ptd_first_td_rate_pre, ptc_teammate_share_sum_pre, ptc_share_rank_pre, ptc_team_hhi_pre, psv_rec_yds_mean_pre, psv_rec_yds_sd_pre, psv_rec_yds_cv_pre,
psv_rush_yds_mean_pre, psv_rush_yds_sd_pre, psv_rush_yds_cv_pre.
Rows in any order (suggested: by date, game_id, team). Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

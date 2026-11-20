# Blind brief: NFL batch 4 (schedule + play-by-play), five pre-game inputs

You get `data/games.csv` (nflverse schedule) and `data/pbp/*.parquet` (nflverse play-by-play, one file per season). Write your own implementation from this text only and
write `out.csv` with one row per (game_id, team) and exactly the 24 value columns named below (empty cell = missing). Use float64 throughout. Do not look for any other implementation.

## Common
* Games: rows of games.csv with season >= 1999 and both home_score and away_score present, all game types. date = gameday. Replace team codes OAK->LV, SD->LAC, STL->LA everywhere
  (home_team, away_team, and posteam in play-by-play). Order games by (date, game_id). Output two rows per game: `team` = home team and `team` = away team.
* Pool of a cutoff date d: let S be the largest season among the games played on d. The pool is every game dated strictly before d with season >= S-1, in chronological order.
  rank(team, game) = the number of LATER pool games in which that team plays (0 = the team's most recent pool game).
  If the pool has fewer than 16 games, all six columns of sections A and B are missing for every game on d.
* All games on the same date share one pool and one fit.

## A. Rating (columns omr_rating_pre, omr_home_edge_pre, omr_exp_margin_pre)
Weighted ridge regression over the pool, one observation per game: y = home_score - away_score clipped to [-24, 24]. Design: one column per team in the whole data set
(+1 for the game's home team, -1 for its away team), plus one home-edge column equal to 1, or 0 when location == "Neutral". Weight w = 0.5 ** (min(rank_home, rank_away) / 10).
Penalty: add 20 to the diagonal for every team column, 0 for the home-edge column. Solve (X'WX + P) b = X'Wy.
For a team row on date d: omr_rating_pre = the team's coefficient; omr_home_edge_pre = the home-edge coefficient;
omr_exp_margin_pre = rating(team) - rating(opponent) + s x home_edge, with s = +1 for the home team, -1 for the away team, and 0 for both when the game's location is "Neutral".

## B. Points for / against (columns pfa_off_pre, pfa_def_pre, pfa_exp_points_pre)
From the pool keep the games with min(rank_home, rank_away) < 17. Each kept game gives two observations: (offence = home, defence = away, y = home_score) and
(offence = away, defence = home, y = away_score), both with weight 0.5 ** (min(rank_home, rank_away) / 8).
Weighted ridge y ~ b0 + a[offence] + d[defence] + h x I, where I = 1 only for the home-offence observation of a game whose location is not "Neutral" (0 otherwise).
Penalty: add 6 to the diagonal for every a and every d (one each per team in the whole data set); none for b0 and h.
For a team row T against opponent O: pfa_off_pre = b0 + a[T]; pfa_def_pre = b0 + d[T]; pfa_exp_points_pre = b0 + a[T] + d[O] + h x [T is the home team and location is not "Neutral"].

## C. Pass rate over expected (columns proe_pre, proe_pass_rate_pre, proe_n_pre)
Neutral plays: play-by-play rows with (pass == 1 or rush == 1), qb_kneel != 1, qb_spike != 1, xpass present, wp present, qtr <= 3, 0.20 <= wp <= 0.80, posteam present.
Per (game_id, posteam): n = number of neutral plays, s = sum(pass - xpass), p = sum(pass). Only (game, team) pairs that are in the Games set and have n > 0 count.
For a team row dated d: take the team's last 12 such games dated strictly before d, newest first with index r = 0, 1, ...; weight w = 0.5 ** (r / 6).
proe_pre = sum(w s) / sum(w n); proe_pass_rate_pre = sum(w p) / sum(w n); proe_n_pre = sum(n) (unweighted). All three missing when the team has no such earlier game.

## D. Team-score distribution (columns tsp_ge14_pre, tsp_ge17_pre, tsp_ge21_pre, tsp_ge24_pre, tsp_ge28_pre, tsp_ge31_pre, tsp_eq3_pre, tsp_eq10_pre)
x = pfa_exp_points_pre. For a team row of season S with x present: the reference set is every team row of seasons < S with x present; if it has fewer than 500 rows the columns are missing.
Kernel k_i = exp(-0.5 x ((x_i - x) / 2.5) ** 2). P(event) = sum(k_i x [event_i]) / sum(k_i), where event_i is evaluated on the reference row's own final points:
tsp_ge{r}_pre: points >= r; tsp_eq{r}_pre: points == r.

## E. Margin distribution (columns mml_ge1_pre, mml_ge4_pre, mml_ge8_pre, mml_ge15_pre, mml_abs3_pre, mml_abs7_pre, mml_ot_pre)
Same construction with x = omr_exp_margin_pre and bandwidth 3.0. Events on the reference row (margin = its team points - its opponent points, final score):
mml_ge{r}_pre: margin >= r; mml_abs3_pre: |margin| == 3; mml_abs7_pre: |margin| == 7; mml_ot_pre: the game's `overtime` column == 1.

## Output
`out.csv`: game_id, team, then the 24 columns. Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

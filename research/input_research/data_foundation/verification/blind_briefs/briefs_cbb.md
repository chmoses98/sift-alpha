# Blind re-implementation brief: college basketball team-game features (strictly pre-game), 5 catalog inputs

Data (read-only, untrusted files: read with `python -I`, keep your scripts elsewhere): `BLIND/cbb/cbb/{team_box,schedule,player_box}_<season>.parquet`, seasons 2004-2026 (concatenate all seasons).
Columns: team_box: game_id, season, season_type, game_date, team_id, team_score, opponent_team_id, opponent_team_score, field_goals_attempted, free_throws_attempted, offensive_rebounds, turnovers, ... ; schedule: game_id, season, season_type, game_date, neutral_site, home_id, away_id, home_score, away_score, status_period, status_type_completed, ...; player_box: game_id, team_id, minutes, starter, did_not_play, ...
You may use numpy and pandas only. Output must match the reference implementation to 1e-9 on every (game_id, team) row, NaN pattern included, so follow the formulas exactly.

## 1. Game universe
* schedule rows with status_type_completed == True and season_type in {2, 3}. n_per = status_period (NaN -> 0, as int); keep n_per >= 2; keep the first row of each duplicated game_id.
* team_box: drop rows with NaN in any of team_score, opponent_team_score, field_goals_attempted, free_throws_attempted, offensive_rebounds, turnovers. poss = field_goals_attempted + 0.44*free_throws_attempted - offensive_rebounds + turnovers. Keep the first row of each (game_id, team_id); keep only game_ids with exactly two such rows. poss_game = mean of the two rows' poss; keep games with poss_game >= 40 (inner join to the schedule games on game_id). date = schedule game_date.
* Two rows per schedule game: the home row (team = home_id, opp = away_id, hv = +1) and the away row (team = away_id, opp = home_id, hv = -1); hv = 0 on both when neutral_site is True (NaN counts as False). pts = team_score and opp_pts = opponent_team_score of the team_box row whose team_id equals this row's team (a game is dropped unless BOTH of its rows find their team_box row). team and opp are integers.
* n_ot = n_per - 2. eff_for = 100*pts/poss_game; eff_against = 100*opp_pts/poss_game (unused); poss40 = poss_game*40/(40 + 5*n_ot); margin = pts - opp_pts.
* Row order for per-team sequences: ascending (date, game_id); a team plays at most once per date. Output key (game_id, team), one row per universe row.
* "Earlier" always means STRICTLY EARLIER DATES (daily batches): a game never sees a game of the same date.

## 2. Walk-forward ridge ratings (columns rf_*, tp_adj_pre, tp_exp_poss_pre, ru_*)
Seasons are the schedule `season` values in ascending order s_0, s_1, ...; cnt(s, team) = number of universe rows of that team in season s.
Index set of season s_k: major teams = teams with cnt >= 12 in at least one of the two previous seasons s_{k-1}, s_{k-2} (those that exist), for k = 0 the teams with cnt >= 12 in s_0 itself; keep only major teams that appear (as team or opp) in season s_k, sorted ascending; every other team (as team or as opp) maps to ONE pooled index "OTHER" placed last. T = number of major teams + 1.
Efficiency parameters theta = [mu, h, o_1..o_T, d_1..d_T]; tempo parameters phi = [mu_t, a_1..a_T].
Prior means: k = 0: mu = 100, h = 0, all o = d = 0; mu_t = 68, all a = 0. k > 0: mu, h, mu_t = the previous season's FINAL values; for every index (major teams and OTHER) that also had an index in the previous season: o = 0.7 * previous final o, d = 0.7 * previous final d, a = 0.7 * previous final a; indices without a previous value: 0.
Penalties (ridge, diagonal): lambda = 8 on every o, d, h and a; lambda = 1 on mu and mu_t.
Observations: efficiency: every universe row of the season gives one observation y = eff_for with design x: mu 1, h hv, o_team 1, d_opp 1 (all other entries 0). Tempo: ONE observation per game (y = poss40) with x: mu_t 1, a_home 1, a_away 1 (the two teams' indices; for a game use its two rows' teams).
Weighting: at a date d the training observations are the season's observations on dates < d, each with weight w = 0.5^((d - obs_date in days)/30). Let S = sum w x x', b = sum w x y, yy = sum w y^2, sw = sum w. Fit: theta = (S + diag(pen))^-1 (b + pen*prior) (pen = penalties, prior = prior means). Do the same for phi with its own S, b. With no training observations theta = prior (S = 0).
s2 = max(yy - 2 theta'b + theta'S theta, 0)/sw if sw > 0 else 225.
sd_t (team's posterior sd of o_t - d_t) = sqrt(max(s2 * (Ainv[o_t,o_t] + Ainv[d_t,d_t] - 2 Ainv[o_t,d_t]), 0)), where Ainv = inverse of (S + diag(pen)) of the efficiency fit.
For every row on date d (using the fits for date d): own index t, opponent index u:
rf_off_pre = mu + o_t; rf_def_pre = mu + d_t; rf_adjem_pre = o_t - d_t; rf_hca_pre = h;
exp_poss = mu_t + a_t + a_u; tp_adj_pre = mu_t + a_t; tp_exp_poss_pre = exp_poss;
rf_pred_margin_pre = ((o_t - d_t) - (o_u - d_u) + 2*h*hv) * exp_poss/100;
ru_sd_pre = sd_t; ru_sd_pair_pre = sqrt(sd_t^2 + sd_u^2).
All these columns are NaN for every row of the very first season s_0 (it only seeds priors).
FINAL values of a season (the next season's priors): process every date of the season (adding that date's observations after predicting it), then multiply all weights by one more day of decay (0.5^(1/30)) and solve once; final mu, h, mu_t and each index's o, d, a (OTHER included, under the key "OTHER").

## 3. Other columns
* tp_raw_ewm_pre: per team along ITS rows (all seasons): poss40.shift(1).ewm(halflife=8, min_periods=3).mean() (pandas, adjust=True default).
* ot_p_tie_reg_pre: m = rf_pred_margin_pre, s = sqrt(tp_exp_poss_pre/68)*10.5; Phi((0.5-m)/s) - Phi((-0.5-m)/s) with Phi the standard normal CDF (0.5*(1+erf(z/sqrt 2))). NaN where m is NaN.
* ot_p_tie_ot_pre: use ONE row per game_id. For each game tied = max(n_ot - 1, 0) and per = n_ot. For a row on date d: Tt = sum of tied and Pp = sum of per over games with date >= d - 3650 days and date < d (all seasons). value = (Tt + 0.25*30)/(Pp + 30). Defined for every row (including the first season).
* ot_p_2plus_pre = ot_p_tie_reg_pre * ot_p_tie_ot_pre.
* bg_p15_pre, bg_p20_pre, bg_p25_pre: indicator (|margin| > 15 / 20 / 25) per team row; per team: indicator.shift(1).ewm(halflife=15, min_periods=5).mean(). bg_pair_p20_pre = (own bg_p20_pre + the opponent's bg_p20_pre in the same game)/2 (NaN if either is NaN).
* Starter minutes: player_box rows with starter == True and did_not_play != True; starter_min = sum of `minutes` per (game_id, team_id) (a team-game with no such row has NaN). close = (|margin| < 10) and starter_min not NaN; blow = (|margin| >= 20) and starter_min not NaN. Per team over ITS previous 60 rows (rows shifted by one, rolling window of 60, min_periods 1): cnt_c, sum_c = count and sum of starter_min over close rows; cnt_b, sum_b likewise for blow rows. bg_starter_close_pre = sum_c/cnt_c if cnt_c >= 5 else NaN; bg_starter_blow_pre = sum_b/cnt_b if cnt_b >= 3 else NaN; bg_starter_drop_pre = close - blow.

## Output
CSV `BLIND/out/blind_cbb.csv` with columns game_id, team and the 20 feature columns: rf_off_pre, rf_def_pre, rf_adjem_pre, rf_hca_pre, rf_pred_margin_pre, tp_adj_pre, tp_exp_poss_pre, tp_raw_ewm_pre, ru_sd_pre, ru_sd_pair_pre, ot_p_tie_reg_pre, ot_p_tie_ot_pre, ot_p_2plus_pre, bg_p15_pre, bg_p20_pre, bg_p25_pre, bg_pair_p20_pre, bg_starter_close_pre, bg_starter_blow_pre, bg_starter_drop_pre (write NaN as empty or 'nan'; full float precision). Also write `BLIND/out/blind_cbb_notes.json` {"ambiguities": [ ... anything in this brief you had to guess ... ]}.

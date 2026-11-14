# Blind re-implementation brief (Phase 15): NBA pre-game features, 11 catalog inputs, two output tables

You are an independent verifier. Re-implement every column below from THIS TEXT ALONE and write the two CSV files named at the end. Use only python with pandas / numpy / scipy / the standard library.

Data (read-only): `/tmp/claude-0/-home-user/4b121d0a-de18-5db8-915a-3a1ef1a5904f/scratchpad/blind/nba/data/espn/team_games_<season>.parquet` and `.../espn/player_games_<season>.parquet` (concatenate all season files of each kind).
Hard rules: do NOT read, list or search anything under `/home/user`, any git repository, or any other directory than that data directory and your own working/output directory. Do not look for an existing implementation. Where the text is ambiguous choose the most literal reading and RECORD the choice in the notes file.
Everything is strictly pre-game: a row for a game on date d may only use rows of games with date STRICTLY BEFORE d. A team (and a player) plays at most once per date.

## Common conventions
* "regular rows" = rows with `season_type == "regular"`. Nothing else is ever used. date = `game_date_et` parsed as a date. sidx = integer of the first 4 characters of `season` (e.g. "2024-25" -> 2024).
* `E(x; H, m)` = for one team, order its rows chronologically (all seasons concatenated, no reset at a season boundary) and take exactly the pandas expression `series_of_x.shift(1).ewm(halflife=H, min_periods=m).mean()` (pandas defaults adjust=True, ignore_na=False; NaN values of x are left in the series).
* "earlier games of the team" = that team's regular rows with an earlier date (all seasons unless "this season" is stated).
* League quantities "over rows with date < d" use ALL regular team rows (both rows of every game, all seasons) dated strictly before d and are the same for every row of date d.
* `o_X` = the value of X on the OTHER row of the same game (the row whose team is this row's opponent).
* Phi(x) = 0.5 * (1 + erf(x / sqrt(2))).
* A mean over an empty set is NaN. Any formula with a NaN input gives NaN unless stated otherwise.

# TABLE 1: team-game table (key game_id, team)
Universe: every regular row of team_games. team = `team_id`, opponent = `opp_team_id`, home = `home` (bool). Use columns pts, opp_pts, possessions, n_ot of the row itself. Sort by (date, game_id, team). One output row per universe row.
st_min(game, team) = sum of `minutes` over player_games regular rows of that (game_id, team_id) with played == True and started == True (NaN if there is no such row).

## nba.rating_blowout_minutes_curve -> rb_adjnet_pre, rb_mu_pre, rb_sd_pre, rb_p15_pre, rb_p20_pre, rb_st_close_pre, rb_st_blow_pre, rb_exp_stmin_pre
margin = pts - opp_pts; net100 = margin / possessions * 100. nr_pre = E(net100; 25, 5). pace_pre = E(possessions; 20, 3). adj = net100 + o_nr_pre. rb_adjnet_pre = E(adj; 25, 5).
hadv(d) = mean of margin over HOME rows with date < d. exp_pace = sqrt(pace_pre * o_pace_pre).
rb_mu_pre = (rb_adjnet_pre - o_rb_adjnet_pre) * exp_pace / 100 + (hadv if home else -hadv).
rb_sd_pre(d) = sqrt(mean of (margin - rb_mu_pre)^2 over HOME rows with date < d whose rb_mu_pre is not NaN); NaN if fewer than 100 such rows. It depends only on the date and is given to every row of that date (also to rows whose own rb_mu_pre is NaN).
For K in (15, 20): rb_pK_pre = Phi((-(K - 0.5) - rb_mu_pre) / rb_sd_pre) + 1 - Phi(((K - 0.5) - rb_mu_pre) / rb_sd_pre).
st_reg = st_min * 240 / (240 + 25 * n_ot). A game is "close" for a team if |margin| < 10 and a "blowout" if |margin| >= 20.
rb_st_close_pre = mean of st_reg over the team's earlier games (all seasons) that were close and have non-NaN st_reg; NaN if fewer than 5 such games. rb_st_blow_pre = the same over blowout games; NaN if fewer than 3.
rb_exp_stmin_pre = (1 - rb_p20_pre) * rb_st_close_pre + rb_p20_pre * rb_st_blow_pre.

## nba.final_margin_pmf_empirical -> fm_p_win_pre, fm_p_gt5_pre, fm_p_gt10_pre
For every HOME row with non-NaN rb_mu_pre and rb_sd_pre define z = (margin - rb_mu_pre) / rb_sd_pre (that row's own pre-game values). Z(d) = the z values of such home rows with date < d. If Z(d) has fewer than 200 values, or the row's own rb_mu_pre or rb_sd_pre is NaN, the three columns are NaN. Otherwise with the row's own mu = rb_mu_pre, sd = rb_sd_pre and thresholds t = 0, 5.5, 10.5 (for win, gt5, gt10):
home row: share of Z(d) with z > (t - mu) / sd. Away row: share of Z(d) with z < (mu - t) / sd. (Strict inequalities; share = count / size of Z(d).)

## nba.own_model_team_totals -> ot_exp_pts_pre, ot_exp_total_pre, ot_exp_margin_pre, ot_sd_team_pre, ot_sd_margin_pre, ot_sd_total_pre, ot_corr_mt_pre
pace20 = weighted mean of possessions over the team's last up to 20 earlier games (all seasons) with weight 0.5^(age/8), age = 1 for the most recent earlier game, 2 for the one before, ...; n20 = number of games used (0..20); pace20 is NaN if n20 < 3.
ppp = pts / possessions; dpp = opp_pts / possessions. lg_pace(d), lg_ppp(d) = mean of possessions, of ppp, over all rows with date < d.
pace_s = (n20 * pace20 + 15 * lg_pace) / (n20 + 15). g40 = min(number of the team's earlier games (all seasons), 40).
off_s = (g40 * E(ppp; 20, 3) + 20 * lg_ppp) / (g40 + 20). def_s = (g40 * E(dpp; 20, 3) + 20 * lg_ppp) / (g40 + 20).
hppp(d) = mean of (ppp - dpp) over HOME rows with date < d. exp_poss = pace_s * o_pace_s / lg_pace.
ot_exp_pts_pre = exp_poss * (off_s + o_def_s - lg_ppp + (0.5 if home else -0.5) * hppp). ot_exp_total_pre = ot_exp_pts_pre + o_ot_exp_pts_pre. ot_exp_margin_pre = ot_exp_pts_pre - o_ot_exp_pts_pre.
resid = pts - ot_exp_pts_pre. ot_sd_team_pre = sqrt(mean of resid^2 over the team's earlier games (all seasons) with non-NaN resid); NaN if fewer than 10 such games.
rm = margin - ot_exp_margin_pre; rt = (pts + opp_pts) - ot_exp_total_pre. Over HOME rows with date < d having non-NaN rm and rt (n of them; all three columns NaN if n < 100): ot_sd_margin_pre = sqrt(mean rm^2); ot_sd_total_pre = sqrt(mean rt^2); corr = mean(rm * rt) / (ot_sd_margin_pre * ot_sd_total_pre) (not centred). ot_corr_mt_pre = corr on home rows and -corr on away rows. These three depend only on the date (and the home flag for the sign) and are given to every row of that date.

## nba.team_points_margin_curve -> tm_resid_bin_pre, tm_exp_pts_curve_pre
mbin = floor(ot_exp_margin_pre / 2) clipped to [-8, 7]; undefined when ot_exp_margin_pre is NaN. For a row with bin b on date d: over ALL rows (home and away) with date < d, the same bin and non-NaN resid: S = sum of resid, N = count. tm_resid_bin_pre = S / (N + 50) (so 0 when N = 0; NaN only when the row's own bin is undefined). tm_exp_pts_curve_pre = ot_exp_pts_pre + tm_resid_bin_pre.

## nba.expectation_overperformance -> eo_exp_wins_pre, eo_surprise_pre, eo_proj_wins_pre
win = 1 if pts > opp_pts else 0. Within (team, sidx), over the team's earlier games of this season: gp = games, w = wins, pf = sum pts, pa = sum opp_pts. ppf, ppa = the team's total pts and opp_pts over ALL its regular rows of season sidx - 1 (NaN if it has none).
pyth(f, a) = 1 / (1 + (a / f)^14). exp_pct = 0.5 + 0.7 * (pyth(ppf, ppa) - 0.5). eo_exp_wins_pre = 82 * exp_pct. eo_surprise_pre = (w - eo_exp_wins_pre * gp / 82) / 6.
cur = pyth(pf, pa) if gp >= 5 else exp_pct. eo_proj_wins_pre = w + (82 - gp) * cur.

## nba.team_win_streak_hazard -> ws_run_pre, ws_p_game_pre, ws_p20_pre
ws_run_pre = the team's current run of consecutive wins within this season (team, sidx) entering the game (0 for its first game of the season or after a loss). ws_p_game_pre = (w + 5) / (gp + 10) (w, gp as above).
ws_p20_pre: p = ws_p_game_pre, R = max(82 - gp, 0). f_0(r) = 1 if r = 20 else 0, for r = 0..20. f_{k+1}(r) = p * f_k(r + 1) + (1 - p) * f_k(0) for r = 0..19 and f_{k+1}(20) = 1. ws_p20_pre = f_R(ws_run_pre) (and 1 if ws_run_pre >= 20).

## nba.lineup_adj_rating -> la_ibar_pre, la_adj_pre, la_out_share_pre, la_out_impact_pre
Player rows = player_games regular rows with played == True and minutes > 0. Impact of player i as of date d: I(i, d) = 48 * (sum of plus_minus) / (sum of minutes + 600) over his player rows with date < d (all teams, all seasons); 0 if he has none.
For the team row of team T on date d, let k = number of T's earlier games (all seasons). If k < 5 all four columns are NaN. Window = T's previous min(30, k) games. M_i = sum of minutes of player i's player rows with team_id == T in the window games; tot = sum of M_i over all such players (all four NaN if tot <= 0); m_i = M_i / tot.
Ibar = sum over players of m_i * I(i, d). A = the players who have a player row for T in T's immediately preceding game. sa = sum of M_i over i in A (all four NaN if sa <= 0). active = sum over i in A of (M_i / sa) * I(i, d).
la_ibar_pre = Ibar. la_adj_pre = active - Ibar. top8 = the 8 players with the largest M_i (ties: smaller nba_id first). OUT = top8 players not in A. la_out_share_pre = sum of m_i over OUT (0 if OUT is empty). la_out_impact_pre = sum over OUT of m_i * (I(i, d) - Ibar) (0 if empty).

# TABLE 2: player-game table (key game_id, team where `team` holds the player's nba_id)
Universe: player_games regular rows with played == True. One output row per universe row; the output column `team` = nba_id. Columns used: minutes, pts, reb, ast, stl, blk, fg3m, fg3a, plus_minus, team_id.
team_gp = for the row's (team_id, sidx): the number of that team's regular-season games of that season with an earlier date, counted over the distinct game_ids of ALL regular player_games rows of that team_id (played or not).
For a quantity X: cur(X) = sum of X over the player's earlier universe rows in the same sidx (any team); car(X) = the same over all his earlier universe rows (all seasons); prev(X) = sum of X over ALL his universe rows in season sidx - 1 (0 if none).
G = cur(1), M = cur(minutes), Gp = prev(1), Mp = prev(minutes). lg_min(d) = sum of minutes over all universe rows with date < d; n_lg(d) = their number.
avail = min(1, G / team_gp) if team_gp > 0 else 1. R = max(82 - team_gp, 0) * avail.

## nba.stat_rate_posterior -> srp_pts36_pre, srp_reb36_pre, srp_ast36_pre, srp_stl36_pre, srp_blk36_pre, srp_fg3m36_pre
For s in (pts, reb, ast, stl, blk, fg3m): lg36(d) = 36 * (sum of s over universe rows with date < d) / lg_min(d) (NaN if lg_min = 0). r0 = 36 * prev(s) / Mp if Mp >= 200 else lg36(d). srp_<s>36_pre = (36 * cur(s) + 400 * r0) / (M + 400).

## nba.avg_rounding_and_games_state -> ag_avg_pts_pre, ag_avg_reb_pre, ag_avg_ast_pre, ag_proj_pts_pre, ag_proj_reb_pre, ag_proj_ast_pre
For s in (pts, reb, ast): lgavg(d) = (sum of s over universe rows with date < d) / n_lg(d) (NaN if none). prior = prev(s) / Gp if Gp >= 10 else lgavg(d). ag_avg_<s>_pre = cur(s) / G (NaN if G = 0). mu = (cur(s) + 10 * prior) / (G + 10). ag_proj_<s>_pre = (cur(s) + R * mu) / (G + R) (NaN if G + R = 0).

## nba.season_plus_minus_projection -> pm_todate_pre, pm_rate_pre, pm_proj_pre
pm_todate_pre = cur(plus_minus). pm_rate_pre = car(plus_minus) / (car(minutes) + 500). mpg = M / G if G > 0, else Mp / Gp if Gp > 0, else NaN. pm_proj_pre = pm_todate_pre + R * mpg * pm_rate_pre.

## nba.rare_make_accrual_rate -> rm_3pa36_pre, rm_p3_pre, rm_lambda_pre, rm_p_any_pre
wa = 0.6 * cur(fg3a) + 0.4 * prev(fg3a); wm = 0.6 * cur(fg3m) + 0.4 * prev(fg3m); wmin = 0.6 * M + 0.4 * Mp. rm_3pa36_pre = 36 * wa / wmin (NaN if wmin <= 0). rm_p3_pre = (wm + 40 * 0.30) / (wa + 40). mpg2 = (M + Mp) / (G + Gp) (NaN if G + Gp = 0). rm_lambda_pre = rm_3pa36_pre * mpg2 / 36 * rm_p3_pre. rm_p_any_pre = 1 - exp(-rm_lambda_pre * R).

# Output
Write to `/tmp/claude-0/-home-user/4b121d0a-de18-5db8-915a-3a1ef1a5904f/scratchpad/blind/nba/out/`:
* `blind_nba_team3.csv`: columns game_id, team and the 30 TABLE 1 feature columns (exact names above); one row per (game_id, team) of the TABLE 1 universe.
* `blind_nba_player3.csv`: columns game_id, team and the 19 TABLE 2 feature columns; one row per (game_id, team) of the TABLE 2 universe.
* `blind_nba_notes.json` = {"ambiguities": ["...", ...]} listing every choice you had to make.
Write NaN as empty cells, full float precision (do not round). game_id is the string exactly as in the data. Keep your implementation script in your working directory. Finish with a short report of the ambiguities you resolved; do not ask questions.

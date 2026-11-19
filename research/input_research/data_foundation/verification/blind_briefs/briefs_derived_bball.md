# Blind re-implementation brief (derived NBA + CBB inputs): 12 catalog inputs, one team-game table per sport

You are an independent verifier. Re-implement every output column below from THIS TEXT ALONE and write the two CSV files named at the end. Use only python with pandas / numpy and the standard library.

Data (read-only): `DATA/NBA/espn_nba_team_boxscores/*.parquet`, `DATA/NBA/espn_nba_schedules/*.parquet`, `DATA/CBB/team_box/*.parquet`, `DATA/CBB/schedules/*.parquet` (DATA is given in the run instructions).
Hard rules: do NOT read, list or search anything under `/home/user`, any git repository, or any directory other than DATA and your own working directory. Do not look for an existing implementation. Where the text is ambiguous choose the most literal reading and RECORD the choice in `notes.json` (`{"ambiguities": [...]}`).
Every output is pre-game: a row of a game dated d may use only games dated strictly before d, except where a rule below says "seasons before S".

## Sport parameters
| | NBA | CBB |
|---|---|---|
| box dir / schedule dir | espn_nba_team_boxscores / espn_nba_schedules | team_box / schedules |
| season_type kept | 2, 3, 5 | 2, 3 |
| P (regulation periods), R (regulation minutes) | 4, 48 | 2, 40 |
| default half-life H, default shrink weight K | 20, 20 | 8, 10 |
| half-life overrides | fg3a100: 15, d_fg3a100: 20 | none |
| shrink-weight overrides | d_fg3a100: 25, d_efg: 40, fg3_pct: 40, d_fg3_pct: 200, ft_pct: 30, fg2_pct: 30 | d_efg: 25, fg3_pct: 25, d_fg3_pct: 90, ft_pct: 20, fg2_pct: 20 |
`H(x)` / `K(x)` = the override for name x if listed, else the default.

## 1. Universe and per-game values (one row per game x team)
1. Read every box parquet file in sorted file-name order and concatenate (keep file row order). Keep rows with `season_type` in the kept set. NBA only: keep rows with 1 <= team_id <= 30 AND 1 <= opponent_team_id <= 30.
2. Numeric values via `pd.to_numeric(..., errors="coerce")`: pts=team_score, fgm=field_goals_made, fga=field_goals_attempted, fg3m=three_point_field_goals_made, fg3a=three_point_field_goals_attempted, ftm=free_throws_made, fta=free_throws_attempted, oreb=offensive_rebounds, dreb=defensive_rebounds, ast=assists, stl=steals, blk=blocks, fb=fast_break_points; tov = total_turnovers where not NaN, else turnovers. game_id as int64, season = int(season), date = pd.to_datetime(game_date), team = team_id, home = (team_home_away == "home").
3. Keep rows with fga > 0; then drop duplicate (game_id, team) keeping the first; then keep only games with exactly 2 remaining rows. The opponent of a row is the other row of its game.
4. Schedules: read all schedule files (sorted names), concatenate, drop duplicate game_id keeping the first. Linescores are strings like `"[{'displayValue': '33', 'period': 1.0, 'value': 33.0}\n {...}]"`: take every `{...}` item, read its `'period'` and `'value'` numbers, sort the (period, value) pairs, keep the values (missing/None string -> empty list). L = number of home linescore items. status_period numeric. Periods played NP = status_period if status_period >= P, else L if L >= P, else 0. A box row whose game has no schedule row, or NP < P: ot_n = NaN; otherwise ot_n = NP - P. neutral = neutral_site (missing -> 0) as 0/1.
5. Sort rows by (date, game_id) with a stable sort.
6. own = fga - oreb + tov + 0.44 fta. poss = (own + opponent's own) / 2. pace = poss * R / (R + 5 * ot_n), with ot_n NaN treated as 0 here only.
7. Per-game metrics of the row's team (opponent's raw values are written o.):
   ortg = 100 pts/poss; efg = (fgm + 0.5 fg3m)/fga; tov_pct = tov/own; orb_pct = oreb/(oreb + o.dreb) (denominator 0 -> NaN); ftr100 = 100 fta/poss; fg3a100 = 100 fg3a/poss; fg2a100 = 100 (fga - fg3a)/poss; ast100, stl100, blk100, fb100 = 100 x/poss;
   fg3_pct = fg3m/fg3a, fg2_pct = (fgm - fg3m)/(fga - fg3a), ft_pct = ftm/fta (each denominator 0 -> NaN).
   The defensive version `d_X` of each metric is the same formula with the roles swapped (the opponent's offence in this game, e.g. d_orb_pct = o.oreb/(o.oreb + dreb), d_tov_pct = o.tov/o.own, d_ortg = 100 o.pts/poss).
   margin = pts - o.pts, total = pts + o.pts. ot = 1.0 if ot_n > 0, 0.0 if ot_n == 0, NaN if ot_n is NaN. site = 0 if neutral, else +1 home / -1 away.
   ADJ metrics = ortg, efg, tov_pct, orb_pct, ftr100, fg3a100, fg2a100, ast100, stl100, blk100, fb100. PCT metrics = fg3_pct, fg2_pct, ft_pct.

## 2. Point-in-time primitives
* `LG(x)` for a row of season s dated d = mean of x over ALL rows (both teams, NaN skipped) of season s dated strictly before d; if no such row has a non-NaN x, the mean of x over all rows of season s-1 (NaN if none).
* `SHR(series, h, k, lg)` for a row of team T in season s: let v = the series values of T's earlier rows of the SAME season (same row order). Compute exactly `series.groupby([team, season]).shift(1)` then, per (team, season), `.ewm(halflife=h, min_periods=1).mean()` (pandas defaults: adjust=True, ignore_na=False) -> ew; n = number of non-NaN earlier values.
  prior target: the mean of the series over T's rows of season s-1 if that season has >= 10 non-NaN values, else lg (the row's LG value). Result = (n * ew + k * target) / (n + k), with ew treated as 0 when NaN; if target is NaN the result is ew.
* Venue edge `E(x)` for season s: for each season u in [s-5, s-1] with non-neutral rows: gap_u = (mean of x over home rows - mean of x over away rows) / 2 among non-neutral rows of season u; E = mean of the available gap_u, 0 if none. E(pace) = 0.
* `WF(fit, apply, window, m)`: for each season S, the training rows are all rows with season in [S-window, S-1]; if they contain fewer than m distinct seasons the output is NaN for season S; else fit on the training rows and apply to the rows of season S. Default window 5.
* `OLS(cols, y)`: on training rows where every col and y are finite, least squares with an intercept (numpy lstsq); applied as b0 + sum b_i col_i.

## 3. Ratings (two stages)
For every ADJ metric x and for pace: lg_x = LG(x).
Stage 1: o1_x = SHR(x, H(x), K(x), lg_x); for ADJ metrics also d1_x = SHR(d_x, H(d_x), K(d_x), lg_x). Pace has o1 only.
Stage 2 (opp. = the opponent row's value of the same game):
  a_x = x - site*E(x) - (opp. d1_x - lg_x), the bracket treated as 0 when NaN; off_x_pre = SHR(a_x, H(x), K(x), lg_x).
  a_d_x = d_x + site*E(x) - (opp. o1_x - lg_x), the bracket 0 when NaN; def_x_pre = SHR(a_d_x, H(d_x), K(d_x), lg_x).
  pace: a_pace = pace - (opp. o1_pace - lg_pace) (bracket 0 when NaN); pace_pre = SHR(a_pace, H, K, lg_pace).
For PCT metrics: off_x_pre = SHR(x, H(x), K(x), LG(x)); def_x_pre = SHR(d_x, H(d_x), K(d_x), LG(x)).
`opp_Y` below always means the opponent row's value of Y for the same game.

## 4. Matchups and expectations
* mx_x_pre = off_x_pre + opp_def_x_pre - lg_x (every ADJ x).
* ff_edge_pre = 40*(mx_efg - (opp_off_efg + def_efg - lg_efg)) - 25*(mx_tov_pct - (opp_off_tov_pct + def_tov_pct - lg_tov_pct)) + 20*(mx_orb_pct - (opp_off_orb_pct + def_orb_pct - lg_orb_pct)) + 0.15*(mx_ftr100 - (opp_off_ftr100 + def_ftr100 - lg_ftr100)) (all *_pre values).
* exp_poss_add = pace_pre + opp_pace_pre - lg_pace; pace_mean_pre = (pace_pre + opp_pace_pre)/2; pace_absdiff_pre = |pace_pre - opp_pace_pre|; pace_slow_pre = min(pace_pre, opp_pace_pre); pace_inter_pre = (pace_pre - lg_pace)(opp_pace_pre - lg_pace).
* tov_sum_pre = mx_tov_pct_pre + opp_off_tov_pct_pre + def_tov_pct_pre - lg_tov_pct. fb_sum_pre = off_fb100_pre + opp_off_fb100_pre.
* rest = days since the team's previous game in ANY season (rows sorted as in step 5), capped at 7, 7 when there is none; rest_min = min(rest, opp_rest).
* exp_poss_joint_pre = WF(OLS([pace_mean, pace_slow, pace_inter], pace), window 5, m 2). exp_poss_comp_pre = WF(OLS([pace_mean, pace_absdiff, tov_sum, fb_sum, rest_min], pace), 5, 2).
* exp_poss_elastic_pre = lg_pace + WF(OLS([pd_t, pd_o], pace - lg_pace), 5, 2) with pd_t = pace_pre - lg_pace, pd_o = opp_pace_pre - lg_pace.
* mtype = [pd_t > 0] + [pd_o > 0] (NaN compares false). poss_sd_pre = WF(fit: sample sd (ddof 1, NaN skipped) of (pace - exp_poss_joint_pre) per mtype; apply: the row's mtype value (NaN if absent), 5, 3).
* ep = exp_poss_joint_pre where not NaN, else exp_poss_add.
* exp_pts = mx_ortg_pre*ep/100; opp_exp_pts = (opp_off_ortg_pre + def_ortg_pre - lg_ortg)*ep/100; mu0 = exp_pts - opp_exp_pts.
* hca = WF(fit: mean of (margin - mu0) over training rows with site == +1 (NaN skipped); apply: that constant, 5, 2), then NaN -> 0. exp_margin = mu0 + site*hca; exp_total = exp_pts + opp_exp_pts.
* exp_fg3a = off_fg3a100_pre * (opp_def_fg3a100_pre / lg_fg3a100) * ep/100; exp_fg2a = mx_fg2a100_pre*ep/100.
* exp_fta_pre = ep*(0.5*off_ftr100_pre + 0.5*opp_def_ftr100_pre)/100; exp_ft_pts_pre = exp_fta_pre*off_ft_pct_pre.

## 5. Opponent three-point defence z-scores
For V = opp_def_fg3a100_pre (-> opp_fg3a_allowed_z_pre) and V = opp_def_fg3_pct_pre (-> opp_fg3pct_allowed_z_pre), per row of season s dated d:
  mu = mean of V over rows of season s dated strictly before d (NaN skipped), sd = sqrt(max(mean of V^2 over the same rows - mu^2, 0)).
  If fewer than 200 rows of season s are dated strictly before d (count rows, not values): mu, sd = mean and sample sd (ddof 1) of V over all rows of season s-1 instead.
  z = (V - mu)/sd (sd == 0 -> NaN), clipped to [-4, 4].
fg3a_matchup_adj_pre = 0.6 * opp_fg3a_allowed_z_pre * 0.8; fg3pct_matchup_adj_pre = 0.1 * opp_fg3pct_allowed_z_pre * 1.5.

## 6. Scale, overtime and joint structure
* fg3_share_sum_pre = off_fg3a100_pre/(off_fg3a100_pre + off_fg2a100_pre) + the same for the opponent's off_* values. ftr_sum_pre = off_ftr100_pre + opp_off_ftr100_pre.
* Residuals: tot_res = total - exp_total; mar_res = margin - exp_margin; pts_res = pts - exp_pts.
* sd_total_style_pre = sqrt(exp(L + 1.27)) where L = WF(OLS([log ep, fg3_share_sum, ftr_sum], log(max(tot_res^2, 0.25))), 5, 3) (log of NaN is NaN).
* sd_margin_pre = WF(OLS([sqrt ep, |exp_margin|], |mar_res|*sqrt(pi/2)), 5, 3).
* sd_pts_style_pre = WF(OLS([o3, sqrt ep, |exp_margin|], |pts_res|*sqrt(pi/2)), 5, 3) with o3 = off_fg3a100_pre/(off_fg3a100_pre + off_fg2a100_pre).
* p_ot_pre = WF(logistic, 5, 3) of y = ot on X = [|exp_margin|, exp_total]. Logistic fit: rows with X and y finite; mu, sd = column means and POPULATION sd (ddof 0), sd 0 -> 1; A = [1, (X - mu)/sd]; start b = [log(max(ybar,1e-4)/max(1-ybar,1e-4)), 0, 0]; repeat exactly 40 times:
  p = 1/(1+exp(-A b)); W = p(1-p) + 1e-9; b = b + solve(A' diag(W) A + 0.001*I, A'(y - p) - 0.001*b*[0,1,1]) (the identity includes the intercept; the gradient penalty does not).
  Original-scale coefficients: c_j = b_j/sd_j, c_0 = b_0 - sum b_j mu_j/sd_j; apply p = 1/(1+exp(-(c_0 + X c))).
* p_ot2_given_ot_pre = WF(fit: (number of training rows with ot_n >= 2 + 30) / (number of training rows with ot_n >= 1 + 200); apply the constant, 5, 3).
* bk = bucket of |exp_margin|: [0,5) -> 0, [5,10) -> 1, [10,20) -> 2, [20, inf) -> 3, NaN -> NaN. fav = 1 if exp_margin > 0 else 0 (NaN -> 0).
* ter = WF(fit: the 1/3 and 2/3 quantiles (pandas linear interpolation, NaN skipped) of sqrt(ep) over training rows; apply: numpy searchsorted(quantiles, sqrt(ep)) (side left, so NaN -> 2), 5, 3).
* rho_margin_total_pre = WF(fit, apply, 5, 3): fit on training rows with z_m = mar_res/sd_margin_pre, z_t = tot_res/sd_total_style_pre, bk, ter all non-NaN and fav == 1: pooled = Pearson corr(z_m, z_t) if more than 50 rows else NaN; for each (bk, ter) group of n rows: r = group corr if n > 5 else pooled, cell = (n*r + 200*pooled)/(n + 200).
  apply: r = the cell of the row's (bk, ter) if it exists, else pooled; output r if fav == 1 else -r.
* k_pts_margin_pre = WF(fit, apply, window 8, m 3): fit on training rows with pts_res, mar_res, bk non-NaN: pooled = cov(pts_res, mar_res)/var(mar_res) (both ddof 1) if more than 50 rows else NaN; per (fav, bk) group of n rows: k = the group's cov/var if n > 5 else pooled; cell = (n*k + 250*pooled)/(n + 250). apply: the cell of the row's (fav, bk) if it exists, else pooled.

## Output
Write `blind_NBA.csv` and `blind_CBB.csv`, one row per universe row, columns `game_id, team` plus (full float precision, e.g. `float_format="%.17g"`, NaN as empty):
* NBA: exp_poss_joint_pre, poss_sd_pre, pace_slow_pre, pace_inter_pre, exp_poss_comp_pre, pace_mean_pre, pace_absdiff_pre, tov_sum_pre, fb_sum_pre, sd_margin_pre, p_ot_pre, p_ot2_given_ot_pre, sd_pts_style_pre
* CBB: off_efg_pre, off_tov_pct_pre, off_orb_pct_pre, off_ftr100_pre, def_efg_pre, def_tov_pct_pre, def_orb_pct_pre, def_ftr100_pre, mx_efg_pre, mx_tov_pct_pre, mx_orb_pct_pre, mx_ftr100_pre, ff_edge_pre, exp_poss_elastic_pre, exp_fta_pre, exp_ft_pts_pre, opp_fg3a_allowed_z_pre, opp_fg3pct_allowed_z_pre, fg3a_matchup_adj_pre, fg3pct_matchup_adj_pre, sd_total_style_pre, fg3_share_sum_pre, ftr_sum_pre, rho_margin_total_pre, k_pts_margin_pre
Also write `notes.json` and keep your implementation as `impl.py`. Print the row counts and a NaN count per column when done.

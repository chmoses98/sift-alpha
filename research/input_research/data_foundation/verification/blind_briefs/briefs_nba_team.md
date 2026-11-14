# Blind re-implementation brief: NBA team-game features (strictly pre-game), 7 catalog inputs

Data (read-only): `/tmp/claude-0/blind/nba/espn/team_games_<season>.parquet` and `/tmp/claude-0/blind/nba/espn/player_games_<season>.parquet` (all files). Use only pandas/numpy. Do NOT read anything under /home/user/sift-alpha, and do not read any other repository clone. Implement from this text alone; where it is ambiguous choose the most literal reading and RECORD every choice in `ambiguities`.

## Universe
* team_games rows with season_type == 'regular'. One row per (game_id, team_id); output key `team` = team_id (int), `game_id` (string as stored), date = game_date_et. The opponent of a row is the other row of the same game_id. Sort rows by (date, game_id) (stable).
* Per-game raw team quantities: pts, opp_pts, n_ot, fga, fta, oreb, tov, possessions from team_games; and from player_games rows with played == True, summed per (game_id, team_id): fgm, fg3m, fg3a, ast, dreb; st_min = sum of `minutes` of rows with started == True; bench_pts = sum of `pts` of played rows whose started is not True (NaN counts as not started). A team-game with no matching player rows has NaN for these.
* "opp_X" = the OPPONENT's same-game raw value of X (NaN if missing).
## Pre-game rules
* (E,hl): per-team series of a per-game raw value in chronological order (date, game_id), NaN allowed; shift by one game; pandas `ewm(halflife=hl, min_periods=3).mean()` (defaults otherwise). Feature value for game G therefore uses only that team's earlier games.
* lg(x): league mean of per-game value x over ALL team-game rows with date STRICTLY BEFORE G's date (NaN values skipped; NaN if none).
* "opp_<feature>_pre" = the opponent's own `_pre` value of the same game.
## Inputs and columns
### nba.four_factors_matchup
Per-game raw: efg_o=(fgm+0.5*fg3m)/fga; efg_d=(opp_fgm+0.5*opp_fg3m)/opp_fga; tov_o=tov/possessions; tov_d=opp_tov/possessions; orb_o=oreb/(oreb+opp_dreb); orb_d=opp_oreb/(opp_oreb+dreb); ftr_o=fta/fga; ftr_d=opp_fta/opp_fga; ppp100=pts/possessions*100.
Columns ff_<c>_pre = (E,12) of c for c in efg_o, efg_d, tov_o, tov_d, orb_o, orb_d, ftr_o, ftr_d (8 columns).
ff_exp_efg_pre = lg(efg_o) + (ff_efg_o_pre - lg(efg_o)) + (opp_ff_efg_d_pre - lg(efg_o)); ff_exp_tov_pre likewise with (tov_o, ff_tov_o_pre, opp_ff_tov_d_pre); ff_exp_orb_pre with (orb_o, ff_orb_o_pre, opp_ff_orb_d_pre); ff_exp_ftr_pre with (ftr_o, ff_ftr_o_pre, opp_ff_ftr_d_pre). (lg is always of the OFFENSIVE variant.)
ff_exp_pts100_pre = lg(ppp100) + 100*(0.40*(ff_exp_efg_pre - lg(efg_o)) - 0.25*(ff_exp_tov_pre - lg(tov_o)) + 0.20*(ff_exp_orb_pre - lg(orb_o)) + 0.15*(ff_exp_ftr_pre - lg(ftr_o))).
### nba.team_three_attempt_matchup
Raw: r3 = fg3a/possessions*100; a3 = opp_fg3a/possessions*100. n = number of the team's earlier games in the SAME season (0 for its first game); w = min(n, 82). season_start = integer year before the dash in `season` ('2024-25' -> 2024). ps = the team's plain mean of r3 over ALL its games of the PREVIOUS season_start (NaN if none).
t3_ewm=(E,15) of r3; a3_ewm=(E,20) of a3. t3_rate_pre = (w*t3_ewm + 20*ps)/(w+20) if ps and t3_ewm are both non-NaN, else t3_ewm.
t3_allowed_idx_pre = (w*(a3_ewm/lg(r3)) + 25*1.0)/(w+25).
pace_pre=(E,20) of possessions; exp_pace_pre = sqrt(pace_pre * opp_pace_pre); exp_3pa_pre = t3_rate_pre * opp_t3_allowed_idx_pre * exp_pace_pre / 100. Columns: t3_rate_pre, t3_allowed_idx_pre, exp_3pa_pre.
### nba.team_assisted_fgm_expectation
ast_rate=ast/fgm; fg_pct=fgm/fga; fga_pp=fga/possessions; each (E,20) -> ast_rate_pre, fg_pct_pre, fga_pp_pre. exp_ast_fgm_pre = exp_pace_pre * fga_pp_pre * fg_pct_pre * ast_rate_pre. Columns: ast_rate_pre, fg_pct_pre, fga_pp_pre, exp_ast_fgm_pre.
### nba.three_point_variance_load
fg2a=fga-fg3a; fg2m=fgm-fg3m; p3=fg3m/fg3a; p2=fg2m/fg2a; (E,20) of p3, p2, fg3a, fg2a, fta -> p3_pre, p2_pre, fg3a_pre, fg2a_pre, fta_pre (internal). pace_dev2 = (possessions - (E,20) of possessions)^2 evaluated per game using that game's own _pre (so pace_dev2_g = (possessions_g - pace_pre_g)^2, the value of the EWMA that game G would have seen); var_pace_pre = (E,40) of pace_dev2. ppp_pre = (E,20) of ppp100, divided by 100.
var_shot_pre = fg3a_pre*9*p3_pre*(1-p3_pre) + fg2a_pre*4*p2_pre*(1-p2_pre). var_total_pre = var_pace_pre*ppp_pre^2 + var_shot_pre + opp_var_shot_pre. Columns: var_pace_pre, var_shot_pre, var_total_pre.
### nba.bench_minutes_distribution
bench_min = 240 + 25*n_ot - st_min; bench_ppm = bench_pts / bench_min (NaN if bench_min <= 0). bench_min_pre=(E,30) of bench_min. bench_min_sd_pre = sqrt( (E,30) of d ), d_g = (bench_min_g - bench_min_pre_g)^2 (using each game's own bench_min_pre). Shrunk ppm: cp = sum over the team's strictly earlier games of bench_pts (NaN skipped, 0 if none), cm = same sum of bench_min; bench_ppm_shr_pre = (cp + 300*lg(bench_ppm)) / (cm + 300). exp_bench_pts_pre = bench_min_pre * bench_ppm_shr_pre. Columns: bench_min_pre, bench_min_sd_pre, bench_ppm_shr_pre, exp_bench_pts_pre.
### nba.own_game_environment
ppp_opp_d = opp_pts/possessions*100. env_ortg_pre=(E,20) of ppp100; env_drtg_pre=(E,20) of ppp_opp_d. env_exp_ortg_pre = env_ortg_pre + opp_env_drtg_pre - lg(ppp100). env_exp_pts_pre = exp_pace_pre*env_exp_ortg_pre/100. env_sd_pts_pre = sqrt((E,20) of e), e_g = (pts_g - (E,20) of pts evaluated for game g)^2. Columns: exp_pace_pre, env_exp_ortg_pre, env_exp_pts_pre, env_sd_pts_pre.
### nba.team_stat_pair_difference_model
fg3_rate_shr_pre = (cum3m + 150*lg(fg3m/fg3a)) / (cum3a + 150) with cum3m, cum3a the team's cumulative fg3m, fg3a over strictly earlier games (0 if none) and lg of the per-game ratio fg3m/fg3a. exp_3pm_pre = exp_3pa_pre * fg3_rate_shr_pre. nb_disp3_pre = max(0, (v - mu)/mu^2) where mu, v = mean and sample variance (ddof=1) of the team's fg3m over its strictly earlier games, requiring at least 20 earlier games (else NaN). Columns: fg3_rate_shr_pre, exp_3pm_pre, nb_disp3_pre.
## Output
Write `/tmp/claude-0/out/blind_nba_team.csv` with columns game_id, team, then ALL 34 feature columns named above (ff_*_pre x13, t3_rate_pre, t3_allowed_idx_pre, exp_3pa_pre, ast_rate_pre, fg_pct_pre, fga_pp_pre, exp_ast_fgm_pre, var_pace_pre, var_shot_pre, var_total_pre, bench_min_pre, bench_min_sd_pre, bench_ppm_shr_pre, exp_bench_pts_pre, exp_pace_pre, env_exp_ortg_pre, env_exp_pts_pre, env_sd_pts_pre, fg3_rate_shr_pre, exp_3pm_pre, nb_disp3_pre), one row per (game_id, team) of the universe, and `/tmp/claude-0/out/blind_nba_team_notes.json` = {"ambiguities":[...]}. Report only a short list of the ambiguities you resolved; you have nothing to compare to.

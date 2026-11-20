# Blind brief: CBB batch 6 (player box scores), seven pre-game player inputs (36 value columns)

You get `data/player_box/player_box_<season>.parquet` (ESPN men's college basketball player box scores, one file per season 2012-2027). Write your own implementation
from this text only and write `out.csv` with one row per (game_id, player) and exactly the columns listed under Output (empty cell = missing). Use float64 throughout.
Do not look for any other implementation.

## 1. Box rows and appearances
* Read every file. Keep rows with season_type in {2, 3} and season >= 2012. date = the calendar date of game_date.
* Stat columns: points, rebounds, offensive_rebounds, defensive_rebounds, assists, turnovers, field_goals_made (fgm), field_goals_attempted (fga),
  three_point_field_goals_made (fg3m), three_point_field_goals_attempted (fg3a), free_throws_made (ftm), free_throws_attempted (fta). A missing stat counts as 0.
  Short names: pts, reb, oreb, dreb, ast, tov. fg2m = fgm - fg3m, fg2a = fga - fg3a. pu = fga + 0.44 * fta + tov.
* **Appearance**: a kept row with athlete_id present and minutes > 0 (missing minutes is not > 0). min = minutes.
  A player's appearances (any team, any season) are ordered by (date, game_id).
* Player id = athlete_id (an integer). Team T = team_id; its opponent O = opponent_team_id.

## 2. Team-games
* A team-game is each distinct (game_id, team_id) among the kept rows (appearances or not). Its date = that game's date, season = the row season, O = opponent_team_id.
* Team totals: the sums over ALL kept rows of that team in that game (appearance or not; missing stat = 0; missing minutes = 0) of fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, reb,
  ast, tov, pu and minutes (t_min).
* opp_X = the opponent's total X in the same game (the team-game (game_id, O)); 0 if that team-game does not exist.
* live_miss = (fga - fgm) + 0.5 * (fta - ftm); opp_live_miss likewise from the opponent's totals.
* A team's team-games are ordered by (date, game_id).

## 3. Exponentially weighted sums
For a sequence of items (a player's appearances, or a team's team-games) and a per-item value x, with half-life h and r = 0.5 ** (1 / h):
W(x) at item i = sum over items j <= i of r ** (i - j) * x_j (i - j counts items, not days). A row of game g dated d reads the value at the entity's LAST item dated strictly
before d ("state before d"). Nothing dated d or later is ever used.

## 4. Row universe
* Output team-games: team-games with season >= 2013.
* For output team-game (g, T) dated d: prev = T's last 5 team-games dated strictly before d (fewer if T has fewer; 2012 team-games count).
  Candidates = players with an appearance for T in one of those games; q = the latest date among those appearances.
* A player who is a candidate for both teams of g is kept only for the team with the larger q (equal q: the smaller team_id).
* One output row per remaining (g, player): game_id, team = athlete_id (integer), with pteam = T and opp = O of that team-game.

## 5. Role and league priors
* Role of a row's player: from athlete_position_abbreviation of his latest appearance dated before d: "C" -> C; "F", "F-C", "PF", "SF" -> F; "G", "G-F", "PG", "SG" -> G; anything else
  (including missing) -> X.
* Player priors of season S (for rows of season S) come from the appearances of season S - 1 only. For role C, F or G: the appearances of season S - 1 whose OWN row position maps to
  that role (same mapping); if there are none, or their minutes sum to 0, use all appearances of S - 1. Role X: all appearances of S - 1.
  * rate_x = sum(x) / sum(min) for x in pts, reb, ast, fga, fta, fg3a.
  * pct_fg3 = sum(fg3m)/sum(fg3a); pct_fg2 = sum(fg2m)/sum(fg2a); pct_ft = sum(ftm)/sum(fta); fg3_share = sum(fg3a)/sum(fga).
  * phi_x for x in pts, reb, ast, fg3m: within that same set of appearances, take each player with >= 10 appearances in the set; m = his mean of x, v = his sample variance of x
    (denominator n - 1) over those appearances; phi = max(v - m, 0) / m ** 2 if m > 0 else 0. phi_x = the plain mean of phi over those players (0 if none).
* Team constants of season S from all team-games of season S - 1: fg3a_rate = sum(fg3a)/sum(fga); tov_per_pu = sum(tov)/sum(pu);
  reb_per_miss = (sum(reb) + sum(opp_reb)) / (sum(live_miss) + sum(opp_live_miss)).

## 6. Player state (over the player's appearances, state before d)
Per appearance, also attach its team-game totals of team T: t_fgm, t_ast, t_reb, t_opp_reb (= opp_reb of that team-game), t_pu, t_min.
* With h = 10: W_min = W(min); W_pts, W_reb, W_ast, W_fga, W_fta, W_fg3a; W_pu = W(pu); W_exp_pu = W(exp_pu) where exp_pu = t_pu * min / (t_min / 5) if t_min > 0 else 0;
  W_tast = W(t_ast); W_tfgm_o = W(t_fgm - fgm); W_greb = W(t_reb + t_opp_reb).
* min_ewm = W(min) / W(1) with h = 5.
* Career (unweighted, all appearances up to the state): C_fg3_m, C_fg3_a, C_fg2_m, C_fg2_a, C_ft_m, C_ft_a = cumulative sums of fg3m, fg3a, fg2m, fg2a, ftm, fta.
* Recent: R_s_m, R_s_a = sums over the last 10 appearances (fewer if fewer) of the same makes / attempts.
* Window: over the last 15 appearances (fewer if fewer), for x in pts, reb, ast, fg3m: n = number of appearances in the window, mean, sample variance (n - 1; missing if n < 2).

## 7. Team state (over the team's team-games, h = 10, state before d)
For a team: W_one = W(1); miss_ewm = W(live_miss) / W_one; fg3a_allowed = W(opp_fg3a) / W(opp_fga) (missing if W(opp_fga) <= 0); tov_forced = W(opp_tov) / W(opp_pu) (missing if <= 0);
orb_rate = W(oreb) / W(oreb + opp_dreb) (missing if <= 0). The row's own team is T and its opponent is O; every opponent value is missing when O has no team-game dated before d.

## 8. Columns (P(...) = player prior of the row's season and role; L(...) = team constant of the row's season; a/b with b <= 0 is missing)
cbb.player_usage:
* pu_usg_pre = (W_pu + 0.20 * 20) / (W_exp_pu + 20).
* pu_x40_pre for x in pts, reb, ast, fga, fta = 40 * (W_x + 200 * P(rate_x)) / (W_min + 200).

cbb.player_shooting_regression, for s in fg3, fg2, ft with K = 100, 80, 60:
* psr_s_shrunk_pre = (C_s_m + K * P(pct_s)) / (C_s_a + K).
* psr_s_luck_pre = R_s_m / R_s_a - psr_s_shrunk_pre (missing if R_s_a = 0).

cbb.stat_dist, for x in pts, reb, ast, fg3m (window of section 6): if n < 5 both columns are missing; otherwise with m = mean, v = variance,
phi_raw = max(v - m, 0) / m ** 2 if m > 0 else 0:
* psd_x_mean_pre = m.
* psd_x_phi_pre = n / (n + 10) * phi_raw + 10 / (n + 10) * P(phi_x).

cbb.player_three_volume:
* pv_fg3a40_pre = 40 * (W_fg3a + 200 * P(rate_fg3a)) / (W_min + 200).
* pv_fg3_rate_pre = (W_fg3a + 50 * P(fg3_share)) / (W_fga + 50).
* pv_opp_fg3a_rel_pre = fg3a_allowed of O / L(fg3a_rate).
* pv_fg3a_exp_pre = pv_fg3a40_pre * min_ewm / 40 * rel, where rel = pv_opp_fg3a_rel_pre, or 1 when it is missing.

cbb.three_makes_compound_distribution: mu = pv_fg3a_exp_pre; a = 100 * P(pct_fg3) + C_fg3_m; b = 100 * (1 - P(pct_fg3)) + (C_fg3_a - C_fg3_m).
* Attempts N: negative binomial with mean mu and variance 1.5 * mu, i.e. pmf NB(N) = Gamma(N + n) / (Gamma(n) N!) * p ** n * (1 - p) ** N with n = 2 * mu, p = 2/3, for N = 0, 1, ..., 40 only
  (mass above 40 is dropped, no renormalisation). If mu = 0: NB(0) = 1 and all other N have 0.
* Makes given N: Beta-binomial(N, a, b): P(X = x | N) = C(N, x) * B(x + a, N - x + b) / B(a, b).
* pc_p_gek_pre for k = 1, 2, 3, 4 = sum over N = 0..40 of NB(N) * (1 - sum over x = 0..min(k - 1, N) of P(X = x | N)).
* pc_mean_makes_pre = mu * a / (a + b).

cbb.assist_creation:
* pa_team_ast_share_pre = W_ast / W_tast.
* pa_ast_pct_pre = W_ast / W_tfgm_o.
* pa_opp_tov_forced_rel_pre = tov_forced of O / L(tov_per_pu).

cbb.rebound_pool:
* pr_pool_pre = miss_ewm of T + miss_ewm of O.
* pr_reb_share_pre = W_reb / W_greb.
* pr_exp_reb_pre = pr_reb_share_pre * pr_pool_pre * L(reb_per_miss).
* pr_opp_orb_rate_pre = orb_rate of O.

## Output
`out.csv`: game_id, team (= athlete_id, integer), then the 36 value columns
pu_usg_pre, pu_pts40_pre, pu_reb40_pre, pu_ast40_pre, pu_fga40_pre, pu_fta40_pre,
psr_fg3_shrunk_pre, psr_fg3_luck_pre, psr_fg2_shrunk_pre, psr_fg2_luck_pre, psr_ft_shrunk_pre, psr_ft_luck_pre,
psd_pts_mean_pre, psd_pts_phi_pre, psd_reb_mean_pre, psd_reb_phi_pre, psd_ast_mean_pre, psd_ast_phi_pre, psd_fg3m_mean_pre, psd_fg3m_phi_pre,
pv_fg3a40_pre, pv_fg3_rate_pre, pv_opp_fg3a_rel_pre, pv_fg3a_exp_pre,
pc_p_ge1_pre, pc_p_ge2_pre, pc_p_ge3_pre, pc_p_ge4_pre, pc_mean_makes_pre,
pa_team_ast_share_pre, pa_ast_pct_pre, pa_opp_tov_forced_rel_pre,
pr_pool_pre, pr_reb_share_pre, pr_exp_reb_pre, pr_opp_orb_rate_pre.
Write floats with full precision (e.g. repr / 17 significant digits). Rows in any order. Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

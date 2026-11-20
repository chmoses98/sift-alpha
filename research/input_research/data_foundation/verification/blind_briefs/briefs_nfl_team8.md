# Blind brief: NFL batch 8 (drive model, team rows), seven pre-game inputs (24 value columns)

You get `data/games.csv` (nflverse schedule) and `data/pbp/play_by_play_<season>.parquet` (nflverse play-by-play 2010-2026). Write your own implementation from this text only
and write `out.csv` with one row per (game_id, team) and exactly the columns listed under Output (empty cell = missing). Use float64. Do not look for any other implementation.

## 1. Games and team-games
* games.csv rows with season >= 2010 and home_score present; if a game_id occurs twice keep the first. date = gameday.
* Replace team codes OAK -> LV, SD -> LAC, STL -> LA in home_team / away_team and in play-by-play `posteam`.
* Two team-games per game: home slot (team = home_team, opp = away_team, pts = home_score, pts_a = away_score, is_home = 1, s = +1) and away slot (team = away_team, opp = home_team,
  pts = away_score, pts_a = home_score, is_home = 0, s = -1). If location == "Neutral", s = 0 for both slots (is_home is unchanged).
* A team's team-games are ordered by (date, game_id).

## 2. Per team-game quantities from play-by-play (rows whose game_id is a kept game)
* T = posteam (codes replaced); rows with T missing are ignored for drives and plays.
* Drives of (game, T): the distinct non-missing fixed_drive values among T's rows. A drive's result = the first non-missing fixed_drive_result among its rows (file order).
  drives = number of drives; td = number of drives with result "Touchdown"; fg = number with result "Field goal".
* plays = number of T's rows with play_type "pass" or "run".
* Missing counts (no rows) are 0. o_drives, o_td, o_fg, o_plays = the opponent's values in the same game.
* Quarter totals (game level, all rows of the game, regulation only): for q = 1..4, M_q = max over rows with qtr == q of (total_home_score + total_away_score) (missing score = 0).
  If a quarter has no rows, M_q = M_{q-1} (M_0 = 0). Then C_q = max(M_1, ..., M_q) and Q_q = C_q - C_{q-1} (C_0 = 0). A game with no pbp row at all has missing quarter totals.

## 3. Team state and league constants
* For a team, half-life 8 and r = 0.5 ** (1/8): W(x) at team-game i = sum over its team-games j <= i of r ** (i - j) x_j. A row of game g dated d reads the team's W values at its last
  team-game dated strictly before d; if none, all its W values are 0 (n = 0 below). Quantities: W_one = W(1), W(drives), W(o_drives), W(pts), W(pts_a), W(td), W(o_td), W(fg), W(o_fg), W(plays).
* League constants for season S, from all team-games (both slots) of season S - 1: dpg = mean of drives; ppd = sum(pts)/sum(drives); tdpd = sum(td)/sum(drives); fgpd = sum(fg)/sum(drives);
  h = mean of (pts - pts_a) over team-games with is_home = 1 and s != 0.
* shr(n, a, b, lg) = n/(n + 8) * R + 8/(n + 8) * lg where R = a / b if b > 0 else 0.

## 4. Row values (row = team-game (g, T, O) of season S >= 2011; T's state "t", O's state "o"; nT = t.W_one, nO = o.W_one; league of S)
* E_dr = 0.5 * (shr(nT, t.W(drives), t.W_one, dpg) + shr(nO, o.W(o_drives), o.W_one, dpg)).
* off_ppd = shr(nT, t.W(pts), t.W(drives), ppd); def_ppd = shr(nO, o.W(pts_a), o.W(o_drives), ppd).
* td_o = shr(nT, t.W(td), t.W(drives), tdpd); td_d = shr(nO, o.W(o_td), o.W(o_drives), tdpd); fg_o = shr(nT, t.W(fg), t.W(drives), fgpd); fg_d = shr(nO, o.W(o_fg), o.W(o_drives), fgpd).
* mtp_mean_pre = E_dr * off_ppd * def_ppd / ppd + 0.5 * h * s.
* mtp_margin_pre = mtp_mean_pre - (the opponent row's mtp_mean_pre in the same game); mtp_total_pre = sum of the two.
* mtd_lambda_pre = E_dr * td_o * td_d / tdpd.
* drl_p_td_pre = td_o * td_d / tdpd; drl_p_fg_pre = fg_o * fg_d / fgpd; drl_p_none_pre = max(0, 1 - drl_p_td_pre - drl_p_fg_pre); drl_exp_points_pre = E_dr * (7 drl_p_td_pre + 3 drl_p_fg_pre).
* x_plays = t.W(plays)/t.W_one + o.W(plays)/o.W_one (missing if a W_one is 0). tot_plays = plays + o_plays of the row's own game (outcome; used only in reference windows).

## 5. Reference-window columns (rows of season S >= 2013 only; earlier rows exist only to serve as reference)
Reference REF(S) = the rows (section 4) of seasons S-3 .. S-1 (seasons >= 2011). Their realised outcomes (pts, pts_a, td, tot_plays, quarter totals) are used.
Tercile assignment: on a reference vector v_ref, c1, c2 = the 1/3 and 2/3 quantiles (linear interpolation, numpy default); a value x is in bin 0 if x <= c1, bin 1 if x <= c2, else bin 2
(reference rows are binned with the same rule).
* mtp_sd_pre: bins on mtp_mean_pre; sample SD (n - 1) of (pts - mtp_mean_pre) over the REF rows in the row's bin.
* mtd_var_pre, mtd_p_ge1_pre: bins on mtd_lambda_pre; D = sample variance of (td - mtd_lambda_pre) over REF rows in the bin divided by the mean mtd_lambda_pre of those rows.
  mtd_var_pre = lambda * D. mtd_p_ge1_pre = 1 - exp(-lambda) if D <= 1 else 1 - (k / (k + lambda)) ** k with k = lambda / (D - 1).
* hms: residual e = pts - pts_a - mtp_margin_pre on REF rows; cell = 3 * (bin of |mtp_margin_pre|) + (bin of mtp_total_pre) (both binned on the REF values); pooled = sample SD of all REF e;
  cellSD_k = n_k/(n_k + 100) * SD_k + 100/(n_k + 100) * pooled with SD_k the sample SD of e in cell k (0 if n_k <= 1). hms_sd_pre = cellSD of the row's cell.
  z = e / cellSD of each REF row's own cell; hms_q05_mult_pre / hms_q95_mult_pre = the 0.05 / 0.95 quantiles of z over REF (linear interpolation).
* tps: OLS (least squares) of tot_plays on (1, x_plays, |mtp_margin_pre|) over REF rows with x_plays present; tps_exp_plays_pre = fitted value at the row; tps_sd_pre = sqrt(SSE / (n - 3)).
* qos: H = REF rows with is_home = 1 and quarter totals present. For each H row: a_q = 1{Q_q = max_q Q} / (number of quarters attaining the max); m = 1{min_q Q_q = 0}.
  Weights w = exp(-0.5 ((x - x_H) / 3) ** 2) with x = the row's mtp_total_pre, x_H = each H row's mtp_total_pre. qos_argmax_qq_pre = sum(w a_q)/sum(w); qos_min0_pre = sum(w m)/sum(w).
* psc: over H' = REF rows with is_home = 1: u = pts - mtp_mean_pre, v = pts_a - (the away row's mtp_mean_pre); bins on mtp_total_pre of H'; rho_p = Pearson(u, v) over H';
  rho_k = n_k/(n_k + 150) * Pearson(u, v over bin k) + 150/(n_k + 150) * rho_p. psc_rho_pre = rho of the row's bin.

## Output
`out.csv`: game_id, team (code), then mtp_mean_pre, mtp_margin_pre, mtp_total_pre, mtp_sd_pre, mtd_lambda_pre, mtd_var_pre, mtd_p_ge1_pre, hms_sd_pre, hms_q05_mult_pre, hms_q95_mult_pre,
tps_exp_plays_pre, tps_sd_pre, qos_argmax_q1_pre, qos_argmax_q2_pre, qos_argmax_q3_pre, qos_argmax_q4_pre, qos_min0_pre, psc_rho_pre, drl_p_td_pre, drl_p_fg_pre, drl_p_none_pre, drl_exp_points_pre
for every team-game of season >= 2013. Full float precision ('%.17g'). Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

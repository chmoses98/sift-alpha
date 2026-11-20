# Blind brief: NFL batch 8, score-path inputs (two inputs, 14 value columns)

You get `data/games.csv` (nflverse schedule) and `data/pbp/play_by_play_<season>.parquet` (2010-2026). Write your own implementation from this text only and write `out.csv`
with one row per (game_id, team) and the columns under Output (empty cell = missing). float64. Do not look for any other implementation.

## A. Model margin and total (the conditioning variables)
Build the team-game rows of seasons >= 2011 and their mtp_margin_pre and mtp_total_pre exactly as in the APPENDIX below (APPENDIX sections 1-4; only those two columns
and the rows' identity, season and is_home are needed here).

## B. Per-game outcomes (used only as reference rows of LATER seasons)
* Path of a game: its pbp rows ordered by play_id (as a number). m_k = total_home_score - total_away_score of row k (a missing score counts 0); prepend m_0 = 0.
* q4_abs14 = 1 if |m at the LAST row with qtr <= 3| >= 14 (if no such row, use m_0 = 0), else 0.
* any_abs21 = 1 if max over k (including m_0) of |m_k| >= 21. max_abs = that maximum.
* lead_chg = number of sign changes between consecutive NONZERO values of the path (zeros are removed first; 0 if fewer than two nonzero values).
* trailed24: w = sign of the last m; trailed24 = 1 if w != 0 and min over k of (w * m_k) <= -24, else 0.
* home_maxlead = max over k of m_k; away_maxlead = max over k of (-m_k). team_lead14 of a row = 1 if (home_maxlead if is_home == 1 else away_maxlead) >= 14, else 0.
* lc_ge2 = 1 if lead_chg >= 2 else 0.
* Second-half shares of a row (game, team T): T's pbp rows with posteam == T (codes OAK -> LV, SD -> LAC, STL -> LA), play_type "pass" or "run", qtr >= 3 and score_differential present.
  Bins of score_differential: <= -17 (m17), -16..-9 (m9), -8..-1 (m1), 0 (z), 1..8 (p1), 9..16 (p9), >= 17 (p17). h2_b = count in bin b / count of those plays (missing if there are none).
  A game with no pbp row at all has every outcome missing.

## C. Kernel frequencies (rows of season S >= 2013)
REF = the rows (section A) of seasons S-3 .. S-1. For an output row with model margin x_m and total x_t, weight of each REF row r: w_r = exp(-0.5 * (((x_m - m_r) / 4) ** 2 + ((x_t - t_r) / 5) ** 2))
with m_r, t_r its mtp_margin_pre and mtp_total_pre. For each outcome o below, value = sum over REF rows with o present of w_r * o_r divided by the sum of w_r over the same rows.
* nfl.market_free_score_state_blowout_mass: ssb_q4_abs14_pre (q4_abs14), ssb_any_abs21_pre (any_abs21), ssb_h2_share_{m17,m9,m1,z,p1,p9,p17}_pre (h2_b of the REF row's own team).
* nfl.score_path_sequence_sim: sps_exp_max_abs_margin_pre (max_abs), sps_exp_lead_changes_pre (lead_chg), sps_p_lead_changes_ge2_pre (lc_ge2), sps_p_winner_trailed24_pre (trailed24),
  sps_p_team_max_lead_ge14_pre (team_lead14 of the REF row).

## Output
`out.csv` for every team-game of season >= 2013: game_id, team (code), then ssb_q4_abs14_pre, ssb_any_abs21_pre, ssb_h2_share_m17_pre, ssb_h2_share_m9_pre, ssb_h2_share_m1_pre, ssb_h2_share_z_pre,
ssb_h2_share_p1_pre, ssb_h2_share_p9_pre, ssb_h2_share_p17_pre, sps_exp_max_abs_margin_pre, sps_exp_lead_changes_pre, sps_p_lead_changes_ge2_pre, sps_p_winner_trailed24_pre,
sps_p_team_max_lead_ge14_pre. Floats '%.17g'. Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

# APPENDIX (model margin and total; same rules as a separately verified input)
### 1. Games and team-games
* games.csv rows with season >= 2010 and home_score present; if a game_id occurs twice keep the first. date = gameday.
* Replace team codes OAK -> LV, SD -> LAC, STL -> LA in home_team / away_team and in play-by-play `posteam`.
* Two team-games per game: home slot (team = home_team, opp = away_team, pts = home_score, pts_a = away_score, is_home = 1, s = +1) and away slot (team = away_team, opp = home_team,
  pts = away_score, pts_a = home_score, is_home = 0, s = -1). If location == "Neutral", s = 0 for both slots (is_home is unchanged).
* A team's team-games are ordered by (date, game_id).

### 2. Per team-game quantities from play-by-play (rows whose game_id is a kept game)
* T = posteam (codes replaced); rows with T missing are ignored for drives and plays.
* Drives of (game, T): the distinct non-missing fixed_drive values among T's rows. A drive's result = the first non-missing fixed_drive_result among its rows (file order).
  drives = number of drives; td = number of drives with result "Touchdown"; fg = number with result "Field goal".
* plays = number of T's rows with play_type "pass" or "run".
* Missing counts (no rows) are 0. o_drives, o_td, o_fg, o_plays = the opponent's values in the same game.
* Quarter totals (game level, all rows of the game, regulation only): for q = 1..4, M_q = max over rows with qtr == q of (total_home_score + total_away_score) (missing score = 0).
  If a quarter has no rows, M_q = M_{q-1} (M_0 = 0). Then C_q = max(M_1, ..., M_q) and Q_q = C_q - C_{q-1} (C_0 = 0). A game with no pbp row at all has missing quarter totals.

### 3. Team state and league constants
* For a team, half-life 8 and r = 0.5 ** (1/8): W(x) at team-game i = sum over its team-games j <= i of r ** (i - j) x_j. A row of game g dated d reads the team's W values at its last
  team-game dated strictly before d; if none, all its W values are 0 (n = 0 below). Quantities: W_one = W(1), W(drives), W(o_drives), W(pts), W(pts_a), W(td), W(o_td), W(fg), W(o_fg), W(plays).
* League constants for season S, from all team-games (both slots) of season S - 1: dpg = mean of drives; ppd = sum(pts)/sum(drives); tdpd = sum(td)/sum(drives); fgpd = sum(fg)/sum(drives);
  h = mean of (pts - pts_a) over team-games with is_home = 1 and s != 0.
* shr(n, a, b, lg) = n/(n + 8) * R + 8/(n + 8) * lg where R = a / b if b > 0 else 0.

### 4. Row values (row = team-game (g, T, O) of season S >= 2011; T's state "t", O's state "o"; nT = t.W_one, nO = o.W_one; league of S)
* E_dr = 0.5 * (shr(nT, t.W(drives), t.W_one, dpg) + shr(nO, o.W(o_drives), o.W_one, dpg)).
* off_ppd = shr(nT, t.W(pts), t.W(drives), ppd); def_ppd = shr(nO, o.W(pts_a), o.W(o_drives), ppd).
* td_o = shr(nT, t.W(td), t.W(drives), tdpd); td_d = shr(nO, o.W(o_td), o.W(o_drives), tdpd); fg_o = shr(nT, t.W(fg), t.W(drives), fgpd); fg_d = shr(nO, o.W(o_fg), o.W(o_drives), fgpd).
* mtp_mean_pre = E_dr * off_ppd * def_ppd / ppd + 0.5 * h * s.
* mtp_margin_pre = mtp_mean_pre - (the opponent row's mtp_mean_pre in the same game); mtp_total_pre = sum of the two.
* mtd_lambda_pre = E_dr * td_o * td_d / tdpd.
* drl_p_td_pre = td_o * td_d / tdpd; drl_p_fg_pre = fg_o * fg_d / fgpd; drl_p_none_pre = max(0, 1 - drl_p_td_pre - drl_p_fg_pre); drl_exp_points_pre = E_dr * (7 drl_p_td_pre + 3 drl_p_fg_pre).
* x_plays = t.W(plays)/t.W_one + o.W(plays)/o.W_one (missing if a W_one is 0). tot_plays = plays + o_plays of the row's own game (outcome; used only in reference windows).


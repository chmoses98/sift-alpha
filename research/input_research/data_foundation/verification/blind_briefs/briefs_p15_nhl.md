# Blind re-implementation brief (Phase 15): NHL pre-game features, 19 catalog inputs, three output tables

You are an independent verifier. Re-implement every column below from THIS TEXT ALONE and write the three CSV files named at the end. Use only python with pandas / numpy / scipy / the standard library.

Data (read-only) under `D = /tmp/claude-0/-home-user/4b121d0a-de18-5db8-915a-3a1ef1a5904f/scratchpad/blind/nhl/data/` (concatenate all season files of each kind):
`D/nhl/games_<season>.parquet`, `D/moneypuck/team_games_<season>.parquet`, `D/moneypuck/shots_<season>.parquet`, `D/players/{team_states,goals,shots,goalies,players}_<season>.parquet`.
Hard rules: do NOT read, list or search anything under `/home/user`, any git repository, or any other directory than that data directory and your own working/output directory. Do not look for an existing implementation. Where the text is ambiguous choose the most literal reading and RECORD the choice in the notes file.
Everything is strictly pre-game: a row for a game on date d may only use rows of games with date STRICTLY BEFORE d. A team (and a player) plays at most once per date.

## Common conventions
* date = `game_date` parsed as a date. `E(x; H, m)` = for one entity, order its rows chronologically (all seasons concatenated, no reset) and take exactly the pandas expression `series_of_x.shift(1).ewm(halflife=H, min_periods=m).mean()` (pandas defaults adjust=True, ignore_na=False).
* "over rows with date < d" = over all rows of the stated universe dated strictly before d (all teams / players, all seasons); the result is the same for every row of date d (within the stated group).
* "the team's earlier rows" = that team's universe rows with an earlier date (all seasons unless "this season" is stated).
* `o_X` = the value of X on the OTHER team's row of the same game.
* A mean or ratio over an empty set (or with a zero denominator) is NaN. Any formula with a NaN input gives NaN unless stated otherwise.

# TABLE 1: team-game table from game results (key game_id, team)
Universe: `games` rows with final == True. Two rows per game: team = home_team_id (home = True) and team = away_team_id (home = False); opp = the other team; season; gtype = game_type (2 = regular season, 3 = playoffs); gf / ga = the team's own / the opponent's final score (home_score, away_score); lpt = last_period_type as text. beyond = 1 if lpt is "OT" or "SO" else 0. win = 1 if gf > ga else 0. Sort by (date, game_id, team). Output ALL rows; a column defined only for regular rows is NaN on playoff rows and vice versa.
"regular rows" = gtype 2; "playoff rows" = gtype 3.

## nhl.settlement_goal_pmf (regular rows only) -> sg_p_regtie_pre, sg_p_ge1_pre, sg_p_ge2_pre, sg_p_ge3_pre
rgd = 0 if beyond == 1 else gf - ga. r_pre = E(rgd; 40, 10) over the team's REGULAR rows only (all seasons). gap = r_pre - o_r_pre. bucket = 0 if gap < -0.75; 1 if -0.75 <= gap < -0.25; 2 if -0.25 <= gap < 0.25; 3 if 0.25 <= gap < 0.75; 4 if gap >= 0.75; undefined if gap is NaN. Cell = (bucket, home).
Events of a row: regtie = beyond; ge1 = 1 if gf - ga >= 1; ge2 = 1 if gf - ga >= 2; ge3 = 1 if gf - ga >= 3.
Over regular rows WITH a defined bucket and date < d: nL = their number and L_x = (sum of event x) / nL; within the row's own cell: nc = number and Sc_x = sum of event x. sg_p_<x>_pre = (Sc_x + 200 * L_x) / (nc + 200), for rows with a defined bucket (NaN otherwise, and NaN when nL = 0).

## nhl.team_season_points_distribution (regular rows only) -> tp_points_pre, tp_exp_final_pre, tp_sd_final_pre
Per regular row: rw = 1 if win and not beyond; ew = 1 if win and beyond; el = 1 if not win and beyond. Over the team's earlier REGULAR rows of the same season: n, RW, EW, EL (counts / sums). League over ALL regular rows with date < d (all seasons): q_rw, q_ew, q_el = sum / count.
p_rw = (RW + 20 * q_rw) / (n + 20), likewise p_ew, p_el. ppg = 2 * (p_rw + p_ew) + p_el. var = 4 * (p_rw + p_ew) + p_el - ppg^2. L = 48 if season == 2012; 56 if season == 2020; else 82. R = max(L - n, 0). pts = 2 * (RW + EW) + EL.
tp_points_pre = pts. tp_exp_final_pre = pts + R * ppg. tp_sd_final_pre = sqrt(R * var).

## nhl.playoff_context (all rows) -> pc_goals_ratio_pre, pc_ot_ratio_pre, pc_homewin_ratio_pre
Using HOME rows only (one per game) with date < d, separately for playoff games (gtype 3) and regular games (gtype 2): mean of (gf + ga); mean of beyond; mean of win. Each column = playoff mean / regular mean (goals, beyond, home win in that order); NaN if either set is empty or the regular mean is not > 0.

## nhl.series_context (playoff rows only) -> sc_p_series_pre, sc_goal_diff_pre, sc_p_home_hist_pre
Series key = (season, min(team, opp), max(team, opp)); its games ordered by (date, game_id) are numbered k = 1, 2, ... top = the HOME team of the series' first game. For each team, wins entering game k = number of the series' earlier games it won (win of its own row).
ph(d) = share of home wins among playoff HOME rows (all series, all seasons) with date < d; NaN if there are fewer than 50 such rows. sc_p_home_hist_pre = ph(d).
F(a, b, g) = 1 if a >= 4; else 0 if b >= 4; else 0.5 if g > 7; else p * F(a + 1, b, g + 1) + (1 - p) * F(a, b + 1, g + 1) with p = ph if g is in {1, 2, 5, 7} else 1 - ph.
sc_p_series_pre = F(wins of top, wins of the other team, k) on top's row and 1 - F(wins of top, wins of the other team, k) on the other team's row; NaN if ph is NaN. sc_goal_diff_pre = sum of (gf - ga) of the team's rows in the earlier games of the series (0 in game 1).

## nhl.ratings_script_distribution (regular rows only) -> rs_xgf60_pre, rs_xga60_pre, rs_lambda_pre
From moneypuck team_games keep rows with situation == "all" and a non-null team_id; first row per (game_id, team_id). For the matching regular (game_id, team) row: ice = iceTime / 3600 if iceTime > 0 else NaN; xgf60 = scoreVenueAdjustedxGoalsFor / ice; xga60 = scoreVenueAdjustedxGoalsAgainst / ice (NaN when there is no moneypuck row).
For each of xgf60, xga60: take the team's last up to 40 earlier REGULAR rows (all seasons; a row counts toward the 40 whether or not its value is NaN); weighted mean of the non-NaN values with weight 0.5^(age/20), where age = 1 for the most recent of those rows, 2 for the one before, ...; k = number of non-NaN values; the mean is NaN if k < 5.
lg(d) = mean of the non-NaN xgf60 over regular rows with date < d. rs_xgf60_pre = (k * mean_xgf + 25 * lg) / (k + 25). rs_xga60_pre = (k * mean_xga + 25 * lg) / (k + 25) (the same lg of xgf60; each with its own k).
hc(d) = mean of (xgf60 - xga60) over HOME regular rows with both values non-NaN and date < d.
rs_lambda_pre = lg * (rs_xgf60_pre / lg) * (o_rs_xga60_pre / lg) + (0.5 if home else -0.5) * hc.

## nhl.game_script_prob (regular rows only) -> gsp_lead20_pre, gsp_tied20_pre, gsp_lead40_pre, gsp_tied40_pre
la = rs_lambda_pre, lb = o_rs_lambda_pre. NaN if either is NaN or <= 0. For T in (20, 40): a = la * T / 60, b = lb * T / 60; Pa(i) = exp(-a) * a^i / i!, Pb(j) = exp(-b) * b^j / j! for i, j = 0..15. gsp_lead<T>_pre = sum over i > j of Pa(i) * Pb(j). gsp_tied<T>_pre = sum over i of Pa(i) * Pb(i).

# TABLE 2: team-game table from the event archive (key game_id, team)
Universe: `team_states` rows with game_type == 2 and season <= 2025 (first row per (game_id, team_id); keep games with exactly two rows). team = team_id; home = is_home; opp = the other team of the game. Sort by (date, game_id, team). Only goals / shots / goalies rows of universe games are used; an event belongs to the home team's row if its is_home is True, else to the away team's row.
Per (game, team) counts from `goals` (0 if none): f10 = goals with period == 1 and t_s < 600; f5 = goals with period == 1 and t_s < 300; fot = goals with period_type == "OT"; fp1, fp2, fp3 = goals with period_type == "REG" and period == 1, 2, 3. a10, a5, aot, ap1, ap2, ap3 = the opponent's counts in the same game.
First goal: tmin = the smallest t_s among the game's goals; if all goals with t_s == tmin belong to one side that side scored first. sf = 1 if the team scored first, 0 if the opponent did, 0.5 if the game has no goal rows or both sides share tmin.
ot_sec = 0 if the row's n_seconds <= 3600; otherwise (smallest t_s among the game's goals with period_type == "OT") - 3600 clipped to [0, 300], or 300 if the game has no such goal. (n_seconds is 3600 or 4800: it marks whether overtime was played, not its length.)
From `shots` rows with kind in ("SOG", "GOAL"): sog_ev = number with strength == "EV"; sog_pp = number with strength == "PP" (0 if none). sog_eva = the opponent's sog_ev.
Starter of a (game, team): among its `goalies` rows, the row with starter == True and the largest toi_s (ties: smallest player_id); if no row has starter == True, the row with the largest toi_s (ties: smallest player_id). starter_id = its player_id, st_toi = its toi_s (undefined if the team has no goalie rows).

## nhl.goalie_start -> gs_top_share_pre, gs_consec_pre, gs_top_rest_pre, gs_p_top_pre
For a team's i-th universe row in chronological order (i = 0, 1, ...; all seasons): if i < 5 everything is NaN. Window = its previous min(20, i) rows. top = the starter_id with the most starts in the window (ties: the one whose latest start in the window is the most recent).
gs_top_share_pre = (starts of top in the window) / (number of window rows). gs_consec_pre = number of consecutive window rows, counting back from the most recent one, whose starter is top (0 if top did not start the most recent one). gs_top_rest_pre = min(days between this row's date and the date of top's most recent start in the window, 14).
y = 1 if this row's own starter_id == top else 0 (defined only when top is defined). b2b = 1 if the team's immediately preceding universe row (any season) is dated exactly one day earlier, else 0.
q(d, b) = mean of y over all universe rows (any team) with defined y, b2b == b and date < d. Over the TEAM's earlier rows with the same b2b value and defined y: sy = sum of y, sn = count. gs_p_top_pre = (sy + 10 * q) / (sn + 10) on rows with a defined top (NaN otherwise). y of the row itself is never used for that row.

## nhl.goalie_minutes_in_net_dist -> gm_p_lt40_pre, gm_p_40_55_pre, gm_p_full_pre
A "start" = a universe row with a defined starter (starter_id, st_toi). Classes of a start: lt40 if st_toi < 2400; 40_55 if 2400 <= st_toi < 3300; full if st_toi >= 3300. q_c(d) = share of class c among all starts with date < d. For a row whose top goalie (defined above) is g: n = number of g's starts (starter_id == g, for any team) with date < d and c_n = how many of them are in class c. gm_p_<c>_pre = (c_n + 25 * q_c) / (n + 25); NaN if top is undefined.

## Shrunk team rates used below
shr(X) = (n * E(X; 60, 10) + 30 * lgX) / (n + 30) with n = min(number of the team's earlier universe rows, 120) and lgX(d) = mean of X over all universe rows with date < d.
f10_s, a10_s, f5_s, a5_s, sf_s = shr of f10, a10, f5, a5, sf. la = (f10_s + o_a10_s) / 2; lb = (o_f10_s + a10_s) / 2.

## nhl.early_window_goal_rate -> ew_gf10_pre, ew_ga10_pre, ew_lambda_pre, ew_p_goal_pre
ew_gf10_pre = f10_s; ew_ga10_pre = a10_s; ew_lambda_pre = la + lb; ew_p_goal_pre = 1 - exp(-(la + lb)).

## nhl.first_goal_hazard -> fgh_gf5_pre, fgh_ga5_pre, fgh_p_first_pre, fgh_first_share_pre
fgh_gf5_pre = f5_s; fgh_ga5_pre = a5_s; fgh_p_first_pre = la / (la + lb); fgh_first_share_pre = sf_s.

## nhl.period_split -> ps_lg_p1_pre, ps_lg_p2_pre, ps_lg_p3_pre, ps_dev_p1_pre, ps_dev_p2_pre, ps_dev_p3_pre
c_k = fp_k + ap_k for k = 1, 2, 3; c_all = c_1 + c_2 + c_3. ps_lg_p<k>_pre = (sum of c_k) / (sum of c_all) over all universe rows with date < d. T_k, T_all = sums of c_k, c_all over the team's earlier rows (all seasons). ps_dev_p<k>_pre = ((T_k + 300 * ps_lg_p<k>_pre) / (T_all + 300)) / ps_lg_p<k>_pre.

## nhl.ot_3v3_rate -> ot_gf5_pre, ot_ga5_pre, ot_p_decided_pre, ot_p_win_pre
t5 = ot_sec / 300. lg(d) = (sum of fot) / (sum of t5) over all universe rows with date < d. F, A, T = sums of fot, aot, t5 over the team's earlier rows (all seasons). ot_gf5_pre = (F + 20 * lg) / (T + 20); ot_ga5_pre = (A + 20 * lg) / (T + 20). la2 = (ot_gf5_pre + o_ot_ga5_pre) / 2; lb2 = (o_ot_gf5_pre + ot_ga5_pre) / 2. ot_p_decided_pre = 1 - exp(-(la2 + lb2)); ot_p_win_pre = la2 / (la2 + lb2).

## nhl.opp_sog_for_rate -> os_ev60_pre, os_pp60_pre, os_eva60_pre, os_exp_sog_faced_pre
n = min(number of the team's earlier universe rows, 80). e(X) = E(X; 40, 5) for X in sog_ev, sog_pp, sog_eva, sec_ev, sec_pp, sec_sh (team_states columns sec_ev, sec_pp, sec_sh). lg_ev(d) = 3600 * (sum of sog_ev) / (sum of sec_ev) and lg_pp(d) = 3600 * (sum of sog_pp) / (sum of sec_pp) over all universe rows with date < d.
os_ev60_pre = (n * 3600 * e(sog_ev) / e(sec_ev) + 15 * lg_ev) / (n + 15). os_pp60_pre = (n * 3600 * e(sog_pp) / e(sec_pp) + 15 * lg_pp) / (n + 15). os_eva60_pre = (n * 3600 * e(sog_eva) / e(sec_ev) + 15 * lg_ev) / (n + 15).
os_exp_sog_faced_pre = lg_ev * (o_os_ev60_pre / lg_ev) * (os_eva60_pre / lg_ev) * e(sec_ev) / 3600 + o_os_pp60_pre * e(sec_sh) / 3600.

# TABLE 3: skater-game table (key game_id, team where `team` holds the player_id)
Universe: `players` rows with game_type == 2 and season <= 2025 (first row per (game_id, player_id)). Sort by (date, game_id, player_id). pg = "D" if position == "D" else "F". The output column `team` = player_id. toi_ev_s, toi_pp_s, gf_ev, gf_pp are NaN on a few rows; the rules below say how such rows are skipped.
gpf = 1 if toi_s > 0 else 0. team_gp = number of the row's team_id's universe games of the same season dated before this game (distinct game_ids of that team in the universe).
pts_ev / pts_pp (per row) = number of `goals` rows of the same game with strength == "EV" / "PP" on which the player is scorer_id, a1_id or a2_id.
From moneypuck `shots` rows whose nhl_game_id is a universe game: own = homeSkatersOnIce if isHomeTeam == 1 else awaySkatersOnIce; other = the other count; state EV if own == other, PP if own > other, otherwise ignored. ixg_ev / ixg_pp (per row) = sum of xGoal over the game's shot rows with shooterPlayerId == player_id in that state (0 if he has none); NaN if the game has no rows at all in the moneypuck shots files.
tgf = sum of `goals` over the universe rows of the same (game_id, team_id); tga = (sum of `goals` over all universe rows of the game) - tgf.
For a per-row quantity X of one player in chronological order (all seasons), wsum(X; N, H) at his i-th row (i = 0, 1, ...) = sum over k = 1..min(N, i) of X[i - k] * 0.5^(k / H).
cur(X) = sum of X over the player's earlier rows of the same season; pv(X) = sum of X over ALL his universe rows of season - 1; pw(X) = the same for season - 2 (0 if none).
"pg-league" sums = over universe rows with the same pg and date < d.

## nhl.ixg_player -> ix_ev60_pre, ix_pp60_pre, ix_exp_pre
For st in (ev, pp), with m0 = 18000 for ev and 3600 for pp: a row is usable if ixg_st and toi_st_s are both non-NaN; x = ixg_st on usable rows else 0; t = toi_st_s on usable rows else 0. r = (pg-league sum of x) / (pg-league sum of t). ix_<st>60_pre = 3600 * (wsum(x; 60, 25) + m0 * r) / (wsum(t; 60, 25) + m0).
ptoi_st = wsum(toi_st_s with NaN replaced by 0; 60, 25) / wsum(1 if toi_st_s is non-NaN else 0; 60, 25). ix_exp_pre = ix_ev60_pre / 3600 * ptoi_ev + ix_pp60_pre / 3600 * ptoi_pp.

## nhl.ipp_by_state -> ipp_ev_pre, ipp_pp_pre, ipp_exp_pts_pre
For st in (ev, pp): gfc = gf_st with NaN replaced by 0; ptc = pts_st if gf_st is non-NaN else 0. P = cur(ptc) + 0.6 * pv(ptc) + 0.4 * pw(ptc); G = cur(gfc) + 0.6 * pv(gfc) + 0.4 * pw(gfc). prior = (pg-league sum of ptc) / (pg-league sum of gfc). ipp_<st>_pre = (P + 25 * prior) / (G + 25).
gfpg_st = wsum(gfc; 40, 20) / wsum(1 if gf_st is non-NaN else 0; 40, 20). ipp_exp_pts_pre = gfpg_ev * ipp_ev_pre + gfpg_pp * ipp_pp_pre.

## Season projection quantities
GP = cur(gpf). avail = min(1, GP / team_gp) if team_gp > 0 else 1. R = max(82 - team_gp, 0) * avail.
For c in (points, goals, assists): S0 = cur(c); lgpos = (pg-league sum of c * gpf) / (pg-league sum of gpf); prior = pv(c) / pv(gpf) if pv(gpf) >= 20 else lgpos; epg = (S0 + 10 * prior) / (GP + 10); proj = S0 + R * epg.

## nhl.player_season_points_projection -> psp_points_pre, psp_exp_pg_pre, psp_proj_final_pre
For c = points: psp_points_pre = S0; psp_exp_pg_pre = epg; psp_proj_final_pre = proj.

## nhl.award_stats -> aw_goals_pre, aw_assists_pre, aw_proj_goals_pre, aw_proj_assists_pre
aw_goals_pre = S0 for goals; aw_assists_pre = S0 for assists; aw_proj_goals_pre, aw_proj_assists_pre = proj for goals, assists.

## nhl.games_played_hazard -> gph_share_pre, gph_missed10_pre, gph_prior_missed_pre, gph_exp_remaining_pre
gph_share_pre = min(1, GP / team_gp) if team_gp >= 5 else NaN. gph_exp_remaining_pre = R.
gph_prior_missed_pre = (sum of w_k * max(82 - g_k, 0)) / (sum of w_k) over k = 1 (w = 0.5, g = pv(gpf)) and k = 2 (w = 0.3, g = pw(gpf)), using only those k with g_k >= 1; NaN if neither qualifies.
gph_missed10_pre: with k = team_gp; NaN if k = 0; otherwise among the previous min(10, k) games of the row's team_id in that season, the number in which the player has NO universe row for that team_id with toi_s > 0.

## nhl.joint_outcome_correlation -> joc_pts_tgf_pre, joc_sog_total_pre, joc_pts_win_pre
win = 1 if tgf > tga; 0.5 if tgf == tga; else 0. tot = tgf + tga. At the player's i-th row the window = his previous min(82, i) rows (all seasons), n = its size; all three NaN if n < 20. For (x, y) = (points, tgf), (sog, tot), (points, win) respectively: vx = n * sum(x^2) - (sum x)^2; vy = n * sum(y^2) - (sum y)^2; if vx <= 0 or vy <= 0 the column is NaN, else r = (n * sum(x * y) - sum(x) * sum(y)) / sqrt(vx * vy). (All values are integers or halves, so these sums are exact in floating point.)

# Output
Write to `/tmp/claude-0/-home-user/4b121d0a-de18-5db8-915a-3a1ef1a5904f/scratchpad/blind/nhl/out/`:
* `blind_nhl2.csv`: game_id, team and the 20 TABLE 1 feature columns; one row per (game_id, team) of the TABLE 1 universe.
* `blind_nhl_ev2.csv`: game_id, team and the 29 TABLE 2 feature columns; one row per (game_id, team) of the TABLE 2 universe.
* `blind_nhl_player2.csv`: game_id, team and the 20 TABLE 3 feature columns; one row per (game_id, team) of the TABLE 3 universe.
* `blind_nhl_notes.json` = {"ambiguities": ["...", ...]} listing every choice you had to make.
Write NaN as empty cells, full float precision (do not round). Keep your implementation script in your working directory. Finish with a short report of the ambiguities you resolved; do not ask questions.

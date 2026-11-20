# Blind brief: NFL batch 8 (quarterback rows), four pre-game inputs (15 value columns)

You get `data/games.csv` (nflverse schedule) and `data/pbp/play_by_play_<season>.parquet` (2010-2026). Write your own implementation from this text only and write `out.csv`
with one row per (game_id, passer) and exactly the columns listed under Output (empty cell = missing). Use float64. Do not look for any other implementation.

## 1. Games
* games.csv rows with season >= 2010 and home_score present (first row if a game_id repeats). date = gameday.
* Codes OAK -> LV, SD -> LAC, STL -> LA in home_team, away_team and in play-by-play posteam and defteam.
* Team slots: (team = home_team, opp = away_team) and (team = away_team, opp = home_team). A team's played games are ordered by (date, game_id).

## 2. Attempts
* An attempt is a pbp row of a kept game with (complete_pass == 1 or incomplete_pass == 1 or interception == 1), two_point_attempt != 1 (missing = 0), passer_player_id present and posteam present.
  T = posteam, D = defteam (codes replaced). td = 1 if pass_touchdown == 1; int = 1 if interception == 1; comp = 1 if complete_pass == 1. cp = nflfastR cp (may be missing).
  The attempt's season and date are its game's (schedule).
* A passer's attempts are ordered by (date, game_id, play_id). "QB" below = any passer.
* xTD model. Cell = 5 * yb + ab, yb from yardline_100: <= 5 -> 0, <= 10 -> 1, <= 20 -> 2, <= 40 -> 3, else (incl. missing) 4; ab from air_yards: missing -> 0, < 0 -> 1, < 10 -> 2, < 20 -> 3, else 4.
  For season S: REF = attempts of seasons max(2010, S - 3) .. max(2010, S - 1) (so for S = 2010 it is 2010 itself); p_all = mean td over REF;
  p_cell = (sum td + 10 p_all) / (count + 10) over REF attempts in the cell; a cell absent from REF gets p_all. Every attempt of season S gets p_td = p_cell of the season-S table.

## 3. Rows
* Rows exist for team slots of games with season >= 2014 (date d). prev = T's last 4 played games dated strictly before d (any season >= 2010).
  Candidates = passers with an attempt for T in one of those games; q = the latest date of those games in which he had an attempt for T.
  A passer who is a candidate for both teams keeps the team with the larger q (equal: alphabetically smaller code). Row: game_id, team = passer id, with pteam = T, opp = O.
* Nothing dated d or later is used for a row's values (except where section 6 explicitly uses EARLIER seasons' own-game outcomes).

## 4. Attempt-window sums (passer state before d)
For a passer's attempts in order, r = 0.5 ** (1 / 350). For attempt i let W_i(x) = sum over his attempts j <= i of r ** (i - j) x_j and
S_i(x) = W_i(x) - r ** 700 * W_{i-700}(x) (the second term only when he has more than 700 attempts up to i; i - 700 counts his attempts). A row reads S at the passer's last attempt dated
strictly before d. Sw1 = S(1), Std = S(td), Sp = S(p_td), Sint = S(int).

## 5. League and club aggregates
* League of season S = from attempts of season S - 1: lg_int = mean int.
* Club rate t: over T's last 8 played games dated before d, attempts with T as posteam: t = sum p_td / count; if there are none, t = Sp / Sw1.
* Opponent defence O over its last 16 played games dated before d: I = interceptions and A = attempts with D == O (0 if none). Over its last 12 played games: E12 = sum of (comp - cp) and N12 = number
  of attempts with cp present, attempts with D == O and cp present.
* Passer games: per (passer, game) over his attempts: att = attempts, C = sum cp (missing cp counts 0), N = attempts with cp present, E = sum (comp - cp) over attempts with cp present, comp = completions.
  Ordered by (date, game_id). For the passer's last game dated before d (call it the state game) and the games before it: att8 = sum of att over the last min(8, available) games ending at the state
  game, g8 = that number of games; over the last 16 games ending at the state game, with j = 0 for the state game: wC = sum 0.5 ** (j/8) C_j, wN = sum 0.5 ** (j/8) N_j, E16 = sum E_j, N16 = sum N_j.

## 6. Columns
nfl.qb_expected_pass_td:
* q = Sp / Sw1; qbx_xtd_rate_pre = (Sw1 * q + 300 * t) / (Sw1 + 300).
* qbx_ratio_reg_pre = 1 + 0.3 * ((Std + 2) / (Sp + 2) - 1).
* qbx_adj_td_rate_pre = qbx_xtd_rate_pre * qbx_ratio_reg_pre.

nfl.td_luck:
* tdl_luck_raw_pre = (Std - Sp) / Sw1; tdl_luck_regressed_pre = 0.2 * tdl_luck_raw_pre.
* tdl_persistent_pre = (sum over the passer's attempts of season S - 1 of (td - p_td)) / (their count + 300); 0 if he had no attempt in S - 1.

nfl.int_rate (lg_int of the row's season):
* int_qb_rate_pre = (Sint + 200 lg_int) / (Sw1 + 200).
* int_opp_rel_pre = ((I + 200 lg_int) / (A + 200)) / lg_int.
* int_exp_rate_pre = int_qb_rate_pre * int_opp_rel_pre; int_exp_ints_pre = int_exp_rate_pre * att8 / g8.

nfl.qb_completion_count_model:
* qcc_xcomp_pre = wC / wN (missing if wN = 0); qcc_cpoe_shr_pre = E16 / (N16 + 300); qcc_opp_factor_pre = E12 / (N12 + 250).
* qcc_p_pre = clip(qcc_xcomp_pre + qcc_cpoe_shr_pre + qcc_opp_factor_pre, 0.35, 0.85) (missing if xcomp is missing).
* qcc_rho_pre: compute qcc_p_pre (as above) also for rows of season 2013 (same definitions with the 2013 games as row games). For a row of season S, REF = rows of seasons S - 3 .. S - 1
  (seasons >= 2013) whose passer had n >= 10 attempts IN THAT ROW'S OWN GAME (c = his completions there) and whose qcc_p_pre is present:
  qcc_rho_pre = clip(mean over REF of ((c - n p)^2 - n p (1 - p)) / (n (n - 1) p (1 - p)), 0, 0.2) with p = that row's qcc_p_pre.

## Output
`out.csv` for rows of season >= 2014: game_id, team (passer id), then qbx_xtd_rate_pre, qbx_ratio_reg_pre, qbx_adj_td_rate_pre, tdl_luck_raw_pre, tdl_luck_regressed_pre, tdl_persistent_pre,
int_qb_rate_pre, int_opp_rel_pre, int_exp_rate_pre, int_exp_ints_pre, qcc_xcomp_pre, qcc_cpoe_shr_pre, qcc_opp_factor_pre, qcc_p_pre, qcc_rho_pre. Floats '%.17g'.
Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

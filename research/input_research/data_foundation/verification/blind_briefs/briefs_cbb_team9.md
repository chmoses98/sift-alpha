# Blind brief: CBB batch 9 (schedule table), two pre-game team inputs (11 value columns)

You get `data/schedules/mbb_schedule_<season>.parquet` (ESPN men's college basketball schedules, 2006-2027). Write your own implementation from this text only and write
`out.csv` with one row per (game_id, team) and the columns under Output (empty cell = missing). float64. Do not look for any other implementation.

## 1. Games and team-games
* Read every file (some seasons lack the line-score columns: treat them as missing). Keep rows with season >= 2006, season_type in {2, 3}, status_type_completed == True and
  home_score and away_score present; first row per game_id. date = calendar date of game_date.
* Team-games: home (team = home_id, opp = away_id, s = +1, is_home = true) and away (team = away_id, opp = home_id, s = -1, is_home = false); if neutral_site is true, s = 0 for both
  (missing neutral_site = false). margin = own score - opponent score; total = sum of the two scores; ot = 1 if status_period > 2 else 0.
* A team's team-games are ordered by (date, game_id).

## 2. Line scores and the first-half ratio of a game
* home_linescores / away_linescores are strings holding a list of dicts. In each dict take `value` (a number); the dict's period is its `period` key when present, otherwise its
  position in the list (1 for the first dict, 2 for the second, ...). If a period appears twice keep the first.
* For a side: h1 = value of period 1; reg = value of period 1 + value of period 2 (missing if either is absent).
* Game ratio r = (h1_home + h1_away) / (reg_home + reg_away), defined only when all four values exist and the denominator > 0.

## 3. Team state
For a team, r_ = 0.5 ** (1/15); for each of its team-games i: W_i(x) = sum over j <= i of r_ ** (i - j) x_j. A row of game g dated d reads the team's W values at its last team-game dated
strictly before d (missing if none). Quantities: W1 = W(1), Wm = W(margin), Wt = W(total), Wr = W(r if defined else 0), Wn = W(1 if r defined else 0).

## 4. Season constants (from season S - 1 for rows of season S)
* lg_r = mean of r over the games of S - 1 where r is defined (missing if none).
* H = mean of margin over the HOME team-games of S - 1 with s != 0.

## 5. Columns (rows: team-games of season >= 2013; T = the row's team, O = its opponent; rows are also built for 2007-2012 to serve as reference)
cbb.first_half_pace_ratio
* For a team X: n = X's Wn (0 if missing); R = Wr / n if n > 0 else lg_r; value_X = n / (n + 12) * R + 12 / (n + 12) * lg_r.
* fhp_team_ratio_pre = value_T; fhp_pair_ratio_pre = (value_T + value_O) / 2; fhp_exp_h1_total_pre = fhp_pair_ratio_pre * 0.5 * (Wt/W1 of T + Wt/W1 of O).

cbb.margin_regime_mixture
* mrm_m_hat_pre = 0.5 * (Wm/W1 of T - Wm/W1 of O) + 0.5 * H * s.
* bin = floor(clip(mrm_m_hat_pre, -29.999, 29.999) / 2).
* Reference for season S: rows of seasons max(2007, S - 10) .. S - 1 with mrm_m_hat_pre present. Per bin over the reference rows (if the bin has fewer than 20 rows, every column below is
  missing): blow = |margin| >= 15.
  mrm_p_blowout_pre = mean of blow; mrm_comp_mu_pre / mrm_comp_sd_pre = mean / sample SD (n - 1) of margin over rows with blow = 0; mrm_blow_mu_pre / mrm_blow_sd_pre = the same over rows
  with blow = 1 (SD missing with fewer than 2 rows; mean missing with none); mrm_p_ot_pre = mean of ot; mrm_p_win_pre = share with margin > 0.
* A row takes the values of its own bin from its season's reference.

## Output
`out.csv` for team-games of season >= 2013: game_id, team, fhp_team_ratio_pre, fhp_pair_ratio_pre, fhp_exp_h1_total_pre, mrm_m_hat_pre, mrm_p_blowout_pre, mrm_comp_mu_pre, mrm_comp_sd_pre,
mrm_blow_mu_pre, mrm_blow_sd_pre, mrm_p_ot_pre, mrm_p_win_pre. Floats '%.17g'. Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

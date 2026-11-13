# Blind re-implementation brief: tennis_ext6 (five inputs)

You implement from this text only. Do not read `alpha_engine/features/tennis_ext6.py`, `tests/test_tennis_ext6.py`, or this repository's tennis builders.
Input: a pandas DataFrame of Sackmann-format match rows with columns `tour` ('atp'/'wta'), `tourney_id`, `tourney_name`, `tourney_date` (int YYYYMMDD),
`surface`, `best_of`, `round`, `match_num`, `winner_id`, `loser_id`, `score`, and `w_`/`l_` + `svpt`, `1stWon`, `2ndWon`, `SvGms`, `bpFaced`, `bpSaved`.
Output: one row per (match, player) with keys `game_id`, `team` and the columns named below. NaN where undefined.

## Keys and cleaning
- Drop rows with missing `tourney_date`, `winner_id` or `loser_id`. `date` = `tourney_date` parsed as YYYYMMDD.
- `game_id` = `tour|tourney_id|match_num|k`, where k = 0,1,… numbers repeated (tour|tourney_id|match_num) in file order.
- Player key `team` = `tour:int(id)`. `opp` = the other player's key.
- **Point-in-time rule, everywhere:** any aggregate for a row uses only rows whose `date` is strictly earlier than the row's own `date`. Windows of W days include dates d with row_date - W <= d < row_date.
  Half-life weighting: weight = 0.5 ** ((row_date - d)/hl) in days.

## Score parsing
- Tokens split on spaces. "W/O" means walkover. RET/DEF mean retirement or default. ABD or UNP is a bad row. Every other token must match `a-b` or `a-b(x)`, otherwise bad.
- A set is complete if max>=6 and diff>=2, or max==7 and min in {5,6}.
- A match is **completed** if there is no flag, the winner's set count equals best_of//2+1 (default 2 when best_of is missing), every set is complete, and **every set's total games is in {6,7,8,9,10,12,13}**.
- A **valid-serve** row: not a walkover, w_svpt>0, l_svpt>0, and all four 1stWon/2ndWon present.

## Walk-forward Elo (needed by several inputs)
- K=32, start 1500. Keep an overall rating, plus a per-surface rating for surfaces in {Hard, Clay, Grass, Carpet}.
- Process per tour in date order. All matches on the same (tour, date) see the ratings from before that date. Updates are summed over the date and applied after it.
- Walkovers get no update.
- Expectation p = 1/(1+10^(-(ra-rb)/400)). Winner += 32(1-p), loser -= 32(1-p); same for the surface ratings with their own p.
- Pre-match combined rating r = (elo+surface_elo)/2, or elo alone if the surface is not one of the four.
- p_w = P(winner) from the r values.
- The favourite is the higher r. On a tie, the favourite is the smaller key string. p_fav = favourite's probability.
- Row-level: `p_win` = this player's probability; `rating` = this player's r.

## Pre-match serve-point-win (spw)
- Per valid-serve row:
  - s_won = own 1stWon+2ndWon, s_pts = own svpt;
  - r_won = opp svpt - opp(1stWon+2ndWon), r_pts = opp svpt.
- Per player, over the previous 1095 days with half-life 365:
  - sp = Σw·s_won / Σw·s_pts;
  - rr = Σw·r_won / Σw·r_pts.
- Per tour, unweighted, same window: t = Σs_won/Σs_pts.
- spw (this player vs the opponent) = clip(sp + (opp_rr - (1 - t)), 0.30, 0.90). o_spw is the same with the roles swapped.
- hold(p) = p^4(1+4q+10q^2) + 20 p^3 q^3 · p^2/(1-2pq), with q = 1-p.

## Set model
- Games alternate serve. A (this player) holds with hold(spw); B holds with hold(o_spw), so A wins a B service game with 1-hold(o_spw).
- A set ends at 6 games with a lead of at least 2, at 7-5, or by a tiebreak at 6-6.
- Average every quantity over the two first-server cases (1/2 each).
- Tiebreak: first to 7, win by 2. The set's first server serves tiebreak point 1. After that, points alternate in pairs (S2,S2,S1,S1,…). A wins a point A serves with spw, and a point B serves with 1-o_spw.
  From 6-6 in the tiebreak: P(A) = a/(a+b), where a = spw·(1-o_spw) and b = (1-spw)·o_spw.
- Needed from this model:
  - the pmf of total games per set over {6,7,8,9,10,12,13} (a tiebreak set counts 13);
  - P(A wins the set);
  - p66 = P(the set reaches 6-6).

## 1. ten.within_match_dependence (`wmd_overdisp_pre`, `wmd_form_sd_pre`, `wmd_n_sets_pre`)
- For each completed match with both spw defined, contributed **once per match**:
  - mu and var = mean and variance of the model games-per-set pmf, normalised to sum to 1;
  - SSR = Σ over the match's sets (games - mu)^2;
  - SV = n_sets·var;
  - N = n_sets.
- Cell = (tour, best_of), window 1095 days, unweighted:
  - `wmd_overdisp_pre` = ΣSSR/ΣSV (NaN if ΣSV = 0);
  - `wmd_n_sets_pre` = ΣN (0 when the window is empty).
- Per player row with valid serve and spw defined: dev = s_won/s_pts - spw, binv = spw(1-spw)/s_pts.
- Per tour, window 1095 days, unweighted over rows: tau2 = mean(dev^2 - binv) - mean(dev)^2.
- `wmd_form_sd_pre` = sqrt(max(tau2, 0)); NaN if fewer than 30 rows.

## 2. ten.hold_rate_uncertainty_propagation (`hru_p66_mean_pre`, `hru_p66_point_pre`, `hru_jensen_pre`, `hru_neff_pre`, `hru_opp_neff_pre`)
- `hru_neff_pre` = min(Σw·s_pts over the player's previous 730 days with half-life 365, 4000); 0 when there is no history. `hru_opp_neff_pre` = the opponent's value.
- Defined only if both spw are defined and both neff > 0. Then:
  - sd_A = sqrt(spw(1-spw)/(neff+1) + 0.02^2), and likewise sd_B;
  - 7-point Gauss-Hermite for a standard normal (probabilists' nodes, weights normalised to sum to 1) on each player independently;
  - each node: A = clip(spw + sd_A·x_i, 0.30, 0.90), B = clip(o_spw + sd_B·x_j, 0.30, 0.90);
  - p66 at holds hold(A), hold(B).
- `hru_p66_mean_pre` = the weighted mean over the 49 nodes; `hru_p66_point_pre` = p66 at hold(spw), hold(o_spw); `hru_jensen_pre` = mean - point.

## 3. ten.player_speed_slope (`pss_cpi_pre`, `pss_beta_pre`, `pss_adj_rating_pre`)
- event = tour + "|" + lower(strip(tourney_name)).
- Per player row: obs_hold = 1 - (bpFaced - bpSaved)/SvGms (NaN if SvGms is 0 or missing). resid = obs_hold - hold(own spw), only where both spw are defined.
- Match residual m = the mean of the two rows' resid (NaN-skipping), assigned to both rows.
- Over the previous 1155 days, half-life 365:
  - Se, Ce = weighted sum and weighted count of m over all rows of the event;
  - Sp, Cp = the same over this player's rows of the event.
- `pss_cpi_pre` = (Se - 2Sp)/(max(Ce - 2Cp, 0) + 20), NaN if Ce = 0.
- g = p_win(1-p_win)·ln(10)/400; gx = g·cpi; y = won - p_win.
- Over the player's previous 730 days, unweighted, rows with gx defined: A = Σgx·y, B = Σgx^2, n = count.
- `pss_beta_pre` = A/(B + 0.25/500^2) if n >= 10, else NaN.
- `pss_adj_rating_pre` = rating + beta·cpi.

## 4. ten.set_dist (`sd_p2_pre`..`sd_p5_pre`, `sd_match_win_pre`, `sd_cal_p2_pre`..`sd_cal_p5_pre`)
- tau = `wmd_form_sd_pre`. Defined if both spw are defined and tau is defined.
- 5-point Gauss-Hermite on each player independently: A = clip(spw + tau·x_i, .30, .90), B = clip(o_spw + tau·x_j, .30, .90).
- w = P(A wins set) from the set model with spw A and o_spw B. Sets are iid within a node.
- Number-of-sets pmf:
  - best of 3: P2 = w^2+l^2, P3 = 1-P2;
  - best of 5: P3 = w^3+l^3, P4 = 3(w^3 l + l^3 w), P5 = 1-P3-P4;
  - unused entries are 0.
- Match win: best of 3 = w^2(1+2l); best of 5 = w^3(1+3l+6l^2).
- Average over the 25 nodes with the product weights.
- Calibration: cell (tour, surface (missing → "NA"), best_of), window 3650 days, unweighted, **one contribution per completed match** where the model is defined:
  O_k = Σ1[n_sets=k] and E_k = ΣP_k.
- ratio_k = (O_k + 200)/(E_k + 200). cal_k ∝ P_k·ratio_k, normalised over k=2..5.

## 5. ten.set_number_calibration (`snc_logit_s1_pre`, `snc_off_{s2_won1,s2_lost1,s3_level,s4_up,s4_down,s5_level}_pre`, `snc_n_pre`)
- For each completed match, read the sets in order from the favourite's view, keeping diff = favourite sets won minus sets lost before the set.
- States: (set 1, diff 0), (2, +1), (2, -1), (3, 0), (4, +1), (4, -1), (5, 0). The indicator = favourite won that set. One contribution per match.
- ebin = min(int((p_fav - 0.5)·20), 4). Cell (tour, best_of, ebin); pool (tour, best_of). Window 3650 days, unweighted.
- Shrunk frequency: if the cell count n > 0, f = (n/(n+50))·cell_mean + (50/(n+50))·pool_mean, else the pool mean. NaN if the pool is empty.
- Clip f to [1e-4, 1-1e-4]; take the logit. `snc_logit_s1_pre` = logit(f_s1); each `snc_off_*` = logit(f_state) - logit(f_s1).
- For best-of-3 matches, the s4 and s5 offsets are NaN. `snc_n_pre` = the cell count for state s1 (0 if none).

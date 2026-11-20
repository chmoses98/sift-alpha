# Blind brief: MLB batch 7 (plate appearances), five pre-game inputs in two tables (team rows: 17 columns; pitcher rows: 17 columns)

You get `data/feeds/<season>/<gamePk>.json` for seasons 2022-2026 (MLB Stats API game feeds, compacted: one JSON per final game). Write your own implementation from this
text only and write `team_out.csv` (one row per (game_id, team)) and `pitcher_out.csv` (one row per (game_id, pitcher)) with exactly the columns listed under Output
(empty cell = missing). Use float64 throughout. Do not look for any other implementation.

## 1. Games
* Read every file whose name does not start with "_", seasons in increasing order and files sorted by name. Keep a game only if game.type is one of R, F, D, L, W and
  status.codedGameState == "F" (and the keys used below exist). If a game_id (= pk) occurs twice keep the first.
* season = int(game.season). date = datetime.officialDate (the FIRST-PITCH date). avail = datetime.resumeDate if that key is present and non-empty, else officialDate
  (the date the result became known; later than date for suspended games).
* home = teams.home.id, away = teams.away.id. h_r = sum over linescore.innings of home.runs (missing -> 0); a_r likewise for away.
* home_sp = box.home.pitchers[0], away_sp = box.away.pitchers[0] (missing if absent): the game's actual starting pitchers. They are used ONLY for history (earlier games).
* **History rule.** A row (game g, date d) may use a game G only if avail(G) < d (strictly). Nothing of g itself is used.

## 2. Plate appearances (PAs)
* Iterate `plays` of each kept game in order. Skip a play if `event` is not a string, or starts with any of: caught_stealing, pickoff, stolen_base, wild_pitch, passed_ball,
  balk, other_advance, other_out, runner, defensive_indiff, game_advisory, ejection; or if `bat` or `pit` is missing. Every other play is a PA.
* Fields: ab (int), half ("top" means the away team bats), bat, pit, throws (pitcher hand "R"/"L"), event. Pitch codes = `code` of each element of `pitches`.
  n_pitch = number of pitch elements; called = number of code "C"; whiff = number of codes in {S, W, T, M, Q}; swing = number of codes in {S, W, T, M, Q, F, L, O, X, D, E}; csw = called + whiff.
* Batting team = away if top else home; fielding team = the other. The PA's season / date / avail are its game's.
* k = 1 if event in {strikeout, strikeout_double_play}; bb = 1 if event in {walk, intent_walk}.
* wOBA: num = 0.69 walk, 0.72 hit_by_pitch, 0.88 single, 1.25 double, 1.58 triple, 2.03 home_run, else 0; den = 1 unless event in {intent_walk, sac_bunt, catcher_interf} (then 0).
* is_start = the PA's pitcher equals the fielding team's starter of that game (home_sp when top, else away_sp).
* bf_i = 1, 2, ... = the PA's position among the PAs of the same (game, pitcher), ordered by ab. tto = min(ceil(bf_i / 9), 3).

## 3. League constants of season s (they are applied to rows of season s + 1), over all PAs of season s
* k = sum(k) / number of PAs; csw = sum(csw)/sum(n_pitch); whiff = sum(whiff)/sum(swing); woba = sum(num)/sum(den).
* For h in R, L over PAs with throws == h: k_h = sum(k)/count; woba_h = sum(num)/sum(den).
* Over start PAs (is_start) with tto == t (t = 1, 2, 3): tto_k_t = sum(k)/count, tto_bb_t = sum(bb)/count, tto_woba_t = sum(num)/sum(den).
* tto_bf_t = the mean, over all (game, pitcher) pairs having start PAs in season s, of min(max(BF - 9 (t - 1), 0), 9) where BF = the number of start PAs of that pair.
* Team-game constants of season s: lg_runs = mean runs per team-game (each game gives two team-games: home scores h_r, away scores a_r);
  lg_phi = phi(mean, sample variance (n - 1)) of those team-game runs, where phi(m, v) = max(v - m, 0) / m ** 2 if m > 0 else 0;
  lg_corr = Pearson correlation of (h_r, a_r) over the games of season s.

## 4. Team-games and rows
* Each kept game gives team-games (team = home, opp = away, runs = h_r, runs_allowed = a_r) and (team = away, opp = home, runs = a_r, runs_allowed = h_r).
* Output rows of the team table: every team-game with season >= 2023 (season 2022 is history only). S = the row's season, d = its date.
* last_n(T, d, n): T's team-games with avail < d, ordered by (date, game_id), the last n of them (fewer if fewer).
* **Window of a row**: PAs with avail < d and season >= S - 1.

## 5. Recent lineup and lineup-vs-hand (used by both tables)
For a team X at row date d (season S):
* Lineup: the batters with PAs for X (as batting team) in last_n(X, d, 10); w_b = b's PA count in those games / total PA count of X in those games.
* For h in R, L: over b's PAs (as batter, any team) in the row's window with throws == h: n = count, K = sum(k), N = sum(num), D = sum(den).
  kh_b = (K + 200 * k_h(S-1)) / (n + 200); wh_b = (N + 300 * woba_h(S-1)) / (D + 300).
* lineup_k_h = sum_b w_b * kh_b; lineup_woba_h = sum_b w_b * wh_b.

## 6. Team table columns (row (g, T, opp O))
mlb.lineup_k_platoon: lkp_k_vs_r_pre = lineup_k_R of T; lkp_k_vs_l_pre = lineup_k_L of T; lkp_k_vs_r_rel_pre = lkp_k_vs_r_pre / k_R(S-1); lkp_k_vs_l_rel_pre = lkp_k_vs_l_pre / k_L(S-1).

mlb.team_wrc_vs_hand: wrc_woba_vs_r_pre = lineup_woba_R of T; wrc_woba_vs_l_pre = lineup_woba_L; wrc_idx_vs_r_pre = 100 * wrc_woba_vs_r_pre / woba_R(S-1); wrc_idx_vs_l_pre likewise with L;
wrc_team_split_vs_h_pre (h = r, l) = sum(num) / sum(den) over the PAs in the row's window with batting team T and throws == h (missing if sum(den) = 0).

mlb.run_dist:
* Run state: order each team's team-games by (avail, date, game_id) (COMPLETION order). For half-life 30 and r = 0.5 ** (1/30): off = (sum_j r^(i-j) runs_j) / (sum_j r^(i-j)) over
  the team's team-games j <= i in that order; dfn the same with runs_allowed. A row reads the state at the LAST team-game in that order with avail < d
  (T's off; O's dfn).
* rd_mu_pre = off(T) * dfn(O) / lg_runs(S-1).
* T's team-games with avail < d and season >= S - 1: n, m = mean runs, v = sample variance (n - 1). phi_T = phi(m, v) if n > 1 else 0.
  rd_phi_pre = n / (n + 50) * phi_T + 50 / (n + 50) * lg_phi(S-1).
* rd_corr_pre = lg_corr(S-1).
* rd_p_gek_pre for k = 3, 4, 5, 6 = P(X >= k) for X negative binomial with mean mu = rd_mu_pre and size 1/phi (phi = rd_phi_pre): pmf(x) = Gamma(x + 1/phi)/(Gamma(1/phi) x!) * q^(1/phi) (1-q)^x,
  q = (1/phi) / (1/phi + mu); if phi == 0 use Poisson(mu).

## 7. Pitcher table (rotation candidates)
* For each team-game row (g, T, O, d, S) of section 4: candidates = the starters (home_sp / away_sp of T's side) of the games in last_n(T, d, 5) (missing starters ignored).
  For a candidate p, q = the latest date among those games where p started for T.
* A pitcher who is a candidate for both teams of g is kept only for the team with the larger q (equal: smaller team id).
* One row per (g, p): game_id, pitcher = p (integer), team T, opp O.
* Window of p: p's PAs AS PITCHER in the row's window (section 4).

mlb.tto, for t = 1, 2, 3, over the window PAs of p with is_start and tto == t: n_t = count, K_t, BB_t, N_t, D_t sums of k, bb, num, den;
f_t = number of window PAs of p with is_start and 9 (t - 1) < bf_i <= 9 t; starts = number of window PAs of p with is_start and bf_i == 1.
* tto_k_t_pre = (K_t + 100 * tto_k_t(S-1)) / (n_t + 100); tto_bb_t_pre = (BB_t + 100 * tto_bb_t(S-1)) / (n_t + 100); tto_woba_t_pre = (N_t + 200 * tto_woba_t(S-1)) / (D_t + 200);
  tto_exp_bf_t_pre = (f_t + 8 * tto_bf_t(S-1)) / (starts + 8).

mlb.k_rates, over all window PAs of p (any role): n = count, K = sum(k), P = sum(n_pitch), C = sum(csw), W = sum(whiff), Sw = sum(swing).
* kr_pit_k_pre = (K + 100 * k(S-1)) / (n + 100); kr_pit_csw_pre = (C + 300 * csw(S-1)) / (P + 300); kr_pit_whiff_pre = (W + 150 * whiff(S-1)) / (Sw + 150).
* hand = `throws` of p's latest PA (as pitcher) with avail < d, latest by (avail, game_id, ab), any season.
* kr_opp_lineup_k_pre = lineup_k_hand of O at the same row (section 5; missing if hand is neither R nor L).
* kr_log5_k_pre: with x = kr_pit_k_pre, l = kr_opp_lineup_k_pre, g = k(S-1): A = x l / g, B = (1 - x)(1 - l)/(1 - g), value = A / (A + B).

## Output
* `team_out.csv`: game_id, team, then lkp_k_vs_r_pre, lkp_k_vs_l_pre, lkp_k_vs_r_rel_pre, lkp_k_vs_l_rel_pre, wrc_woba_vs_r_pre, wrc_woba_vs_l_pre, wrc_idx_vs_r_pre, wrc_idx_vs_l_pre,
  wrc_team_split_vs_r_pre, wrc_team_split_vs_l_pre, rd_mu_pre, rd_phi_pre, rd_corr_pre, rd_p_ge3_pre, rd_p_ge4_pre, rd_p_ge5_pre, rd_p_ge6_pre.
* `pitcher_out.csv`: game_id, team (= the PITCHER id, integer), then tto_k_1_pre, tto_k_2_pre, tto_k_3_pre, tto_bb_1_pre, tto_bb_2_pre, tto_bb_3_pre, tto_woba_1_pre, tto_woba_2_pre, tto_woba_3_pre,
  tto_exp_bf_1_pre, tto_exp_bf_2_pre, tto_exp_bf_3_pre, kr_pit_k_pre, kr_pit_csw_pre, kr_pit_whiff_pre, kr_opp_lineup_k_pre, kr_log5_k_pre.
* Full float precision (e.g. '%.17g'). Rows in any order. Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

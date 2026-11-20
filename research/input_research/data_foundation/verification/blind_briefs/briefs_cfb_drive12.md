# Blind brief: CFB batch 12 (ESPN drives and scoring plays), four pre-game team inputs (23 value columns)

You get `data/summaries/<game>.json` (ESPN college-football game summaries, 2014-2026, one file per game). Write your own implementation from this text only and write `out.csv` with one row
per (game_id, team) and the columns under Output (empty cell = missing). float64. Do not look for any other implementation.

## 1. Extraction
Files are read in sorted file-name order; skip names starting with "_". A game is kept only if header.competitions[0].status.type.completed is true and these parse: game_id = int(header.id),
season = int(header.season.year), date = (competitions[0].date as a UTC time, made naive, minus 10 hours) truncated to the calendar day, home / away team ids = int(team.id) of the competitors with
homeAway "home" / "away". First occurrence per game_id. Keep seasons >= 2014.
* Drives: `drives.previous` in list order (idx = position). team = int(drive.team.id) (-1 if not parseable); period = drive.start.period.number; secs = drive.timeElapsed.displayValue "m:ss"
  in seconds (missing if absent or unparseable); result = drive.displayResult lower-cased ("" if absent); start_margin = |homeScore - awayScore| of the drive's FIRST play (`plays[0]`, a
  missing score counts 0); missing if the drive has no plays.
* Scoring plays: `scoringPlays` in list order (idx). period = period.number; clock = clock.displayValue "m:ss" in seconds (seconds REMAINING in the period); home_score = homeScore,
  away_score = awayScore (after the play; missing counts 0).

## 2. Team-games and per-game quantities
* Each game gives two team-games: (team = home, opp = away, is_home = true) and (team = away, opp = home, is_home = false). A team's team-games are ordered by (date, game_id).
* Only drives whose team is the game's home or away team are used anywhere.
* Eligible drive: secs present, result does not start with "end of", and NOT (start_margin >= 28) (a missing start_margin is eligible).
* For p in {all, 1, 2, 3, 4} (p = all: every eligible drive; p = k: eligible drives with period == k): n_p / s_p = count / sum of secs of the team's eligible drives in the game;
  on_p / os_p = the same for the opponent's. Missing = 0.
* Game actuals (game level): drv = number of drives (any result) of the two teams; drv_k = those with period == k (0 if none); T_game = sum of secs over those drives where secs is present
  (0 if none). A game with no drive at all has drv and T_game missing. own_drv_k = the team's drives with period == k (0 if none).
* recv = 1 if the team owns the game's first drive (lowest idx) among drives with period == 1, 0 if the opponent owns it, missing if the game has no period-1 drive. recv2 the same with period 3.
* Scoring states (Q2-Q4): keep the game's scoring plays with period in 1..4 and clock present; t = (period - 1) * 900 + 900 - clock; sort by (t, idx). Let m_i = home_score - away_score after
  play i, and m_before_i = m_(i-1) (0 for the first). Segments: boundaries 0, t_1, ..., t_n, 3600; segment j (between consecutive boundaries) has margin 0 before the first play and m_i after
  play i. For the home side (sign +1) and the away side (sign -1):
  ml = minutes (seconds / 60) of the overlap of each segment with [900, 3600] where sign * margin >= 14; mc = minutes where |margin| <= 8.
  The side's points on play i = its score after play i minus its score after play i-1 (from 0 before the first play). pl = sum of those points over plays with 900 <= t <= 3600 and
  sign * m_before >= 14; pc = the same with |m_before| <= 8. A team-game takes its own side's values; a game with no qualifying scoring play has them missing.

## 3. Season constants (from season S - 1, for rows of season S), over the team-games of S - 1
* lg_p = sum s_p / sum n_p (p in all, 1..4). T_eff = mean of T_game over the games of S - 1 (one value per game; missing values skipped).
* r1 / k1 = mean own_drv1 over team-games with recv == 1 / recv == 0; r3 / k3 = mean own_drv3 over recv2 == 1 / recv2 == 0; q2 / q4 = mean own_drv2 / own_drv4 over all team-games.
* L_lead = sum pl / sum ml; L_close = sum pc / sum mc (missing values skipped).

## 4. Windows
* Drive window of team X at date d: X's last 10 team-games dated strictly before d (fewer if fewer), j = 0 for the newest, w = 0.8 ** j. Sums: W(c) = sum w * c for c in s_p, n_p, os_p, on_p.
  n_g(X) = number of games in that window with n_all > 0.
* own_p(X) = W(s_p)/W(n_p) if W(n_p) > 0, else lg_p; allowed_p(X) = W(os_p)/W(on_p) if W(on_p) > 0, else lg_p. Each shrunk: (n_g(X) * v + 5 * lg_p) / (n_g(X) + 5).
* Row (g, T, O): D_p = (own_p(T) + allowed_p(O) + own_p(O) + allowed_p(T)) / 4.
* Receiving window of X: X's last 10 team-games before d among those with recv present; weights as above. f = sum w recv / sum w (0.5 if none); c = number of those games;
  F(X) = (c * f + 5 * 0.5) / (c + 5).

## 5. Rows and columns
Rows are built for seasons >= 2015 (so that season S - 1 rows exist as reference) and OUTPUT for seasons >= 2016.
* raw = T_eff / D_all; raw_k = 900 / D_k.
* Reference of season S: the HOME rows of season S - 1. bias = mean of (drv - raw) over reference rows where both are present; sd = their sample SD (n - 1); bias_k, sd_k likewise with drv_k and raw_k.
cfb.expected_possessions: cep_exp_drives_pre = raw + bias; cep_sd_pre = sd; cep_drive_secs_pre = D_all.
cfb.period_drive_clock_budget: pdc_qk_exp_pre = raw_k + bias_k; pdc_qk_p_le4_pre = Phi((4.5 - pdc_qk_exp_pre) / sd_k) (standard normal CDF), k = 1..4.
cfb.period_possession_allocation: P = 0.5 F(T) + 0.5 (1 - F(O)); ppa_p_receive_first_pre = P; ppa_exp_drives_q1_pre = P r1 + (1 - P) k1; ppa_exp_drives_q3_pre = (1 - P) r3 + P k3;
ppa_exp_drives_q2_pre = q2; ppa_exp_drives_q4_pre = q4.
cfb.leader_scoring_persistence: over T's team-games dated strictly before d of seasons S (weight 1) and S - 1 (weight 0.5) with ml present: lsp_ppm_lead14_pre = (sum w pl + 60 L_lead) / (sum w ml + 60);
lsp_ppm_close_pre = (sum w pc + 60 L_close) / (sum w mc + 60); lsp_ratio_pre = lsp_ppm_lead14_pre / lsp_ppm_close_pre.

## Output
`out.csv` (seasons >= 2016): game_id, team, cep_exp_drives_pre, cep_sd_pre, cep_drive_secs_pre, pdc_q1_exp_pre, pdc_q2_exp_pre, pdc_q3_exp_pre, pdc_q4_exp_pre, pdc_q1_p_le4_pre, pdc_q2_p_le4_pre,
pdc_q3_p_le4_pre, pdc_q4_p_le4_pre, ppa_p_receive_first_pre, ppa_exp_drives_q1_pre, ppa_exp_drives_q2_pre, ppa_exp_drives_q3_pre, ppa_exp_drives_q4_pre, lsp_ppm_lead14_pre, lsp_ppm_close_pre,
lsp_ratio_pre. Floats '%.17g'. Also write `notes.json` = {"ambiguities": [...]}.

# Blind brief: CFB inputs from ESPN post-game summaries (37 value columns)

Data: `/tmp/raw/CFB/*.json` and `/tmp/raw/CFB26/*.json` (one ESPN summary JSON per game; ignore files whose name starts with "_"). If a game id occurs twice keep the first.

## Games (parse per file j)
co = j.header.competitions[0]; H / A = the entry of co.competitors with homeAway "home" / "away". Keep the game only if co.status.type.completed is true, H.score and A.score parse as integers, and both
H.linescores and A.linescores have at least 4 entries whose displayValue parse as integers. game_id = int(j.header.id); season = j.header.season.year; team id = int(competitor.team.id);
date = the calendar date of (co.date as UTC minus 10 hours); ne = 0 if co.neutralSite is true else 1.
* q1..q4 per side = the first four linescore values; regulation points = q1+q2+q3+q4; final score = competitor.score; n_per = max(number of linescore entries of H, of A).
* Touchdowns: sp = j.scoringPlays (missing or empty list = no list). The touchdown list is the entries of sp, in file order, with scoringType.name == "touchdown"; each belongs to int(team.id).
  If sp is non-empty, or both final scores are 0: td(side) = the count of that side's touchdowns; first_td = 0 if the touchdown list is empty, else +1 if its first entry belongs to the home team, -1 if to the away
  team (missing if neither). Otherwise td of both sides and first_td are missing.
* Team box: for each entry t of j.boxscore.teams (team id = int(t.team.id)), stats = {name: displayValue} over t.statistics. yards = int(totalYards); rush = int(rushingAttempts);
  plays = (the second number of completionAttempts, which looks like "35/52" or "35-52") + rush. If anything fails to parse for either side, or plays is not > 0 for both sides, then yards, plays, rush are missing for both sides.
* Drives: count the entries of j.drives.previous by int(team.id). If either side has 0 (or drives are absent), the drive counts of both sides are missing.

## Ridge targets (Method R with LAM = 3, HL = 10)
pts = regulation points; ypp = yards / plays; rush = rush attempts; drv = drive count.
For a team row T against opponent O: x_pts = ep_pts(T); x_mar = ep_pts(T) - ep_pts(O); x_tot = ep_pts(T) + ep_pts(O).

## Columns (own = the row's team, opp = its opponent; own_qk / opp_qk = quarter-k points; c_k = own_qk + opp_qk)
Direct ridge columns: nyp_off_pre = off_ypp(T); nyp_def_pre = def_ypp(T); nyp_exp_pre = ep_ypp(T); sra_exp_pre = ep_rush(T); ods_exp_pre = ep_drv(T); ods_share_pre = ep_drv(T) / (ep_drv(T) + ep_drv(O)).
Kernel on x_pts, bw 3:  qj_q{k}_zero_pre = P(own_qk == 0) for k = 1..4;  qj_all4_pre = P(own_qk > 0 for all four k);  tdc_mean_pre = E[own td];
  tdc_var_pre = E[own td squared] - (E[own td]) ** 2;  tdc_ge2_pre, tdc_ge4_pre, tdc_ge6_pre = P(own td >= 2 / 4 / 6)  (event missing when own td is missing).
Kernel on x_tot, bw 5:  qj_hi_q{k}_pre = P(k is the smallest index attaining max(c_1..c_4)) for k = 1..4;  pst_q{k}_pre = E[c_k] / E[c_1 + c_2 + c_3 + c_4] for k = 1..4;
  ftd_none_pre = P(first_td == 0)  (event missing when first_td is missing).
Kernel on x_mar, bw 4:  pml_lead_q1_pre = P(own_q1 > opp_q1);  pml_tie_q1_pre = P(own_q1 == opp_q1);  pml_lead_half_pre = P(own_q1 + own_q2 > opp_q1 + opp_q2);  pml_tie_half_pre = P(the two are equal);
  pml_win_2h_pre = P(own_q3 + own_q4 > opp_q3 + opp_q4);  pml_tie_2h_pre = P(the two are equal);  ftd_first_pre = P(the first touchdown belongs to own team; false when first_td == 0; missing when first_td is missing);
  sra_script_pre = E[own rush attempts].
Kernel on two dimensions (|x_mar| with bw 4, x_tot with bw 7):  rtc_tie_pre = P(n_per > 4).
Kernel on x_mar, bw 4, with a condition (win = own final score > opp final score):  hft_win_lead_pre = P(win), condition own_q1 + own_q2 > opp_q1 + opp_q2;  hft_win_trail_pre = P(win), condition own half < opp half.
Kernel on x_mar, bw 6, with a condition:  htc_win_tied_pre = P(win), condition own half == opp half.

## Method R: walk-forward ridge (used for every "ridge target" below)
Order the Games by (date, game_id). Teams = every team id appearing in the Games. All games on the same date d share one fit:
* S = the largest season among the games on d. Pool = every game dated strictly before d with season >= S-1, in (date, game_id) order. If the pool has fewer than 16 games, every ridge value is missing for games on d.
* rank(team, pool game) = the number of LATER pool games (later in pool order) in which that team plays (0 = the team's most recent pool game). rk = min(rank of home team, rank of away team).
  Ranks are always counted over the whole pool, also when a target is missing in some pool games. Weight w = 0.5 ** (rk / HL).
* For a target with per-side values (y_home, y_away): keep the pool games where both values are present (if fewer than 16 are kept, that target is missing on d). Each kept game gives two observations with
  weight w: (offence = home team, defence = away team, y = y_home, I = ne) and (offence = away team, defence = home team, y = y_away, I = 0). ne = 0 for a neutral-site game, else 1.
* Weighted ridge y ~ b0 + a[offence] + d[defence] + h * I. Penalty: add LAM to the diagonal for every a and every d coefficient; nothing for b0 and h. Solve (Z'WZ + P) b = Z'Wy.
* For a game on d with home team H and away team V: ep(H) = b0 + a[H] + d[V] + ne * h;  ep(V) = b0 + a[V] + d[H];  off(X) = b0 + a[X];  def(X) = b0 + d[X].

## Method K: season-walk-forward kernel (used for every "kernel" column below)
Team rows = two rows per game (one per team). For a team row of season s with conditioning values x (one or more dimensions, each with a bandwidth bw):
* The reference rows are the team rows of seasons strictly earlier than s whose conditioning values are all present, further limited to rows where the event value v is present
  (and, where a condition is stated, where the condition is true). If there are fewer than MIN_REF such rows (150 where a condition is stated, else 500) the column is missing for season s.
* k_i = exp(-0.5 * sum over dimensions of ((x_i - x) / bw) ** 2);  value = sum(k_i * v_i) / sum(k_i)  (missing if the row's own x is missing or sum(k_i) is 0).
* "P(event)" means v = 1 if the event is true else 0; "E[quantity]" means v = the quantity.

Use float64 throughout. Write `out.csv` with one row per (game_id, team), columns game_id, team and exactly the value columns named below (empty cell = missing). Also write `notes.json` =
{"ambiguities": [every place where you had to guess]}. Write your own implementation from this text only. Do not look for or read any other implementation or repository.

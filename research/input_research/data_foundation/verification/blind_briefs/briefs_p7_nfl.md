# Blind re-implementation brief (Phase 7): NFL pre-game features, 2 catalog inputs, two output tables

You are an independent verifier. Re-implement every column below from THIS TEXT ALONE and write the two CSV files named at the end. Use only python with pandas / numpy / pyarrow / the standard library.

Data (read-only) under `D = /tmp/claude-0/-home-user/fe2fcd93-36fe-556b-87d8-e4244ab88677/scratchpad/blind/nfl/data/`:
`D/pbp/pbp_<season>.parquet` (nflverse play-by-play 1999-2026; concatenate all), `D/games.csv` (nflverse schedule), `D/players.parquet` (nflverse players).
Write outputs to `/tmp/claude-0/-home-user/fe2fcd93-36fe-556b-87d8-e4244ab88677/scratchpad/blind/nfl/out/`.
Hard rules: do NOT read, list or search anything under `/home/user`, any git repository, or any directory other than that data directory and your own working/output directory. Do not look for an existing
implementation. Where the text is ambiguous choose the most literal reading and RECORD the choice in `notes.json` (key `ambiguities`, a list of strings).

## Common conventions
* Team codes: replace `OAK` -> `LV`, `SD` -> `LAC`, `STL` -> `LA` everywhere (schedule `home_team`/`away_team`, pbp `posteam`/`defteam`). No other renaming.
* Schedule universe `G`: rows of games.csv with `season` >= 1999 and `home_score` not null. date = `gameday` parsed as a date. Game season = the schedule `season`.
* `REG` games: rows of G with `game_type` == "REG".
* Numeric pbp flags (`pass`, `rush`, `qb_kneel`, `qb_spike`, `rush_attempt`): NaN -> 0. Other numeric columns (`epa`, `wp`, `xpass`, `qtr`, `rushing_yards`, `play_id`) keep NaN.
* All arithmetic in float64.

# TABLE A: team-game table (key game_id, team) -> `blind_nfl_prs.csv`
Universe: two rows per game of G: (game_id, team = home_team, opp = away_team) and (game_id, team = away_team, opp = home_team), after the code replacement.

Plays: pbp rows with `season_type` == "REG", (pass == 1 or rush == 1), qb_kneel != 1, qb_spike != 1, epa not NaN, wp not NaN with 0.05 <= wp <= 0.95, posteam and defteam not null, and whose
game_id is a REG game of G (inner join; the play's date is that game's date). O = posteam, D = defteam. kind = "pass" if pass == 1 else "rush".
Observations: group plays by (game_id, O, D, kind): n = number of plays, s = sum of epa, y = s / n.
Neutral rows: plays (as above) with qtr <= 3, 0.20 <= wp <= 0.80 and xpass not NaN, grouped by (game_id, O): nn = count, sx = sum of xpass, sp = sum of pass.

For EVERY distinct date d of the universe, compute the following and use it for all universe rows dated d:
1. Team game lists: for each team, the REG games of G in which it plays (home or away) with date < d, ordered by (date, game_id); keep the last 12; rank = 0 for the most recent, 1 for the next, ... up to 11.
2. Entering observations: observations with date < d such that (game_id, O) has a rank in step 1 OR (game_id, D) has a rank (a rank for (game, team) means that game is in that team's kept list).
   r = the smaller of the two ranks that exist. weight w = n x 0.5 ** (r / 6).
3. For kind in {pass, rush}, using the entering observations of that kind (skip the kind if there are none: all its outputs NaN): teams = every team appearing as O or D. Unknowns: b0, a_t for each team,
   d_t for each team. Solve exactly (normal equations) min over these of  sum w x (y - b0 - a_O - d_D)^2 + 50 x (sum_t a_t^2 + sum_t d_t^2)   (b0 is not penalised).
   off_t = b0 + a_t, def_t = b0 + d_t. nO_t = sum of n of the entering observations of that kind with O == t; nD_t = same with D == t. K = 150 for pass, 100 for rush.
   offS_t = b0 + nO_t / (nO_t + K) x (off_t - b0); defS_t = b0 + nD_t / (nD_t + K) x (def_t - b0). A team not among `teams` has NaN.
4. League expected pass rate lx = (sum of sx) / (sum of nn) over the neutral rows whose game_id is the game_id of ANY entering observation (either kind); NaN if the denominator is 0.
5. PROE for team T: join T's kept games from step 1 (with their rank) to the neutral rows on (game_id, O == T) (inner). wg = 0.5 ** (rank / 6). proe_T = sum(wg x (sp - sx)) / sum(wg x nn); NaN if the
   denominator is not > 0 or there are no joined rows.
6. For a universe row (team T, opp U) dated d:
   * `prs_off_pass_pre` = offS_T (pass), `prs_off_rush_pre` = offS_T (rush), `prs_def_pass_pre` = defS_T (pass), `prs_def_rush_pre` = defS_T (rush)
   * `prs_pass_rate_pre` = lx + proe_T
   * `prs_exp_epa_pre` = pA x (offS_T(pass) + defS_U(pass) - b0(pass)) + (1 - pA) x (offS_T(rush) + defS_U(rush) - b0(rush)), pA = prs_pass_rate_pre (NaN if any term is NaN).
Output columns: game_id, team, prs_off_pass_pre, prs_off_rush_pre, prs_def_pass_pre, prs_def_rush_pre, prs_pass_rate_pre, prs_exp_epa_pre (all universe rows).

# TABLE B: rusher-game table (key game_id, team = RUSHER gsis id) -> `blind_nfl_ryt.csv`
Carries: pbp rows (ANY season_type) with rush_attempt == 1, qb_kneel != 1, rusher_player_id not null, rushing_yards not NaN, posteam and defteam not null, and game_id in G (inner join; take season and
date from G, not from pbp). y = rushing_yards. O = posteam, D = defteam (after code replacement).
Group of a rusher: take the FIRST row of players.parquet for each gsis_id; grp = "QB" if its `position` == "QB", else "RB" (including rushers absent from the file).
Order carries by (date, game_id, play_id) with a stable sort. Indicators: e_k = 1[y >= k] for k in {7, 10, 15, 20, 30, 40}; stuff = 1[y <= 0].
Universe: one row per (game_id, rusher_player_id) present in the carries; opp = D of that rusher's FIRST carry of that game in the order above. season, date = the game's.

For a universe row (rusher R, season s, date d, group g, opponent U):
* Rusher: the carries of R with season in [s-2, s] and date < d, in the order above; if there are N of them, the j-th (j = 0 oldest .. N-1 newest) gets weight 0.5 ** ((N - 1 - j) / 25).
  num_k = sum of weight x e_k; W = sum of weights (both 0 when N = 0).
* Group prior: P_k = (number of carries with grp == g, season in [s-2, s], date < d and y >= k) / (number of carries with grp == g, season in [s-2, s], date < d); NaN if the denominator is 0.
* League: over ALL carries with season in [s-1, s] and date < d: L_k = share with y >= k, L_stuff = share with y <= 0 (NaN if no carries).
* Defence: over carries with D == U, season in [s-1, s] and date < d: n_U = count, c_k = count with y >= k, c_stuff = count with y <= 0 (all 0 when none).
* r_k = (num_k + 60 x P_k) / (W + 60); e_k = (c_k + 100 x L_k) / (n_U + 100).
* `ryt_p<k>_pre` = min(1, r_k x e_k / L_k) for k in {7, 10, 15, 20, 30, 40} (NaN if L_k is NaN or not > 0, or r_k NaN).
* `ryt_opp_stuff_pre` = ((c_stuff + 100 x L_stuff) / (n_U + 100)) / L_stuff (NaN if L_stuff NaN or not > 0).
Output columns: game_id, team (= rusher gsis id), ryt_p7_pre, ryt_p10_pre, ryt_p15_pre, ryt_p20_pre, ryt_p30_pre, ryt_p40_pre, ryt_opp_stuff_pre (all universe rows).

Write both CSVs (full float precision, e.g. `float_format="%.17g"`) and `notes.json`.

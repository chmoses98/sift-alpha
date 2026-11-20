# Blind brief: NFL batch 11, player expected touchdowns (one input, 3 value columns)

You get `data/games.csv` (nflverse schedule) and `data/pbp/play_by_play_<season>.parquet` (2010-2026). Write your own implementation from this text only and write `out.csv` with one row per
(game_id, player) and the columns under Output (empty cell = missing). float64. Do not look for any other implementation.

## 1. Games and opportunities
* games.csv rows with season >= 2010 and home_score present (first row per game_id). date = gameday. Codes OAK -> LV, SD -> LAC, STL -> LA in home_team, away_team and pbp posteam.
* Team slots: (team = home_team, opp = away_team) and (team = away_team, opp = home_team); a team's games are ordered by (date, game_id).
* Opportunities: pbp rows of kept games with posteam present and two_point_attempt != 1 (missing = 0):
  - target: play_type == "pass" and receiver_player_id present; player = receiver_player_id; td = 1 if pass_touchdown == 1.
  - carry: play_type == "run", rusher_player_id present and qb_scramble != 1 (missing = 0); player = rusher_player_id; td = 1 if rush_touchdown == 1.
  - T = posteam (code replaced). Season / date = the game's.
* Cell = 10 * kind + 2 * yb + dg with kind = 0 target / 1 carry; yb from yardline_100: <= 2 -> 0, <= 5 -> 1, <= 10 -> 2, <= 20 -> 3, else (incl. missing) 4; dg = 1 if down is 3 or 4, else 0.
* Model for season S: REF = opportunities of seasons max(2010, S - 3) .. max(2010, S - 1) (for S = 2010 that is 2010 itself); p_all = mean td over REF; p_cell = (sum td + 10 p_all)/(count + 10) over
  REF opportunities in the cell; a cell absent from REF gets p_all. Each opportunity of season S gets x = p_cell from the season-S model.

## 2. Aggregates
* Player-game (game, T, player) with >= 1 opportunity: xtd = sum x over his opportunities; xtd_team = sum x over all opportunities of (game, T).
* A player's player-games are ordered by (date, game_id, T). EWM sums, half-life 6: W(z) at item i = sum over j <= i of 0.5 ** ((i - j)/6) z_j. Player state: W_x = W(xtd), W_t = W(xtd_team), W_1 = W(1),
  read after his last player-game dated strictly before the row's date.
* Club state: over the club's played games in order (team slots of kept games), z = the club's xtd_team in that game (0 if it has no opportunity rows), half-life 6: C_t = W(z), C_1 = W(1),
  read after the club's last game dated strictly before the row's date.
* League constants for season S from season S - 1: L_share = mean over player-games of season S - 1 with xtd_team > 0 of xtd / xtd_team; K = 4 * (mean of the club z over all team slots of season S - 1).

## 3. Rows (games of season >= 2013)
* For team slot (g, T) dated d: prev = T's last 4 games dated strictly before d. Candidates = players with a player-game for T in one of those games; q = latest date of those.
  A player who is a candidate for both teams keeps the team with the larger q (equal: alphabetically smaller code). Row: game_id, team = player id, pteam = T.
* pxt_xtd_pg_pre = W_x / W_1; pxt_share_pre = (W_x + K L_share) / (W_t + K); pxt_exp_td_pre = pxt_share_pre * C_t / C_1.

## Output
`out.csv`: game_id, team (player id), pxt_xtd_pg_pre, pxt_share_pre, pxt_exp_td_pre. Floats '%.17g'. Also write `notes.json` = {"ambiguities": [...]}.

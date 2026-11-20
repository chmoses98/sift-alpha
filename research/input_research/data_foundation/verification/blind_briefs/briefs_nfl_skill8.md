# Blind brief: NFL batch 8, skill-position availability (one input, 5 value columns)

You get `data/games.csv` (nflverse schedule), `data/pbp/play_by_play_<season>.parquet` (2010-2026) and `data/injuries/injuries_<season>.parquet` (nflverse weekly injury reports).
Write your own implementation from this text only and write `out.csv` with one row per (game_id, team) and the columns under Output (empty cell = missing). float64. Do not look for any
other implementation.

## 1. Games
* games.csv rows with season >= 2010 and home_score present (first row if a game_id repeats). date = gameday.
* Codes OAK -> LV, SD -> LAC, STL -> LA in home_team, away_team, pbp posteam and injury `team`.
* kickoff = gameday + " " + the first 5 characters of gametime (a missing gametime -> "09:00"), local time America/New_York, converted to UTC.
* Team-games: (game, home_team) and (game, away_team).

## 2. Player usage shares (history)
* Plays: pbp rows of kept games with posteam present and two_point_attempt != 1 (missing = 0). Target: play_type == "pass" and receiver_player_id present (player = receiver).
  Carry: play_type == "run", rusher_player_id present and qb_scramble != 1 (missing = 0) (player = rusher). T = posteam (code replaced).
* Per (game, T): n_tgt = targets, n_car = carries, n_rzt = targets with yardline_100 <= 20, n_air = sum over targets of air_yards (missing -> 0).
* Per (game, T, player) with at least one target or carry: tgt, car, rzt, air the same sums over his plays. Shares: s_tgt = tgt / n_tgt, s_air = air / n_air, s_rzt = rzt / n_rzt, s_car = car / n_car,
  each UNDEFINED when its denominator <= 0 (a share may be negative or exceed 1 for air).
* A player's games = his (game, T) rows ordered by (date, game_id, T). For each share x: EWM with half-life 4 over those games, pandas ewm(halflife=4, adjust=True, ignore_na=False).mean()
  semantics: undefined games are skipped in numerator and denominator but keep their position; the value AFTER a game is the EWM including it.
* For a row dated d, a player's share value = the value after his last game dated strictly before d; missing if he has none or the value is undefined.

## 3. Injury listings
* An injury row belongs to the team-game with the same (season, week, team) (team code replaced). Its time = date_modified parsed as UTC; rows with no parseable date_modified are never used.
* usable rows of a team-game: its injury rows with date_modified <= kickoff.
* listed players of a team-game: distinct gsis_id (present) of usable rows with report_status in {Out, Doubtful} and position in {WR, TE, RB, FB}.

## 4. Columns (rows: team-games of season >= 2013)
If the team-game has NO usable row, every column is missing. Otherwise, summing over its listed players (a missing share counts 0):
* ska_vac_target_share_pre = sum of s_tgt; ska_vac_air_share_pre = sum of s_air; ska_vac_rz_target_share_pre = sum of s_rzt; ska_vac_carry_share_pre = sum of s_car;
* ska_n_listed_pre = number of listed players. (A usable team-game with no listed player has 0 in every column.)

## Output
`out.csv`: game_id, team, ska_vac_target_share_pre, ska_vac_air_share_pre, ska_vac_rz_target_share_pre, ska_vac_carry_share_pre, ska_n_listed_pre. Floats '%.17g'.
Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.

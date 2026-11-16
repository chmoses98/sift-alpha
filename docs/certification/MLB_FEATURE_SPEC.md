# MLB game-level feature specification (certification spec v1, RESEARCH_ONLY)

Written specification of the first MLB dataset (`alpha_engine.certify.mlb_game_v1`). An independent implementation
built from this text alone, without reading that module, must reproduce the dataset column for column.
Tolerance: |a - b| <= 1e-6 * max(1, |a|), with identical missing-value patterns. Agent-written, not human verified.

## Inputs
* Private vault archives `archives/MLB/postgame_feed_compact/<S>/mlb_statsapi/collected-20261116`, S = 2022..2026,
  restored to one directory per season. Each game is one file `<gamePk>.json`. Ignore every file whose name starts
  with `_` (for example `_schedule.json`).
* Fields used, by JSON path:
  `pk`; `game.type`; `game.season`; `game.gameNumber`; `datetime.officialDate`; `game_info.firstPitch`;
  `teams.home.id`, `teams.away.id`; `linescore.teams.home.runs`, `linescore.teams.away.runs`;
  `box.<side>.pitchers` (list of player ids in order of appearance); `box.<side>.players` (list of objects with
  `id` and `pit`, the pitching line: `outs`, `runs`, `strikeOuts`, `baseOnBalls`, `battersFaced`);
  `plays` (list; each element has `end`, an ISO-8601 UTC timestamp).

## Game table
1. Keep games with `game.type == "R"` (regular season). All 12,148 such games in the archive are final.
2. `game_id` = `pk` (integer). If a `pk` appears in more than one season directory keep the lowest season.
3. `season` = integer `game.season`. `official_date` = `datetime.officialDate` (string `YYYY-MM-DD`).
4. `start_utc` = `game_info.firstPitch` parsed as a UTC instant. `end_utc` = the `end` of the LAST element of `plays`,
   parsed as a UTC instant. Both exist for every kept game; a game missing either is dropped and counted.
5. `home_runs`, `away_runs` = the linescore team runs. `total_runs` = their sum.
   `y_home_win` = 1 if `home_runs > away_runs` else 0.
6. `home_sp_id`, `away_sp_id` = the FIRST element of `box.<side>.pitchers` (the pitcher who started).
   The starter's line is the element of `box.<side>.players` whose `id` equals that id; its `pit` object gives
   `outs`, `runs`, `strikeOuts`, `baseOnBalls`, `battersFaced` (integers; a missing value counts as 0).

## Point-in-time rule
For a game `g`, another game `h` is **prior** when `h.season == g.season`, `h` is a kept game, and
`h.end_utc < g.start_utc` (strictly). Nothing else may be used: not games of other seasons, not games that ended
at or after `g`'s first pitch (including a suspended game finished later, or the first game of a doubleheader that
ran long). Features of `g` never use `g` itself.

## Team features (for each side `X` in `home`, `away`; team = `teams.X.id`)
Let `H` be the prior games in which that team played (home or away), ordered by (`end_utc`, `game_id`) ascending.
For each `h` in `H`: `rs` = the team's runs in `h`, `ra` = its opponent's runs in `h`.
* `X_n_pre` = |H| (integer, 0 when empty).
* `X_rs_pg_pre` = mean of `rs` over H. `X_ra_pg_pre` = mean of `ra` over H.
* `X_win_pct_pre` = share of H with `rs > ra`.
* `X_rs_l10_pre`, `X_ra_l10_pre` = mean of `rs`, `ra` over the LAST min(10, |H|) games of H.
* All five are missing when |H| = 0.

## Starter features (for each side `X`; pitcher = `X_sp_id`)
Let `P` be the prior games in which that pitcher was the FIRST element of `box.<side>.pitchers` for either side
(his starts only; relief appearances are ignored), using his line from that game.
* `X_sp_n_pre` = |P| (integer, 0 when empty).
* `X_sp_ip_ps_pre` = (sum of `outs` over P) / 3 / |P|. Missing when |P| = 0.
* `X_sp_ra9_pre` = 27 * (sum of `runs`) / (sum of `outs`). Missing when the sum of `outs` is 0.
* `X_sp_k_rate_pre` = (sum of `strikeOuts`) / (sum of `battersFaced`).
  `X_sp_bb_rate_pre` = (sum of `baseOnBalls`) / (sum of `battersFaced`). Missing when the sum of `battersFaced` is 0.

## Output
One row per kept game, sorted by (`start_utc`, `game_id`) ascending. Columns in this order:

`game_id, season, official_date, start_utc, end_utc, game_number, home_id, away_id, home_sp_id, away_sp_id,`
then for `X` = `home` and then `away`: `X_n_pre, X_rs_pg_pre, X_ra_pg_pre, X_win_pct_pre, X_rs_l10_pre, X_ra_l10_pre,
X_sp_n_pre, X_sp_ip_ps_pre, X_sp_ra9_pre, X_sp_k_rate_pre, X_sp_bb_rate_pre`,
then `home_runs, away_runs, total_runs, y_home_win`.

`game_number` = `game.gameNumber`. `start_utc` and `end_utc` are written as strings `YYYY-MM-DDTHH:MM:SS.mmmZ`
(millisecond precision, UTC). Integer columns: `game_id, season, game_number, home_id, away_id, home_sp_id,
away_sp_id, *_n_pre, *_sp_n_pre, home_runs, away_runs, total_runs, y_home_win`. All other feature columns are
floating point with missing = NaN. Written as Parquet.

## Labels and what is NOT pregame
`home_runs, away_runs, total_runs, y_home_win, end_utc` are outcomes. The starter IDENTITY (`X_sp_id`) is read from
the box score; it is known when the lineup card is exchanged, before first pitch, but this dataset does not prove
when. A user who needs an earlier decision time must replace it with an announced probable.

# NBA player-box feature specification v1.1 (certification spec, RESEARCH_ONLY)

Player-level pregame features from archived ESPN player box scores (sportsdataverse release files held in the private
vault), seasons 2002-2027. This file is the only document an independent re-implementation may read.
Agent-written, not human verified. It adds a dataset; no existing dataset changes.

## Input
Every file `player_box_<YYYY>.parquet` found recursively under `<root>`, read in sorted file-path order.
Columns used: `game_id, season, season_type, game_date, athlete_id, team_id, minutes, points, rebounds, assists, starter`.

## Row table
1. Keep rows with `season_type == 2`, non-null `athlete_id` and non-null `team_id`. Cast `game_id`, `athlete_id`,
   `team_id`, `season` to int64; `date` = `game_date` as a calendar date string `YYYY-MM-DD`.
2. Drop duplicate (`game_id`, `athlete_id`) rows, keeping the first in file-path then row order.
3. A (`season`, `team_id`) is a **league team** when it has at least 5 distinct `game_id` in that season. Keep only rows
   of league teams. (v1.1: the threshold was 20 in the unregistered v1 draft, which excluded the season in progress.)
4. `appeared` = `minutes` is non-null and `minutes > 0`. `starter` is true only when the value is boolean True
   (null counts as false).
5. Row order for "earlier": within a group, sort by (`date`, `game_id`) ascending.

## Player features (one row per kept `game_id`, `athlete_id`)
History = the same athlete's kept rows in the same `season` (any team) with `date` strictly earlier than this row's `date`.
Prior appearances = history rows with `appeared`. All shares/means are NaN when their denominator is 0.

| column | definition |
|---|---|
| `n_rows_pre` | number of history rows |
| `n_app_pre` | number of prior appearances |
| `app_rate_pre` | `n_app_pre / n_rows_pre` |
| `min_mean_pre` | mean `minutes` over prior appearances |
| `min_last5_pre` | mean `minutes` over the last (at most) 5 prior appearances |
| `start_rate_pre` | share of prior appearances with `starter` true |
| `heavy38_rate_pre` | share of prior appearances with `minutes >= 38` |
| `full30_n_pre` | number of prior appearances with `minutes >= 30` |
| `pts_ge25_full30_pre` | share of those `full30` appearances with `points >= 25` |
| `pts_ge30_full30_pre` | share of those `full30` appearances with `points >= 30` |
| `pts_p90_full30_pre` | 90th percentile (linear interpolation between order statistics, numpy default) of `points` over the `full30` appearances; NaN when fewer than 5 |
| `cov_pts_reb_pre`, `cov_pts_ast_pre`, `cov_reb_ast_pre` | sample covariance (denominator n-1) of the pair over prior appearances; NaN when `n_app_pre < 5` |
| `var_pra_pre` | sample variance (n-1) of `points + rebounds + assists` over prior appearances; NaN when `n_app_pre < 5` |
| `pra_var_ratio_pre` | `var_pra_pre / (var(points) + var(rebounds) + var(assists))` (sample variances, same rows); NaN when `n_app_pre < 5` or the denominator is 0 |

`points`, `rebounds`, `assists` of an appearance with a null value count as 0.

## Team bench features (joined to every row of the team-game)
Team-game = (`game_id`, `team_id`). For a team-game, over its `appeared` rows: `bench_min` = sum of `minutes` of rows with
`starter` false; `all_min` = sum of `minutes`; `bench_share` = `bench_min / all_min` (NaN when `all_min == 0`).
History = the same `team_id`'s team-games in the same `season` with `date` strictly earlier (a team-game's `date` is the
date of its rows).

| column | definition |
|---|---|
| `team_games_pre` | number of history team-games |
| `team_bench_share_pre` | mean of `bench_share` over history team-games (NaN values skipped; NaN when none) |
| `team_bench_min_mean_pre` | mean `bench_min` over history team-games |
| `team_bench_min_sd_pre` | sample standard deviation (n-1) of `bench_min` over history team-games; NaN when fewer than 2 |

## Labels (outcomes; never features)
`y_appeared` (1.0 / 0.0), `y_minutes` (`minutes` if appeared else 0.0), `y_points`, `y_rebounds`, `y_assists`
(value with null as 0 if appeared, else NaN), `y_starter` (1.0 / 0.0).

## Output
Columns, in order: `key` (string `"<game_id>:<athlete_id>"`), `game_id`, `athlete_id`, `team_id`, `season`, `date`,
then the player features in table order, then the team features in table order, then the labels. Sort by
(`date`, `game_id`, `athlete_id`). Float columns float64.

## Catalog mapping
* `nba.heavy_minutes_tail_prob`: `heavy38_rate_pre`, `full30_n_pre`, `n_app_pre`
* `nba.points_upper_tail_rate`: `full30_n_pre`, `pts_ge25_full30_pre`, `pts_ge30_full30_pre`, `pts_p90_full30_pre`
* `nba.combo_covariance`: `cov_pts_reb_pre`, `cov_pts_ast_pre`, `cov_reb_ast_pre`, `var_pra_pre`, `pra_var_ratio_pre`
* `nba.bench_minutes_distribution`: `team_bench_share_pre`, `team_bench_min_mean_pre`, `team_bench_min_sd_pre`

Limits: same-season history only (no carry-over across seasons), no opponent adjustment, no overtime split, and no
lineup-stint data (the catalog's lineup-stint source is not used). The catalog definitions are therefore met in part.

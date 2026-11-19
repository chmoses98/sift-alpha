# NBA long-history team-box feature specification v1 (certification spec, RESEARCH_ONLY)

Team-level pregame features from archived ESPN team box scores (sportsdataverse release files held in the private
vault), seasons 2002-2027. This file is the only document an independent re-implementation may read.
Agent-written, not human verified. It adds a dataset; the existing NBA dataset `f079a9ffa007` is unchanged.

## Inputs
* Team boxes: every file `team_box_<YYYY>.parquet` found recursively under `<root>`. Two rows per game.
  Columns used: `game_id, season, season_type, game_date, team_id, team_home_away, team_score,
  opponent_team_score, field_goals_made, field_goals_attempted, three_point_field_goals_made,
  three_point_field_goals_attempted, free_throws_made, free_throws_attempted, offensive_rebounds,
  defensive_rebounds, turnovers`.
* Schedules: every file `nba_schedule_<YYYY>.parquet` found recursively under `<root>`.
  Columns used: `game_id, date, neutral_site`.

`turnovers` is used as the turnover count in every season (the files' `total_turnovers` changes meaning in 2014
and is not used).

## Game table
1. Take team-box rows with `season_type == 2`.
2. A row is **usable** when all fourteen numeric columns listed above after `team_home_away` are non-null and
   `field_goals_attempted > 0`.
3. A (season, team_id) is a **league team** when it has at least 5 usable rows in that season (this removes
   All-Star and other exhibition sides).
4. Keep a game when it has exactly two usable rows, one with `team_home_away == "home"` and one `"away"`, and both
   teams are league teams of the game's season. `season` and `game_date` come from the home row.
5. `date` = `game_date` (a calendar date). `cutoff_utc` = the schedule row's `date` parsed as a UTC instant
   (missing when the game has no schedule row; if several schedule rows share the `game_id`, use the first in
   file-name order then row order). `neutral` = 1.0 if that schedule row's `neutral_site` is true, else 0.0
   (0.0 when there is no schedule row).
6. Labels: `y_home_margin` = home `team_score` - away `team_score`; `y_total` = their sum;
   `y_home_win` = 1 if `y_home_margin > 0` else 0.

## Per team-game quantities (team T in kept game h, opponent U)
`FGM, FGA, TPM, TPA, FTM, FTA, ORB, DRB, TOV, PTS` = T's row; `o*` = U's row (e.g. `oFGA`).
* `poss_T = FGA - ORB + TOV + 0.44*FTA`; `poss_U` likewise from U's row; `POSS = (poss_T + poss_U) / 2`.
* `MISS2 = (FGA - TPA) - (FGM - TPM)`; `MISS3 = TPA - TPM`; `MISSFT = FTA - FTM`.

## Point-in-time rule
For game `g`, game `h` is **prior** for team T when `h` is kept, `h.season == g.season`, T played in `h`, and
`h.date < g.date` strictly (calendar dates). Nothing else may be used, except `prev_net_prior` below.
`H` = T's prior games ordered by (`date`, `game_id`) ascending; `n` = |H|. `S(x)` = sum of x over H.
The **league** prior set `L(g)` = all team-game rows (both teams of every kept game) with the same season and
`date < g.date`; `SL(x)` = sum over `L(g)`.

## Team features (for each side `X` in `home`, `away`)
| Column | Definition | Missing when |
|---|---|---|
| `X_n_pre` | n (integer) | never |
| `X_off_rtg_pre` | 100 * S(PTS) / S(POSS) | n = 0 |
| `X_def_rtg_pre` | 100 * S(oPTS) / S(POSS) | n = 0 |
| `X_net_rtg_pre` | `X_off_rtg_pre` - `X_def_rtg_pre` | n = 0 |
| `X_pace_pre` | S(POSS) / n | n = 0 |
| `X_efg_pre` | (S(FGM) + 0.5*S(TPM)) / S(FGA) | n = 0 |
| `X_tov_pre` | S(TOV) / S(poss_T) | n = 0 |
| `X_orb_pre` | S(ORB) / (S(ORB) + S(oDRB)) | n = 0 or denominator 0 |
| `X_ftr_pre` | S(FTA) / S(FGA) | n = 0 |
| `X_d_efg_pre` | (S(oFGM) + 0.5*S(oTPM)) / S(oFGA) | n = 0 |
| `X_d_tov_pre` | S(oTOV) / S(poss_U) | n = 0 |
| `X_d_orb_pre` | S(oORB) / (S(oORB) + S(DRB)) | n = 0 or denominator 0 |
| `X_d_ftr_pre` | S(oFTA) / S(oFGA) | n = 0 |
| `X_three_rate_pre` | S(TPA) / S(FGA) | n = 0 |
| `X_miss2_pg_pre`, `X_miss3_pg_pre`, `X_missft_pg_pre` | S(MISS2)/n, S(MISS3)/n, S(MISSFT)/n | n = 0 |
| `X_win_pct_pre` | share of H with PTS > oPTS | n = 0 |
| `X_pyth_pct_pre` | P^14 / (P^14 + A^14), P = S(PTS), A = S(oPTS) | n = 0 |
| `X_pyth_resid_pre` | `X_win_pct_pre` - `X_pyth_pct_pre` | n = 0 |
| `X_close_n_pre` | count of H with abs(PTS - oPTS) <= 5 (integer) | never |
| `X_close_win_pct_pre` | share of those with PTS > oPTS | `X_close_n_pre` = 0 |
| `X_net_l10_pre` | 100 * (sum PTS - sum oPTS) / sum POSS over the LAST min(10, n) games of H | n = 0 |
| `X_rest_days` | (g.date - date of the last game of H) in days (float) | n = 0 |
| `X_b2b` | 1.0 if `X_rest_days` == 1 else 0.0 | n = 0 |
| `X_prev_net_prior` | T's final net rating of season `g.season - 1`: 100*(sum PTS - sum oPTS)/sum POSS over ALL kept games of T in that season | T has no kept game in that season |

## Matchup features (one per game; "own offence against the opponent's defence, relative to the league")
League values: `lg_efg = (SL(FGM) + 0.5*SL(TPM)) / SL(FGA)`, `lg_tov = SL(TOV) / SL(poss_T)`,
`lg_orb = SL(ORB) / (SL(ORB) + SL(oDRB))`, `lg_ftr = SL(FTA) / SL(FGA)`; missing when `L(g)` is empty.
For side X with opponent side Y and factor f in (`efg`, `tov`, `orb`, `ftr`):
`X_exp_<f>` = `X_<f>_pre` + `Y_d_<f>_pre` - `lg_<f>`; missing when any of the three is missing.
Rebound pool: `exp_miss2` = `home_miss2_pg_pre` + `away_miss2_pg_pre`; `exp_miss3`, `exp_missft` likewise;
`exp_reb_pool` = `exp_miss2` + `exp_miss3`; each missing when either side is missing.
`exp_poss` = `home_pace_pre` * `away_pace_pre` / (SL(POSS) / |L(g)|) ; missing when either pace is missing.

## Output
One row per kept game sorted by (`date`, `game_id`) ascending. Columns in this order:
`game_id, season, date, cutoff_utc, neutral, home_team_id, away_team_id,`
then for `X` = `home` then `away`: the table columns in table order (`X_n_pre` ... `X_prev_net_prior`),
then `home_exp_efg, home_exp_tov, home_exp_orb, home_exp_ftr, away_exp_efg, away_exp_tov, away_exp_orb,
away_exp_ftr, exp_miss2, exp_miss3, exp_missft, exp_reb_pool, exp_poss, y_home_margin, y_total, y_home_win`.

Types: `game_id, season, home_team_id, away_team_id, X_n_pre, X_close_n_pre, y_home_win` integers;
`date` a string `YYYY-MM-DD`; `cutoff_utc` a string `YYYY-MM-DDTHH:MM:SSZ` (empty string when missing);
`y_home_margin, y_total` and everything else floating point with missing = NaN. Written as Parquet.

## Not pregame
`y_*` are outcomes. `cutoff_utc` is the scheduled tip time. No injury, lineup or minutes information is used.

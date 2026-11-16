# CBB game-level feature specification (certification spec v1.1, RESEARCH_ONLY)

This is the written specification of the CBB Phase 8 dataset (`training_sets_multi cbb`). An independent
implementation built from this text alone, without reading `alpha_engine/features/cbb_box.py` or
`alpha_engine/foundation/training_sets_multi.py`, must reproduce the dataset column-for-column.
Tolerance: |a - b| <= 1e-6 * max(1, |b|), with identical missing-value patterns.

## Inputs
* `team_box/team_box_<S>.parquet` and `schedules/mbb_schedule_<S>.parquet` for every season S >= 2006 present
  (SportsDataverse hoopR-mbb ESPN releases). Read files in ascending S and concatenate in file row order.
* Schedule columns used: `game_id, start_date, neutral_site, conference_competition, home_id, away_id,
  home_conference_id, away_conference_id`. Deduplicate the schedule on `game_id`, keeping the first occurrence.

## Team-game table
1. Coerce to numeric (invalid -> missing): `field_goals_attempted, field_goals_made, three_point_field_goals_made,
   free_throws_attempted, offensive_rebounds, defensive_rebounds, turnovers, team_score`.
2. Keep rows with `season_type` in {2, 3}; drop rows missing any of the eight columns; deduplicate on
   (`game_id`, `team_id`) keeping the first.
3. `date` = `game_date` parsed as a calendar date (no time zone conversion).
4. Own possessions `poss_own = FGA - OREB + TO + 0.475 * FTA`.
5. Attach the opponent's row from the same filtered table, matched on `game_id` and opponent `team_id` =
   this row's `opponent_team_id` (inner join: both sides required). Opponent fields are prefixed `o_`.
6. `poss = (poss_own + o_poss_own) / 2`; keep rows with `poss > 40`.
7. `pts_for = team_score`; `pts_against = opponent_team_score` (numeric).
   `eff_o = 100 * pts_for / poss`.
8. Four Factors (offence / defence):
   * `efg = (FGM + 0.5 * 3PM) / FGA`, `tov = TO / poss_own`, `orb = OREB / (OREB + o_DREB)`, `ftr = FTA / FGA`
   * `d_efg, d_tov, d_orb, d_ftr` = the same with the roles of the two sides swapped
     (`d_tov = o_TO / o_poss_own`, `d_orb = o_OREB / (o_OREB + DREB)`).
9. Left-join the schedule on `game_id`. `neutral = neutral_site` (missing -> false).
   `site = 0` if neutral, else `+1` if `team_home_away == "home"`, else `-1`.
   `conf_id` = `home_conference_id` if `team_id == home_id`, else `away_conference_id` if `team_id == away_id`,
   else missing.
10. Sort by (`date`, `game_id`, `team_id`), stable.

## Point-in-time ratings (per game date D, ascending over every distinct team-game date)
* History H(D) = team-game rows with `D - 400 days <= date < D` (strictly before D).
* If |H(D)| < 200: every feature for D's rows is missing, and the warm-start state is cleared.
* Weights `w = 0.5 ** (age_days / 60)`, `age_days = (D - date)` in days.
* Additive efficiency model on `y = eff_o`: `y = lg + O[team] - D[opp] + h * site`.
  Solve by weighted alternating updates, 12 iterations, in this exact order per iteration:
  1. `O[t] = sum_{rows with team t} w * (y - lg - h*site + D[opp]) / (sum_{team t} w + 3)`
  2. `D[t] = sum_{rows with opp t} w * (lg + O[team] + h*site - y) / (sum_{opp t} w + 3)` (uses the new O)
  3. `h = sum_{site != 0} w * site * (y - lg - O[team] + D[opp]) / sum_{site != 0} w` (0 if no non-neutral rows)
  4. `lg = weighted mean over all rows of (y - O[team] + D[opp] - h*site)`
  Initial values: `lg` = weighted mean of `y`; `O`, `D`, `h` from the previous solved date's final solution
  (warm start; teams absent from it start at 0), or 0 when the warm-start state is clear. The team set is the
  union of `team_id` and `opponent_team_id` in H(D).
* Features for a team-game on D (team absent from H(D) -> missing):
  * `adj_o_pre = lg + O[t]`, `adj_d_pre = lg - D[t]` (points allowed per 100; lower is better),
    `adj_net_pre = adj_o_pre - adj_d_pre`, `hca_pre = h` (same for every row on D, present even for teams absent from H)
  * `n_pre` = sum of `w` over the team's rows in H(D)
  * `tempo_pre` = sum(w * poss) / sum(w) over the team's rows
  * each factor f: sum(f * w * poss) / sum(w * poss) over the team's rows (a missing f contributes 0 to the
    numerator but its weight stays in the denominator)
  * `conf_net_pre`: in H(D), take for each team its last row (in the sort order above) among rows with a
    non-missing `conf_id`; average `adj_net` (= O + D) over teams by that conference; map the row's own `conf_id`
    (from the game's schedule) to that mean.

## Game-level dataset
* One row per game: the team-game row with `team_home_away == "home"`. Key columns: `game_id, season, date,
  home_team (= team_id), away_team (= opponent_team_id)`.
* `cutoff_utc` = schedule `start_date` (UTC). Outcomes: `y_home_margin = pts_for - pts_against`,
  `y_total = pts_for + pts_against`, `y_home_win = 1 if margin > 0 else 0`.
* `neutral` (0/1 float); `conference_game` = schedule `conference_competition` (missing -> 0).
* Feature columns: `home_<f>` and `away_<f>` for f in
  `adj_o_pre, adj_d_pre, adj_net_pre, hca_pre, tempo_pre, n_pre, conf_net_pre, efg_pre, tov_pre, orb_pre, ftr_pre,
  d_efg_pre, d_tov_pre, d_orb_pre, d_ftr_pre`, joined on (`game_id`, team); the away side's values are missing when
  its team-game row is absent.
* `split`: train 2006-2019, validate 2020-2022, test 2023-2026, prospective 2027.
* Sort by (`date`, `game_id`), stable.

## Amendments
* **v1.1 (2026-11-16).** `conf_net_pre` is exempt from the "team absent from H(D) -> missing" rule. It is the
  conference mean for the row's own `conf_id` whenever that conference has at least one member in H(D), even when
  the team itself has no row in H(D). Found by the blind comparison: 193 of 3.7M cells (84 home, 109 away) differed
  only in this respect. The value uses rows dated before D only, so this is a specification gap, not leakage.

# CFB game-level feature specification (certification spec v1.1, RESEARCH_ONLY)

This is the written specification of the CFB Phase 8 dataset (`training_sets_multi cfb`). An independent
implementation built from this text alone, without reading `alpha_engine/features/cfb_cfbd.py`,
`alpha_engine/features/cbb_box.py` or `alpha_engine/foundation/training_sets_multi.py`, must reproduce the dataset
column-for-column. Tolerance: |a - b| <= 1e-6 * max(1, |b|), with identical missing-value patterns.

## Inputs
CFBD research cache `<cache>/<S>/<name>.json.gz` for S = 2014..2025 in ascending order (a missing file is empty;
the payload is a JSON list, or an object whose `data` member is the list). Concatenate in season order:
* `games`; `advanced_regular_nogarbage` (advanced team box, garbage time excluded, regular season only);
  `drives_regular` followed by `drives_postseason`; `portal`; `returning_production`; `talent`; `recruiting_teams`.
* Not used, by design: betting lines, end-of-season ratings, season totals, polls, provider pregame Elo, postseason
  advanced box.

## Games
* Deduplicate on `id` (first). Keep `completed == true` with both `homePoints` and `awayPoints` present, and
  `homeClassification == "fbs"` or `awayClassification == "fbs"`.
* `start_utc` = `startDate` as UTC; `date` = the America/New_York calendar date of `start_utc`. `game_id = id`.

## Team-game statistics (one row per advanced-box record; deduplicate on (`gameId`, `team`), first)
* From `offense` / `defense`: `plays` (offense.plays), `ppa_o` (offense.ppa), `ppa_d` (defense.ppa),
  `sr_o/sr_d` (successRate), `expl_o/expl_d` (explosiveness), `pass_ppa_o/_d` (passingPlays.ppa),
  `rush_ppa_o/_d` (rushingPlays.ppa), `line_yds_o` (offense.lineYards), `stuff_o` (offense.stuffRate).
  A value that is not a JSON number is missing.
* Drives: drive points = 7 if `driveResult` contains `TD` and contains none of `DEF`, `INT TD`, `FUMBLE TD`,
  `PUNT TD`; 3 if `driveResult` equals `FG`; else 0. Per (`gameId`, `offense`): `ppd_o` = mean drive points,
  `start_ytg_o` = mean `startYardsToGoal`. `ppd_d` = the opponent's `ppd_o` in the same game.
* Inner-join to the filtered games. `site = 0` if `neutralSite` is true, else `+1` if team == `homeTeam`, else `-1`.

## Team-game frame
Every kept game contributes two rows (home team vs away team, away team vs home team) with
`game_id, date, season, team, opp`; the statistics above are left-joined on (`game_id`, `team`), so games without
an advanced-box record (e.g. postseason, FCS opponents) still receive features.

## Point-in-time in-season features (per distinct game date D of the frame, ascending)
* History H(D) = frame rows with non-missing `ppa_o` and `D - 400 days <= date < D`.
* If |H(D)| < 100: every in-season feature for D's rows is missing and the warm-start state is cleared.
* Time weights `w = 0.5 ** (age_days / 120)`.
* Opponent-adjusted EPA: on `y = ppa_o`, `y = lg + O[team] - D[opp] + h * site`, solved exactly like the CBB
  ratings (CBB spec: 12 iterations of O, D, h, lg updates in that order, shrinkage +3 in the O and D denominators,
  warm start from the previous solved date, team set = union of team and opp in H(D)).
  * `adj_epa_o_pre = lg + O[t]`, `adj_epa_d_pre = lg - D[t]`, `adj_epa_net_pre = o - d`, `hfa_epa_pre = h`,
    `n_pre` = sum of `w` over the team's rows (as `team`). Teams absent from H(D) -> missing (except `hfa_epa_pre`).
* Window means for c in `sr_o, sr_d, expl_o, expl_d, pass_ppa_o, rush_ppa_o, pass_ppa_d, rush_ppa_d, line_yds_o,
  stuff_o, ppd_o, ppd_d, start_ytg_o`: weight `v = w * plays` (missing plays -> 60);
  `c_pre = sum(v * c) / sum(v)` over the team's rows in H(D) with non-missing c.

## Season priors (team, season)
* `talent_prior` = talent composite (`year` is the season); `ret_ppa_prior` = returning `percentPPA`,
  `ret_usage_prior` = returning `usage`.
* `recruit_prior` = mean recruiting `points` over seasons S-3..S.
* Portal, entries with `season == S` and `transferDate` (UTC) before S-08-01 00:00 UTC:
  `portal_in_prior` = count by `destination` (non-missing), `portal_out_prior` = count by `origin`,
  `portal_stars_net_prior` = mean_stars_in * count_in - mean_stars_out * count_out (missing terms -> 0).
* Outer-join the four sources on (team, season); attach to frame rows by (team, season).

## Game-level dataset
* One row per kept game: `game_id, season, date, cutoff_utc (= start_utc), home_team, away_team,
  neutral (= neutralSite, missing -> 0), conference_game (= conferenceGame, missing -> 0),
  postseason (= 1 if seasonType != "regular")`.
* Outcomes: `y_home_margin = homePoints - awayPoints`, `y_total`, `y_home_win = 1 if margin > 0`.
* Features `home_<f>` / `away_<f>` for the 18 in-season features then the 7 priors, joined on (`game_id`, team).
* `split`: train 2014-2019, validate 2020-2021, test 2022-2025. Sort by (`date`, `game_id`), stable.

## Amendments
* **v1.1 (2026-11-16).** `recruit_prior` exists for (team, S), S = 2014..2025, whenever the team has at least one
  recruiting record in S-3..S; a year-S record is not required. Found by the blind comparison: 274 cells
  (6 home, 268 away) differed only in this respect. Every class used is signed before season S, so this is a
  specification gap, not leakage.

## Known semantic defect (not leakage; documented, not fixed)
The drive-points rule credits `FUMBLE RETURN TD`, `PUNT RETURN TD`, `MISSED FG TD`, `DOWNS TD`, `FG TD` and similar
labels to the drive's offense as 7 points. Most of these are scores by the defending team. In 2024 these labels cover
about 85 of 5,600 TD-labelled drives (~1.5%). Both implementations reproduce the rule as written. Correcting it
would be a new builder version (`cfb_cfbd` v2) with a new dataset hash. It must not silently rewrite the v1 dataset.

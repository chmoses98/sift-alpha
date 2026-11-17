# MLB game-level feature specification v1.1 (certification spec, RESEARCH_ONLY)

Successor of `MLB_FEATURE_SPEC.md` v1 for TEAM inputs only. v1 stays registered and unchanged. v1.1 adds season state,
Pythagorean / BaseRuns luck, one-run and late-close records, bullpen run rate and an explicit decision-time lead.
It contains NO starting-pitcher feature: the starter identity in the archive is the box-score starter, which is not a
timestamped pregame announcement.

This file is the only document an independent re-implementation may read. Agent-written, not human verified.

## Inputs
One JSON file per game: `<feed-root>/<season>/<gamePk>.json` (files whose name starts with `_` are not games).
Fields used: `pk`, `game.type`, `game.season`, `game.gameNumber`, `datetime.officialDate`, `game_info.firstPitch`,
`plays[-1].end`, `teams.<side>.id`, `linescore.teams.<side>.runs`, `linescore.innings[*].n`,
`linescore.innings[*].<side>.runs`, `box.<side>.team_stats.batting.{hits,baseOnBalls,homeRuns,totalBases,atBats}`,
`box.<side>.pitchers` (ordered list of player ids), `box.<side>.players[*].{id,pit}` with `pit.{runs,outs}`.
`<side>` is `home` or `away`. A missing or null numeric value counts as 0.

## Parameter
`lead_hours` L (a non-negative number, default 0). The decision time of game `g` is `T(g) = g.start_utc - L hours`.

## Game table
1. Keep games with `game.type == "R"`.
2. `game_id` = `pk` (integer). If a `pk` appears in more than one season directory keep the lowest season.
3. `season` = integer `game.season`. `official_date` = `datetime.officialDate`.
4. `start_utc` = `game_info.firstPitch` as a UTC instant; `end_utc` = `end` of the LAST element of `plays` as a UTC
   instant. A game missing either is dropped (and counted).
5. Per side X: `runs` = `linescore.teams.X.runs`. `home_runs`, `away_runs`, `total_runs` = sum,
   `y_home_win` = 1 if `home_runs > away_runs` else 0.
6. Per side X, per game: batting totals `H, BB, HR, TB, AB` = `hits, baseOnBalls, homeRuns, totalBases, atBats` of
   `box.X.team_stats.batting`.
7. Per side X, per game: `r6` = sum of `linescore.innings[i].X.runs` over innings with `n <= 6`.
8. Per side X, per game: reliever totals `rel_runs`, `rel_outs` = sums of `pit.runs`, `pit.outs` over every id in
   `box.X.pitchers` EXCEPT the first element, taking each pitcher's `pit` object from the element of `box.X.players`
   with that `id` (no such element or `pit` null = 0).

## Point-in-time rule
For game `g`, another game `h` is **prior** when `h.season == g.season`, `h` is kept, `h != g`, and
`h.end_utc < T(g)` strictly. Nothing else may be used.
`h` is **unresolved** for `g` when `h.season == g.season`, `h` is kept, `h != g`, `h.start_utc < T(g)` and
`h.end_utc >= T(g)` (in progress, suspended and not yet completed, or a doubleheader opener still running).

## Team features (for each side `X` in `home`, `away`; team = `teams.X.id`)
`H` = prior games in which that team played (home or away), ordered by (`end_utc`, `game_id`) ascending.
For each `h`: `rs` = the team's runs, `ra` = the opponent's runs; the team's own batting totals and its opponent's
batting totals in `h`; the team's `r6` and the opponent's `r6`; the team's own reliever totals.
Sums below are over all of `H` unless stated. `n` = |H|. All sums are exact integers before any division.

| Column | Definition | Missing when |
|---|---|---|
| `X_n_pre` | n (integer) | never (0) |
| `X_wins_pre` | count of `rs > ra` (integer) | never |
| `X_losses_pre` | count of `rs < ra` (integer) | never |
| `X_ties_pre` | count of `rs == ra` (integer) | never |
| `X_games_remaining_pre` | 162 - n (integer; the scheduled regular-season length is a published constant) | never |
| `X_run_diff_pre` | sum(rs) - sum(ra) (integer) | never (0) |
| `X_unresolved_pre` | number of unresolved games in which the team plays (integer) | never |
| `X_rs_pg_pre`, `X_ra_pg_pre` | sum(rs)/n, sum(ra)/n | n = 0 |
| `X_rs_l10_pre`, `X_ra_l10_pre` | mean of rs, ra over the LAST min(10, n) games of H | n = 0 |
| `X_win_pct_pre` | wins / (wins + losses) | wins + losses = 0 |
| `X_pyth_pct_pre` | RS^1.83 / (RS^1.83 + RA^1.83), RS = sum(rs), RA = sum(ra) | RS + RA = 0 |
| `X_pyth_luck_pre` | `X_win_pct_pre` - `X_pyth_pct_pre` | either is missing |
| `X_one_run_n_pre` | count of games with abs(rs - ra) = 1 (integer) | never |
| `X_one_run_win_pct_pre` | share of those games with rs > ra | `X_one_run_n_pre` = 0 |
| `X_bsr_rs_pg_pre` | BsR(own batting totals summed over H) / n | n = 0 or BsR undefined |
| `X_bsr_ra_pg_pre` | BsR(opponents' batting totals summed over H) / n | n = 0 or BsR undefined |
| `X_bsr_pct_pre` | S^1.83 / (S^1.83 + A^1.83), S = BsR(own totals), A = BsR(opponents' totals) | either BsR undefined, or S + A <= 0, or S < 0, or A < 0 |
| `X_bsr_luck_pre` | `X_win_pct_pre` - `X_bsr_pct_pre` | either is missing |
| `X_late_close_n_pre` | count of games with abs(team r6 - opponent r6) <= 1 (integer) | never |
| `X_late_close_win_pct_pre` | share of those games with rs > ra (final score) | `X_late_close_n_pre` = 0 |
| `X_bullpen_ra9_pre` | 27 * sum(rel_runs) / sum(rel_outs) | sum(rel_outs) = 0 |

BaseRuns for totals (H, BB, HR, TB, AB): `A = H + BB - HR`; `B = 1.02 * (1.4*TB - 0.6*H - 3*HR + 0.1*BB)`;
`C = AB - H`; `D = HR`; `BsR = A * B / (B + C) + D`. BsR is undefined when `B + C <= 0`.

`X_last_end_utc` = `end_utc` of the last game of `H` (the instant the team's features above became final), empty
string when n = 0. It is evidence of availability, not a feature.

## Output
One row per kept game, sorted by (`start_utc`, `game_id`) ascending. Columns in this order:

`game_id, season, official_date, start_utc, end_utc, game_number, home_id, away_id,`
then for `X` = `home` and then `away`, in the order of the table above (`X_n_pre` ... `X_bullpen_ra9_pre`),
then `home_last_end_utc, away_last_end_utc`, then `home_runs, away_runs, total_runs, y_home_win`.

`start_utc`, `end_utc`, `X_last_end_utc` are strings `YYYY-MM-DDTHH:MM:SS.mmmZ` (millisecond precision, UTC; fractional
seconds beyond milliseconds are truncated). Integer columns: `game_id, season, game_number, home_id, away_id`, the
columns marked integer above, `home_runs, away_runs, total_runs, y_home_win`. All other feature columns are floating
point with missing = NaN. Written as Parquet. Comparison instants use full input precision, not the truncated strings.

## Labels and what is NOT pregame
`home_runs, away_runs, total_runs, y_home_win, end_utc` are outcomes. With L = 0 a feature may depend on a game that
ended minutes before first pitch; a forecast made earlier must be built with the matching L.

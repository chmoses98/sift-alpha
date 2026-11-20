# NFL legacy builder (`alpha_engine/features/nfl.py`), amendment 1: relocated-franchise home games (2026-11-20)

## Defect (correctness, not leakage)
The builder joins play-by-play team rows (`posteam`) to the nflverse schedule (`home_team`, `away_team`). The two sources code
relocated franchises differently:
- **Play-by-play:** current codes (LA, LAC, LV).
- **Schedule:** the historical code for that franchise's home games (STL 2010–15, SD 2010–16, OAK 2010–19).

So `team == home_team` was false for both rows of **184 games**, and both rows got `home = 0`. The home team's row then took the
away team's score, rest and coach. Example: 2010 week 1 ARI at STL records 17 points for LA when LA scored 13.

The point-in-time replay could not detect this. It checks leakage, not correctness. Found by the NFL research agent; confirmed here.

## Fix
`gm.home_team` and `gm.away_team` are mapped with `TEAM_FIX = {OAK: LV, SD: LAC, STL: LA}` before the join. This is the same mapping
`nfl_ext`, `nfl_pbp_ext*` and `nfl_part_ext` already use. Test:
`tests/test_pipeline.py::test_nfl_legacy_builder_one_home_row_per_game_for_relocated_franchises` (one home row per game, correct points).

## Effect (`verification/superseded/nfl_legacy_v1_relocated_home_flag/v1_vs_v2_diff.json`)
13 of the 33 legacy inputs change values. Rows that changed (all / 2020+ / 2024+), with the largest absolute change:

| Input | Column | Rows changed | Largest change |
|---|---|---|---|
| nfl.ratings | margin_pre | 796 / 316 / 106 | 30 |
| nfl.points_vs_expected | pts_vs_exp_pre | 827 / 347 / 137 | 14.7 |
| nfl.q_scoring | pts_pre | 766 / 286 / 83 | 15 |
| nfl.team_total_split, nfl.script | exp_pts_pre / exp_total_pre | every row (league means move) | 17.2 / 1.3 |
| nfl.officials_crew | ref_pen_pre | 6,710 | 0.007 |
| nfl.rest_travel | rest, rest_gap, short_rest, bye | 2010–19 only | — |
| nfl.venue | home | 184 games, 2010–19 only | — |
| nfl.coaching | coach_games_pre | 416 | — |

Also affected: nfl.pythag_luck, nfl.ot_model, nfl.score_resid and nfl.schedule_strength. Long exponentially weighted histories
carry the old errors into recent seasons at decaying weight.

## Re-certification
- The legacy replay (`replay_verify NFL`) was re-run on the fixed builder: 33 specs. Determinism, truncation and perturbation pass
  33/33; own-game passes 32/33. The exception is `nfl.weather_pit`, which depends on as-played weather and was never certified.
- `regenerate --apply` produces **no status change**: FULL 62, PARTIAL 226, PROXY 37, and 841 missing PRIMARY slots are all unchanged.
- The previous replay is preserved as `superseded/nfl_legacy_v1_relocated_home_flag/replay_NFL.json`.
- Legacy NFL inputs were certified by replay only, as for every earlier-milestone input. They were never blind re-implemented, so no
  blind run exists to repeat. Recommendation: a blind brief for the 13 affected inputs.

## Not redone tonight (recorded, not hidden)
- **NFL training-set manifest.** `research/data_foundation_ops/training_sets/NFL.json` records a `walk_forward_home_margin` diagnostic
  computed with the v1 builder. A faithful rebuild needs 1999–2009 play-by-play, which the vault pins (manifest only) but does not hold.
  Rebuild it when that range is restored. The diagnostic was never a promotion basis.
- **NFL research study.** The overnight study (`research/nfl_certified_inputs`) is being re-scored under the same frozen protocol with
  the fixed builder (amendment A4). Both results are kept.

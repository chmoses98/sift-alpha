# Blind re-implementation brief: NFL participation-based team-game features (strictly pre-game)

Data (read-only): pbp `/tmp/claude-0/data/nfl/pbp/pbp_<season>.parquet` (use seasons 2016-2025 only), participation `/tmp/claude-0/data/nfl/part/p<season>.parquet` (2016-2025; columns nflverse_game_id, play_id, offense_formation, offense_personnel, defenders_in_box, number_of_pass_rushers, was_pressure, defense_man_zone_type, defense_coverage_type), schedule `/tmp/claude-0/data/nfl/games.csv`.
Use only pandas/numpy. Do NOT read anything under /home/user/sift-alpha. Implement from this text alone; record every ambiguity you resolve.

## Universe
Games: games.csv rows with season >= 2016 and non-null home_score. Team keys: OAK->LV, SD->LAC, STL->LA on all team columns (pbp posteam/defteam and schedule). One output row per (game_id, team) for home and away team; date = gameday.
## Play universe
pbp plays with play_deleted != 1 and aborted_play != 1 (null counts as not deleted), non-null posteam and defteam, and being a scrimmage play: (pass_attempt==1 or rush_attempt==1 or sack==1 or qb_scramble==1) and qb_kneel != 1 and qb_spike != 1 (nulls count as 0). Left-join participation on (game_id == nflverse_game_id, play_id) (drop duplicate participation keys keeping the first). dropback = qb_dropback==1. designed rush = rush_attempt==1 and qb_scramble != 1 (nulls 0).
Parsing offense_personnel: RB count = integer before " RB" in the string (e.g. '1 RB, 1 TE, 3 WR' -> RB=1, TE=1); NaN if the string is null or lacks the token.
## Pre-game feature rule
Per-game raw value r for each (game, team) (NaN when its set is empty or the game has no pbp plays). Feature `<name>_pre` for game G = pandas ewm(halflife=8, min_periods=3).mean() applied to the team's chronological (date, then game_id) series of raw values AFTER shifting by one game (so G sees only earlier games; NaN raw values keep their slot and count as missing observations).
## Raw values (offence ones keyed by posteam, defence ones by defteam)
* p11,p12,p13,p21,p22 (offense): among scrimmage plays with non-null RB and TE counts, share with (RB,TE) equal to (1,1),(1,2),(1,3),(2,1),(2,2).
* gun (offense): among scrimmage plays with non-null offense_formation, share with formation in {SHOTGUN, PISTOL, EMPTY}; empty: share == EMPTY.
* man (defence): among dropbacks with defense_man_zone_type in {MAN_COVERAGE, ZONE_COVERAGE}, share MAN_COVERAGE.
* single_high, two_high, cover0 (defence): among dropbacks with defense_coverage_type in {COVER_0,COVER_1,COVER_2,COVER_3,COVER_4,COVER_6,2_MAN}: share in {COVER_1,COVER_3}; share in {COVER_2,COVER_4,COVER_6,2_MAN}; share == COVER_0.
* blitz (defence): among dropbacks with non-null number_of_pass_rushers, share with >=5.
* pressure (defence): among dropbacks with non-null was_pressure, share True.
* def_sack (defence): among all dropbacks, share with sack==1.
* box8, box6, box_mean (defence): among designed rushes with non-null defenders_in_box: share >=8; share <=6; mean.
* stuff (defence): among designed rushes with non-null yards_gained: share with yards_gained <= 0.
* gl_n (offense): COUNT of scrimmage plays with yardline_100 <= 5 (0 if none but the game has plays; NaN if no plays for the game at all).
* gl_run (offense): among those plays, share with rush_attempt==1.
* gl_heavy (offense): among those plays with non-null RB and TE, share with RB>=2 or TE>=2.
Feature columns: p11_pre p12_pre p13_pre p21_pre p22_pre gun_pre empty_pre man_pre single_high_pre two_high_pre cover0_pre blitz_pre pressure_pre def_sack_pre box8_pre box6_pre box_mean_pre stuff_pre gl_n_pre gl_run_pre gl_heavy_pre (20 columns).
## Output
Write `/tmp/claude-0/out/blind_part.csv` (game_id, team, the 20 columns, every (game_id, team) of the universe) and `/tmp/claude-0/out/blind_part_notes.json` {"ambiguities":[...]}. Report only a short list of ambiguities you resolved; you have nothing to compare to.

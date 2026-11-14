# CBB multi-season game-level data: what exists, and the acquisition spec

RESEARCH_ONLY. Written 2026-11-14 for `alpha-cbb-mean-0.1`. Nothing in this document was downloaded, probed or
requested; it is a search record plus a ready-to-run specification. No workflow is activated by it.

## 1. What was searched, and what was found

Searched: every branch of `chmoses98/cbb-edge-finder` (`git ls-remote --heads`, 62 heads), the working tree and full
history of `main` (blobs over 2 MB), `data/`, `manifests/`, `models/`, `research/`, and the other owner clones
(`nba-`, `NHL-`, `cfb-`, `nfl-edge-finder`) for CBB files.

| Where | What it holds | Game-level, earlier seasons? |
|---|---|---|
| `projections-archive`, `period-scores-archive`, `schedule-archive`, `prospective-scores`, `espn-lines-archive`, `kalshi-*-archive`, `app-data`, `market-research`, `availability-archive`, `roster-archive` | 2026-27 prospective captures only (from 2026-10-05 / 2026-11-01) | No |
| `main:models/pure/checkpoints/*/boundary_{2025,2026}` | end-of-season team ratings 2006-2026 (`finals.parquet`, 7,356 team-seasons), `engine_end.npz` (373 teams, end state), player tables, `preseason.parquet` | No (team-season and player-season level) |
| `main:research/wave12/wave12_game_table.csv` | 359 games, 2026-11-01..09: finals, **box-score possessions**, ESPN line, pure-0.5.0 projection | Game-level, **this season only** (used by `alpha-cbb-mean-0.1` for the tempo/efficiency split) |
| `main:research/wave{2..6}/`, `research/baseline/` | per-season and per-slice **aggregates** of the owner's historical backtests: `wave5/full_table.csv` (seasons 2015-2026, 5,3xx-5,7xx games each), `wave5/market_scorecard.csv`, `wave{3,4,5}/convergence.csv` (RMSE gap to the market by games seen) | No rows, aggregates only |
| `main:manifests/bronze/sportsdataverse_releases.jsonl` (198 files) and `github_raw.jsonl` (15) | **Manifest only** (URL, sha256, bytes, retrieved 2026-10-04..11-02) of the owner's local bronze lake: `mbb_schedule_{2003..2027}.parquet` (40 entries), `team_box_{2003..2026}.parquet` (24), `player_box` 2006-2026, `pbp` 2010-2026, NCAA possessions / lineups 2010-2026, ESPN lines 2018-2023 and 2026 | The lake itself is **not committed**; only the owner's machine / Actions cache has it |
| other owner repositories | no CBB data (name matches are CFB tickers) | No |

Conclusion: **no multi-season game-level table is committed anywhere the research system can read.** The owner's
historical evidence is nevertheless useful as aggregates: in the owner's validation seasons the pure model's margin RMSE
gap to the market is +0.50..+0.58 points in a team's first game (n = 1,051), +0.19..+0.21 in games 1-4 (n = 3,656) and
about +0.05..+0.07 after ten games (n = 16,062) (`research/wave5/market.json`). The early-season weakness seen in
2026-27 is therefore a recurring property of the preseason prior, not a one-season accident.

## 2. Rights position (binding, unchanged)

* SportsDataverse / hoopR-derived releases: **new collection frozen by the owner.** Do not download.
* ESPN endpoints: rights unresolved. No bulk scrape.
* CollegeBasketballData (CBBD) direct API: the one rights-cleared path. It needs the owner's key and is behind the
  cost gate (`ALLOW_CBBD=false`, `CBBD_MAX_REQUESTS=0` in `cbb_edge/data/cost_policy.py` and
  `.github/workflows/source-probe.yml`). A manual `workflow_dispatch` probe with the owner's key is the only way in.

## 3. Path A (fastest, no new collection): owner-side export from the lake already held

The owner's bronze lake was retrieved before the freeze and is hashed in the committed manifest. Reading a copy
already held is not new collection, but **whether a derived table may be committed is the owner's rights decision**;
nothing below runs without it.

* Command (owner's machine, existing code): `python -m cbb_edge.data.silver.build --seasons 2006-2027`, then export
  the canonical `games` and `team_games` silver tables.
* Deliver to a new orphan branch `history-games` of `cbb-edge-finder` (same pattern as the archive branches), one
  parquet per season: `games/games_<season>.parquet`, plus `manifest.json` with sha256, row counts and the bronze
  sha256 each file was built from.
* Seasons 2015-2026 (12 seasons; matches the owner's own validation tables). Expected rows: 5,300-5,760 D-I games per
  season (3,868 in 2021), about 65,000 games in total; `team_games` is twice that.
* Fields, `games`: `game_id` (ESPN id), `season`, `start_time_utc`, `available_at` (silver rule: start + 3 h),
  `home_team_id`, `away_team_id` (canonical `T####`), `neutral_site`, `conference_game`, `home_conference`,
  `away_conference` (as of that season), `home_score`, `away_score`, `overtime_periods`, `season_type`
  (regular / conference tournament / postseason).
* Fields, `team_games` (per team per game): `possessions`, `fgm`, `fga`, `fg3m`, `fg3a`, `ftm`, `fta`, `orb`, `drb`,
  `tov` (enough for possessions, points per possession and the four factors).
* Optional third table `lines_<season>.parquet` from the held ESPN lines (2018-2023, 2026: 3,941-5,714 games with a
  line per season): `game_id`, `spread_home`, `over_under`, `provider`, `captured_at` if known, else `closing=True`.

## 4. Path B (rights-cleared): CollegeBasketballData direct API

Host `api.collegebasketballdata.com`, header `Authorization: Bearer <owner key>`. Run only from the owner's manual
probe workflow after setting `ALLOW_CBBD=true` and an explicit `CBBD_MAX_REQUESTS`. **Step 0 is a 3-request probe**
(one `/games` month, one `/games/teams` month, one `/lines` month for season 2025) to confirm the field names, the
per-response row cap and the quota cost before the full pull; the numbers below assume a cap of about 3,000 rows per
response and must be corrected from the probe.

| Endpoint | Parameters | Pull | Requests (est.) | Rows (est.) | Fields to keep |
|---|---|---|---|---|---|
| `GET /games` | `season=<Y>`, `startDateRange`, `endDateRange` (monthly windows Nov-Apr), `status=final` | seasons 2015-2026 | 12 x 6 = 72 | ~65,000 games | `id`, `sourceId`, `season`, `seasonType`, `startDate`, `neutralSite`, `conferenceGame`, `homeTeamId`, `homeTeam`, `homeConference`, `homePoints`, `awayTeamId`, `awayTeam`, `awayConference`, `awayPoints`, `homePeriodPoints`, `awayPeriodPoints`, `gameType`, `venueId` |
| `GET /games/teams` | same windows | seasons 2015-2026 | 12 x 12 = 144 (two rows per game, half-month windows) | ~130,000 team-games | `gameId`, `teamId`, `opponentId`, `isHome`, `pace`, `teamStats.possessions`, `points`, field goals / threes / free throws made-attempted, rebounds off/def, turnovers, `fourFactors` |
| `GET /lines` | `season=<Y>`, monthly windows | seasons 2015-2026 | 72 | one row per game-provider | `gameId`, `provider`, `spread`, `overUnder`, `homeMoneyline`, `awayMoneyline`, `spreadOpen`, `overUnderOpen` |
| `GET /teams` and `GET /conferences/history` | `season=<Y>` | 12 + 1 | 13 | ~4,400 team-seasons | team id, `sourceId` (ESPN id, for the crosswalk to `T####`), conference by season |
| `GET /ratings/srs` (optional) | `season=<Y>` | 12 | 12 | ~4,300 | end-of-season rating: **label only, never a feature** |

Total about 300 requests (inside a 1,000-call monthly tier in one run). Store raw responses as immutable bronze
(`bronze/cbbd/<endpoint>/<season>/<window>.json.gz` with sha256 and `retrieved_at`) on a private branch; commit only
the manifest to `main`. Join key to the owner's identities: CBBD `sourceId` = ESPN game / team id =
`teams.csv:espn_team_id`.

## 5. Point-in-time rule (identical for both paths)

* A game's result and box score become available at `available_at = start_time_utc + 3 h`. A forecast for a game tipping
  at `t` may use only rows with `available_at < t`; season-level tables (conference membership, team list) use the
  value in force for that season; end-of-season ratings and closing lines are **labels / benchmarks only**.
* The prior for season `Y` is built from seasons `< Y` only (the owner's `boundary_<Y-1>` checkpoints already obey
  this). Closing lines may be used as a benchmark for the game they belong to, never as a feature.
* Walk-forward by slate date within a season, and season-forward across seasons (fit on seasons `< Y`, test on `Y`),
  with the chronological two-cohort rule of the evaluation contract applied to seasons (for example 2015-2020 /
  2021-2026).

## 6. Which studies this unlocks (in priority order)

1. **Conference re-centring of the preseason prior** (the finding of `alpha-cbb-mean-0.1`): do cross-conference
   November games in 2015-2026 show the same "between-tier gap too small, within-tier spread too wide" pattern, and
   does a prior that regresses each team toward its **conference** mean rather than the Division I mean beat the
   frozen prior season-forward? Needs `games` only (about 20,000 non-conference games before 1 January).
2. **Prior-versus-current-season blend by games played** (the study left undone by both earlier CBB slices): the
   optimal weight on last season as a function of games seen, per component (tempo, offence, defence). Needs `games`
   and `team_games`.
3. **Early-season scoring-level drift**: year-over-year change in November points per possession and tempo versus the
   prior season's late-season level (the untested "better-centred prior mean" variant the owner's diagnostics name).
   Needs `team_games`.
4. **Market benchmark by games seen** on an independent line source. Needs `lines`.

Until one of the two paths is cleared, these remain blocked; `alpha-cbb-mean-0.1` cannot be validated on other seasons.

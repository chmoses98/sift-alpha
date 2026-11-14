# Access constraints, what was physically read, and the smallest read-only changes (RESEARCH_ONLY)

Phase 7 (2026-11-10). Nothing here changes permissions, secrets, environments or schedules; every item below is a *request for the owner to decide*. Evidence: `research/input_research/data_foundation/source_samples/rights_and_access_20261110b.json` (what was read, licences, hosts) and `access_unlock_analysis.json` (unlock counts, computed from the committed matrix).

## 1. What was actually accessed and reused (not what documentation claims)

| Repository (public, read-only via the session git proxy) | Physically read | Rows used by a verified builder | Inputs built and verified |
|---|---|---|---|
| `nba-edge-finder` | `data/history/espn/{team_games,player_games,shot_events}_*.parquet` (committed to git, not a gitignored cache): 7,570 team-games, 81,170 player-games, 927,349 shot events, seasons 2023-24..2026-27 | all of it | 14 (7 team-game, 7 player-game) |
| `NHL-edge-finder` | `data/history/nhl/games_2008..2025` (23,344 games), `data/history/moneypuck/team_games_2008..2025` (185,776 rows) | all of it | 6 |
| `Tennis-Edge-Finder` branch `tennis-data` | Sackmann ATP/WTA match files 2000-2026 of snapshot 20261109T145505Z (79,019 + 72,434 matches) | all of it | 14 |
| `edge-finder-api` (3.4 GB) | layout and `data/slates` / `data/pipeline` structure inspected | none (see section 5) | 0 |
| `soccer-edge-finder` | `data/research/xg_history_v1.csv.gz` (12,676 matches, a 2016-2023 archived third-party SPI file) and docs | none (on hold, see rights file) | 0 |
| `cfb-edge-finder`, `cbb-edge-finder` | **not read**: attaching them was denied by the session's permission classifier; no workaround was attempted | none | 0 |

Data NOT reusable as-is: anything gitignored (`.cache/`, `data/raw/`, `data/local/`, `data/archive/`) is absent from a clone, so no claim in those repos' docs about local caches or millions of CBB rows could be checked here. CBB/CFB counts quoted in earlier notes remain **unverified documentation claims**.

## 2. Priority-4 requests, smallest first

### 2.1 Read access to the CFB and CBB archive repos (largest unknown, zero new network host)
* **What**: allow the `add_repo` action (access `read`) for exactly `chmoses98/cfb-edge-finder` and `chmoses98/cbb-edge-finder` (both are public, so no GitHub permission is missing; the denial came from this session's permission rule). Alternatively the owner attaches them to the session. Read-only is sufficient; no push, no secrets, no API.
* **Why**: the owner's own archives and workflows may already hold CFBD/CBBD pulls and opponent-adjusted packets, which avoids both a network exception and any key. Whether they do cannot be known until the manifests are read.
* **Expected gain** (upper bound, not a promise): the matrix lists dataset `cfb.pbp_cfbd` in 73 open CFB inputs and `cbb.box_player` in 94 open CBB inputs (many overlap with other datasets). Only what the archives physically contain would be built; each input still needs replay + blind exact match.

### 2.2 CFBD API (only if the archives do not hold the data)
* **Host**: `api.collegefootballdata.com` (probe: `POLICY_DENIED (HTTP 0)` from the runner). CBBD: `api.collegebasketballdata.com`, same status.
* **Smallest change**: add those exact hosts to a *personal* environment's allowed hosts (an environment proposal needs the owner's approval prompt) and supply the key through the credential form, never in chat or a repo. The key is reported to exist as a secret in `cfb-edge-finder`; this session cannot read secrets and did not try.
* **Expected gain**: dataset `cfb.pbp_cfbd` alone fully unlocks **56** open CFB inputs (73 list it; the rest also need datasets not yet reachable). Usage terms: CFBD free tier with key, monthly quota; read the current terms before bulk collection.

### 2.3 Historical weather forecasts (cross-sport, point-in-time)
* **Hosts**: `historical-forecast-api.open-meteo.com` (past model runs, documented from ~2022) and, if needed for run-vintage detail, `previous-runs-api.open-meteo.com`; the archive host `api.open-meteo.com` is for *observed* weather and must never replace a forecast (owner policy). Probe: `POLICY_DENIED (HTTP 0)`.
* **Smallest change**: add exactly those hostnames to the allowed hosts of a personal environment. No key. Open-Meteo's terms (free for non-commercial use with attribution) must be read from the provider before collection and recorded; not assumed.
* **Expected gain**: dataset `env.weather_forecast_pit` is listed by 53 open inputs across the sports; only **5** are unlocked by it alone (the others also need venue geometry / schedule datasets). Forecast history reaches back only to ~2022, so football/baseball seasons before that stay unavailable.

### 2.4 Other high-value free sources that are permitted but blocked (counts computed from the matrix)
| Dataset | Host (probe result) | Open inputs listing it | Unlocked by it alone |
|---|---|---|---|
| `nhl.shifts_lines` | `api.nhle.com` shiftcharts (`POLICY_DENIED`), dailyfaceoff | 18 | 5 |
| `mlb.statcast_bulk` | `baseballsavant.mlb.com` CSV (`POLICY_DENIED`) | 10 | 5 |
| `mlb.leaderboards_external` | fangraphs / baseball-reference (`POLICY_DENIED`; terms restrict automated bulk use) | 7 | 0 |
| `cbb.ratings_barttorvik` | `barttorvik.com` (`POLICY_DENIED`; scraping terms medium risk) | 8 | 0 |
| `soc.ratings_elo` | `clubelo.com` (`UNRESOLVED`) | 3 | 1 |

These are listed for completeness; MLB/CBB rating sites are not recommended (terms), and none is requested without reading its current terms.

### 2.5 No new permission needed (already readable)
* Tennis `tennis-data` branch also holds ATP/WTA rankings files and the MatchChartingProject (same CC BY-NC-SA licence): candidates for `ten.rankings_history` (2 open inputs) and `ten.point_charting` (1). Not built this phase.
* NBA/NHL archive branches of the owner's repos were listed (`data-archive`, `delta-archive`, `claude/*`); only default branches were read.

## 3. On hold, unchanged
SportsDataverse / hoopR releases and any other source whose upstream rights are unresolved are **not** used and **not** copied through another repository. ESPN site-API terms (NBA/CBB/CFB box and shot archives), the NHL API and MoneyPuck bulk terms are unresolved: the 20 NBA/NHL inputs built this phase are **internal-research only** and not cleared for redistribution or commercial use. Only the 14 tennis inputs rest on a licence text that was read from the data owner's own file (CC BY-NC-SA 4.0: attribution, non-commercial, share-alike).

## 4. Why most open inputs did not move
The 56 `DATA_IN_HAND` inputs were the only ones whose data was already physically readable; 33 are now built and verified. The other 23 confirmed ones (NBA 7, NHL 4, tennis 12) were not built this phase: they are mostly joint/simulation definitions (copulas, correlation matrices, bracket or series simulations). Spot-checking the remaining `REQUIRES_COLLECTION` NBA/NHL/tennis inputs whose datasets are all readable shows the same: simulation or fitted-model outputs, not raw-data transformations, so building them is modelling, which is paused.

## 5. MLB: a PIT-native capture exists but is not backfill
`edge-finder-api/data/slates/<date>/scheduled_refresh_*.json` (96 dates, 2026-06-15..2026-10-28) records timestamped pre-game state (probable pitchers, `lineupStatus`/`lineupCheckedAt`, bullpen and Savant pitcher aggregates, park factor) next to market prices and model outputs. It is one season of prospective-style capture with market-derived fields mixed in; no input was built from it this phase. It is the natural source for lineup-posting-time and pregame-bullpen vintages once the mixed fields are separated.

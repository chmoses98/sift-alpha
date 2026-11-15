# Phase 8 (2026-11-15): capture repair, integration, and training datasets for all five sports (RESEARCH_ONLY)

Agent verification only, **not human verified**. No model retrained or promoted, no schedule created or activated, no purchase, credential or rights-tier change. No raw or dataset row is committed: manifests (counts, hashes, missingness, diagnostics) and evidence only.
Dashboard: Data foundation → **Phase 8** tab, rendered from `research/data_foundation_ops/phase8_acquisition.json` (`python -m alpha_engine.foundation.phase8`, which joins the training-set manifests and `phase8_evidence.json`). Stacked on #78 → #77.

## 1. NFL weather capture (nfl-edge-finder #278)
* **Root cause.** `context-capture.yml` published through a **non-sparse** worktree of `market-data` (~52 GB). From 2026-10-28 the hosted runner ran out of disk mid-checkout. Runs 275–284 captured data, but nothing reached the branch; the last context commit is 2026-10-28 13:46Z. The capture step stayed green, so the workflow looked healthy while weather was lost. The Kalshi conductor hit the same failure on 11-01 and was fixed then; context capture was missed.
* **Secondary cause.** About nine publishers share the `market-data-write` concurrency group, and GitHub keeps only one *pending* run per group. A newer pending run from any of them cancelled a waiting capture (runs 276, 277, 283).
* **Fix.**
  * `state.json` is read through the contents API.
  * The publish step uploads only the files this run wrote, using `--sparse --only-from`.
  * `verify_context_archive.py` reads the run's manifest and weather file back from the remote branch, and `Capture health` fails red if publish or verification did not succeed.
  * Forecast accounting (`has_forecast`, `weather_health`): a weather row that holds only provider errors no longer counts as collected weather.
  * The workflow has its own concurrency group. Its schedule is unchanged.
* **Archive acquired into Alpha.**
  * 3,907 forecast vintages from 222 capture runs.
  * 117 completed 2026 games (weeks 1–8) have a kickoff-hour forecast retrieved before kickoff (`features/nfl_weather_fcst.py`).
  * Validation against observed game weather on open-air games: temperature r 0.95 (MAE 2.3 °F), wind r 0.72 (MAE 2.2 mph).
* **Lost.** 16 completed games (2026-11-01..11-15) have no pre-game forecast, and point-in-time forecasts cannot be backfilled. Five international games have no venue coordinates by design.

## 2. PR #77 / #78 CI (this PR, stacked on #78)
* **e2e.** The summary assertion now derives the missing PRIMARY count from `map.json` using the map's own predicate, and requires `reconciliation.json` to agree. Nothing is hard-coded.
* **research-desk.**
  * `hitter_archive_gate` authenticates `api.github.com` reads with the job token.
  * It retries rate-limit responses.
  * On a persistent quota refusal it exits **75 `RATE_LIMITED_NOT_VERIFIED`** and writes no evidence. It still fails closed, and the result is distinguishable from a missing or altered archive.

## 3. Training datasets (manifests in `research/data_foundation_ops/training_sets/`)
| Sport | Games | Seasons | Admission | Inputs / columns | Checks | Walk-forward (market-free ridge, diagnostic) |
|---|---|---|---|---|---|---|
| NFL | 7,548 (7,414 with outcome) | 1999–2026 | training-ready only | 12 / 70 | deterministic, outcomes reconciled | margin MAE 9.97 vs 10.71 constant, 65.0% winners |
| NFL upcoming | 13 next games (6 pre-kickoff at build; 12 with complete inputs) | 2026 wk 10–11 | same 70 columns | — | **exact truncation equivalence on 6 dates / 51 games** | — |
| NHL | 21,608 | 2008–2025 | training-ready only (team-level) | 6 / 50 | deterministic | goal-diff MAE 2.14 vs 2.24, 58.1% |
| NBA | 3,785 | 2023-24 .. 2026-11-01 | training-ready only (team / team-constant) | 3 / 10 | deterministic | margin MAE 12.62 vs 13.25, 60.8% |
| CBB | 121,841 (817 in 2026-27) | 2005-06 .. 2026-11-14 | **BUILT_NOT_CERTIFIED** (`features/cbb_box.py`) | 1 builder / 32 | deterministic, **truncation exact (3 dates)** | margin MAE 11.17 vs 14.49, 74.3% |
| CFB | 10,373 | 2014–2025 | **BUILT_NOT_CERTIFIED** (`features/cfb_cfbd.py`) | 2 groups / 53 | deterministic, **truncation exact (3 dates)** | margin MAE 13.08 vs 17.28, 73.9% |

* **Upcoming NFL games** (`features/nfl_upcoming.py`, `training_sets nfl-upcoming`).
  * Stub team-game rows are appended after every completed game, and the certified builders' own formulas run over them. The legacy builder was refactored into `_team_stats` + `_pre_features`, and its output is bit-identical before and after.
  * Rows already past kickoff at build time are flagged. Rows whose team has a scored game without play-by-play yet are flagged `inputs_complete = false`.
* **CBB builder.**
  * Opponent-adjusted offence and defence points per 100 possessions, solved per date by warm-started weighted ALS with a home-court term.
  * Tempo, Four Factors for and against, and conference strength.
* **CFB builder.**
  * Opponent-adjusted EPA/play from the owner's CFBD cache (no garbage time), plus success rate, explosiveness, pass/rush PPA, line yards and stuff rate.
  * Points per drive for and against.
  * Season priors: talent, returning production, recruiting, and pre-season transfer-portal in/out and net stars.
  * Excluded: betting lines, end-of-season ratings and season totals.

## 4. Data collected this phase (held outside the repository)
* **NFL.**
  * nflverse play-by-play refreshed: 1,303,630 plays, 1999–2026.
  * Raw nflverse files, not yet built: snap counts 337,397 rows (2012–2026), injuries 93,920 (2009–2026), participation 478,989 (2016–2025), depth charts 2.2M, weekly rosters 931k, FTN charting 208,516, NGS and player stats.
  * The owner's PIT availability store (57 MB) and the weather archive above.
* **CFB.** CFBD cache 2014–2025: 10,374 games, 24,712 advanced team-games, 258,557 drives, 14,422 portal entries, plus returning production, talent and recruiting.
* **CBB.**
  * 109 files re-materialised from the owner's cbb-edge-finder bronze manifest. 49 are byte-identical; 60 were republished upstream, and their new hashes are recorded.
  * Also the 2026-27 team box (1,634 team-games through 11-14).
* **NHL.**
  * 2026-27: 372 scheduled / 325 final games from `api-web.nhle.com`. The archive collector's stats REST host is denied here.
  * The player / goalie / team-state backfill was still running when this was written.
* **NBA.** One transactions snapshot (439 rows), local only. The capture is prepared in nba-edge-finder #106 and has no schedule.

## 5. Status discipline
Training-ready inputs stay at **41** and missing PRIMARY slots at **886**. Nothing new was certified, because certification needs a blind re-implementation. The CBB and CFB datasets and the weather feature are **BUILT**, not training-ready, and nothing is model-active.

## 6. Owner decisions
1. Merge nfl-edge-finder #278. Every week without it loses forecasts permanently.
2. CFBD probe: copy `research/input_research/data_collection/college_direct_authorization.PENDING_OWNER.json` to the active name on `main`, fill `shared_quota_remaining` and `quota_declared_on`, and dispatch.
3. Approve or decline the NBA transactions schedule (nba-edge-finder #106).
4. Rights: `sportsdataverse_espn_mbb_cfb` stays UNRESOLVED_INTERNAL_ONLY. It was used for internal research under the existing-archive directive. A decision is needed before any commercial use.
5. Merge order: #77 → #78 → this PR. Do not deploy the dashboard without approval.

## 7. Regeneration
    python -m alpha_engine.foundation.training_sets nfl --raw RAW_NFL --out OUT --write-manifest
    python -m alpha_engine.foundation.training_sets nfl-upcoming --raw RAW_NFL --out OUT --write-manifest
    python -m alpha_engine.foundation.training_sets_multi nhl --nhl-history NHL-edge-finder/data/history --out OUT --write-manifest
    python -m alpha_engine.foundation.training_sets_multi nba --raw HUB (HUB/nba -> nba-edge-finder) --out OUT --write-manifest
    python -m alpha_engine.foundation.training_sets_multi cbb --cbb CBB_BRONZE --out OUT --write-manifest
    python -m alpha_engine.foundation.training_sets_multi cfb --cfb cfb-edge-finder@research-data:data/research_cache/v2 --out OUT --write-manifest
    python -m alpha_engine.foundation.phase8

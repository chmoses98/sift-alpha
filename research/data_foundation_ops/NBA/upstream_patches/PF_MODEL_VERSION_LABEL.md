# Proposed upstream fix: make the `pf` model version identify the forecast code (PROPOSAL ONLY, NOT APPLIED)

Target repository: `chmoses98/nba-edge-finder` (read-only for this research). Nothing here has been applied, pushed or opened as a PR.
Evidence: `research/data_foundation_ops/NBA/pf_version_lineage.json` (built by `alpha_engine.foundation.nba_rate.version_lineage`).

## What is wrong

`research/projection_foundation/nba/project.py` writes `model_version = f"pf-{PF_VERSION}+{git rev-parse --short HEAD}"`.

* The label part (`pf-1.3.0`) is the `pf_core` library version. It changed once in the window (1.2.1 to 1.3.0, a scoring-only change:
  `pf_core/prospective.py`, `archive_guard.py`), and did **not** change on any of the commits that altered forecast code.
* The sha part is the repository HEAD, so it changes on every merge, including ticker, watchdog, report and documentation commits.

Result on `projection-data@dd561a7` (2026-10-19 to 2026-11-14): 28 distinct `model_version` strings under 2 labels. All 28 shas resolve to
commits on `main`, and every run was generated after its commit. Comparing a digest of the forecast-affecting source files between
consecutive run revisions gives **7 forecast-source changes, 8 constant-source segments**:

| first run revision | forecast files changed | commit |
|---|---|---|
| `1a2375f` | `nba/live/run.py` | archive preparation of the run (orchestration) |
| `b415341` | `nba/live/availability.py`, `run.py` | availability verification: run ignored its own capture |
| `90a5af1` | `nba/project.py`, `run.py` | withhold likely-out players (D3) |
| `77d3d6c` | `nba/features.py`, `nba/project.py` | ridge pace/efficiency fitted on observed games only (`67aa73e`) |
| `f56cbe4` | `nba/live/participation.py`, `nba/project.py` | confirmed-OUT projections fix (#84) |
| `863ee82` | `nba/live/participation.py`, `starter_onoff.py`, `nba/project.py` | point-in-time starter capture (#87) |
| `c6120ad` | `nba/live/run.py` | all-market postmortem (#95) |

The other 20 revisions ran byte-identical forecast source. So the label is too coarse (one name for 6 behaviour changes) and the sha is
too fine (21 names for unchanged code). Neither can be used as a model key in an evaluation.

## Proposed change

1. Add a **model source digest** computed at run time from file bytes, not from git:

   ```python
   # nba/project.py
   MODEL_SOURCE = ["pf_core/models.py", "pf_core/dists.py", "pf_core/pit.py", "pf_core/gate.py", "pf_core/availability.py",
                   "nba/common.py", "nba/data.py", "nba/distributions.py", "nba/features.py", "nba/injury.py", "nba/minutes.py",
                   "nba/pipeline.py", "nba/project.py", "nba/stats.py", "nba/team.py", "nba/live/availability.py",
                   "nba/live/participation.py", "nba/live/participation_calibration.json", "nba/live/forecasts.py",
                   "nba/live/reconcile.py", "nba/live/sources.py", "nba/live/starter_onoff.py", "nba/live/run.py",
                   "nba/paper/paper_config.json", "results/frozen_params.json"]

   def model_source_digest() -> str:
       h = hashlib.sha256()
       for rel in MODEL_SOURCE:
           h.update(rel.encode()); h.update((data.PF_DIR / rel).read_bytes())
       return h.hexdigest()[:12]
   ```

2. Write three separate fields on every forecast and game-forecast row instead of one overloaded string:
   `model_version = f"pf-nba-{NBA_MODEL_VERSION}"` (a hand-bumped semantic version of the NBA model, separate from `pf_core.VERSION`),
   `model_source_digest`, and `code_commit` (full sha, plus `code_dirty: true` when the worktree has uncommitted changes).
   Keep the old `pf-x.y.z+sha` string in a `legacy_model_version` field for one release so existing readers keep working.
3. Add `training_data_asof` (latest box-score date used by the refit). The LightGBM rungs are refitted on every run, so identical source
   is still not an identical fitted model; this field makes that visible.
4. CI guard: a test recomputes the digest and compares it with a committed `nba/MODEL_MANIFEST.json` (`{"version": ..., "digest": ...}`).
   A change to any `MODEL_SOURCE` file without a version bump and manifest update fails the test. `pf_core/MANIFEST.json` already uses
   this pattern for the library.
5. Backfill is not needed and the archive must not be rewritten: `pf_version_lineage.json` already maps every existing run to its
   revision and source digest.

## Related observations for the owner (not part of the labelling fix)

* The team model's expected points are `exp_pace x exp_ortg / 100` with pace per 48 minutes, i.e. regulation only, while markets settle
  on the final score including overtime. On 2026-27 this term is -0.67 points per team-game; the later rest-adjustment stage adds +1.35,
  so the net stage offset is positive.
* The frozen forecasts **over**-forecast 2026-27 scoring: team points +2.40, game total +4.80 (SE 1.37, 176 games). The alpha-nba-avail-0.2
  write-up says "under-forecast"; its bias column is actual minus forecast.
* Summed `P(play) x minutes` over a frozen roster averages 248.8 team minutes, not 240, and summed player points exceed the team model by 2.0.
* `market_snapshots/nba` on projection-data has no T-60 rows for games after 2026-11-06, while the capture-worker archive on `data-archive`
  holds usable boards for 48 of those 56 games.

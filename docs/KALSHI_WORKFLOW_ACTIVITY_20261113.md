# Kalshi-touching workflows: current activity (RESEARCH_ONLY, observation only)

Observed 2026-11-13 at about 20:40 UTC through the GitHub Actions API (read-only), for `chmoses98/sift-alpha`. **No workflow, schedule, gate, secret or branch was changed.**
The risk analysis is in `docs/KALSHI_RIGHTS_IMPACT_AUDIT.md`; this file records only what is running.

| Workflow (on `main`) | Trigger | Runs | Recent activity | State |
|---|---|---|---|---|
| `shadow-ledger.yml` ("Shadow-order ledger, research-only, hypothetical, no orders") | hourly cron `41 * * * *`, plus self-dispatch of a successor run | 1,082 total | Run #1082 was queued at 20:06 UTC (self-dispatched by `github-actions[bot]`). Two sampled pages of completed runs (the latest 100, and the 100 from 11-12 08:29–13:33 UTC) are **all failures (197) or cancellations (3); no success**. Page 2, in between, was not read. Failing step: "Loop sync + build + validate + publish (every 10 minutes)", about 20 s in. "Dispatch the successor link" succeeds first, so the chain keeps restarting. | **ACTIVE and failing.** It consumes runner minutes about every 15–20 min. Whether any Kalshi data is still fetched or published before the failure is not visible without logs; the logs were not read. |
| `nfl-prospective-ops.yml` | dated NFL-window crons + manual | 20 total | Successful runs on 11-10, 11-11 (×2), 11-12 (×4) and 11-13 (×2: 08:46 manual, 16:43 schedule). | **Running.** By its own design, scheduled capture and refresh do nothing unless `ci/GHA_CAPTURE_ENABLED` / `ci/GHA_REFRESH_ENABLED` exist on `prospective-data`. That gate was not inspected here, so whether Kalshi books were actually captured in these runs is **unverified**. |
| `pages.yml` (publishes the public dashboard) | cron `23 */6 * * *` + manual | 35 total | Successes on 11-12 07:24, 11-12 20:06 and 11-13 06:56; one failure on 11-11 19:43. Run #35 was queued at 19:52 UTC today. | **Active**. It republishes dashboard content, including Kalshi-derived aggregates. |
| `kalshi-series-sweep.yml` | manual only | 6 total | Last run 2026-11-02 (success). | Dormant (manual). |

## Observations relevant to the Kalshi terms (no action taken)
- **Shadow ledger:** the shadow-ledger chain is the only Kalshi-related job running in a continuous loop. It currently fails each cycle, but the successor dispatch means it never stops on its own. Pausing it would need a workflow change, which this authorization excludes.
- **Prospective capture:** the gate state of `nfl-prospective-ops.yml` decides whether Kalshi data is actually being captured. Checking the `ci/GHA_*_ENABLED` markers on `prospective-data` is a cheap read-only next step.
- **Public dashboard:** the Pages deployment keeps republishing every 6 hours. Whether it carries Kalshi data is covered in the impact audit (item: published benchmarking/aggregates).

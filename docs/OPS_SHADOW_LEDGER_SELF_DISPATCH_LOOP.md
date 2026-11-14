# Operational issue: `shadow-ledger.yml` self-dispatch loop keeps failing

**Opened:** 2026-11-13. **Severity:** operational. It wastes runner minutes, the ledger is not published, and it runs unattended.

**Status:** open. It needs owner attention. **Nothing was modified.** No workflow, schedule, branch or run was changed or cancelled, and fixing it needs owner approval.

## Observed (read-only, GitHub Actions API, about 21:45 UTC 2026-11-13)
- **Run count:** 1,084 runs in total. Run #1084 was `queued`, self-dispatched by `github-actions[bot]` at 21:43 UTC.
- **Recent results:** the 15 most recent completed runs (#1070–#1083, 17:11–21:43 UTC) were 14 `failure` and 1 `cancelled` (#1074, a scheduled run).
- **Earlier sample:** `docs/KALSHI_WORKFLOW_ACTIVITY_20261113.md` sampled 200 earlier completed runs: 197 failures and 3 cancellations, with **no success**.
- **Commit:** all runs are on `main` @ `f121d5a`.

## Root cause (from the failed-job log of run #1083, job `ledger`)
- **Data stages succeed:**
  - sync: 353 new runs, 14,077 quotes, 132,274 trades;
  - ledger build: 486 placed, 72 settled;
  - report;
  - `validate_shadow_output.py`: `valid: true`, `error_count: 0`, capture age 38 minutes.
- **Publish fails:** the force-push of the `shadow-data` branch is rejected:
  ```
  remote: error: File extract/trades.jsonl is 141.50 MB; this exceeds GitHub's file size limit of 100.00 MB
  ! [remote rejected] shadow-data -> shadow-data (pre-receive hook declined)
  ##[error]publish not confirmed (pass 1)
  ```
- **Why the job stops:** the loop exits 1 on the first unconfirmed publish (correct fail-closed behaviour).
- **Why the chain never stops:**
  - The step "Dispatch the successor link" runs **before** the work and has `continue-on-error: true`.
  - So every failing run has already started the next one. The hourly cron `41 * * * *` is a second, independent restart path.
  - `concurrency: cancel-in-progress: false` queues the successors instead of dropping them.

## Consequences
- **Ledger not published:** `shadow-data` is no longer updated, so the published shadow ledger is stale.
- **Accumulated history is lost:** each run restores the last published state, so the shadow decisions recorded since then are rebuilt and discarded on every run.
- **Runner minutes:** a new run starts about every 15–30 minutes.
- **Kalshi data:** the job fetches Kalshi-derived capture data from `nfl-edge-finder` `market-data` on every run (GET-only, no credentials). This is noted in `docs/KALSHI_RIGHTS_IMPACT_AUDIT.md`.
- **No orders:** none can be placed. There are no credentials and only GET reads.

## Options (proposals only; each needs owner approval)
1. **Stop the loop now:** disable the workflow in the Actions UI. This also stops the hourly cron and is easy to undo. Cancelling the queued run alone does nothing, because the cron restarts it.
2. **Fix the size:**
   - stop publishing the raw `extract/trades.jsonl` (keep the derived ledger, summary and health only); or
   - shard it into dated files under 100 MB; or
   - compact it (gzip, or drop trades older than the `--since-days 2` window it already uses).
   - Add a pre-push size check that fails with a clear message.
3. **Break the self-dispatch failure mode:** dispatch the successor only after a confirmed publish, or skip the dispatch when the previous run failed. This keeps the cron as the only restart path while broken.

Recommended order: 1 now, then 2 and 3 together in one reviewed PR.

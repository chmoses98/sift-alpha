# Prospective capture worker — standing orders (RESEARCH_ONLY)

Version-controlled so a worker session never depends on a long, drifting prompt.  A scheduled firing needs **one** shell command and **one** line of output.

## Capture firing
1. Run it in the BACKGROUND with the maximum timeout (the harness default of 30 min kills a 57-min window run): Bash `run_in_background=true`, `timeout=3500000`, command `bash scripts/prospective/bootstrap.sh capture`. Wait for it to exit. Do NOT re-run it after a kill: the start heartbeat already records the firing and a retry would only duplicate captures.
2. Reply with the single line it prints (`CAPTURE <status> run=… ticks=… series_failures=… publish_errors=… heartbeat=pushed|NOT_PUBLISHED …`). Nothing else.
3. If it prints nothing or fails, reply `CAPTURE failed reason=no_output`. Do not debug, edit code, or retry more than once.

## Hard limits
- Never modify files outside what the script writes; never touch `research/`, model configs, ledgers, `LEASE.json` or `RELEASE.json`.
- Never create/modify triggers, sessions, environments or credentials. No trading, no orders, no paid services.
- The worker may only add files under `captures/`, `contracts/`, `heartbeats/`, `settlements/` on `prospective-data` (enforced in code: `publish_captures` allowlist).

## Release control plane
`RELEASE.json` on `prospective-data` holds `{"code_commit": "<sha>"}`.  Only the owner/reviewer publishes it.  `bootstrap.sh` refuses a pin that is not an ancestor of `origin/feat/sift-lab` or `origin/main`, so rollback = publish the previous sha (e.g. `a4d87a7`).

## Refresh (daily, single writer)
`bash scripts/prospective/bootstrap.sh refresh` — takes the data-branch lease, ingests shards exactly once into the hash-chained ledgers, verifies pins/frozen model, publishes with commit trailers (`writer-run`, `role`, `code`).

## Scheduling
`alpha_engine/lab/schedule_plan.py` derives wake-ups from the real schedule (≈3.7 firings/day vs 24 hourly); `uncovered()` proves no decision window is left without a firing.  Changing the schedule or adding a second offset worker needs owner approval.

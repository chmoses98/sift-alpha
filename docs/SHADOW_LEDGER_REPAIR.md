# Shadow-order ledger (`shadow-ledger.yml`): incident and repair plan (RESEARCH_ONLY)

**Status: DISABLED (contained).** The owner disabled the workflow in GitHub Actions. State is
`disabled_manually` (2026-11-13 22:42 UTC). The last queued link (run #1086) was cancelled before it ran, and
no run has started since, including the next hourly-cron slot. No other workflow or schedule was touched.
**The repair below is a proposal for review, not implemented.**

## What broke
1. **Oversized file.** `extract/trades.jsonl` is append-only: every pre-kickoff KXNFLGAME trade, never
   compacted. It was 104.4 MB at the last accepted publish and 141.9 MB at the failing runs. GitHub refuses
   any file over 100 MiB (`GH001: Large files detected`), so every publish to `shadow-data` since
   **2026-11-08 13:03 UTC** has been rejected. `extract/seen_ids.json` (12.6 MB) and `extract/quotes.jsonl`
   (26.6 MB) grow the same way.
2. **Dispatch before publish.** Step 1 of every link is `gh workflow run shadow-ledger.yml` (dispatch the
   successor). It runs before sync, validation or publish, so a link that is certain to fail still spawns the
   next one. With the hourly cron as a second entry point, the failure perpetuated itself: about 1,000 failed or
   cancelled runs over 5 days, each burning runner minutes until `publish not confirmed`.

## Data preserved
* `shadow-data` @ `0a4ce92` ("shadow ledger pass 19 2026-11-08T13:03:08Z") is intact. Every later push was
  rejected by the pre-receive hook, so nothing was overwritten.
* Raw inputs are unaffected: live capture lives in `nfl-edge-finder` `market-data`, which this workflow only reads.
* **Lost:** decisions computed in failing runners between 2026-11-08 and 2026-11-13 were never published.
  They can be rebuilt from `market-data`, but only as `RETROSPECTIVE_REPLAY`, never as `PROSPECTIVE`: a
  decision counts as prospective only if it is recorded within 30 minutes of its quote. The gap must stay
  labelled as such.

## Repair (proposed; implement only after review)
1. **Bound file sizes.** Write `extract/` as date shards, gzipped
   (`extract/trades/dt=YYYY-MM-DD.jsonl.gz`, same for quotes). JSONL compresses about 8–10×, and a day of
   NFL pre-kickoff trades is a few MB. Replace the global `seen_ids.json` with per-shard de-duplication, or a
   per-ticker last-trade cursor. One-time migration: split the current `trades.jsonl` and `quotes.jsonl` from
   `0a4ce92` into shards, and verify row counts and trade-id sets match exactly.
2. **Size gate before publish.** `validate_shadow_output.py` fails closed if any file to be published exceeds
   90 MB, naming the file, so an oversized artifact is a clear validation error, never a rejected push. Add a
   unit test.
3. **Publish before dispatch.** Move the successor dispatch to after the first confirmed publish in the
   link, and skip it when the link has failed. A broken link then ends the chain; the hourly cron remains the
   only re-entry. Add a circuit breaker: the link exits early, without dispatching, if the previous 3 completed
   links all failed.
4. **Do not use Git LFS.** LFS has storage and bandwidth quotas, which is spending; sharding makes it unnecessary.
5. **Backfill the gap** with one manual run, `--since-days 6`, labelled `RETROSPECTIVE_REPLAY`. Prospective
   counts restart at re-enable.

## Re-enable checklist (owner)
1. Review and merge the repair PR (sharding + gate + ordering + tests; CI green).
2. Run once via `workflow_dispatch` with `minutes=15`. Confirm: publish confirmed, every file < 90 MB,
   `validate_shadow_output` valid, row counts match `0a4ce92` plus the new runs, exactly one successor dispatched.
3. Then re-enable the workflow in Actions, and watch the first two cron links.

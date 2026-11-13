# Prospective capture: operations log (facts, not intentions)

Updated by hand when a fact changes. Times UTC. RESEARCH_ONLY.

## Verified (2026-11-07)
* Public Kalshi market API reachable from the cloud environment; fail-closed full books captured for `KXNFLTOTAL`, `KXNFLRECYDS`, `KXNFLREC`, `KXNFLRSHYDS`, `KXNFLPASSYDS`, `KXNFLANYTD` (285 / 1,507 / 1,019 / 713 / 266 / 0 markets, all pages).
* A shard written and pushed from a *separate remote container* (worker session, run id `worker-20261107T062140Z`) reached `prospective-data` (shards 06:22:07Z, 06:23:38Z, 06:25:08Z) and is hash-verified on read.
* Scheduled-task sessions created WITHOUT attached repositories can fetch the repository but cannot push (3 shards lost with the container, correctly not reported as published).
* A dedicated worker session created WITH the repository attached and `outcome_branch=prospective-data` CAN push.

## Verified later (2026-11-07, reliability audit)
* Scheduled delivery PROVEN: worker v2 (`session_01H5Aao53XxXY3EF64tEDgxN`, trigger `trig_01NLp38ay6cBXpfcy4Z7uDpP`, `37 * * * *`) published 8 shards 13:55:33-14:30:26Z from firing `worker2-20261107T133747Z`; 0 of 13 firings missed; all shards hash-valid; 7/8 due T-24h cells eligible (mean observation age 2.1 min). A trigger `SUCCEEDED` status is only a hand-off; proof is the published shard/heartbeat.
* Defect fixed: Kalshi uses `LAR` for the Rams (nflverse `LA`); before the alias fix those contracts were silently skipped (`NO_QUOTE_ROW`).  Unmapped events are now reported and alert.
* Staged v3 worker (`session_01H5Aao3WmFdab7kpEKGaN7q`, Haiku, NO trigger, manual proof firing) published schema-2 shards + contract-registry shards with commit trailers (`writer-run`, `code`) from pinned release `1ac7101`; series coverage identical to v2 (6 series). v2 stays live as the rollback path; v3 has no recurring trigger (needs owner approval).
* `RELEASE.json` on `prospective-data` is the owner-controlled code pin (`scripts/prospective/set_release.py`); capture workers cannot write it (allowlist).
* Obsolete worker v1 (`session_01H5Aao3DLW3YZH4W23T6Hm1`) archived; its trigger and the two older source-less triggers are disabled; nothing unpublished depends on them.

## Not verified / open
* Heartbeat shard from a real firing at the END of a window run (v3 proof run in progress when this was written).
* The existing nfl-edge-finder collector stopped publishing at 2026-11-06T05:49Z (Conductor run queued for hours); it is ingested if and when it resumes (`capture_ingest`), never required.
* Windows missed before capture was running are missed for good (`decision_audit.json`).

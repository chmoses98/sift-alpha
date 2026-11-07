# Prospective capture: operations log (facts, not intentions)

Updated by hand when a fact changes. Times UTC. RESEARCH_ONLY.

## Verified (2026-11-07)
* Public Kalshi market API reachable from the cloud environment; fail-closed full books captured for `KXNFLTOTAL`, `KXNFLRECYDS`, `KXNFLREC`, `KXNFLRSHYDS`, `KXNFLPASSYDS`, `KXNFLANYTD` (285 / 1,507 / 1,019 / 713 / 266 / 0 markets, all pages).
* A shard written and pushed from a *separate remote container* (worker session, run id `worker-20261107T062140Z`) reached `prospective-data` (shards 06:22:07Z, 06:23:38Z, 06:25:08Z) and is hash-verified on read.
* Scheduled-task sessions created WITHOUT attached repositories can fetch the repository but cannot push (3 shards lost with the container, correctly not reported as published).
* A dedicated worker session created WITH the repository attached and `outcome_branch=prospective-data` CAN push.

## Not verified / open
* Delivery of the hourly scheduled trigger into the worker session (see REPORT in the PR); until a scheduled firing produces a `worker-...` shard unprompted, scheduled capture is unproven.
* The existing nfl-edge-finder collector stopped publishing at 2026-11-06T05:49Z (Conductor run queued for hours); it is ingested if and when it resumes (`capture_ingest`), never required.
* Windows missed before capture was running are missed for good (`decision_audit.json`).

# Ledger segments and verified publication (RESEARCH_ONLY)

**Why.** 2026-11-09: `nfl_totals_v1/quotes.jsonl` reached 108.6 MB locally (73.5 MB published). GitHub rejects files over 100 MiB, `publish()` exhausted its retries, and the worker still printed `REFRESH ok` because it only looked at `aborted`/`lease_busy`. No evidence was lost (capture shards are durable and ingestion is once-only) but the ledgers, report and projections stopped publishing.

## Layout (deterministic, backward compatible)
A logical ledger `quotes.jsonl` is an ordered list of segment files: `quotes.jsonl` (segment 0, the legacy file, **byte-identical**), `quotes.0001.jsonl`, `quotes.0002.jsonl`, ...
* A record goes to the last segment unless that would exceed `MAX_SEGMENT_BYTES` (50,000,000); then a new segment opens. Segment 0 is already 73.5 MB, so it is grandfathered and simply never extended.
* **One hash chain spans all segments**: the first record of segment *k* has `prev` = hash of the last record of segment *k-1*. Record format and hash definition are unchanged, so every existing chain verifies unmodified.
* Sealed segments are never rewritten, so the append-only guard (published file is a byte-prefix of its local twin) holds per segment. A segment present on the branch but absent locally, or a hole in the numbering, is a violation.
* Readers: `prospective.read_ledger` / `iter_lines` / `verify_chain` are segment-aware; `capture_ingest._read`, `capture_window.ingest_shards`, `player_prospective`, `summary.py` (dashboard counts), the evaluator and the claim gate all go through them. A non-segmented ledger is just segment 0.
* Migration helper `prospective.repartition(path, keep_bytes=<published size>)` splits an oversized local file at record boundaries (bytes, order and chain preserved, published prefix kept). The live ledgers need no migration.

## Fail-closed publication
`publish()` refuses (no push) on: lost lease, append-only violation, missing segment, any file over `MAX_PUBLISH_FILE_BYTES` (95,000,000). A rejected push returns git's own error text (`push REJECTED by the remote: ... GH001`). After a push, or when nothing changed, `verify_remote()` fetches the remote head and compares the git blob id of every expected file to the local file. `worker.refresh` prints `REFRESH ok` only if `publication_status()` says every attempted publication (totals, player, settlement) is verified; otherwise `REFRESH failed ... reasons=[...]`, exit 2, and the heartbeat records `publication_verified: false`. Alerts `REFRESH_UNPUBLISHED` and `REFRESH_STALE` (>30 h) surface this in the next report.

## Tests (`tests/test_ledger_partition.py`, 17)
rotation bounds and determinism; chain across boundaries; tampering and missing-segment detection; grandfathered oversized segment 0; migration (bytes/order/chain/published prefix, idempotent); concurrent writers (4 processes, 160 records, no fork); idempotent and deterministic shard ingestion across segment boundaries; publish verified against a bare remote; append-only and missing-segment refusals; oversize guard; GitHub-style rejecting remote (pre-receive hook); remote mismatch by blob; end-to-end recovery (rejected, repartition, republish, fetch, chain verifies); concurrent publishers; `REFRESH ok` only when verified; alerts. Full suite: 851 passed.

## Rehearsal on the real data (local bare mirror of `prospective-data`, nothing pushed to the real remote)
`worker refresh` with this code: `REFRESH ok ... published_verified=True`; mirror holds `quotes.jsonl` (73,465,344 B, byte-identical to origin) + `quotes.0001.jsonl` (35.1 MB); chains verified across segments (quotes 172,116 / observations 760 / predictions 280); every previously published line preserved as a prefix; accounting 816 = 366 + 450, unaccounted []; frozen mu+sigma digest OK; 13 eligible settled T-6h games (local rehearsal only, **not published**).

## RELEASE.json pin (owner-only; NOT applied)
Current pin `c152a84179d8...` cannot publish ledgers once `quotes.jsonl` passes the limit. Requested pin: the code commit named in the PR #59 status comment (tested head that carries this change). Rollback = `c152a84` (publishes nothing new while oversized) — a rollback is only safe with the ledger split already on the branch.
Owner command (from a clone with `origin/feat/sift-lab` fetched): `python scripts/prospective/set_release.py <sha> --note "ledger segments + verified publication"`.
After pinning: run the refresh once (canonical trigger or `bash scripts/prospective/bootstrap.sh refresh`) and require `REFRESH ok ... published_verified=True` and a `prospective refresh` commit on `prospective-data` before counting anything as published.

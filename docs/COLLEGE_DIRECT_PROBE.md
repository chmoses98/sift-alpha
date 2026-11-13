# CFBD/CBBD direct-API probe (public repository; RESEARCH_ONLY)

Code: `alpha_engine/collect/college_direct.py`. Workflow: `.github/workflows/college-direct-probe.yml`. Ledger script: `.github/scripts/college_ledger.sh`. Tests: `tests/test_college_probe.py` (run in CI by `research-tests.yml`). Nothing here has been executed against the API.

## Terms and provenance (owner-reported, not agent-verified)
CFBD/CBBD terms (collegefootballdata.com/terms, effective 2026-08-12): direct-API use permits derived outputs, the quota is shared across tools under one key, and raw redistribution is prohibited. The free tier is 1,000 shared calls per month. Because this repository is public:
- the probe never writes a response body anywhere. Each body is reduced in memory to sha256, size, JSON type, row count, field names and per-field non-null counts, then dropped;
- no artifacts are uploaded, runner scratch is deleted in an `always()` step, and `.gitignore` covers raw directories;
- the bulk collector `run()` is local-only and refuses under GitHub Actions;
- derived data may enter the repository only via `write_derived()`, which requires provenance (source, hosts, endpoints, retrieval time, source-response sha256s, terms URL, effective date and evidence, attribution, generator), tier `CLEARED_PROVIDER_TERMS_DIRECT_API`, derivation `aggregate|model_feature|validation_summary`, and `contains_raw_records: false`. `check_public_derived()` is enforced by the test suite.

## Key isolation
The owner's existing key is the secret `CFBD_API_KEY` in GitHub environment `college-direct`, with deployment branches restricted to `main`. Only a job that names the environment can read it, and the only such job is `probe`, which runs only on `workflow_dispatch` from `main`. Pull-request runs never get it: fork PRs receive no secrets, and no job they run names the environment. A job on any other branch that names the environment is blocked by the branch rule. Tests forbid any other workflow from mentioning `CFBD_API_KEY` or `college-direct`, and forbid `pull_request_target`/`workflow_run` triggers. Every action in the probe workflow is pinned to a commit SHA.

## Gates (each fails closed)
- Dispatched **and** re-run by the repository owner (`github.actor`, `github.triggering_actor`), from `refs/heads/main`, with `AUTHORIZE-10-CALL-PROBE` typed.
- Owner authorization file `research/input_research/data_collection/college_direct_authorization.json` on `main` with these fields:
  - `authorized` and `probe_authorized` set to `true`;
  - `monthly_call_cap`, and `max_share_of_cap` at most 0.5;
  - `shared_quota_remaining`, declared at most 2 days before the run and at least 10 + `quota_reserve`, where `quota_reserve` is at least 100;
  - `expires`, not yet passed.
- At most **10 probe calls per calendar month across both domains** (cbb = 6 calls, cfb = 4), and the general monthly cap `monthly_call_cap * max_share_of_cap`.
- Call 1 is CFBD `/info`. It must return an integer remaining count that covers the rest of the probe plus the reserve and agrees with the owner's declaration; otherwise the probe stops.
- Any non-200 response or transport error stops the probe. So does a 200 that is not a JSON object or array, or that carries a non-JSON `Content-Type` (for example an HTML documentation page); such a response never counts as API validation. The CBB probe calls `/info`, `/plays/types`, `/games`, `/plays/date`, `/plays/team` and `/lineups/team`, all JSON operations. There are no retries; a retry is a new owner dispatch that must still fit within 10 calls.

## Durable ledger (branch `college-direct-ledger`: counts, hashes and safe summaries only)
| Job | Key | Token | Role |
|---|---|---|---|
| `reserve` | no | contents: write | charges the full probe size and records a pending reservation keyed `run_id-run_attempt`; pushed **before any call** |
| `probe` | yes | contents: read, no stored git credentials | refuses unless the pushed ledger holds this attempt's reservation; counts each call before making it |
| `reconcile` | no | contents: write | `always()`: refunds `reserved - calls_made` only from a strictly validated summary of this run and publishes it to `summaries/<run>.json`; otherwise the reservation stays charged in full |

What each failure does:
- **Ledger branch unreadable:** the run is refused. Only "branch absent" counts as first use.
- **Runner lost or job killed:** the reservation stays charged in full and is closed out at the next reserve as `UNRECONCILED_COUNTED_IN_FULL`.
- **SIGTERM/SIGINT:** a summary is written whose call count is an upper bound.
- **Refused before any call:** the summary records exactly 0 calls, and the reservation is fully refunded.
- **Re-run attempt:** no reservation for that attempt, so the probe refuses.
- **Corrupt ledger:** treated as a refusal, never as an empty ledger.
- **Writes and pushes:** ledger writes are atomic (temp file + fsync + rename). Commits only append; pushes are never forced, and a non-fast-forward push fails.

## Owner setup (nothing below has been done by the agent)
1. Merge the PR into `main`.
2. Settings → Environments → New environment `college-direct` → Deployment branches and tags: *Selected branches and tags* → add `main`. Add environment secret `CFBD_API_KEY` (existing key).
3. Commit the authorization file on `main` (template in the PR description).
4. Within 2 days: Actions → *College direct-API probe (manual)* → Run workflow on `main`, domain `cbb`, confirm `AUTHORIZE-10-CALL-PROBE`.

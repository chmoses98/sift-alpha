# CFBD/CBBD direct-API collection path and MoneyPuck isolation (2026-11-11, public-repo revision 2026-11-13; RESEARCH_ONLY, $0, nothing executed)

Agent verification only. Continues `8a7ba09`. Catalog untouched (1,649 inputs, baseline lock unchanged). No probe was run, no key used, no network opened, no PR/merge/polling/spend.

## Externally reported evidence (ChatGPT retrieval, 2026-11-11; NOT agent-verified: all hosts still return no connection from this session)
- CFBD/CBBD terms (collegefootballdata.com/terms, effective 2026-08-12): direct API permits commercial derived outputs; quota shared; raw redistribution prohibited.
- CFBD tiers: free = 1,000 shared monthly calls. CBBD endpoints `…/api/plays`, coverage at `…/data-availability`.
- MoneyPuck data.htm: listed downloads permitted non-commercially with attribution.
Re-checked this session: `curl` to all three hosts returns no response (proxy blocked). Unchanged policy; no workaround attempted.

## 1. Corrected CBB inventory (`college_direct.py`, `plan --domain cbb --seasons 2014-2025`)
Per-game was the wrong default (74,400 play calls + lineups). Lineups start **2024** (owner-relayed), so lineups cost only 2 seasons.
| Strategy (2014-2025) | Calls | Notes |
|---|---|---|
| plays by game (fallback) | 74,400 | 6,200 x 12; only for responses that look truncated |
| **plays by date** (`/plays/date`) | **1,932** (1,935 with leap days) | one call per game day, Nov 1 - Apr 10 |
| plays by team (`/plays/team`) | 4,392 | 365 teams + 1 `/teams` per season; each game appears twice |
| lineups by game, 2024-25 | 12,400 | fallback only |
| **lineups by team, 2024-25** | **732** | |
| static non-play (games/teams/players/rankings) | 84 | |
| **Recommended total** | **~2,750** | date plays + team lineups + static |
Still **unverified** until the probe (recorded in code): per-response row limit (a busy date may truncate; detect rows at the limit and fall back to team/game), plays start season (2013 assumed), season numbering (ending year assumed; the probe cross-checks), populated fields in early seasons. Point-in-time: plays are event-time keyed, but a backfill is retrieved after the fact. Store retrieval time + sha256; use only as post-game truth, never as pre-game information, and never the provider's ppa/win-probability columns (model/market-adjacent). At the free 1,000/month shared cap, ~2,750 calls is ~3 months at 100% (~6 at the 50% share ceiling) for CBB alone. Spending that share is the owner's decision; the probe measures the real remaining quota first.

## 2. Existing-key reuse (public repository; updated 2026-11-13)
The repository stays **public** (free Actions compute). The owner's existing key is stored once, as the Actions secret `CFBD_API_KEY` in the GitHub **environment** `college-direct` (deployment branches: `main` only). It is mapped to both providers (one shared-quota key per owner report; if CBBD rejects it the probe stops on 401/403). An environment secret, not a plain repository secret, is used because only a job that names the environment can read it: in this repository that is the single `probe` job, which runs only on `workflow_dispatch` from `main`. `pull_request` runs never receive it (fork PRs get no secrets, and no job they run names the environment); tests forbid any other workflow from mentioning `CFBD_API_KEY` or `college-direct`, and forbid `pull_request_target`/`workflow_run` triggers. Nothing was created, bought or read by the agent.

## 3. Manual fail-closed probe (`.github/workflows/college-direct-probe.yml`, `college_direct.py reserve|probe|reconcile`)
`workflow_dispatch` only; no schedule/PR/push trigger; top-level `permissions: {}`. Runs only if: dispatched **and** re-run by the repo owner, from `main`, with `AUTHORIZE-10-CALL-PROBE` typed; the owner authorization file exists on `main` with `authorized`, `probe_authorized`, cap, `max_share_of_cap` <= 0.5, `shared_quota_remaining` declared <= 2 days ago and >= 10 + `quota_reserve` (>= 100), unexpired. The private-repository requirement is **removed**.

Three jobs:
| Job | Key | Token | Does |
|---|---|---|---|
| `reserve` | no | contents: write | charges the **full** probe size (cbb 6, cfb 4) to the month and records a pending reservation keyed `run_id-run_attempt`, then pushes it to branch `college-direct-ledger` **before any call** |
| `probe` | yes (env `college-direct`) | contents: read, no stored git credentials | refuses unless the pushed ledger holds *this attempt's* reservation; call 1 is CFBD `/info` (integer remaining >= rest + reserve and consistent with the owner declaration, else stop); any non-200/transport error stops; **no retries**; bodies are reduced in memory to a validation summary (sha256, bytes, JSON type, row count, field names, per-field non-null counts) and dropped. Nothing raw touches disk; runner scratch is deleted in an `always()` step |
| `reconcile` | no | contents: write | `always()`: refunds `reserved - calls_made` only from a summary of this run that passes a strict key/type check, writes it to `summaries/<run>.json`; otherwise the reservation stays **charged in full** |

Limits: at most **10 probe calls per calendar month across both domains**, and the general cap `monthly_call_cap * max_share_of_cap`. A retry is a new owner dispatch with the phrase and must fit the 10-call ceiling; a re-run attempt never inherits an earlier attempt's reservation.

Ledger durability (audited and repaired):
| Failure | Before (`03da1e2`) | Now |
|---|---|---|
| ledger branch unreadable (network/auth) | treated as empty -> fail-open | refused (only "branch absent" = first use) |
| job killed / runner lost mid-probe | local counts lost -> next probe allowed | reservation already pushed; stays charged in full, closed out as `UNRECONCILED_COUNTED_IN_FULL` |
| cancellation (SIGTERM/SIGINT) | depended on `always()` push | summary written with an upper-bound `calls_made` (incremented before each call); reconcile refunds only the rest |
| summary missing at persist | `git add` of missing file aborted the push | reconcile always pushes; missing/invalid summary => full charge |
| concurrent / stale writer | `push -f` of an orphan branch overwrote history | append-only commits, pushed without force (non-fast-forward fails) |
| partial file write / corrupt JSON | crash or silent empty | atomic temp+fsync+rename; unreadable ledger = refusal |
| "Re-run failed jobs" | could re-probe with the same counts | attempt-keyed reservation: probe refuses |
| pre-call refusal (e.g. key missing) | n/a | exact 0-call summary, fully refunded |

Public outputs: no artifacts, no raw in git (also `.gitignore`d). The ledger branch holds counts, hashes, field names and row counts only. CFBD/CBBD-derived data may enter the repository only via `write_derived()`, which requires provenance (source, hosts, endpoints, retrieval time, source-response sha256s, terms URL/effective date/evidence, attribution, generator), tier `CLEARED_PROVIDER_TERMS_DIRECT_API`, derivation `aggregate|model_feature|validation_summary`, and `contains_raw_records: false`; `check_public_derived()` runs in CI. The bulk collector `run()` is local-only and refuses under GitHub Actions. 46 tests (`tests/test_college_probe.py`, now run by `research-tests.yml`) cover refusal, caps, stops, cancellation, reconcile, the ledger branch script end-to-end, leakage, licence gate and workflow gating. **Not executed against the API.**

## 4. NHL / MoneyPuck (`alpha_engine/collect/moneypuck.py`, `.github/workflows/moneypuck-listing.yml`)
Publicly listed families **cannot be enumerated exactly from here** (page unreadable). Evidenced as downloaded by the owner's code: `seasonSummary/{year}/regular/teams.csv`, `.../goalies.csv`, `careers/gameByGame/all_teams.csv`. Remembered, unverified: `shots_{year}.zip`, season `skaters/lines/pairings`, `allPlayersLookup.csv`. The manual workflow makes one GET of the public page and publishes the actual link list (`listing.json`); ingestion accepts only evidenced files or files in that listing, writes only under a `non_commercial/` directory, and tags manifests `CLEARED_NONCOMMERCIAL_RESEARCH`, `commercial_use: false`, with attribution. No MoneyPuck-derived output may enter commercially cleared datasets.

## 5. Python baseline
Fresh environment (`pip install -r requirements-dev.txt`, Python 3.13): `python -m pytest -q` **1021 passed**; CI-style `python3 -W ignore -m unittest discover -s tests -p 'test_*.py'` (906 tests, pytest-style tests are not collected by unittest) green. **The three inherited failures did not reproduce** in either runner; no code was changed to "fix" them. Likely causes if they appear elsewhere: missing `pytest/pyyaml/pyarrow` in the runner, or running pytest with `-W error` (which produces ~100 failures and 2 errors, an invalid baseline). Please send the failing test ids if they come from another environment.

## Owner actions to run the first probe
1. Merge this PR (and the data-foundation line it sits on) into `main`.
2. Settings -> Environments -> New environment `college-direct`; Deployment branches: `main` only; add secret `CFBD_API_KEY` (existing key).
3. Commit `research/input_research/data_collection/college_direct_authorization.json` on `main` (declare current remaining quota, today's date).
4. Within 2 days: Actions -> College direct-API probe (manual) -> Run workflow on `main`, domain `cbb`, confirm `AUTHORIZE-10-CALL-PROBE`.

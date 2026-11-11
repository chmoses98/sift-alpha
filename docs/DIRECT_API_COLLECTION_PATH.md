# CFBD/CBBD direct-API collection path and MoneyPuck isolation (2026-11-11; RESEARCH_ONLY, $0, nothing executed)

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

## 2. Existing-key reuse
No `CFBD_API_KEY`/`CBBD_API_KEY` variable (checked by name only), no repository/environment secret visible to this session, no account created, nothing purchased. Reuse path = the owner's **existing** key stored as secret `CFBD_API_KEY` in the protected GitHub environment `college-direct`; the workflow maps it to both providers (one shared-quota key per owner report; if CBBD rejects it the probe stops on 401/403).

## 3. Manual fail-closed probe (`.github/workflows/college-direct-probe.yml`, `college_direct.py probe`)
`workflow_dispatch` only; no schedule/PR/push trigger. Runs only if: actor is repo owner; confirmation phrase typed; environment `college-direct` approved; repo is **private**; owner authorization file exists with `authorized`, `probe_authorized`, cap, `max_share_of_cap` <= 0.5, `shared_quota_remaining` declared <= 2 days ago and >= 10 + `quota_reserve` (>= 100), unexpired. Max 10 calls (cfb 4, cbb 6), one probe per month. Call 1 is CFBD `/info`: it must return an integer remaining count >= the rest + reserve and consistent with the owner's declaration, else stop (quota uncertainty). Any non-200 (401/403/429/other) or transport error stops immediately. Every call is ledgered before it is made; the counts-only ledger and sha256/status/row log persist on branch `college-direct-ledger`; raw bodies go to a 1-day private artifact, never git. Key only in the `Authorization` header; never logged/stored. 20 tests (`tests/test_college_probe.py`) cover refusal, caps, stops, leakage, workflow gating. **Not executed.**

## 4. NHL / MoneyPuck (`alpha_engine/collect/moneypuck.py`, `.github/workflows/moneypuck-listing.yml`)
Publicly listed families **cannot be enumerated exactly from here** (page unreadable). Evidenced as downloaded by the owner's code: `seasonSummary/{year}/regular/teams.csv`, `.../goalies.csv`, `careers/gameByGame/all_teams.csv`. Remembered, unverified: `shots_{year}.zip`, season `skaters/lines/pairings`, `allPlayersLookup.csv`. The manual workflow makes one GET of the public page and publishes the actual link list (`listing.json`); ingestion accepts only evidenced files or files in that listing, writes only under a `non_commercial/` directory, and tags manifests `CLEARED_NONCOMMERCIAL_RESEARCH`, `commercial_use: false`, with attribution. No MoneyPuck-derived output may enter commercially cleared datasets.

## 5. Python baseline
Fresh environment (`pip install -r requirements-dev.txt`, Python 3.13): `python -m pytest -q` **1021 passed**; CI-style `python3 -W ignore -m unittest discover -s tests -p 'test_*.py'` (906 tests, pytest-style tests are not collected by unittest) green. **The three inherited failures did not reproduce** in either runner; no code was changed to "fix" them. Likely causes if they appear elsewhere: missing `pytest/pyyaml/pyarrow` in the runner, or running pytest with `-W error` (which produces ~100 failures and 2 errors, an invalid baseline). Please send the failing test ids if they come from another environment.

## Single smallest owner action
Add the existing key as secret `CFBD_API_KEY` in a protected environment `college-direct` of a **private** repo, commit `college_direct_authorization.json` (declaring current remaining shared quota), then dispatch the probe once. Nothing else is blocking.

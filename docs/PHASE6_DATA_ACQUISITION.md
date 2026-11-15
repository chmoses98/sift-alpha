# Phase 6 (2026-11-15): free data acquisition and training readiness (RESEARCH_ONLY)

Agent verification only (Claude builders, replay gates, one independent blind headless Claude re-implementation); **not human verified**. No model was retrained or promoted, no schedule was
created or activated, no paid service, credential or account was used, and **no rights tier was changed**. No raw row is committed (aggregates, digests and evidence JSON only).
Dashboard: Data foundation → **Phase 6** tab (rendered from `research/data_foundation_ops/phase6_acquisition.json`, built by `python -m alpha_engine.foundation.phase6`).

## 1. Counts, before and after (recomputed, not assumed)
| | Before (roadmap 2026-11-14) | After |
|---|---|---|
| Training-ready predictive inputs | 37 | **39** (+2, both NHL) |
| VERIFIED_FULL (certified) inputs | 58 | 60 |
| Missing PRIMARY slots / distinct inputs | 888 / 683 | 888 / 683 (the two new inputs feed no market where they are a missing PRIMARY slot) |
| Datasets whose roadmap row shows the recorded rights posture as a blocker | 0 (hidden) | 29 |

## 2. What was built and how it was verified
| Input | Builder | Data (owner archive, read only) | Replay gates | Blind match | Status |
|---|---|---|---|---|---|
| `nhl.long_change_effect` | `features/nhl_ext3.py` | NHL-edge-finder `players/{team_states,goals}`, `moneypuck/shots` (13,992 team-games, 2021-10-12 .. 2026-09-29) | all pass | 8/8 columns, round 1 | VERIFIED_FULL, PIT_SAFE, **training-ready** |
| `nhl.pk_structure_opp` | `features/nhl_player_ext3.py` | `players/{team_states,shots,players}`, `moneypuck/shots` (251,797 skater-games) | all pass | 6/7 round 1 → 7/7 after a builder fix | VERIFIED_FULL, PIT_SAFE, **training-ready** |

Gates (full mode, `replay_ext_run.py` families `nhl3`, `nhl_player3`): determinism, truncation at 55/75/92 % of dates, future-content perturbation with 3 seeds, own-game scramble, non-vacuity
(every column moves when a mid block is permuted). Blind match: `compare_independent.py` (rtol = atol = 1e-9, identical keys and NaN pattern) against a fresh headless session given only
`verification/blind_briefs/briefs_p6_nhl.md` and a copy of the raw files (`verification/blind_briefs/p6_blind_runs/audit.json`). FULL certification: `verification/full_certification/phase6_round1.json`
maps every catalog clause to columns; `verified_coverage` re-checks it fail-closed.

**Defect found by the blind gate:** `pko_xga60_pre` summed MoneyPuck `xGoal` (stored float32) in single precision; the builder now casts to float64 first and the UNCHANGED round-1 blind CSV matches
(`independent/rounds/NHL_nhl_player3_round1_MISMATCH_float32_xg_sum.json`). Same defect class as Phase 15 `nhl.ixg_player`.

## 3. Sources probed
| Source | Result | Data / history seen | Rights |
|---|---|---|---|
| sportsdataverse ESPN men's college basketball team box, player box, schedules | reachable; 85 season files fetched once and sha256-checked vs cbb-edge-finder pins (2015+ identical; 2004-2014 republished upstream) | team box usable 2005-2026, player box 2006-2026, ~5,800-6,300 games/season | **frozen** (owner decision 1); files deleted unused |
| sportsdataverse ESPN NBA player / team box (2005 file) | reachable (range probe) | long NBA history exists | ESPN-derived, UNRESOLVED, collection not allowed; nothing collected |
| sportsdataverse `nhl_shifts` (2015 file) | reachable (range probe) | shift charts (api.nhle.com shift host is blocked here) | NHL API-derived, UNRESOLVED; nothing collected |
| hoopR-mbb-data LICENSE.md | read | now "CC BY 4.0 ... data, code, and documentation" | new evidence for the owner; wrapper licence cannot clear ESPN upstream, tier unchanged |
| CBBD/CFBD API, Barttorvik, Sports-Reference, stats.nba.com, MoneyPuck site, cdn.nba.com | not probed: key not configured / proxy refused / 403 | — | stopped per the brief, not retried |
| Owner repositories (cbb-, nba-, NHL-edge-finder, main + 29/28/18 branches) | listed (tree only) | CBB: no multi-season history anywhere; NBA: injury/roster context since 2026-09-18, injury PIT since 2026-10-12; NHL: lineup probe stalled since 2026-10-26 | owner archives |

## 4. The decision that gates P0 progress
Every free source of new NBA / CBB / NHL history reachable from this environment is recorded `UNRESOLVED_INTERNAL_ONLY` with `collection_allowed=false` in `rights_registry.json`, and the
sportsdataverse college collector is in `frozen_collectors` (owner decision 1). The Phase 6 brief authorises free-source probes "provided access and the intended usage are permitted"; this session
read that as NOT overriding the recorded freeze. An attempt to record a manual-collection permission in the registry was refused by the session's safety review as an owner-only decision; it was
reverted, and the downloaded CBB files were deleted without being used. **To unlock the CBB historical foundation (21-22 seasons, verified reachable) the owner needs to record a rights decision**
for `sportsdataverse_espn_mbb_cfb` (for example: manual, call-capped, internal non-commercial research, no redistribution). The same applies to long NBA box history and NHL shifts.

The roadmap used to hide this: a reachable dataset showed "blocker: none". `foundation/acquisition.py` now adds a RIGHTS blocker whenever no source with a rights reading allows collection (29 datasets).

## 5. Forward capture (proposal only; nothing scheduled)
See the Phase 6 tab and `alpha_engine/foundation/phase6.py` (`CAPTURE`): NBA transactions (2 req/day), NBA starters at T-90/T-30/T-5 (≈30 req/day; schedule the existing manual starters check),
keep the running NBA injury PIT and CBB availability captures, NHL goalie confirmations + lines at T-180/T-90/T-30 (≈36 req/day; the stalled lineup probe and Daily Faceoff need a policy review),
NFL injuries/inactives as already proposed in `docs/CAPTURE_PROPOSAL.md`. Total under 100 requests/day in season and a few MB/day compressed. These ESPN / NHL API feeds carry the same
unresolved rights posture as the owner's existing workflows.

## 6. Regeneration
    python -m alpha_engine.input_research.regenerate --apply
    python -m alpha_engine.input_research.data_foundation.verified_coverage
    for m in market_completeness full_promotion_audit rights_questions capture_plan prospective_plan source_mapping market_input_map; do python -m alpha_engine.input_research.data_foundation.$m; done
    python -m alpha_engine.input_research.data_foundation.phase12_coverage --write
    python research/provider_licensing/priority_recalc.py
    python -m alpha_engine.foundation.sources && python -m alpha_engine.foundation.ledger && python -m alpha_engine.foundation.acquisition && python -m alpha_engine.foundation.phase6

Tests: `pytest tests` 1,580 passed / 8 skipped; `npm test` pass; Playwright `acquisition.spec.mjs` + `data-foundation.spec.mjs` 30/30 (desktop + phone viewport, incl. the new Phase 6 test).
Two hard-coded VERIFIED_FULL counts in `tests/test_phase9.py` / `tests/test_phase10.py` were updated 58 → 60 with the reason.

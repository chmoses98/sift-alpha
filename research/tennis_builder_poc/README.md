# Tennis builder proof of concept (RESEARCH_ONLY)

> **PAUSED 2026-11-13 (owner decision; priority moved to NBA, CBB, NFL, CFB, NHL).** State `PAUSED_PARTIAL`: all five inputs PARTIAL, synthetic-tested only, **not real-data verified**. Handoff, unresolved issues and resume steps: `docs/TENNIS_HANDOFF.md`; record: `CLOSURE_20261113.json`.

Branch `claude/provider-licensing-research-k7d0tj`, 2026-11-13. Sackmann data is CC BY-NC-SA 4.0: **non-commercial research only**.
No data was downloaded, no collection, no registry, catalog, map or baseline change, no status promotion.

## What exists now

| Input | Columns (`alpha_engine/features/tennis_ext6.py`, table `team`) | Level claimed | Status |
|---|---|---|---|
| `ten.within_match_dependence` | `wmd_overdisp_pre`, `wmd_form_sd_pre`, `wmd_n_sets_pre` | PARTIAL | synthetic tests only |
| `ten.hold_rate_uncertainty_propagation` | `hru_p66_mean_pre`, `hru_p66_point_pre`, `hru_jensen_pre`, `hru_neff_pre`, `hru_opp_neff_pre` | PARTIAL | synthetic tests only |
| `ten.player_speed_slope` | `pss_cpi_pre`, `pss_beta_pre`, `pss_adj_rating_pre` | PARTIAL | synthetic tests only |
| `ten.set_dist` | `sd_p{2..5}_pre`, `sd_match_win_pre`, `sd_cal_p{2..5}_pre` | PARTIAL | synthetic tests only |
| `ten.set_number_calibration` | `snc_logit_s1_pre`, `snc_off_*_pre` (6 states), `snc_n_pre` | PARTIAL | synthetic tests only |

None of these is built, verified or FULL in any registry. The map, audit and coverage files are untouched. The `specs()` `missing` lists state every departure from the catalog definition:
- quadrature replaces Monte Carlo;
- a 730-day window replaces the "last ~120 matches" window;
- the slope prior mean is 0;
- set *counts* are produced, but not the full set-score pmf;
- the match-form SD is a moment estimate that also absorbs pre-match estimation error, so it is an **upper bound**, and `set_dist` inherits it.

### Reuse
The builders reuse existing, already-verified pieces:
- From `tennis_ext2`: score parsing, the strictly-earlier windowed sums (`_wsum`), shrinkage, and the date-batched walk-forward Elo.
- From `tennis_ext4`: the closed-form hold and the set DP. Its opponent-adjusted serve-point-win estimate is reproduced exactly; a test asserts equality with `tennis_ext4.gps_hold_pre`.

The replay runner gains one family, `tennis6` (`replay_ext_run.py`), which has never been run on real data.

### Point-in-time
Sackmann gives every match of a tournament the tournament start date. Every aggregate therefore uses only matches with a `tourney_date` strictly earlier than the row's own. That excludes the same tournament and the same date, as in `tennis_ext2` to `tennis_ext5`.

### Tests (`tests/test_tennis_ext6.py`, 15, all pass)
- **Generic replay harness.** Runs on a synthetic point-level simulation (`tests/tennis_synth.py`). Checks determinism, truncation and future perturbation at 3 cuts, own-date perturbation, and non-vacuity for all 5 inputs.
- **Adversarial checks:**
  - later rounds of the same tournament cannot move that tournament's rows;
  - absurd future scores and statistics cannot move earlier rows;
  - the first date has no history;
  - the leave-player-out index is exactly 0 when every prior event match involves the player;
  - an injected match-form shock is detected;
  - specs are never FULL;
  - `load_raw` refuses a missing, unpinned or tampered file. It checks the SHA-256 of all 54 pinned files.
- **Record.** `synthetic_replay.json` records the synthetic harness run. It is deliberately **outside** `verification/replay_ext/`, so `verified_coverage` can never read it as evidence.

## Readiness conflicts (no promotion)

1. **`ten.joint_event_correlation`.** The map says `audit_status DATA_IN_HAND` but `bucket/vstatus REQUIRES_COLLECTION`. Both come from the same records, which hold:
   - Raw availability: its direct needs (`PLAYER_BOX`, `TEAM_BOX` → `ten.matches`) are in hand.
   - Upstream inputs: `input_audit.json` derives it from `ten.path_difficulty_sim` and `ten.health_persistence_between_events`. Both are unbuilt and `REQUIRES_COLLECTION`. The audit flag reads "status DATA_IN_HAND -> COLLECT_PROSPECTIVE: limited by an upstream input it is derived from".
   - The source mapping (`MAP_TENNIS.json`) says `NO_FREE_PATH` ("Needs draws and health state").
   - A completeness review (`TENNIS_a.json`) judged it `KEEP_CONTEXT`: it is the quantity being forecast, not an input.

   **Verdict:** not build-ready. The rev-2 `priority_recalc` ranked it #6 because it ignored `depends_on`. Rev 3 adds that check (tier `BLOCKED_BY_UPSTREAM_INPUT`).

2. **`ten.service_points_scenario_mixture`.**
   - Data-in-hand round 1 said `CONFIRMED`.
   - Round 2 (`DIH_CONFIRMED27.json`) said `DOWNGRADED → BLOCKED_NO_SOURCE`. The catalog definition conditions the retirement scenario P(ret) on a "pre-match fitness flag". The files have no injury or withdrawal vintages, and no permitted source has them. The verifier wrote: "Core without flag is possible; as specified it is not."
   - The completeness input audit also marks it a `DUPLICATE` of `ten.match_length_expectation`.

   **Verdict:** not build-ready as specified. A core-only variant would need a catalog redefinition, which is not done here. Rev 3 tier: `VERIFIER_DOWNGRADED`.

`priority_recalc` build-ready inputs: rev 2 = 7, **rev 3 = 5** (the five targets above). The upstream inputs of the five (`ten.hold_break`, `ten.surface_rating`, `ten.venue_speed_history`) are built and `VERIFIED_PARTIAL`.

## What a real-data validation needs (authorization)

`required_files.json` (generated by `required_files.py` from the committed ledger) lists the **54 pinned files with SHA-256**:
`tennis_atp/atp_matches_2000..2026.csv.gz` and `tennis_wta/wta_matches_2000..2026.csv.gz`, from `github.com/chmoses98/Tennis-Edge-Finder`, branch `tennis-data`. They hold 79,019 ATP and 72,434 WTA rows, 2000-01-03..2026-04-22.

Note: the ledger says snapshot 2026-11-06, while the access record says 20261109T145505Z. The hashes are authoritative.

1. **Authorization needed:** read-only access to the owner's own repo `chmoses98/Tennis-Edge-Finder` in a session (attach it, or allow `add_repo` read). Alternatively, the owner places the 54 files in a directory. No other host, account, key or cost is involved.
2. **Then:** run `python -m alpha_engine.input_research.data_foundation.replay_ext_run tennis6 <dir> …/replay_ext/TENNIS_tennis6.json`. `load_raw` refuses any hash mismatch.
3. **Then:** an independent blind re-implementation from a written brief, compared with `compare_independent.py`, as done for `tennis_ext4`.

Only if both pass may a status change be *proposed*, and the owner approves it. Expect real-data issues the synthetic data cannot show:
- WTA serve statistics are missing in about 34% of rows;
- final sets played as advantage sets, and match tiebreaks, are excluded by `_sets_ok`;
- event renames break the `tourney_name` key of the pace index.

## Update 2026-11-13: authorized real-data replay attempt and blind verification

**Real-data replay: FAILED CLOSED, not run.** See `real_data_attempt_20261113.json`.
- **Retrieval:** the owner authorized a one-time read-only retrieval of the 54 files from `tennis-edge-finder` `tennis-data` `…/20261109T145505Z/sackmann/`. All 54 were retrieved.
- **Hash check:** **0 of 54** match the pinned SHA-256 manifest, compared both as gzip bytes and as decompressed CSV.
- **Likely cause:** every daily snapshot on that branch holds different blobs, because the gzip header embeds a timestamp. The ledger says the manifest came from snapshot 2026-11-06, which is probably `20261106T134626Z`. That directory was not retrieved, because it is outside the authorized path.
- **Cleanup:** the staged files and the clone were deleted. No raw data is committed.
- **What remains unmeasured:** missingness, calibration, real-data PIT leakage, anomalies and coverage on real data. They are **not measured**. Nothing below substitutes for them.

**Blind verification: synthetic only.** See `blind_verification_synthetic.json`, `blind/`.
- **Setup:** an independent agent implemented all five inputs from `blind_brief.md` alone, with no repository access.
- **Clean fixture (4,464 matches):** identical keys, identical NaN patterns, and every column of all five inputs **MATCHes** at 1e-9.
- **Dirty fixture:** RET, W/O, ABD, advantage final sets, match tiebreaks, missing serve stats, SvGms of 0, missing surface or best_of, duplicate match numbers, and messy event names.
  - The first run **found a defect**: `tennis_ext6` crashed on a missing `best_of`. It is fixed (missing → 3, matching the blind choice), with a regression test.
  - After the fix, all five inputs MATCH.
- **Limits:** this shows the code implements the brief. It does not validate the brief against the catalog, and it says nothing about real data.

**Status: unchanged.** All five stay `PARTIAL` (the definition gaps are listed in `specs().missing`). None is verified, built or FULL in any registry.

**To finish, choose one:**
- (a) authorize the same read-only retrieval from `20261106T134626Z` and verify it against the existing manifest; or
- (b) authorize re-pinning the manifest to `20261109T145505Z`.

Then rerun `replay_ext_run tennis6`, and run the blind comparison on the real files.

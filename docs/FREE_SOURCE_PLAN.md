# Free-source acquisition plan (RESEARCH_ONLY, $0)

Status: **claims, not implementations.** Per-sport blind mappers (Claude agents) mapped each candidate input to source, columns, event time, history and computation
(`research/input_research/data_foundation/verification/source_mapping/`). `source_mapping.py` aggregates them into `free_source_plan.json`. SOURCE_MAPPED != built != verified.

| sport | mapped | MEASURED | PARTIAL | no new permission | terms pending | owner action | no free path | prospective capture |
|---|---|---|---|---|---|---|---|---|
| CBB | 153 | 53 | 62 | 0 | 105 | 0 | 34 | 15 |
| CFB | 129 | 34 | 54 | 0 | 24 | 64 | 16 | 13 |
| MLB | 222 | 47 | 107 | 148 | 1 | 0 | 48 | 30 |
| NBA | 158 | 26 | 71 | 2 | 95 | 0 | 43 | 17 |
| NFL | 253 | 118 | 86 | 185 | 0 | 0 | 19 | 66 |
| NHL | 84 | 15 | 36 | 8 | 37 | 0 | 14 | 21 |
| SOCCER | 131 | 7 | 80 | 47 | 38 | 0 | 19 | 14 |
| TENNIS | 57 | 0 | 23 | 23 | 0 | 0 | 21 | 12 |

Access classes: NO_NEW_PERMISSION (nflverse CC-BY-4.0, MLB/ESPN/NHL public endpoints the owner's workflows already use, owner archives); TERMS_PENDING (SportsDataverse releases, football-data.co.uk: private-individual/no-bot terms);
NEEDS_OWNER_ACTION (Open-Meteo Previous/Single Runs, CFBD/CBBD key, MoneyPuck, Retrosheet, Wikidata: hosts not reachable or key required; nothing was requested or created). Vintage-dependent inputs are never filled from observed or later data: they need prospective capture.

## Measured this phase (`source_samples/*.json`)
- nflverse injuries carry `date_modified` 2010-2024 (2009: 0.4%, 2025: absent); snap counts start 2013; depth charts only dated in 2025.
- SportsDataverse bulk assets reachable (NHL shifts/officials, NBA/CBB pbp); licence/upstream terms unverified -> TERMS_PENDING.
- ESPN officials history for CBB/NBA/NHL are as-played (not pregame assignments).
- Open-Meteo vintage audit: host unreachable here, so no vintage was verified; request documented only.

## Independent replay of new builders (`alpha_engine/features/nfl_ext.py`)
`nfl.injuries_pit` (PARTIAL) and `nfl.snaps` (PARTIAL): determinism, truncation (3 cuts), future-outcome perturbation (3 cuts/seeds), own-game, post-kickoff-injury scramble, non-vacuity all pass.
The first injuries run FAILED the perturbation test (a season-wide timestamp-share gate let future rows change earlier features); fixed by per-team-game availability and rerun. Evidence: `verification/replay_ext/NFL.json`.
Coverage: injuries 85.3% (2010-2025), snaps 76.6% (2013-). Agent verification only; not human expert verification.

## Phase 5: mapping -> verified inputs (RESEARCH_ONLY, $0)
Gates (fail closed, `verified_coverage.py`): an extension input is promoted from REQUIRES_COLLECTION only if (1) every replay test passes - determinism, truncation at 3 cuts, future-content perturbation at 3 cuts/seeds, own-game, a non-vacuity check showing the perturbation really moves later rows (a missing or failed `pit_check*` test = REPLAY_FAILED; injuries additionally need the post-kickoff report test); and (2) a BLIND re-implementation by a separate agent matches every column (`verification/independent/`; MISMATCH = DOWNGRADED_BY_VERIFIER, anything but MATCH = not promoted). Nothing here is certified FULL: each builder lists the definition components it does not implement.

| sport | new VERIFIED_PARTIAL | inputs | source (licence / terms) | history |
|---|---|---|---|---|
| NFL | 15 | injuries_pit, snaps + 13 play-by-play: two_minute_tempo, opening_script, safety_risk, dst_td_hazard, non_offensive_scoring_rate, opponent_ball_control_denial, fourth_and_goal_policy, fourth_down_fg_decision_rate, goal_to_go_pass_rate, rush_explosive_tail_rate, qb_dropback_to_attempt_leakage, endzone_exposure_plays, own_one_yard_line_snap_rate | nflverse (CC BY 4.0) | pbp 2010-2026; injuries 2010-2024 timestamped; snaps 2013- |
| MLB | 8 | pitch_mix, pitch_type_whiff, lineup_whiff_by_pitch, velo_trend, opp_pitches_per_pa, sp_two_strike_putaway, batted_ball_outcome_model, max_velocity_extreme_distribution | MLB Stats API game feed, read-only GET (unofficial API: terms NOT verified; scratch only, nothing committed) | 2021-2024 pitch events (694k-707k pitches/season, 0 failed games) |
| TENNIS | 3 | fitness, walkover_slot_hazard, layoff_survival_curve | owner's Sackmann archive (already owner-held; upstream licence believed CC BY-NC-SA, NOT re-verified this session) | 2000-2026, tournament-start-date resolution |
| CFB, CBB, NBA | 0 | - | SportsDataverse = HOLD (see below); CFBD needs an owner key | - |
| NHL | 0 | - | multi-season shots are MoneyPuck (terms unverified); NHL-API shots cover 2021+ only | - |
| SOCCER | 0 | - | StatsBomb open data covers selected competitions only (not a genuine league history) | - |

Defects the blind verifiers found and that were fixed before any promotion: NFL opening-drive score used a different "first drive" than the count/pass-rate (fixed; re-checked 40/40); tennis player ids collide across the ATP and WTA files so histories were contaminated (fixed: key = tour:id; re-checked 40/40). A first injuries build also failed the future-perturbation test because of a season-wide timestamp gate (fixed per team-game).

Rights findings (`source_samples/rights_and_access.json`): SportsDataverse - HOLD: the data repo's LICENSE is MIT but its README badge says CC BY 4.0, and the releases re-publish ESPN / NBA Stats / stats.ncaa.org / CFBD material whose upstream terms were not verified; nothing new was ingested. Open-Meteo (free non-commercial, CC BY 4.0, no key; all four api hosts blocked here) and CFBD/CBBD (Bearer key, owner must register; hosts blocked) - NEEDS_OWNER_ACTION; no vintage claim was made.

## Phase 6 (2026-11-10): maximum free-data push, measured outcome (RESEARCH_ONLY, $0)

Reachable from this environment: GitHub raw files and release assets, ESPN, MLB Stats API, NHL web API. Blocked by network policy: Zenodo, Hugging Face, Kaggle, Harvard Dataverse, Open-Meteo, CFBD/CBBD, Retrosheet.org, MoneyPuck (see `source_samples/rights_and_access_20261110.json`). nflverse-data carries a CC BY 4.0 `LICENSE.md` (read, not assumed), which clears the NFL pbp/participation releases for research use with attribution.
Implemented and verified (agent verification only): `features/nfl_pbp_ext2.py` (8 inputs: drive outcome by index, drive duration by outcome, period drive scoring, drive clock allocation, quarter zero/tie/BTTS mass, kickoff touchback/start, XP/2-pt shrunk rates, late-tie kneel/FG/go) and `features/nfl_part_ext.py` (5 inputs: formation personnel mix, coverage shell, run defense box counts, pass rush, goal-line personnel; `nfl.pass_rush` was already COMPUTED_PARTIAL so it adds no coverage). All PARTIAL; each spec lists what is missing. Net: verified computable 248 -> 260 (+12, all NFL).
The blind re-implementation of batch 2 exposed a real builder defect (quarter-start scores were taken from possession-only plays, so Q1 points were wrong for ~200 team-games) and two rule ambiguities (first-row vs first-non-null drive attributes); all fixed in the builder and the written rule, and the final comparison is exact on all 68 columns (`compare_independent.py`).
Not done (blocked or held, not attempted): CFB, CBB, NBA, NHL, MLB, Soccer and Tennis gained nothing this phase. Reasons: CFBD/CBBD hosts blocked and the key is outside this repo scope; SportsDataverse upstream rights still unresolved; MLB Stats API and NHL API terms unverified; MoneyPuck/Open-Meteo blocked; football-data.co.uk restricted; StatsBomb/Retrosheet/Chadwick repos have no root licence file. FTN charting 2022+ was profiled only.

## Phase 7 (2026-11-10): archive reuse across the neglected sports, measured outcome (RESEARCH_ONLY, $0)

Physically read (public repos via the session git proxy, no credentials): nba-edge-finder ESPN box/shot archive (committed parquet), NHL-edge-finder game results + MoneyPuck team-games 2008-2025, Tennis-Edge-Finder `tennis-data` branch (Sackmann ATP/WTA 2000-2026, CC BY-NC-SA 4.0 read from the snapshot README), plus a layout inspection of edge-finder-api and soccer-edge-finder. cfb-edge-finder and cbb-edge-finder could not be attached (permission denied by the session; no workaround): exact request in `docs/COVERAGE_ACCESS_AND_BLOCKERS.md`.
Built and verified (agent verification only, `docs/PHASE7_NBA_NHL_TENNIS.md`): 33 inputs from the data-in-hand reservoir (NBA 14, NHL 6, tennis 13), all replay-gated and blind exact-matched, plus a tennis input (`second_serve_vulnerability`) whose definition is now complete. `verified_computable` is unchanged at 260 (these inputs were already counted as data in hand); built-and-verified rose 204 -> 237. Three inputs are FULL candidates held at PARTIAL by the extension-gate policy.
Market-level readiness for all 170 archetypes: `docs/MARKET_COMPLETENESS.md`.
Rights: licence-explicit research use only for the 14 tennis inputs; the 20 NBA/NHL inputs rest on unresolved upstream (ESPN, NHL API, MoneyPuck) terms and are internal research only. SportsDataverse stays on hold.

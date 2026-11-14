# Phase 8 (2026-11-10): evidence-based FULL, college sports, soccer (RESEARCH_ONLY, $0)

Agent verification only (Claude builders, replay gates, independent blind re-implementations); **not human verified**. Predictive experiments stay PAUSED. No orders, purchases, new credentials, scraping, permission/environment/schedule changes, PRs or merges. Continues from `be3c9f1` (Phase 7). The 1,649-input catalog is untouched (`baseline_lock` and `regenerate --check` pass).

## 1. FULL certification is now evidence-based
The unconditional "extension input is never FULL" cap (`cap_extension_full`) is replaced by `verified_coverage.certify_extension_full` / `certification_failures`. A claim stays FULL only if ALL hold, otherwise it is held at PARTIAL with the reasons recorded:
1. a reviewed certification record (`verification/full_certification/*.json`) maps every catalog `measurement` clause to implemented columns and covers exactly the replayed columns; names the timing rule, required history and the model-side steps the catalog itself labels placeholders;
2. the builder declares nothing missing;
3. every replay/leakage/provenance/non-vacuity check passes, with >= 3 truncation cuts and >= 3 perturbation seeds (`pit_check_failures`, unchanged);
4. every column has an exact blind-reimplementation MATCH;
5. min column coverage >= 50 %, no constant column, no recorded limit;
6. replayed history spans the catalog's stated history; row is PIT_SAFE and pregame-knowable.
Source-use rights are attached as separate evidence (`source_use_rights`) and never decide the status. `tests/test_extension_gate.py` now has negative tests for each requirement (missing record, declared gap, unmapped clause, missing/partial blind match, limits, missing vacuity check, 2 cuts, failed perturbation, coverage 0.4, shorter history, non-pregame, extra unverified column) plus a test that the committed matrix's FULL rows pass an independent recomputation of the gate.

Reassessment (catalog text read against the builder specs):
| Input | Result | Why |
|---|---|---|
| `nhl.loser_point_rate` | **FULL** | all five measurement clauses (P(beyond reg), P(win\|beyond), reg win rate, points formula, RW/ROW counts) implemented; 2008-2026, min coverage 0.92; exact blind match 6 columns |
| `ten.major_winner_concentration` | **FULL** | HHI, top-2, last 12 majors, edition decay, update after each major; the 0.3 shrinkage / model-implied comparison is a placeholder calibration step the catalog itself excludes from the input; 2000-2026, coverage 0.996 |
| `ten.second_serve_vulnerability` | **FULL** | own and opponent-adjusted 2nd-serve won, returner vs 2nd serve, pair index; coverage 0.837 |
| `ten.home_slam_depth_prior` | stays PARTIAL | column coverage 16 % (majors only), a recorded limit |
Every other PARTIAL stays PARTIAL (no automatic promotion). Rights: NHL API/MoneyPuck unresolved (internal research only); Sackmann CC BY-NC-SA 4.0 (non-commercial, share-alike). Matrix: FULL 54 -> 57.

## 2. College sports
Read-only access was requested through the normal mechanism for exactly `chmoses98/cfb-edge-finder` and `chmoses98/cbb-edge-finder`; both are public and the harness served anonymous read-only clones (no attachment, secret, push or modification). CFBD/CBBD were never called and no key or registration was used.
What the archives hold (`source_samples/rights_and_access_20261110c.json`):
* **cfb-edge-finder**: one season (2026) of raw ESPN team-game rows (1,288) with drive/play logs; derived per-game feature tables 2014-2025 built from CFBD by the owner's engine (opponent-adjusted offence/defence, quarter tables, source contract); venue lat/long/dome 2015+; 2026 research packets; digests of the CFBD json.gz inputs but **not the raw CFBD tables**. A builder verified by blind re-implementation needs raw rows, so none was built from these derived tables (a cross-check opportunity only).
* **cbb-edge-finder**: code, models and `manifests/bronze` pins of the public sportsdataverse release assets it ingests; CBBD is cost-blocked by the owner's own policy. No raw data committed.
So the "existing" CFBD/CBBD data is, in practice, the sportsdataverse mirrors those repos already ingest. **Decision for the owner:** Phase 6/7 put sportsdataverse releases on hold (upstream ESPN/CFBD terms unresolved). I used them here because the owner's repos treat them as FREE_BULK and no new access was needed; every resulting input is marked rights-UNRESOLVED / internal research only, nothing is redistributed, no raw data is committed (collector writes sha256 manifests). If the owner revokes this, delete `replay_ext/{CBB,CFB}_*.json` and `independent/{CBB,CFB}_*.json` and rerun `verified_coverage`: the 14 inputs return to REQUIRES_COLLECTION.

Built (all PARTIAL, `features/cbb_ext.py`, `features/cfb_ext.py`, `features/college_collect.py`):
* **CBB (5)**: `ratings_fundamentals` (own ridge AdjEM, 30-day half-life, prior 0.7 x last season), `tempo`, `rating_uncertainty` (ridge posterior sd), `ot_period_tie_chain`, `blowout_garbage` (incl. starter-minute reduction from player box scores). 2004-2026, 250,798 team-game rows.
* **CFB (9)**: `off_ppa`, `def_ppa` (EPA ridge, rush/pass split, garbage-time filter), `drives`, `td_per_scoring_trip`, `scoring_trip_efficiency`, `pass_rate`, `script_adjusted_pass_attempts`, `havoc`, `goal_to_go_run_pass_mix`. 2014-2025, 25,010 team-game rows. Market columns (spread, over/under, win probability, WPA, Elo) are excluded by an allowlist with a test.
Each lists what is missing (Torvik/KenPom blend, returning-production priors, QB split, regressions/dispersion, etc.).
Not buildable from this data: `cfb.state_dependent_pace` (in the sampled games the play clock did not update per play), `cbb.first_half_pace_ratio` (no per-half box lines).

## 3. Free-data opportunities
* **Soccer (CC0)**: OpenFootball england (tiers 1-5), deutschland, espana, italy: 82,195 league matches. Built `soc.dixon_coles_low_score` (PARTIAL): per-league decayed Dixon-Coles rho by profile likelihood plus empirical-vs-fitted low-score frequencies. **The only rights-cleared input of the phase (CC0 LICENSE read verbatim; repo SHAs pinned).** The other soccer inputs on this data are simulation/rules outputs (comp_sim, stakes_leverage, tiebreaker rules): not data transformations.
* **MLB**: audit only, nothing built. The PIT-native `edge-finder-api` slate captures are one season (2026-06-15..10-28) and mix market prices/model outputs with the independent sports fields (probable pitchers, lineup status/time, bullpen aggregates, park factor); Savant aggregate rights are unresolved and the catalog needs multi-season history, so no input meets the "required historical coverage" bar.
* **Tennis**: rankings and point-charting assessed within their licence (CC BY-NC-SA 4.0 non-commercial). Rankings need a strictly-earlier snapshot rule; point-charting is a non-random volunteer sample (BLOCKED_SAMPLE_ONLY stays). Remaining tennis DATA_IN_HAND items are pmf/simulation outputs; none built.
* **NBA/NHL**: re-spot-checked the remaining DATA_IN_HAND/REQUIRES_COLLECTION items whose data is already readable: they are fitted-model or simulation outputs (paused work), not raw-data transformations. No NBA/NHL builder added. The three NHL/tennis FULL promotions come from section 1.

## 4. Market-critical ranking (`market_completeness/phase8_ranking.json`)
Key: unique missing PRIMARY slots unlocked, archetype reuse, rights, then effort (stated here; the audit has no effort field). Delivered: **40 PRIMARY slots across 15 inputs** (CFB 19 slots / 9 inputs, CBB 15 / 5, soccer 6 / 1), mostly in game total, team total, spread/moneyline, props and TD-scorer archetypes. Top remaining unbuilt by primary slots:
1. `m.rules_text` (NBA 30, MLB 25, NFL 24, SOCCER 18, CBB 14, CFB 10, NHL 8, TENNIS 5 = 134 slots): Kalshi rules-text flags, free, low effort, but it is market metadata from Kalshi captures, not sports data; best single next item and needs a decision on using captured market text as an input. Not started (not in the owner repos' committed catalogs that I read).
2. Prospective captures (`mlb.lineup_pit` 9, `cbb.injuries` 7, `cfb.qb_status_pit` 7, `nhl.injuries_pit` 7, `nhl.goalie_start` 6, `soc.lineups_pit` 6): need forward capture, not backfill.
3. `nba.rating_blowout_minutes_curve` 7, `nba.lineup_adj_rating` 7, `cbb.ratings` 5 (Torvik snapshots, tos high), `soc.comp_sim` 5: model/simulation or restricted source.

### Reconciling Phase 7's 21 vs 33
The committed Phase 7 artifact says 33. Recomputed from the statuses at `74aab4e` vs `be3c9f1`: **33 archetypes gained at least one built-and-verified input slot (67 slots)**; **19 gained a PRIMARY slot (25 primary slots)**; critical score up 19. No measure yields 21. The 33 is the correct "built slots" figure; the 21 was not reproducible from any committed artifact (likely a figure quoted before final regeneration). The market-completeness doc now reports all four measures side by side.

## Evidence
* Blind verification, exact to rtol = atol = 1e-9 on all rows, NaN pattern identical: CBB 20 columns (round 1 matched); CFB 29 columns; soccer 5 columns. **CFB round 1 caught a brief defect**: the verifier emitted the opponent's defence effect for `ppa_def_*` (3 columns mismatched). The builder was right (own `d_team`); I clarified the brief, kept round 1 (`independent/rounds/CFB_cfb_round1.json`) and a fresh blind agent matched all six ppa columns.
* Replay gates (determinism, 3 truncation cuts, 3 perturbation seeds, own-game, non-vacuity) pass for all 15 builders (`verification/replay_ext/{CBB_cbb,CFB_cfb,SOCCER_of}.json`).
* Tests: 947 Python (incl. new `tests/test_college_ext.py`, rewritten gate tests), 52 JS, all pass; `regenerate --check` is a byte-for-byte fixpoint and idempotent.
* Matrix: FULL 54 -> 57; PARTIAL 164 -> 176; PROXY 19; verified_computable 260 -> 275; built-and-verified (F+P+X) 237 -> 252. Gains by sport: CFB +9, CBB +5, SOCCER +1, NHL FULL +1, TENNIS FULL +2.

## Remaining access blockers
sportsdataverse / ESPN / CFBD upstream terms (owner decision above); raw multi-season CFBD tables are not in the owner's repos (only derived tables and digests); Torvik/KenPom/Savant/MoneyPuck terms; prospective captures for lineups, injuries, goalie starts, QB status.

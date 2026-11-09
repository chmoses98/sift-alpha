# Catalog-completeness acceptance report (RESEARCH_ONLY)

Round: blocker re-resolution on `claude/market-catalog-completeness-continue-b47pbb` (starting point c691f4b). Predictive experimentation remains PAUSED. Nothing here claims profitability, predictive validity, or human expert verification. Every review, audit and verification named below was done by Claude agents (**agent verification, not human expert verification**). The human decision lives in `approval.json` and has NOT been made.

## Acceptance-gate result (computed from the committed artifacts)
**`meets_criteria` = false.** Exactly one documented criterion fails: *no catalog blocker remains open* (64 of 65 resolved, **1 open: `NBA unreg:all_star_weekend_events#u10`**). All other criteria pass: 170 of 170 archetypes at the code's ceiling (ready for your approval), 4156 of 4156 ledger series assigned, 2610 in-scope series in existing archetypes, 1004 audited inputs for 952 review-added inputs, 1029 of 1029 declared gaps classified, 0 detached-input references. Because a blocker is open, the catalog is **not** being returned for approval.

## The 8 original blockers
| # | Blocker | Disposition | Evidence |
|---|---|---|---|
| 1 | NFL `season_awards#u7` (AP ballot model) | **Catalog change CONFIRMED** by independent audit; the factual claims stay unverified and are declared separately as `u7b` (SOURCE_UNVERIFIED, classified DATA_SOURCE_LIMITATION, non-blocking, open) | The model is now a ranked-points ballot parameterised by voters, places and points per award and season, each parameter's evidence status flagged; the old winner-rule/plurality text is gone. The ballot facts (50 voters, 10-5-3-2-1, Stafford 366 / Maye 361) were seen only in search-result copies: no AP page could be fetched. `evidence_zblk/NFL_u7_ap_ballot.json`. An earlier audit said STILL_OPEN; the later audit CONFIRMED because the split separates a verified catalog change from an evidence limitation. |
| 2 | NFL `unreg:team_and_event_counting_specials#u1` | **CONFIRMED** | Split into four archetypes with their own chains: team and both-team counts (6 series, kept), `score_path_functionals` (3), `rare_play_call_events` (2), `league_tie_and_long_kick_counts` (3), plus `team_window_event_hazards` (KXNFLNEXTINT, added after review judged it a survival process). Per-team and both-team counts remain merged by documented decision. |
| 3 | NBA `player_points#pp-bucket-mixing` | **CONFIRMED as a split** | KXNBABENCHPTS is out of `player_points`; both records reconciled. The original premise ("team-entity stat") was **not proven**: its terms file BASKETBALLENTITYSTAT.pdf is shared with player series and no market is listed. The entity question is preserved everywhere as unknown and carried once, in `game_overtime_and_team_events#u8` (UNVERIFIABLE_CONTRACT). `evidence_zblk/NBA_pp_bucket_kalshi_series.json`. |
| 4 | NBA `all_star_weekend_events#u10` (Shooting Stars) | **OPEN (by decision)** | Per-spot points, attempts per spot, and the advancement/final tie rules lack authoritative evidence: the official rules PDF (pr.nba.com) could not be reached from this environment. The format fields are labelled REPORTED (search relays) and the unknowns UNVERIFIED; the input refuses to simulate scores. The missing 2-point-spot input was added (`nba.shooting_stars_two_point_spot_skill`, NOT_COMPUTED). The blocker was not relabelled. |
| 5 | NBA `all_star_weekend_events#u8` | **CONFIRMED** | Split into skills contests (kept), `all_star_exhibition_games` and `all_star_game_mvp`; skills and exhibition re-homed to the off_field blueprint; unsuitable inherited blueprint inputs audited. |
| 6 | MLB `pitch_velocity_extremes#velo_kxmlbstat_scope` | **CONFIRMED** | KXMLBSTAT (11 Kalshi events: 3 velocity thresholds, 8 season feats) is filed under new `season_stat_feats` with an explicit `event_routing` of the three velocity events to the velocity archetype; the routing is now honoured by `completeness.ledger_by_archetype` and the evidence packs (regression tests added). `evidence_zblk/MLB_kxmlbstat_events.json`. |
| 7 | MLB `player_and_team_counting_specials#unr_mixed` | **CONFIRMED** | Split into postseason league counts (kept, re-homed to the `extras` blueprint), `player_home_run_exposure` and `pitcher_scoreless_innings_streak`. |
| 8 | Soccer `first_to_score_event#archetype_mismatch` | **CONFIRMED** | `first_to_score_event` holds only the 32 first-team-to-score series; 41 Method series are in `knockout_method_of_victory`; stale Method interactions removed; retired inputs no longer referenced. `evidence_zblk/SOCCER_ftts_mov_kalshi_series.json`. |

Counts changed legitimately: archetypes 161 -> 170 (NFL +4, NBA +2, MLB +3); catalog inputs 1636 -> 1648 (12 new inputs, all `NOT_COMPUTED` in `computable_inputs.json`); published interactions 1364 -> 1351 (stale interactions dropped).

## Newly discovered defects (this round)
* **Detached-input references (resolved).** 325 (archetype, input) pairs across 89 archetypes had interactions, non-linearities or stages naming inputs their archetype did not carry. A new gate criterion now fails on any such reference (0 today). Repair was a provenance-citing context attach (`archetype_patches/*_detached.json`) audited independently: 295 of 297 attaches judged sound, 2 corrected (dropped instead of attached).
* **Series mis-files (resolved on metadata only).** KXAFCCL2GAME (regulation match result) -> `match_result_3way`; KXWCFINALMATCHUP -> `tournament_bracket_composition`. Both have no listed market: the filings rest on Kalshi series metadata and are marked medium confidence.
* **KXWCWINMARGIN (open, declared).** Settlement unknown, not assumed to be a final margin; carried as `kxwcwinmargin_settlement_unknown`.
* **Routing tooling bug (fixed).** A velocity ledger row carried the primary row's `routed_away_events`; regression test added.
* **Blueprint inheritance.** Archetype patches could not change a blueprint, and inherited blueprint interactions could not be excluded: added `blueprint` patches and per-archetype `blueprint_exclusions` (published and shown on the dashboard).
* **`score_path_functionals#u5`** (no market-free score-state input) was declared a CATALOG_BLOCKER by the author, then addressed by a new market-free input (self-audited, independently reviewed) and reclassified EMPIRICAL_QUESTION.

## Remaining declared data limitations (not hidden)
* Primary sources unreachable from this environment: AP award pages, pr.nba.com / nba.com, Kalshi contract-terms PDFs (assets.kalshi.com), UEFA/other regulations, FBref and Sports Reference (12 knockout inputs carry a SOURCE_UNVERIFIED FBref note; about 35 other Soccer inputs still list FBref alongside other sources).
* KXMLBSTAT-26P105 has no retrievable market object; its wording is unverified (`sstat_p105_unretrievable`).
* The `pitch_velocity_extremes` archetype still inherits `player_pitch` blueprint interactions; all four are explicitly listed as not applicable.
* Most contract texts remain "partially verified": unstated overtime, postponement and tie handling are preserved as unknown.
* The research artifacts are agent-authored and agent-verified only.

## Proposed network allowlist (NOT applied; needs your approval)
Add exactly: `pr.nba.com` (2026 Shooting Stars rules PDF), `assets.kalshi.com` (contract-terms PDFs), `apnews.com` (AP award announcements and tallies) to the personal environment "Edgefinder" (limited network). With these, `u10` and `u7b` could be re-checked against primary sources.

## Verification process
Authors per sport -> independent reviewers (separate agents) -> fix rounds -> second verifiers -> closing re-audits; each REOPENED finding was sent back. Findings, verdicts and evidence are in `research/input_research/completeness/{independent,reverification,reconcile_audit,gap_resolution_audit}/*` (files suffixed `_zblk*` are this round). CI and iPhone WebKit results are reported against the final commit SHA in the hand-off message.

# Phase 11 capture workflows: root causes, inactive fixes (RESEARCH_ONLY, nothing activated)

Date 2026-11-11. Agent verification only. Extends `docs/PHASE10_METADATA_RIGHTS_AUDITS_BUILDS.md` section 3 and
`research/input_research/data_foundation/collector_audit/`; it does not restate those tables. Nothing was pushed, no workflow in this
repository was edited, no credential used. The capture workflows live in public sibling repos (`nba-edge-finder`, `nhl-edge-finder`,
`nfl-edge-finder`, `cbb-edge-finder`, `cfb-edge-finder`); I read them from anonymous blobless clones in the scratchpad (not from the
sift-alpha origin branches, which only hold `nba-starters-live-check.yml`, `nfl-prospective-ops.yml` and `cfb-availability-source-audit.yml`).

## Files
- `nba_starters_live_check_3min.diff` - against sift-alpha `origin/ci/nba-starters-live-20261104` (`git apply --check` OK in a temp worktree, removed).
- `nba_conductor_starter_refresh.diff` - against `chmoses98/nba-edge-finder` main `c6120ad` (`git apply --check` OK).
- `nhl_conductor_goalie_context_refresh.diff` - against `chmoses98/nhl-edge-finder` main `de1c36a` (`git apply --check` OK).
- `alpha_engine/capture_quality/` (inactive pure helpers) and `tests/test_phase11_capture_quality.py` (18 tests, pass), real samples in `samples/`.
- Existing Phase 10 diffs (CBB self-chain, CFB capture crons, NFL holiday slots) remain the proposed fixes for those streams; not duplicated.

## Cross-cutting root cause: GitHub cron is not a clock (measured, in the repos' own words and in our data)
- nba-edge-finder `capture_worker.yml` header: `*/10` conductor cron delivered 34 of 864 expected runs (3.9%); omission, not lateness.
- nfl-edge-finder `pit-availability-nfl.yml` header: 36% of capture cron events never created (2026-10-20..28), report-day ones 2.2-5.5 h late.
- cbb-edge-finder (measured here from `availability-archive` file names): cron `4,34` over 2026-11-01..11-10 delivered 37 captures in 10.4 days vs ~500 expected (about 7%); delivered runs started 1-26 min after the slot (uniform), and the gaps cluster at about 8 h.
- Concurrency: nba worker and conductor deliberately share group `conductor-archive` (one running, one pending; a third cancels the pending one) so writers never race; this is by design and not a cause of lost captures. `pit_injuries.yml` uses one `capture` group, `cancel-in-progress: false`, with a push-retry loop (4 tries, rebase). Branch push contention was therefore not evidenced: pit commits land 0.6 min (median) / 1.0 max after their stamp.
- Not visible: Actions run history. The GitHub API for these repos is blocked in this session (403), so skipped/cancelled run counts and run durations could NOT be measured. Statements about drops are inferred from archive gaps or from the repos' own measurements.

## NBA starters (proposed 3-minute cadence)
- Root cause 1 (measured): `conductor.decide` refreshes context when `age > STARTER_REFRESH_MIN (6.0)` inside 40 min of tip, but worker cycles are 300 s in the final tier, so age is 5.0 at the next cycle (skipped) and 10.0 at the one after. Archive gaps since 2026-11-06 show repeated 9.9-10.1 min steps (e.g. 11-08 00:40:48, 00:50:48, 01:00:49, 01:10:46). Zero in-window gaps were <= 7 min.
- Root cause 2: outside the 40 min window and in cycles where the worker is busy (capture up to 186 s plus serial simulate/settle jobs), gaps of 20-80 min occur (e.g. 11-10 01:05:40 to 01:37:30, 11-11 00:56:33 to 01:29:20).
- Earlier failure (sift-alpha `audit/nba-starters-production` lineage JSON): the 02:00Z game had no observation in its last 55 min because the scheduled conductor ran 81 min apart. The worker has replaced that path.
- Result after the worker plus fast window (Nov 6-11, 32 games, tips from the 10-day schedule snapshots): latest context capture before tip median 7.3 min, p90 19.8, 2 of 32 games over 30 min.
- 3 min is feasible in a dedicated loop, not in the worker cycle: the sift-alpha probe loop (`probe/nba-starters-live`) produced 60 captures with a 181 s median gap (max 186 s) on 2026-11-06, and 39 with 183 s on 11-04. ESPN published CONFIRMED starters only inside ~25 min of tip (probe coverage: 0-20 min 100% of teams, 20-30 min 33%, 30+ min 0%), so about 8 polls fall in the useful window.
- Fix: `nba_starters_live_check_3min.diff` (interval input default 3, lower bound 1, concurrency group so two dispatches never double the request rate) and `nba_conductor_starter_refresh.diff` (6.0 to 4.0 so every 5-min cycle refreshes; a true 3-min cadence inside the worker would need cycle < capture duration and is NOT proposed).
- Status: both need owner approval; neither applied. Approval needed: (a) merge to `chmoses98/nba-edge-finder` main (workflow dispatch resolves from default branch), (b) owner decision that a read-only 3-min poll of the ESPN core rosters is within the source terms (ESPN terms were unreachable in Phase 10; rights unresolved). No schedule trigger is added: a cron would be dropped as shown above; the loop is dispatched by the owner or by a clock lane.
- Limits: starters before 2026-11-06 are not in the archive (5 days); no publication timestamp in the payload; predictive value of starters unvalidated.

## NBA injuries (114/220 games with no capture within 30 min of tip)
- Root cause (measured): historical context cadence was the 55-min threshold (`last_context_age_min > 55`), observed median gap 60 min. With uniform phase, P(latest capture is more than 30 min before tip) is about (60-30)/60 = 50%; observed 114/220 = 52%. Same `context` job writes injuries and starters, so the 40-min fast window (added ~2026-11-05) also fixed injuries.
- After the fast window (same 32 games Nov 6-11, file stamps of `context/injuries`): 2 of 32 games over 30 min (vs 114/220 before), median 7.3 min.
- The separate `pit_injuries.yml` stream (hourly `41 * * * *`) commits only when something is new: 140 commits in 30 days (about 4/day) with median 301 min between commits. I cannot separate cron drops from "nothing new" without run history, so I do not claim a drop rate for it. Phase 10 proposed a 4-wakes/hour cron; with a documented 4-36% delivery rate for crons, more crons alone are a weak fix.
- Remaining defects not addressed by cadence: `game_id`/`nba_id` null in 100% of injury rows (join problem), official PDF `not_yet_submitted` teams (e.g. 7 on 2026-11-11 01:41Z) mean a capture can be fresh but empty for a team.
- Fix: covered by `nba_conductor_starter_refresh.diff` only marginally (cadence parity); the 114/220 problem was already largely fixed upstream. Status: no further change proposed.

## NHL goalies (pregame gaps, status history)
- Zero-capture games: 10 of 291 games (my recomputation from schedule snapshots reproduces Phase 10): all 10 are the 2026-11-03 ET evening slate (tips 00:00-01:00Z 11-04). Cause is one silence of 454 min (last capture 17:45Z by run 41671566505, next 01:20Z by run 41717134588), not a systematic gap. Why the worker was silent is not visible (no run logs).
- Cadence (measured): `PREGAME_FAST_REFRESH_MIN = 20.0` with strict `>` against 5/7/10-min cycles gives ~30 min effective; evening 2026-11-09 captures at 21:33, 22:08, 22:38, 23:08, 23:38. Since 2026-11-05: 45 games, latest capture median 17.2 min, 4 over 30 min, 11 over 20 min.
- Same constant also sets the simulate refresh; lowering it would rerun a 2400 s-budget job each cycle, so the diff adds a separate context-only constant (4.5).
- Status history: archived rows are snapshots (`status` PROJECTED/PROBABLE/CONFIRMED, `source_reported_at_utc` set for dailyfaceoff; 65% null overall per Phase 10). `history.build_status_history` / `diff_status_snapshots` produce FIRST_SEEN, STATUS_UPGRADE/DOWNGRADE and PLAYER_CHANGE events from the snapshots already archived. It is not wired in.
- `nhl_api_boxscore` rows are post-start actuals; `status.classify_lineup_status` labels them POSTGAME_ACTUAL (or UNKNOWN if observed pre-start) and only source-confirmed pre-start rows as VERIFIED_PREGAME. In the real sample 2026-11-09T22:38Z: 4 VERIFIED_PREGAME, 16 PROJECTED (includes PROBABLE).
- Fix: `nhl_conductor_goalie_context_refresh.diff`. Approval needed: merge to `chmoses98/nhl-edge-finder` main plus owner decision on NHL/DailyFaceoff rate and terms (unresolved; DailyFaceoff terms not read).
- Limits: whether DailyFaceoff changes between observations is not measured by cadence alone; no change-log history older than the archive (43 days).

## NFL injuries (coordination only, no new worker)
- sift-alpha `prospective-data` holds Kalshi book captures (`books`, `KXNFL*` series) and contracts/heartbeats; it contains no injury or QB payloads. Injury vintages are in nfl-edge-finder `pit-availability-nfl.yml` (primary trigger `pit-availability-clock.yml`, cron and watchdog as fallback, idempotent slot gate). Its release pin (`RELEASE.json` code_commit `d0d2a11`) was not touched and no competing worker was created.
- Observed on `prospective-data`: `ci/GHA_REFRESH_ENABLED` exists and `ci/GHA_CAPTURE_ENABLED` does not, so per the workflow header scheduled capture is gated off and captures there come from dispatch. I did not verify who dispatches them.
- Fix: Phase 10 `nfl_pit_holiday_slots.diff` stands (needs verification against the 2026 official schedule). `status.classify_lineup_status` treats generic ESPN "Active" QB rows as UNKNOWN and depth-chart rows as PROJECTED.
- Limits: nfl-edge-finder run history not visible; nflverse rights unresolved (WRAPPER_ONLY).

## CFB QB availability (verified starter vs projection)
- Only source is `pf_cfb_prior_game_passer` (PROJECTED, 100% of event-teams) plus stale ESPN injuries (Phase 10). No verified starter source exists in the archive; the pinned `cfb-availability-source-audit.yml` explicitly records `player_participation_completeness = NOT_ESTABLISHED`.
- Fix: classifier labels that source PROJECTED regardless of its status text "STARTING" (test `test_cfb_prior_game_passer_never_verified`), so downstream code cannot count it as a confirmed starter. Cadence fix is the Phase 10 `cfb_projection_foundation.diff` (capture-only crons; subject to the same cron-drop caveat).
- Limits: I did not locate any source that publishes a verified CFB QB before kickoff; none is claimed.

## CBB availability (empty/placeholder must not count)
- Measured on the latest capture (2026-11-10T19:40:51Z): 1,693 rows, all `available/Active/no_report` with null injury fields; raw `league_injuries.json` is `{"injuries": []}`. Phase 10's 46,481-row figure agrees.
- Cadence root cause (new): 37 captures in 10.4 days vs about 500 scheduled (about 7%), delivered 1-26 min late; consistent with cron drop, not a concurrency or push problem (no concurrency block fires since runs do not overlap). Run history not visible.
- Fix: `availability.classify_availability_capture` returns EMPTY_CAPTURE / EMPTY_SOURCE_PAYLOAD / PLACEHOLDER_ONLY / EVIDENCE_PRESENT; only the last is usable. Tested on the real capture (unusable, EMPTY_SOURCE_PAYLOAD). Phase 10's self-chain diff (`cbb_availability_capture.diff`) stands; chaining a 25-min sleep inside a job costs runner minutes and needs owner approval. Even a perfect cadence yields nothing while the ESPN injury feed is empty.

## What I could not verify
Actions run history (skipped, cancelled, queue delay, duration) for every repo; why specific worker runs went silent; third-party terms; any source of verified CFB starters; DailyFaceoff behaviour between polls; value of any of these inputs for prediction. Diffs were checked with `git apply --check` only; the sibling-repo test suites were not run.

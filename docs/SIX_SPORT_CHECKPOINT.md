# Six-sport data foundation: checkpoint (resume here)

Updated 2026-11-16 ~06:10Z (third session). Mission: complete, durable, independently verified game data, pregame
data and Kalshi official outcomes for MLB, CFB, CBB, NFL, NBA and NHL. RESEARCH_ONLY. Agent-run, not human verified.

## Official Kalshi results: NOT durably preserved

* Nothing survives between sessions: the earlier scratch copy was gone at start. No persistent mount, no connected
  computer folder, and every repository this session can reach is public (checked through the session's repo list).
* Re-fetched in full this session (about 45 minutes, unauthenticated): **1,996,986 contracts**, 166 series, both
  endpoints, 0 errors, 0 truncated, 0 read-back problems. Historical is unchanged at 1,344,479; live is 652,507.
* Packed and restore-tested in scratch: one 266 MB `.tar.gz` plus sha256 sidecar (`kalshi_official snapshot` /
  `restore`). **This copy dies with the session.** Protecting it is one copy command once a private destination exists.
* Fastest free private destinations (owner action, either one):
  1. Connect a local folder to cloud sessions (Claude desktop app: Settings, Claude Code, Remote Control). A session
     can then write the snapshot there and read it back.
  2. A private GitHub repository added to the session scope (`docs/KALSHI_OFFICIAL_ARCHIVE.md` section 4).

## PRs (verified at session start)
| Repo | PR | State | What |
|---|---|---|---|
| sift-alpha | #77, #78, #79 | merged | input development (separate mission, untouched) |
| sift-alpha | #80 | draft | completeness verifier (base) |
| sift-alpha | #81 | draft, stacked on #80 | official-results recovery, rules audit |
| sift-alpha | branch `claude/sift-alpha-six-sport-foundation-ro0xsn` | draft PR, stacked on #81 | this session (below) |
| edge-finder-api | #318 | draft | MLB linescore backfill tool |
| edge-finder-api | branch `claude/sift-alpha-six-sport-foundation-ro0xsn` | draft PR, stacked on #318 | MLB settlement regrade overlay |
| nba-edge-finder | #107 | draft | 2H includes OT (engine version not bumped: owner re-freeze) |
| nfl-edge-finder | #283 | draft | date-aware 2H overtime rule |
| nfl-edge-finder | #278 | merged | weather archive repair |
| NHL-edge-finder | #129 | draft | offline period scores |
| nba-edge-finder | #106 | draft | manual transactions collector |

## Done this session
1. **MLB: 920 archived settlements corrected by an overlay, every one confirmed by the exchange result.**
   `edge-finder-api/scripts/regrade_archived_settlements.py` re-runs the current engine on linescores. 902 August
   rows (total rungs, F5 total, F5 spread) plus 18 October rows from a new finding: two postponed postseason events
   (TB@CLE) were attached to each other's game. Linescore-family disagreements: 920 before, 0 after. The archive is
   not edited; readers call `apply_overlay()`. The 32 remaining MLB disagreements are hitter props.
2. **CFB and CBB now have an independent check** (`official_values.py`): the exchange's settled figure per event
   against owner-held CFB box scores and ESPN CBB scoreboards. CFB 12,027 figures agree, 9 differ (3 games);
   CBB 1,953 agree, 8 differ (6 games). Total ladders graded per contract: CFB 53,504 agree / 8 differ,
   CBB 11,473 / 0. Rung rule confirmed for both: ticker N pays YES when total >= N.
3. **CFB 2H rule confirmed on results**: 9 of 9 overtime games (2026-10-03 .. 10-31) settled 2H including overtime.
   `cfb-edge-finder research_packet/history.py` still uses Q3+Q4 only. A fix changes numbers in frozen packets
   (`test_derived_estimates` compares against them), so it is left as an owner decision.
4. **NHL: all 47 prop disagreements reviewed** (`prop_review.py`, league box score re-read). 45: the league still
   shows the engine's figure. 24 of those are saves contracts on 2026-09-29 that the exchange resolved No for every
   goalie. 1 league correction after the engine read, 1 changed but still different. No engine bug.
5. **NBA protected props measured** (`protected_props.py`): 40,267 agree with the engine's base-family result, 19
   differ; 2,438 resolved to a fair price, never when the engine's base result is YES.
6. Snapshot / restore commands with tests; cross-check evidence regenerated (NBA now 147 disagreements, 55,437
   exchange-settled contracts the engine leaves unsettleable).

## How to resume (cheap)
    python -m alpha_engine.game_completeness.kalshi_official fetch-scope --scope research/game_completeness/kalshi_official_scope.json --out OUT
    python -m alpha_engine.game_completeness.kalshi_official fetch-scope --historical --scope ... --out OUT_HIST
    python -m alpha_engine.game_completeness.kalshi_official snapshot --root live=OUT historical=OUT_HIST --archive X.tar.gz
    python -m alpha_engine.game_completeness.kalshi_official restore --archive X.tar.gz --dest EMPTY_DIR
    python -m alpha_engine.game_completeness.official_values CFB --official OUT/CFB OUT_HIST/CFB --cfb-season-dir ../cfb-edge-finder/data/football/2026 --as-of <ts> --out ...
    python -m alpha_engine.game_completeness.prop_review NHL --official OUT/NHL --computed 'DA/settlements/*/*.jsonl.gz' --cache C --as-of <ts> --out ...
    python -m alpha_engine.game_completeness.protected_props --official OUT/NBA --computed 'DA/settlements/*/*.jsonl.gz' --as-of <ts> --out ...
`DA` is a sparse checkout of a repo's `data-archive` branch (`settlements/` only). A failed series is retried by
re-running `fetch-scope`. If a snapshot exists in private storage, `restore` replaces the fetch.

## Decisions waiting on the owner
1. Private destination for the official results (above). Until then every session re-fetches or goes without.
2. MLB: adopt the regrade overlay in evaluation readers, and approve the 2022-2026 linescore backfill (#318).
3. CFB: 2H semantics in research packets (regenerates frozen packets).
4. NBA: settle-1.1 re-freeze (#107); whether to settle protected props YES-side from the box score.
5. CFBD exposure remedy (`docs/SPORTS_DATA_FOUNDATION.md`).
6. This container exposes cloud-credential environment variables. They were not read or used. If they are meant
   as storage for this project, say so.

## Next engineering (no approval needed)
* MLB: fix the event-to-game join for postponed games in `settle_markets` (use the exchange's "originally
  scheduled" date); the overlay only corrects the 2 known events.
* NBA prop disagreements (54): the NHL-style review needs an ESPN box-score reader in `prop_review.py`.
* CBB history: join 2025-26 official results (129,535 contracts) to sportsdataverse box scores.
* CFB: 183 events not joined (mostly FCS or differing abbreviations); a committed alias table would close it.
* NFL: recompute the cross-check (needs settle_v2 over the market-data archive; carried over unchanged here).

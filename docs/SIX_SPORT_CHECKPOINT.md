# Six-sport data foundation: checkpoint (resume here)

Updated 2026-11-16 ~03:00Z. Mission: complete, durable, independently verified game data, pregame data and Kalshi
official outcomes for MLB, CFB, CBB, NFL, NBA and NHL. RESEARCH_ONLY.

## PRs
| Repo | PR | State | What |
|---|---|---|---|
| sift-alpha | #80 | draft | completeness verifier (base) |
| sift-alpha | branch `claude/sift-alpha-six-sport-completeness-e4cpso` (stacked on #80) | draft PR | official-results recovery (live + historical), rules audit, evidence v2, this file |
| nba-edge-finder | #107 | draft | 2H includes OT. ENGINE_VERSION not bumped: it is in the frozen champion digest, so a bump needs an owner re-freeze. |
| nfl-edge-finder | #283 | draft | settle_v2 2H overtime rule is date-aware (Kalshi changed it 2026-09-14/17) |
| nfl-edge-finder | #278 | open, CI green at 913d485 | weather repair. Owner-approved merge conditions met: diagnostic run 286 read-back 24/25 forecasts; final commit only swapped `python -c` for an equivalent `jq` check plus test harness |
| NHL-edge-finder | #129 | draft | offline period scores 2008-2025 from archived shots: 22,924/23,227 VERIFIED vs finals, 25/25 spot-check vs NHL API |
| edge-finder-api | #318 | draft | manual MLB linescore backfill. Verified on 2026-09: 368 games, 3,272/3,272 official inning results agree |
| nba-edge-finder | #106 | draft (earlier) | manual transactions collector |

## How to resume the official-results work (cheap)
    python -m alpha_engine.game_completeness.kalshi_official fetch-scope --scope research/game_completeness/kalshi_official_scope.json --out OUT
    python -m alpha_engine.game_completeness.kalshi_official fetch-scope --historical --scope ... --out OUT_HIST
    python -m alpha_engine.game_completeness.kalshi_official verify --out OUT
    python -m alpha_engine.game_completeness.kalshi_official report --live OUT --historical OUT_HIST \
        --computed 'NBA=<nba data-archive>/settlements/*/*.jsonl.gz' 'NHL=...' --as-of <ts> --out research/game_completeness/kalshi_official_crosscheck.json
    python -m alpha_engine.game_completeness.kalshi_rules_audit OUT OUT_HIST
Resumable: a series is re-fetched only if its `.done` marker is missing. Scratch output does not survive a session.

## Decisions waiting on the owner
1. Archive destination for official results: a private repo is proposed (`docs/KALSHI_OFFICIAL_ARCHIVE.md` §4).
2. CFBD exposure remedy (`docs/SPORTS_DATA_FOUNDATION.md`, CFBD section).
3. MLB linescore backfill 2022-2026 (about 35 requests; StatsAPI bulk terms unverified) and its destination.
4. NBA settle-1.1 re-freeze; CFB research-packet 2H semantics (stale, feeds production packets).
5. Merge nfl #278.

## Local-only results (scratch; lost at session end unless approved for archiving)
* Kalshi official results: 1,991,343 contracts across 166 series, sha256 manifest, read-back verified.
* NBA 2026-27 play-by-play from the owner's own `scripts/pbp_backfill.py` (ESPN is reachable from this container):
  188/188 regular-season games, 94,431 events, 0 errors. Lineups certified for 142 games (75.5%; prior seasons
  ~90%). Re-fetch spot check 6/6 identical. To archive: dispatch `full_pbp.yml` with `seasons=2026-27` on a PR
  branch (owner approval: Actions dispatch).

## Next engineering (no approval needed)
* Join NFL / CBB / CFB computed settlements to the official results (NFL: kalshi-router settlement records; CFB/CBB: repo ledgers).
* NHL period scores from play-by-play; NBA 2026-27 play-by-play / stints from the source already used for 2024-26 (prepare, then ask before collecting).

# Sports data foundation: game-by-game completeness (RESEARCH_ONLY)

Agent-run, **not human verified**. No model trained or promoted, no schedule created or changed, no purchase, no
rights-tier change, no raw provider row committed. Complements the input-development work (#77 merged; #78, #79
open) and does not touch its files or the 1,649-input catalog.

## What exists

| Piece | Path | State |
|---|---|---|
| Classification engine (COMPLETE / PARTIAL / MISSING / STALE / UNVERIFIED / RIGHTS_BLOCKED) | `alpha_engine/game_completeness/{model,engine}.py` | code, tested |
| Adapters for MLB, NFL, NBA, NHL, CBB, CFB | `alpha_engine/game_completeness/adapters/` | code, run once against the archives as of 2026-11-15 |
| Join to the approved Market & Input Map (read-only) | `alpha_engine/game_completeness/impact.py` | code, tested |
| Evidence per sport: denominators, status counts per dataset and season, reasons, dependent inputs / markets | `research/game_completeness/<SPORT>/summary.json` | generated |
| Per-game ledger (one row per expected game, one status letter per dataset) | `research/game_completeness/<SPORT>/games.csv.gz` | generated, deterministic |
| Cross-sport tables: unrecoverable gaps, recoverable gaps, market-family data readiness | `docs/GAME_COMPLETENESS.md`, `research/game_completeness/overview.json` | generated |
| Kalshi official-result recovery and cross-check (manual, no schedule) | `alpha_engine/game_completeness/kalshi_official.py` | code, tested; run locally for NHL and NBA |

Rules the engine enforces: the denominator is expected games, not files found; only records that were parsed count
as COMPLETE; a file listing or manifest count is UNVERIFIED; a post-start observation is never accepted for a pregame
dataset; an absent record is MISSING, never zero; unplayed games are outside the denominator.

## How to run

Adapters read local directories only (they never fetch). Data branches are far too large to clone whole, so each
root is a sparse, blob-filtered checkout of just the directories the adapter names in its docstring:

    git clone --filter=blob:none --no-checkout --depth=1 --branch <data-branch> --sparse <repo-url> DIR
    git -C DIR sparse-checkout set --no-cone '<path>/' ... && git -C DIR checkout <data-branch>
    git -C DIR ls-tree -r --name-only HEAD > DIR/ARCHIVE_LISTING.txt        # where the adapter asks for it

    python -m alpha_engine.game_completeness.cli NHL --root nhl=../NHL-edge-finder --root nhl_da=DIR --root nhl_ref=REF
    python -m alpha_engine.game_completeness.report

`*_ref` roots hold the league's own schedule, used only as the expected-games denominator (MLB StatsAPI schedule,
nflverse `games.csv`, NHL api-web weekly schedule, ESPN scoreboard for NBA and CBB). Adapters need `pyarrow`.

## Denominators and their limits

| Sport | Expected games | Independent of the owner's archive? |
|---|---|---|
| MLB | 12,361 (2022-2026, regular + postseason) | yes: league schedule |
| NFL | 7,548 (1999-2026) | yes: nflverse schedule |
| NHL | 23,721 (2008-2026) | 2026-27 yes (377); 2008-2025 uses the owner's `games_<y>.parquet` |
| NBA | 4,159 (2023-24 .. 2026-27) | 2026-27 yes (197); earlier seasons use the owner's `team_games` parquet |
| CBB | 142,985 (2003 .. 2026-27) | sportsdataverse ESPN schedule; current season cross-checked against the ESPN scoreboard (30 finals not yet final upstream) |
| CFB | 11,265 (2014-2026, FBS-involved) | no: CFBD cache and the repo's ESPN schedule file |

Where the denominator is the owner's own file, a game absent from that file is invisible to this check.

## Findings that matter most

1. **Kalshi's own settlement result is not archived for MLB, NBA or NHL.** Those archives store settlements
   computed by each repo's engine; NBA and NHL market snapshots contain active markets only. The public API still
   serves results for recently settled markets, but the live listing for `KXMLBGAME` reached back only to
   2026-09-07 when sampled, so older results may already require Kalshi's historical tier (not verified).
2. **MLB is the thinnest archive.** No inning linescores anywhere (inning markets cannot be re-settled from the
   archive), hitter box scores for 54 games, pitch-level data for 643 of 2,469 games in 2026 (218 reconciled to
   box-score pitch counts), and the 2026 team / pitcher box caches stop at 2,004 / 2,029 games. Pregame starters,
   lineups and Kalshi quotes exist only from mid-season; no pregame weather vintage exists at all.
3. **NFL context capture has a 17-day hole** (no `data/context` day between 2026-10-28 and 2026-11-15), which is
   the incident nfl-edge-finder #278 repairs; 30 of 101 open-air 2026 games lack a usable kickoff forecast. #278
   is still open, so the fix is not on `main`.
4. **NFL, CBB and (for 2026 player-level data) CFB game / player / play data is not held durably by the owner.**
   NFL comes from nflverse at run time (gitignored); CBB commits only a manifest of sportsdataverse files. Content
   verified here against the upstream mirror is complete to the rates shown, but there is no owner-held copy.
5. **CFB has no player box and no play-by-play dataset on any branch**; 2026 advanced (EPA) stats are
   RIGHTS_BLOCKED pending the owner's CFBD authorisation.
6. **Current-season event data is missing for NBA** (no play-by-play, stints or shot file for 2026-27) and NHL has
   no per-shot xG for 2026-27 (MoneyPuck history ends at 2025-26).
7. **Pregame capture is late more often than absent.** CBB availability: 543 of 847 games have their newest
   pre-tip capture more than 2 h before tip; NBA starters exist for 68 of 189 games (capture began 2026-11-06).
8. **CBB half scores and NHL period scores are not stored for history** (CBB from 2026-11-07 only; NHL never as a
   field), although both are derivable from archived or re-fetchable event data.

Full numbers: `docs/GAME_COMPLETENESS.md`.

## Official settlement cross-check (local run, 2026-11-16)

Kalshi's own results were fetched with `kalshi_official.py` to a local directory (not archived on any branch) and
compared with each repo's computed settlements. Evidence: `research/game_completeness/kalshi_official_crosscheck.json`.

| Sport | Official contracts fetched | Computed YES/NO compared | Agree | Disagree | Computed UNSETTLEABLE that the exchange did settle |
|---|---|---|---|---|---|
| NHL | 80,280 (20 series, closes 2026-09-20 .. 11-15) | 70,576 | 70,529 | 47 | 1,565 of 2,897 |
| NBA | 122,360 (34 of 50 series, closes 2026-10-04 .. 11-15) | 112,337 | 112,206 | 131 | 3,007 of 5,201 |

* NHL disagreements are all player props: saves 29, points 9, assists 9. Cause not investigated; stat corrections
  after the box score was read are the obvious candidate.
* NBA disagreements cluster in second-half markets (2H total 66, 2H spread 21, 2H winner 6), which points at a
  semantics difference (for example overtime treatment) rather than noise; the rest are player props.
* 51,841 NBA computed contracts were not compared: 16 series were not fetched in this run.
* Every disagreeing ticker is listed in the evidence file so each engine's owner can check the rule.

## Not assessed in this pass

* Kalshi quote and order-book *content* for NBA and NHL (files listed on the branch, not read: UNVERIFIED).
* CFB pregame injuries / weather and CFB Kalshi contracts per game (Kalshi `game_key` is not yet joined to ESPN ids;
  693 of 695 game keys have a two-sided game-winner quote within 90 minutes of kickoff, summarised only).
* Kalshi contract-to-player identity matching, fees, and rules-text versioning.
* Independent certification of the Phase 8 CBB and CFB feature builders (this work verifies their source data, not
  the builders).

## CFBD exposure in the public cfb-edge-finder repository (facts only)

* Branch `research-data`, `data/research_cache/v2/**`: 219 gzip files, about 25.8 MB, raw CFBD API responses for
  2014-2026 (games, team box, drives, advanced stats, lines, ratings, talent, recruiting, portal).
* Same branch: `data/research/v2/*` (CFBD-derived feature tables) and, on `main`, per-game derived files under
  `data/research_inputs/` and `data/scripting/validation/`.
* The repository's own text says redistribution of raw API data is prohibited and that the licence is unresolved
  (`docs/DATA_SOURCES.md`, `scripts/research_export.py`, `src/cfb_edge_finder/scripting/cfbd.py`).
* Nothing was copied, re-published or removed. Removing data from a public branch does not remove it from git
  history or forks, so the remedy (private repository, history rewrite, or a licence that permits it) is an owner
  decision.

### CFBD exposure: metadata and proposed remedy (2026-11-16, metadata only, no blob content read)

* `data/research_cache/` exists on three branches: `research-data` (227 paths), `research-data-shard-migration-proof`
  (227) and `research-data-v2enrich` (6). It was introduced in 5 commits between 2026-08-28 and 2026-09-02. At the
  tip of `research-data` it holds 154 files, about 25.6 MB: per-season directories for 2014-2026, a per-season JSON
  for 2019 and 2021-2026, and `manifest.json` and `venues.json.gz`.
* The repository is public, with 0 forks and 0 stars (GitHub API). Zero forks means no fork copies to chase, but
  anyone could already have cloned it.
* The risk: the repository's own notes say redistribution of raw CFBD API output is prohibited and the licence is
  unresolved. Publishing it on a public branch is redistribution for as long as it stays reachable, and that
  includes history.
* Proposed remedy, in order. Each step is an owner action, and none has been taken.
  1. **Contain without rewriting history.** Make `cfb-edge-finder` private, or move the three branches to a private
     repository and delete them from the public one. Before doing this, check the readers: sift-alpha CI pins and
     reads public sibling archives, and the cfb script engine commits to this repository many times a day. Those
     jobs need a token or a new source first.
  2. If the repository must stay public, **rewrite history on the three branches only** (`git filter-repo --path
     data/research_cache --invert-paths`, then force-push). Then ask GitHub Support to purge cached views and dangling
     objects. Do this in coordination with the automated writers. Derived tables (`data/research/v2/*`,
     `data/research_inputs/`) need their own licence decision.
  3. Or **obtain written permission** from CFBD that covers redistribution. The cheapest route is if it is granted.
  4. Going forward, keep raw CFBD responses out of any public tree. The adapter already records CFB 2026 advanced
     stats as RIGHTS_BLOCKED.

## Update 2026-11-16 (continuation session)

See `docs/KALSHI_OFFICIAL_ARCHIVE.md` and `docs/SIX_SPORT_CHECKPOINT.md`. In short:
* Official results are recoverable well beyond the live window through the unauthenticated `/historical/markets`.
* NBA 2H and NFL 2H settlement bugs were found from Kalshi's own rules text and fixed in draft PRs (nba #107, nfl #283).
* MLB linescore backfill prepared and verified against 3,272 official inning results (edge-finder-api #318).
* nfl #278 meets the owner's recorded merge conditions.

## Update 2026-11-16 (third session)

See `docs/SIX_SPORT_CHECKPOINT.md`. In short: official results re-fetched (1,996,986 contracts) but still not in
durable storage; MLB archived settlements have a verified correction overlay (920 rows, edge-finder-api); CFB and
CBB are now checked against the exchange's settled figures (`official_values.py`); all 47 NHL prop disagreements
are explained without an engine bug (`prop_review.py`); NBA protected props agree with the engine's base-family
result in 40,267 of 40,286 binary settlements (`protected_props.py`).

## Backlog, in priority order

1. Capture Kalshi's official result at settlement for every sport (and backfill what the API still serves) before
   more of it leaves the live listing. Tool prepared; durable archiving needs an owner-approved destination.
2. Merge nfl-edge-finder #278 (owner decision; every week without it loses forecasts permanently).
3. MLB historical backfill from StatsAPI: linescores, hitter box, the missing 2026 team / pitcher box, pitch feed.
4. Read-back verification after publish for collectors that lack it (NBA / NHL capture worker, CBB capture
   workflows, MLB snapshot commits): the NFL incident pattern is present elsewhere.
5. Durable owner-held copies (or pinned hashes plus a mirror) of nflverse and sportsdataverse inputs, subject to
   their licences.
6. NBA 2026-27 play-by-play / shots / stints backfill from the source already used for 2024-26.
7. Earlier pregame capture for CBB availability; NBA transactions capture (nba-edge-finder #106, no schedule).
8. Join CFB Kalshi game keys to ESPN ids so CFB market completeness can be measured per game.

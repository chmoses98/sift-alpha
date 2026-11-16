# Kalshi official results: recovery, verification and archive proposal (RESEARCH_ONLY)

Agent-run, **not human verified**. Nothing here is archived on any branch yet. Official rows sit in a local
scratch directory of one session and are lost when that session ends, until the owner approves a destination
(section 4). Only counts, series names and contract identifiers are committed.

## 1. What changed in this pass

| Item | State |
|---|---|
| `kalshi_official.py`: `fetch-scope` (resumable, per-series `.done` marker, `manifest.json` with sha256, row count and close-date span), `verify` (re-hashes every file against the manifest), `report` (writes the evidence file) | code, 17 tests pass |
| **`/historical/markets` support.** Markets settled before the exchange's historical cutoff (`GET /historical/cutoff` → `market_settled_ts`, 2026-09-16 when read) leave the live listing. They are still served unauthenticated from `/historical/markets`. | code; verified live |
| Scope: `research/game_completeness/kalshi_official_scope.json`, 166 series in 6 sports (MLB, NBA and NHL: every series in the repo's computed archive; NFL, CBB and CFB: per-game series their code uses) | committed |
| `kalshi_rules_audit.py`: classifies every contract's rules text for its overtime / extra-innings clause | code |
| Evidence: `research/game_completeness/kalshi_official_crosscheck.json` (schema 2.0) | regenerated |

## 2. What was recovered (local scratch, read-back verified)

All 166 series were fetched from both endpoints, with no truncation, no errors and 0 read-back problems.

| Sport | Live contracts (close span) | Historical contracts (close span) |
|---|---|---|
| MLB | 125,288 (2026-09-06 .. 10-29) | 782,320 (2025-04-16 .. 2026-09-15) |
| NFL | 93,764 (2026-09-10 .. 11-16) | 74,786 (2025-08-01 .. 2026-09-15) |
| NBA | 181,083 (2026-10-04 .. 11-16) | 155,051 (2025-04-16 .. 2026-06-14) |
| NHL | 80,345 (2026-09-20 .. 11-16) | 149,794 (2025-04-20 .. 2026-06-15) |
| CBB | 25,091 (2026-11-01 .. 11-16) | 129,535 (2025-11-03 .. 2026-04-07) |
| CFB | 141,293 (2026-09-05 .. 11-15) | 52,993 (2025-08-23 .. 2026-09-13) |
| **Total** | **646,864** | **1,344,479** |

Rights note: the rows are Kalshi Data. See `docs/KALSHI_RIGHTS_IMPACT_AUDIT.md`. DA §3.1 limits storing it, except to
facilitate the member's own trading, and prohibits sharing it.

## 3. Findings from the official results

### 3a. Engine vs exchange disagreements

| Sport | Compared YES/NO | Agree | Disagree | Computed UNSETTLEABLE that the exchange settled |
|---|---|---|---|---|
| MLB (edgelab settlements, 21 series) | 245,218 | 244,266 | 952 | 6,318 |
| NBA (all 50 computed series) | 113,525 | 113,394 | 131 | **52,648** |
| NHL (20 series) | 70,576 | 70,529 | 47 | 1,565 |
| NFL (settle_v2 on market-data, 63 games) | 32,892 | 32,879 | 13 | 2 |

* **MLB: 914 of the 952 disagreements are stale August 2026 records.** In KXMLBTOTAL, F5TOTAL and F5SPREAD, the
  engine of that time read the ticker strike N as "more than N", where the rule says "more than N - 0.5". For example,
  a total of 6 against "more than 5.5" was recorded NO. That August slice (8,838 contracts) is about 10% wrong.
  September has 0 disagreements, so the code was fixed later. The archived rows were never corrected, and any
  evaluation over August totals inherits the error. The official results correct it.
* **NFL: all 13 disagreements are 2H contracts in two overtime games on 2026-09-20.** GB@NYJ was 17-17 after
  regulation: the engine's 2H total was 20 and Kalshi's was 23. This is the rule change in 3b, and nfl #283 fixes it.

* **NBA 2H: root cause found and fixed (nba-edge-finder #107, draft).** Kalshi's rule is "2nd half (including
  overtime)", but the engine summed only Q3 and Q4. All 93 2H disagreements are in overtime games, and there are
  0 in regulation games. Overtime games were identified independently from Kalshi's own `KXNBAOT` results: 11 of
  194 games. 4Q markets say "excluding overtime", and the engine already agrees with them.
* **NBA, 52,648 recoverable labels.** The engine marks whole families UNSETTLEABLE ("semantics not proven"):
  `*PROT` player props, `TOTALPRECISE`, `PTSLEADER`, `WINMARGIN`, `STOCK`, `RACE`. The exchange settled them. An
  official archive turns these into usable evaluation labels without guessing the semantics.
* **NBA and NHL player props (the other 38 NBA and all 47 NHL disagreements) are a source or timing difference,
  not an engine bug.** Three NHL cases were checked against the current NHL boxscore:
  * Ersson: the engine read 23 saves, and the NHL now says 24. This is a stat correction after settlement.
  * Saros: the engine read 25, the NHL now says 24, and Kalshi says 26.
  * Shea: the NHL says 1 assist and Kalshi says 0.

  Kalshi's stats source differs from the league boxscore at about 0.07%. For player props the official result
  has to be the label. A computed result is a proxy.

### 3b. Settlement-rule audit across sports (`kalshi_rules_audit`)

| Market | Rule text | Engine |
|---|---|---|
| NBA 2H | including OT (always) | excluded OT; **fixed in nba #107** |
| NBA / NFL / CFB 4Q | excluding OT | correct |
| **NFL 2H** | excluding OT for games through 2026-09-13, **including OT from 2026-09-17**, both texts on 09-14 | always excluded; **fixed in nfl #283** (settle_v2, date-aware, refuses 09-14 OT games) |
| **CFB 2H** | excluding OT through 2026-09-07, **including OT from 2026-09-17** | `research_packet/history.py` states "Kalshi's 2H markets settle on the same" as Q3+Q4. That is stale, but not changed here, because it feeds production packets (owner decision). |
| CBB 2H | including OT | correct (`cbb_edge/kalshi/semantics.py`) |
| MLB inning markets | no extra-innings clause | n/a (F3 / F5 / F7 / RFI verified against linescores, below) |

The rule changed in the middle of the season. Settlement semantics therefore have to come from each contract's
own rules text, or from a dated rule table. One constant per market family is not enough.

### 3c. MLB inning results reproducible from linescores

edge-finder-api #318 (draft) adds a manual linescore backfill. On a bounded test (2026-09, 368 games), all 3,272
official F3 / F5 / F7 / RFI results agree with the linescore, and 0 disagree.

## 4. Proposed durable destination (owner approval needed; nothing published)

All seven in-scope repositories are **public** (checked through the GitHub API on 2026-11-16). No cloud credentials
exist in this environment. The session was refused access to `kalshi-bet-router`, so its visibility is unknown.

**Recommendation: a new private GitHub repository**, for example `chmoses98/sift-kalshi-official`, created by the
owner and added to the session's repository scope.

| Aspect | Proposal |
|---|---|
| Access | Private, owner only. Public CI never reads it. Public repos receive counts, identifiers and sha256 only. |
| Layout | `<SPORT>/<series>.jsonl.gz` (live) and `<SPORT>/<series>__historical.jsonl.gz`; `<SPORT>/<series>[__historical].rules.json.gz`; `manifest.json` (per file: rows, sha256, close span, retrieval time, endpoint) |
| Row fields | ticker, event_ticker, status, result, expiration_value, settlement_value_dollars, close_time, settlement_ts, rules_sha256, `_retrieved_at_utc`, `_source`. No prices or order book. |
| Size | Measured on the rows fetched so far, gzipped: about 60 bytes per contract for rows, plus about the same for rules text. The rules text is unique per contract, because it names the player, threshold and date. Expected total for full history: a few hundred MB, with every file under 100 MB, so no LFS is needed. |
| Cost | $0 (private repo, no LFS, no Actions minutes needed: the publish is a manual push) |
| Provenance | Each row carries its retrieval timestamp and endpoint. The manifest hash is checked after push by a fresh clone and `kalshi_official verify`. |
| Compatibility | `compare` and `report` read a local clone directly. Adapters stay unchanged. |
| Updates | Manual re-runs of `fetch-scope` (resumable). A recurring capture would be a separate, later approval. |
| Option | Store `rules_sha256` only and drop the rules text, which halves the size and minimises stored Kalshi Data. **Not recommended**: the rules text is what exposed the NFL / CFB / NBA overtime rules. |

Rejected:
* A branch, release asset or Actions artifact on any of the public repos. That is redistribution under DA §3.1,
  and artifacts expire.
* A cloud bucket. No credentials or billing exist, so it would be new paid infrastructure.
* `kalshi-bet-router`. It may fit best, because it is the owner's own-trading repo, but this session could not
  verify that it is private.

Private storage reduces the redistribution risk. It does not settle whether research storage counts as
"facilitating own trading" (audit item 1, counsel and owner).

## 5. Remaining gaps

* CBB and CFB settle at evaluation time and keep no computed-settlement archive to join. Their official results
  are recovered (above), but not cross-checked.
* A durable archive of anything listed above still needs the section 4 approval.

## 6. Third session, 2026-11-16: storage check, full re-fetch, snapshot, new checks

**Durability: none yet.** The scratch copy from section 2 did not survive. This session found no persistent mount,
no connected computer folder and only public repositories. The results were fetched again and still exist only in
session scratch.

| Sport | Live contracts (close span) | Historical contracts (close span) |
|---|---|---|
| MLB | 125,288 (2026-09-06 .. 10-29) | 782,320 (2025-04-16 .. 2026-09-15) |
| NFL | 94,421 (2026-09-10 .. 11-16) | 74,786 (2025-08-01 .. 2026-09-15) |
| NBA | 184,615 (2026-10-04 .. 11-16) | 155,051 (2025-04-16 .. 2026-06-14) |
| NHL | 81,558 (2026-09-20 .. 11-16) | 149,794 (2025-04-20 .. 2026-06-15) |
| CBB | 25,277 (2026-11-01 .. 11-16) | 129,535 (2025-11-03 .. 2026-04-07) |
| CFB | 141,348 (2026-09-05 .. 11-16) | 52,993 (2025-08-23 .. 2026-09-13) |
| **Total** | **652,507** | **1,344,479** |

* Cost of a full recovery: about 45 minutes, about 2,000 unauthenticated requests, one transient failure that the
  resumable `fetch-scope` retried. The historical set is identical in size to the previous session's.
* `kalshi_official snapshot` packs both folders into one deterministic `.tar.gz` (266 MB for this run) with a
  sha256 sidecar. It refuses a folder that fails read-back. `kalshi_official restore` checks the archive hash,
  unpacks into an empty folder and re-hashes every series file. The round trip passed in scratch: 332 series files,
  1,996,986 rows, 0 problems. A copy counts as protected only after `restore` passes on bytes read back from the
  destination.
* `expiration_value` on a settled row is the figure the exchange settled on (total, margin, winner, per-team
  points, overtime count). It can be a lower bound ("at least 28") when a market settled early, and for CBB half
  winners it is an internal id. `official_values.py` uses it for the CFB / CBB checks in
  `research/game_completeness/official_values_{CFB,CBB}.json`.
* Value differences that do not change any contract: in 6 CBB games the exchange's total or margin differs from
  ESPN's final by 1 or 2 points, yet all 11,473 total-ladder contracts grade the same. Read `expiration_value` as
  "the figure at settlement", not as a box score.
* Exchange-side anomalies found: CFB WKU@MTSU 2026-11-07 (exchange total 87 and margin 3, ESPN 51-42);
  NHL 2026-09-29, where 24 saves contracts for 7 goalies resolved No although each goalie reached the line.
  For these the official result is the label and a computed result is wrong by construction.

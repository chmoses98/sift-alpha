# SIFT Alpha unified checkpoint (resume here)

Updated 2026-11-16 ~19:30Z (Phase 11 settlement-integrity session; section 0 is the newest). RESEARCH_ONLY. Agent-run, not human verified.
This file supersedes `docs/SIX_SPORT_CHECKPOINT.md` (workstream B) and the "Next steps" of
`docs/PHASE10_DATA_PRESERVATION.md` (workstream A) as the place to resume. Both remain as historical records.

## 0. Latest session (2026-11-16, settlement integrity) - read this first

All new work is on branch `claude/fable-phase-11-settlement-p9pm9t` in each repo, as draft PRs stacked on the earlier ones.

| Repo | New draft PR | Stacked on | What |
|---|---|---|---|
| nfl-edge-finder | **#286** | #285 | `nfl-settlement-overlay-1.0.0`: 728 week-wins contracts (116,480 rows) recomputed on 2026. 668 settled, 668 of 668 agree with the exchange, 122 flips, 60 pending. Not activated. |
| nba-edge-finder | **#110** | #109 | `NBA_BASELINE_2026_PRESEASON_V2` prepared beside V1 (digest `2a05589f...`). V1 digest unchanged and V1 prices 2H as frozen again; `ACTIVE_BASELINE_ID` is V1. |
| edge-finder-api | **#320** | #319 | Reschedule-aware event-to-game rule + 2026 audit. Derives both ALCS overrides from the schedule; no other postponement mismatch. Not wired into ingest. |
| sift-alpha | this branch's PR | #84 | NFL overlay dialect in `settlement_reconcile`; first MLB dataset certified; this checkpoint. |

Findings that change earlier notes:
* The 728 NFL contracts are `26W4`, `26W8` and `26W12` (not only W12). W4 and W8 are final; 60 W12 contracts stay pending
  until week 12 is final (2026-11-30). Then rerun `scripts/research/build_settlement_overlay.py` with a new `--as-of`
  (writes a second overlay file; never overwrite the first).
* NFL with the overlay: 135 disagreements -> 13, none introduced (`research/settlement_reconcile/NFL_with_overlay.json`).
  The 13 are the 2H overtime contracts fixed by #283.
* MLB postponements: "use the originally scheduled date" (old section 7 item 2) is WRONG for the postseason. The exchange
  follows the series game number, not the gamePk. Regular season: same gamePk follows to the makeup. Rule and evidence in #320.
* MLB dataset v1: 12,148 regular-season games 2022-2026, 22 pregame features (team run form, starter form), sha
  `f598384b...`. Blind re-implementation identical on 12,148 x 35; truncation and future-scramble leakage checks pass.
  Evidence `research/certification/certification_mlb_v1.json`, spec `docs/certification/MLB_FEATURE_SPEC.md`.
  Registered in `dataset_versions.json` with `training_ready: false`: its inputs are NOT yet in the acquisition catalog,
  so the training-ready count is still 48.
* #84 integration check: #80-#83 heads are all ancestors of #84; all 59 files of #83 are byte-identical; the only files
  that differ from #82 are the four Phase 11 edits. Full suite 1,656 passed locally on the #84 head; merges cleanly into main.

CI at the time of writing: NFL #285 pytest passed. NBA #109 `test` passed, `pf-injury-correctness` queued (runner backlog).
Alpha #84 `research-desk` passed, `test` running, `e2e` and `dashboard` queued. Re-read with one `get_check_runs` call per PR.

Cheap resume for this session's tools (scratch is gone; restore from the vault):

    python scripts/research/build_settlement_overlay.py --settlements <nfl market-data>/data/shadow/v2/settlements --schedule-csv <nflverse games.csv> --as-of <ts> --official <vault NFL>/KXNFLWINSWEEK.live.jsonl --out research/settlement_overlay   # nfl-edge-finder
    python scripts/edgelab/audit_reschedule_identity.py --start 2026-08-01 --end 2026-11-05 --out <file>                                                # edge-finder-api, one public schedule request
    python -m alpha_engine.certify.mlb_game_v1 --feed-root <restored MLB postgame_feed_compact, one dir per season> --out mlb.parquet --evidence ev.json   # ~1 min

## 1. What is unified

Branch `claude/sift-alpha-phase-11-unify-yd8246` = `main` + PR #83 (Phase 10) + PR #82 (which contains #80 and #81).
The two workstreams share **no file**; the merge is conflict-free and the full suite passes on the merged tree
(1,645 passed before the Phase 11 additions). Nothing from either side was dropped or rewritten.

| Repo | PR | State | Role after unification |
|---|---|---|---|
| sift-alpha | #77, #78, #79 | merged | unchanged |
| sift-alpha | **#84** (this branch) | draft | **the one to review and merge**; contains #80-#83 |
| sift-alpha | #80, #81, #82, #83 | draft | superseded by the integration PR once it merges; close them then, not before |
| nba-edge-finder | #108 | draft | preferred 2H overtime repair |
| nba-edge-finder | #107 | draft | superseded by #108 (its tests pass unmodified on #108's code); close after #108 merges |
| nba-edge-finder | #109 (stacked on #108) | draft | offline re-verification from the vault, 108 of 108 |
| nfl-edge-finder | #283 | draft | date-aware 2H overtime rule (keep) |
| nfl-edge-finder | #285 (stacked on #283) | draft | week-ticker season fix (new defect, section 3) |
| edge-finder-api | #318 -> #319 | draft, stacked | linescore backfill tool, then the 920-row correction overlay (keep both) |
| NHL-edge-finder | #129 | draft | offline period scores (keep) |

Recommended merge order (owner action, nothing merged by an agent):
1. sift-alpha #84, then this branch's PR (docs, evidence, research tooling only; no production path). Close #80-#83.
2. edge-finder-api #318, #319, #320. 3. NHL #129. 4. NFL #283, #285, #286.
5. NBA #108, #109, #110 together (with #110, V1 stays intact, so no baseline decision blocks the merge); close #107.
Each stacked PR targets its parent's branch: merge parents first, or retarget the child to main after the parent merges.

## 2. Official vs computed settlements (all six sports)

Tool: `alpha_engine.game_completeness.settlement_reconcile` (reads the vault's `kalshi_official_settlements` archives
restored locally; about one minute for 2.19M official rows). Evidence: `research/settlement_reconcile/`.
Layers are never merged: official (vault), computed (sport repo archive), computed + versioned overlay.
Official rows are classed before comparison; administrative, fair-price and void settlements are never judged.

| Sport | Official contracts (unique) | Nonstandard | Computed | Agree | Disagree | Engine unsettled, exchange settled |
|---|---|---|---|---|---|---|
| MLB | 899,625 | 15,003 | 255,097 | 244,262 | 952 (32 after the #319 overlay) | 6,318 |
| NFL | 293,248 | 7,555 | 38,409 | 37,247 | 135 | 300 |
| NBA | 351,286 | 10,601 | 178,693 | 116,723 | 147 (39 after #108) | 55,920 |
| NHL | 232,387 | 4,323 | 73,477 | 70,406 | 24 | 1,565 |
| CFB | 186,087 | 1,656 | no computed archive | independent check below | | |
| CBB | 161,555 | 368 | no computed archive | independent check below | | |

Row counts in the Phase 10 report (2,191,994) count a contract twice when both API tiers serve it (MLB 39,327,
CFB 14,371, NFL 14,108); the two tiers never disagree on a result.

* **MLB**: the #319 overlay fixes exactly 920 of 952 and introduces none. The 32 left are hitter props
  (HRR 13, HIT 9, RBI 5, TB 3, SB 2), not yet reviewed against a box score.
* **NBA**: 108 are 2H contracts in overtime games (93 known + 15 since); #108 turns all 108 into agreements,
  keeps the side of 332 other overtime-game 2H contracts and leaves 7,430 non-overtime contracts unchanged
  (nba-edge-finder `research/settlement_2h_overtime/phase11_20261116/`). 39 props remain: 32 exchange differs from
  the box score, 6 stat corrections, 1 new and unreviewed. Protected-prop findings: `research/game_completeness/protected_props_NBA.json`.
* **NHL**: of the 47 researched disagreements, 23 saves contracts are administrative settlements (literal "No",
  never traded) and are now bucketed as nonstandard instead of disagreements. The other 24 keep their researched
  causes (22 exchange differs from the league box score, 1 stat correction, 1 traded saves contract). No engine defect.
* **NFL (new defect)**: 122 of the 135 are `KXNFLWINSWEEK-26W12-*`. Every one of the 116,480 projection rows for
  these 728 contracts was stamped season 2025 and settled on 2026-09-18 against the finished 2025 season. Fixed
  fail-closed in nfl-edge-finder #285; the wrong rows in the append-only corpus are not rewritten (owner decision).
  The other 13 are the known 2H overtime contracts fixed by #283.
* **CFB / CBB independent check** (`official_values`, now reading vault box scores): CFB 2,057 of 2,403 events joined,
  12,192 settled figures agree, 9 differ; total ladders 55,201 agree, 8 differ. CBB went from 655 to 5,983 events:
  4,936 joined, 10,342 figures agree, 54 differ; ladders 43,562 agree, 1 differs.
  **Rule finding**: in the 2025 seasons a total rung `N` meant "over N" (strike N + 0.5); in 2026 it means "N or more"
  (strike N - 0.5). Ladders are now graded on the exchange's stated strike, never on the ticker number.
  CFB 2H in overtime games (2026-10-03 .. 10-31): 20 settled figures match only the including-overtime reading, 7 match either, none match regulation only.

Historical evaluations that would change if official results became the label: MLB 952 flips (920 already covered by
the overlay) and 6,318 new labels; NFL 135 flips and 300 new labels; NBA 147 flips and 55,920 new labels;
NHL 24 flips and 1,565 new labels. Ticker lists are in `research/settlement_reconcile/<SPORT>.json`.

## 3. Completeness against the vault

Tool: `alpha_engine.game_completeness.vault_overlay`. Evidence: `research/game_completeness_vault/`.
It re-reads the #80 per-game ledger and upgrades a cell only where the vault record for that game was parsed and
passed a content check (tier `VAULT_VERIFIED`); the original ledger is untouched, nothing is downgraded.

| Sport | Dataset | Complete before | Complete after | Still missing |
|---|---|---|---|---|
| MLB | inning linescore / hitter box / pitch events | 0 / 54 / 218 | 12,359 each | 0 |
| MLB | team box / pitcher box | 11,723 / 11,919 | 12,359 each | 0 |
| NHL | period scores | 0 | 7,318 | 0 |
| CFB | player box / play-by-play | 0 / 0 | 11,122 / 10,953 | 2 / 171 |
| CBB | half scores | 824 | 25,904 | 74,944 |
| CBB | team box | 126,220 | 126,342 | 11,353 |
| MLB / NBA / NHL | official exchange result per game | 0 | 705 / 189 / 325 | MLB 1,764 |

Audit fix: the CBB adapter no longer counts a zero-filled team box as complete (`adapters/cbb.py`). The committed
#80 CBB ledger was not regenerated (needs the CBB archives); regenerate it before quoting CBB team-box totals.
Not yet in the overlay: NBA and NFL postgame archives, CBB player boxes, pregame vintages (prospective only).

## 4. Inputs

Training-ready inputs: **48** (unchanged this session; 41 -> 48 came from #83 and is now on the integration branch).
Model-active: 0. MLB: dataset v1 certified (section 0) but its 22 features are not yet catalogued as inputs, so MLB training-ready inputs are still 0.

## 5. How to resume (cheap)

    S=<scratch>; cd sift-data-vault
    for s in MLB CFB CBB NFL NBA NHL; do python tools/vault.py restore --path archives/$s/kalshi_official_settlements/all-to-20261116/kalshi_public_api/snapshot-20261116 --to $S/official/$s; done
    # computed archives: sparse, blobless checkouts of each data branch (settlements only)
    #   nba-edge-finder data-archive: settlements/ boxscores/     NHL-edge-finder data-archive: settlements/
    #   nfl-edge-finder market-data: data/shadow/v2/settlements/  edge-finder-api main: data/edgelab/settlements/
    python -m alpha_engine.game_completeness.settlement_reconcile --official-root $S/official --as-of <ts> --out research/settlement_reconcile \
        --computed MLB=... NBA=... NHL=... NFL=... --overlay MLB=<#319 corrections.json> \
        --known research/settlement_discrepancies/nhl_nba_20261116.json research/game_completeness/prop_review_NHL.json
    python -m alpha_engine.game_completeness.official_values CFB --official $S/official/CFB/CFB --cfb-season-dir ../cfb-edge-finder/data/football/2026 --espn-summaries <restored CFB espn_summary_postgame dirs> --as-of <ts> --out ...
    python -m alpha_engine.game_completeness.official_values CBB --official $S/official/CBB/CBB --sdv-schedules <restored CBB espn_team_box_schedules> --as-of <ts> --out ...
    python -m alpha_engine.game_completeness.vault_overlay --as-of <ts> --out research/game_completeness_vault --mlb-feed ... --nhl-scores ... --cfb-summaries ... --cbb-schedules ... --cbb-recovered ... --official-root $S/official --computed MLB=... NBA=... NHL=...

Do not re-download Kalshi results: the vault snapshot is the record. A newer pull is a new dated snapshot.

## 6. Owner decisions

1. Merge order in section 1 (start with the sift-alpha integration PR).
2. NBA: V2 is minted beside V1 in #110 and is not active. Decision: activate V2 (one line, own PR, with a before / after
   2H evaluation) or stay on V1.
3. NFL: the overlay for the 728 wrongly settled week-wins contracts is prepared in #286. Decision: adopt it in
   evaluation readers.
3b. MLB: wire the reschedule rule (#320) into ingest. Production-path change; season is over, no exposure until spring.
4. MLB: adopt the #319 overlay in evaluation readers; approve the 2022-2026 linescore backfill (#318).
5. CFB: 2H including overtime in research packets (changes frozen packet numbers).
6. CFBD raw responses on three public cfb-edge-finder branches: remedy in `docs/SPORTS_DATA_FOUNDATION.md`. The cache
   is now preserved and restore-tested in the private vault, so removal loses nothing.
7. Kalshi / MLB / ESPN storage rights: unchanged, private internal research only.

## 7. Next engineering (no approval needed)

1. **MLB inputs (highest value)**: catalogue the 22 certified MLB features as inputs (acquisition catalog + phase
   progress), so training-ready goes 48 -> 70 with MLB no longer at zero. Then add bullpen, lineup and park inputs as v2.
2. After 2026-11-30: second NFL overlay snapshot to settle the 60 pending W12 contracts (command in section 0).
3. Review the 32 MLB hitter-prop and 1 new NBA prop disagreements against vault box scores (`prop_review` needs MLB
   and ESPN readers).
4. CFB alias table for the 346 unjoined events; CBB join for the 1,047 unjoined events.
5. Add NBA and NFL vault archives to `vault_overlay`; regenerate the CBB ledger with the zero-box fix.
6. Register NBA (through 2026-11-15) and CBB (122 recovered boxes) dataset versions; CFB v3 only with independent
   evidence for the drive-scoring flag.

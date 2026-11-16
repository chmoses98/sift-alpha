# SIFT Alpha unified checkpoint (resume here)

Updated 2026-11-16 ~20:00Z (Phase 11 unification session). RESEARCH_ONLY. Agent-run, not human verified.
This file supersedes `docs/SIX_SPORT_CHECKPOINT.md` (workstream B) and the "Next steps" of
`docs/PHASE10_DATA_PRESERVATION.md` (workstream A) as the place to resume. Both remain as historical records.

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
1. sift-alpha #84 (docs, evidence, research tooling only; no production path).
2. edge-finder-api #318, then #319. 3. NHL #129. 4. NFL #283, then #285.
5. NBA #108 after the baseline decision below, then #109; close #107.

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
Model-active: 0. No MLB input is certified yet; the MLB postgame records it needs are now verified per game (section 3).

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
2. NBA: approve a versioned corrected baseline. #108 pins the frozen preseason baseline to `settle-1.0` so its digest is
   unchanged; recommended: mint `NBA_BASELINE_2026_PRESEASON_V2` (2H priced including overtime) beside V1, publish
   before / after 2H evaluation, switch only on approval. Until then nothing is activated.
3. NFL: invalidate the 728 wrongly settled `KXNFLWINSWEEK-26W12` contracts (new settlement version or an overlay);
   the corpus is append-only so this is not done silently.
4. MLB: adopt the #319 overlay in evaluation readers; approve the 2022-2026 linescore backfill (#318).
5. CFB: 2H including overtime in research packets (changes frozen packet numbers).
6. CFBD raw responses on three public cfb-edge-finder branches: remedy in `docs/SPORTS_DATA_FOUNDATION.md`. The cache
   is now preserved and restore-tested in the private vault, so removal loses nothing.
7. Kalshi / MLB / ESPN storage rights: unchanged, private internal research only.

## 7. Next engineering (no approval needed)

1. **MLB inputs**: build the first MLB training dataset from the verified compact feeds (team run-scoring and
   starting-pitcher form, strictly pregame, chronological), then certify fail-closed like CBB / CFB.
2. MLB postponed-game identity at the source: the event-to-game mapping is assigned at market ingest, not in
   `scripts/edgelab/settle_markets.py`; use the exchange's "originally scheduled" date when two games share a matchup
   within a day. The overlay covers only the two known events.
3. Review the 32 MLB hitter-prop and 1 new NBA prop disagreements against vault box scores (`prop_review` needs MLB
   and ESPN readers).
4. CFB alias table for the 346 unjoined events; CBB join for the 1,047 unjoined events.
5. Add NBA and NFL vault archives to `vault_overlay`; regenerate the CBB ledger with the zero-box fix.
6. Register NBA (through 2026-11-15) and CBB (122 recovered boxes) dataset versions; CFB v3 only with independent
   evidence for the drive-scoring flag.

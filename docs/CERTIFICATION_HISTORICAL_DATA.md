# Certification and historical data (2026-11-16, RESEARCH_ONLY)

Agent-run, **not human verified**. No model trained or promoted, no trading change, no workflow added or edited,
no schedule, no purchase, no merge. PR #80 is read, never edited. No raw provider row is committed in this repository.

Evidence: `research/certification/` (`certification.json`, `evidence/*.json`, `dataset_versions.json`,
`game_index/<SPORT>.csv.gz`, `recovery_manifest.json`) and `research/settlement_discrepancies/`.
Code: `alpha_engine/certify/` (`cbb_independent.py`, `cfb_independent.py`, `compare.py`, `leakage.py`,
`reconcile.py`, `registry.py`, `recovery.py`); tests `tests/test_certify.py`.

## 1. CBB and CFB certification: both CERTIFIED

Method:
1. **Written specifications.** `docs/certification/{CBB,CFB}_FEATURE_SPEC.md` describe each dataset in prose.
2. **Blind re-implementation.** Two implementers rebuilt each dataset from the spec and raw data only, without
   access to `features/cbb_box.py`, `features/cfb_cfbd.py` or `training_sets_multi.py`.
3. **Comparison.** Every cell was compared (relative tolerance 1e-6; missing-value patterns must be identical).
4. **Leakage suite.** All of these run against the production builder:
   * truncation;
   * future-data scrambling, where every row dated on or after D, including D's own games, gets random statistics
     and scores;
   * own-game perturbation, plus a check that the perturbation does reach later games, so the test isn't vacuous;
   * outcome reconciliation against an independent result table;
   * missing-data classification of every expected game.

| Check | CBB | CFB |
|---|---|---|
| Fresh-container rebuild reproduces manifest `canonical_sha256` | yes (`3e73d70d…`) | yes (`a73a3e14…`) |
| Blind re-implementation: rows / columns / mismatched cells | 121,841 / 41 / **0** | 10,373 / 62 / **0** |
| Spec amendments needed (documented in each spec) | 1 (`conf_net_pre` for teams absent from the window: 193 cells) | 1 (`recruit_prior` without a year-S class: 274 cells) |
| Truncation (rebuild from data ≤ D) | identical on 3 dates | identical on 3 dates |
| Future scramble (rows ≥ D) | identical: 2008-01-12 (135 games), 2014-02-01 (147) | identical: 2016-10-15 (49), 2021-11-27 (45), 2025-09-06 (79) |
| Own-game perturbation | identical on both dates; reaches later games on both | identical on all 3 dates; reaches later games on 2 of 3 |
| Outcomes vs independent table | 121,840 / 121,841 agree with ESPN schedule scores | 10,369 / 10,369 agree with CFBD `games_teams` (4 without a reference) |

Both spec amendments were gaps in the written specification, not leakage: in each case the value uses only data
known before the game.

Caveats that remain attached to the certificates:
* **CFB drive points (semantic defect, not leakage).** `FUMBLE RETURN TD`, `PUNT RETURN TD`, `MISSED FG TD`,
  `DOWNS TD` and similar labels are credited to the drive's offense as 7 points. That is about 1.5% of TD-labelled
  drives, and it affects `ppd_o_pre` / `ppd_d_pre` only. The fix will be a new builder version with a new dataset
  hash; the certified v1 dataset will not be rewritten.
* **CBB 401726454.** ESPN's schedule still lists the game unplayed (0–0). The team box has the final, 121–49, and
  the dataset uses the team box. This is an upstream status defect.
* **CBB 310573129.** The team box is zero-filled (FGA 0), so the builder correctly drops the game. PR #80 counts it
  COMPLETE, which is a verifier gap (see §5).
* **Catalog.** Six catalog inputs are now eligible for TRAINING_READY:
  * CBB: `cbb.adj_off`, `cbb.adj_def`, `cbb.tempo`, `cbb.conf_strength`;
  * CFB: `cfb.off_ppa`, `cfb.def_ppa`.

  `cfb.drives` is held back because of the drive-points defect. `acquisition_inputs.json` is generated and was not
  hand-edited, so the catalog count stays at **41** until it is regenerated with this evidence.

## 2. Coverage reconciliation against PR #80

`alpha_engine/certify/reconcile.py` puts every FINAL ledger game, and every dataset game, in exactly one class.
That keeps differences of denominator, scope or build date from being reported as missing records.

| Sport | Ledger FINAL | In dataset | Outside season range | Out of scope (game type) | After build vintage | Source not complete | Builder excluded | Dataset only |
|---|---|---|---|---|---|---|---|---|
| NHL | 23,552 | 21,608 | 325 (2026-27) | 1,615 (playoffs) | 0 | **4** (no MoneyPuck xG) | 0 | 0 |
| NBA | 4,151 | 3,785 | 0 | 269 (play-in / playoffs) | 97 (11-02..11-15) | 0 | 0 | 0 |
| CBB | 137,695 | 121,840 | 15,021 (2003-05) | 0 | 30 | **803** (no ESPN team box; 485 in 2006-07) | 1 | 1 |
| CFB | 11,124 | 10,373 | 751 (2026) | 0 | 0 | 0 | 0 | 0 |
| NFL | 7,421 | 7,548 rows (all scheduled games; 7,414 with outcome) | same nflverse denominator | — | — | — | — | — |

Genuine source gaps are small: 803 CBB games and 4 NHL games. The rest is scope:
* CBB 2003–05 seasons are outside the builder.
* Playoffs are excluded for NHL and NBA.
* CFB 2026 is not in the builder.
* The NBA history ended 2026-11-01. It now runs to 2026-11-15 (§4).

NFL was not rebuilt in this session. The 1.3M-play nflverse pull was not repeated, and its denominator is identical
to PR #80's (7,548).

## 3. Durability

Re-running in a fresh container showed what survives a session. NBA, NHL, CFB and CBB all rebuilt **bit-exact**
from durable or re-fetchable sources (manifest hashes match). `research/certification/recovery_manifest.json` pins
every input:

| Source | Class | Status |
|---|---|---|
| CFBD cache (cfb-edge-finder `research-data` @ `292f3aac`) | GIT_PINNED | 106 used files hashed. **The branch is in a public repository and CFBD prohibits raw redistribution** (PR #80 finding). Owner decision. |
| NHL / NBA history (`data/history` on each repo's main) | GIT_PINNED | durable |
| CBB SportsDataverse releases | UPSTREAM_MUTABLE | 44 files hashed. **16 of 43 differ from the owner's 2026-10-04 bronze hashes** (seasons 2006–2014 republished), although the dataset hash is unchanged. Recover with `python -m alpha_engine.certify.recovery verify --fetch`; any drift is reported, never silently absorbed. |
| nflverse | UPSTREAM_MUTABLE | not hashed this session; the current-season file is republished weekly |

The following items were lost from earlier sessions' temporary storage:
* NBA transactions snapshot: unrecoverable.
* NFL pre-kickoff forecasts for 16 games: unrecoverable.
* The Phase 8 NHL player backfill: recoverable, and re-collected for 2026-27 (§4).
* Kalshi official results fetched for PR #80: only partly recoverable, because older markets leave the public listing.

**Proposed durable storage (owner approval needed; $0).** Every repository here is public, and the restricted
sources include CFBD raw data, ESPN via SportsDataverse and Kalshi.
1. The owner creates a **private** repository (for example `sift-data-vault`). Use its release assets: each file can
   be up to 2 GB and there is no storage charge.
2. Copy the pinned CBB, CFBD and nflverse inputs there with their `recovery_manifest.json` hashes.
3. Kalshi official results go there only if the owner decides that storing them for the owner's own trading is
   within the Kalshi Developer Agreement. The 2026-11-13 rights audit reads the primary terms as prohibiting storage
   without written authorisation.

Nothing was copied anywhere in this session.

## 4. Collection this session (existing collectors, run manually; no workflow, no schedule)

| Sport | What | Result | Where |
|---|---|---|---|
| NBA | 2026-27 history, shot events, full play-by-play, stints, lineup certification | history +105 games (to 11-15); 197 regular-season games of play-by-play (98,854 events); stints for 197 (150 lineup-certified); 60,137 shot events (77% located); refetch spot-check 4/4 identical | nba-edge-finder branch `claude/sift-alpha-certify-historical-vkb4ou` |
| NHL | 2026-27 skater / goalie / shot / goal tables from the official box score and play-by-play | 322 / 322 final games, 0 errors: 36,835 shots, 1,288 goalie-games, 11,592 skater-games, 2,016 goals. Shift charts unavailable (`api.nhle.com` denied here), so TOI / on-ice tables are not produced and must be re-run on a runner | NHL-edge-finder branch `claude/sift-alpha-certify-historical-vkb4ou` |
| CBB | 2006–2027 team box and schedules re-fetched and hashed | 44 files, drift measured | session only, pinned in `recovery_manifest.json` |
| CFB / NFL | — | Blocked. CFBD 2026 needs owner authorisation, and `api.collegefootballdata.com` is denied here. NFL has no durable owner-held store for nflverse yet (§3). | — |

## 5. Settlement discrepancies (PR #80 cross-check)

See `docs/SETTLEMENT_DISCREPANCIES.md` and `research/settlement_discrepancies/nhl_nba_20261116.json`.

| Sport | Contracts | Cause | n |
|---|---|---|---|
| NBA | 131 | **Engine bug:** 2H markets exclude OT. Kalshi's rules say "including overtime" (10 OT games). | 93 |
| | | Kalshi differs from current ESPN box (off by 1; ESPN only, NBA.com denied here) | 32 |
| | | Stat correction (ESPN changed after settlement, to Kalshi's value) | 6 |
| NHL | 47 | Kalshi administrative "No" on untraded opening-night save strikes | 24 |
| | | Kalshi differs from current NHL box (assist credits, saves) | 22 |
| | | Stat correction | 1 |

Proposed fixes. These were **not applied**: the change affects settlement records and model pricing, so it needs
review.
* NBA: in `nba-edge-finder/src/nba_edge/settlement/boxscore.py:126-127`, compute 2H as the final score minus 1H.
* NBA: apply the same change in `src/nba_edge/sim/result.py:109-110`.
* NBA: bump `ENGINE_VERSION` in `settlement/engine.py:27`, so corrected records are appended rather than overwritten.
* Both engines: re-read box scores during a stat-correction window, in `workflows/settle.py` (NBA :265, NHL :339-340).

PR #80 verifier gaps to raise on that PR (not edited here):
* a zero-filled team box is counted COMPLETE;
* the official-result compare should bucket untraded administrative results separately.

## 6. Connecting postgame and predictive records

* `dataset_versions.json` is **append-only**. Each entry is a (sport, canonical_sha256) version with its builder,
  spec, rows and readiness tiers. A changed builder, spec or source adds a new entry; an existing one is changed only
  by setting `superseded_by`. Tests enforce uniqueness and immutability.
* `game_index/<SPORT>.csv.gz` has one row per expected FINAL game and per dataset game. Each row joins:
  * PR #80's postgame completeness, through `game_id`;
  * the reconciliation class;
  * the immutable `dataset_version` that holds the game's pre-game feature row;
  * the outcome check.

  A model change therefore cannot silently rewrite either the historical record or its feature row.

## 7. Readiness tiers (dataset level)

| Sport | Raw available | Historically complete (in scope) | Independently verified | Training-ready | Model-active |
|---|---|---|---|---|---|
| NFL | yes | 7,238 / 7,421 FINAL complete (PR #80) | Phase 7 inputs certified; not rebuilt here | yes (12 inputs) | **no** |
| NHL | yes | 21,608 / 21,612 regular-season | inputs certified earlier; dataset reproduced bit-exact | yes (6 inputs) | **no** |
| NBA | yes | 3,785 / 3,785 regular season to 11-01 (97 newer now collected) | inputs certified earlier; reproduced bit-exact | yes (3 inputs) | **no** |
| CBB | yes | 121,840 / 122,644 (803 upstream gaps) | **CERTIFIED today** | **yes (dataset)**; 4 catalog inputs eligible | **no** |
| CFB | yes (2014–2025) | 10,373 / 10,373 | **CERTIFIED today** (ppd defect noted) | **yes (dataset)**; 2 catalog inputs eligible | **no** |

## 8. Next priorities (exact)

1. Owner: approve or decline the private data vault (§3), and the CFBD exposure remedy on the public
   `research-data` branch.
2. Review and merge the nba-edge-finder 2H-overtime settlement fix as its own PR (§5). It touches settlement
   records, so no trading change happens without review.
3. Regenerate `acquisition_inputs.json` with `research/certification/certification.json`, which promotes the six
   eligible CBB/CFB inputs (41 → 47).
4. CFB `cfb_cfbd` v2: fix the drive-points rule and register a new version. Leave v1 untouched.
5. Re-run the NHL 2026-27 player pull on a GitHub runner (only the `nhl-players` job; the Kalshi jobs in the same
   workflow should be split off first) to restore shift charts.
6. Rebuild the NBA dataset with history through 11-15 and register it as a new version.
7. CBB: test whether the 803 missing team boxes are recoverable from ESPN summaries (485 are in 2006–07).

## 9. Phase 10 update (2026-11-16)

* The catalog was regenerated with this evidence: 41 -> 47 training-ready inputs (`alpha_engine.foundation.acquisition.load_certification`, fail-closed).
* CFB v2 builder (`features/cfb_cfbd_v2.py`, spec `docs/certification/CFB_FEATURE_SPEC_V2.md` v2.2) corrects the drive-points defect. The
  independent verifier rejected spec v2.0 and v2.1 on label evidence; v2.2 passed every check. Dataset `0b9226c0…` is appended to
  `dataset_versions.json`; v1 `a73a3e14…` is unchanged and still registered. `cfb.drives` is certified on v2 only: 48 training-ready inputs.
* The private vault proposed in §3 exists and is populated; see `docs/PHASE10_DATA_PRESERVATION.md` (generated).

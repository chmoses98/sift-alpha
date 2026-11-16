# Phase 12 handoff (for Fable)

Written 2026-11-16 at the close of Phase 11. RESEARCH_ONLY. Agent-run, not human verified.
Read this, then `docs/UNIFIED_CHECKPOINT.md` sections 00, 0, 2 and 3 only if you need detail. Do not re-investigate
anything marked DONE.

## 1. Ground truth you can rely on

**Private vault** `chmoses98/sift-data-vault` (private repo): 24 archives verified (`python tools/vault.py verify` ->
24/24 OK, 1,525,282,312 bytes; ~35 s). Restore one archive with
`python tools/vault.py restore --path <archive dir> --to <scratch>`; never re-download what the vault holds.

| Sport | Archives (dataset, seasons, version) |
|---|---|
| MLB | Kalshi official settlements (snapshot-20261116); `postgame_feed_compact` 2022, 2023, 2024, 2025, 2026 (MLB Stats API, collected-20261116) |
| NFL | Kalshi official; nflverse pbp 1999-2009 (pin) and 2010-2026; in-season player/team 1999-2026 |
| NBA | Kalshi official; sportsdataverse pbp/boxes/schedules 2002-2027 |
| NHL | Kalshi official; NHL API daily scores/periods 2021-2026; sportsdataverse pbp/boxes/schedules and shifts 2011-2027 |
| CFB | Kalshi official; CFBD cache 2014-2026 (`v1-292f3aac`); ESPN postgame summaries 2014-2025 and 2026; training dataset `v1-a73a3e14_v2-0b9226c0` |
| CBB | Kalshi official; sportsdataverse team box/schedules 2006-2027 and player box/pbp early seasons; ESPN summaries for missing team boxes 2005-2025 |

Kalshi official settlements: ~2.19M rows (2,191,994; contracts served by both API tiers counted twice).

**Certified dataset versions** (`research/certification/dataset_versions.json`, none superseded):

| Sport | sha256 (canonical) | Rows | Spec |
|---|---|---|---|
| NFL | `d061651148541f02cc37100131764d95a4d3b0cfc9b554397f2ad7f295957763` | 7,548 | Phase 7 certified inputs (12) |
| NHL | `71f08bf06a7819e811dbab6003dadd33839353d94fac6c368ec156acd7593297` | 21,608 | team-level (6) |
| NBA | `f079a9ffa007fcf55f60c8c31526d99704eba10c853774fe32c62c1c1630e179` | 3,785 | team / team-constant (3) |
| CBB | `3e73d70db9836005bd270fba6e81c507037a14907c6a7e88178962757b504b56` | 121,841 | `CBB_FEATURE_SPEC.md` v1.1 |
| CFB v1 | `a73a3e141af490cc5e13499a67104feec07c41ae3778b667146c78e1fe9b90ce` | 10,373 | `CFB_FEATURE_SPEC.md` v1.1 |
| CFB v2 | `0b9226c089fad0e4b83770bb288c236c83e5fc830e42e288976214b96ec6d7eb` | 10,373 | `CFB_FEATURE_SPEC_V2.md` v2.2 (corrects v1 drive-points attribution) |
| MLB v1 | `f598384b39f7afd306171cbc41fb5674d3bfcccf72d0f2bbc61d117f2b569396` | 12,148 | `MLB_FEATURE_SPEC.md` v1, `training_ready: false` |

**Training-ready inputs: 48** (`research/data_foundation_ops/phase10_progress.json` -> `training_ready`):
NFL 13, NHL 8, CBB 4, CFB 3, NBA 3, MLB 0. Model-active: 0. Market-input map: 1,649 rows, 1,536 predictive.

## 2. Settlement truth: three layers, never merged

Tool `alpha_engine.game_completeness.settlement_reconcile` keeps `official` (vault), `computed` (sport repo) and
`with_overlay` (versioned corrections) as separate keys. Evidence `research/settlement_reconcile/<SPORT>.json`.

| Sport | Residual disagreements | Cause (researched) | Status |
|---|---|---|---|
| MLB | 32 after the 920-row overlay (edge-finder-api #319) | 29 exchange differs from final box; 3 post-settle stat corrections (`mlb_prop_review.json`) | no engine defect; overlay adoption = owner decision |
| NFL | 135 -> 13 with overlay; 13 = 2H overtime | fixed in code (#288, gated) | 60 W12 contracts pending until 2026-11-30 |
| NBA | 147; 108 2H-OT fixed by settle-1.1 (#111, gated); 39 props | 32 exchange vs box, 6 stat corrections, 1 unreviewed | settle-1.1 activation = owner decision |
| NHL | 24 | 22 exchange vs league box, 1 stat correction, 1 traded saves contract | no engine defect |
| CFB / CBB | 9 / 54 settled figures; ladders 8 / 1 | total-ladder rule: 2025 rung N = over N (strike N+0.5), 2026 = N or more (strike N-0.5); grade on stated strike only | no computed archive; independent check only |

Labels that would change if official results replace computed: MLB 952 flips (920 covered by overlay) + 6,318 new;
NFL 135 + 300; NBA 147 + 55,920; NHL 24 + 1,565. **Use the official layer as the label in Phase 12 research**,
and treat engine-only settlements as a secondary check.

## 3. Production state (do not change without owner approval)

| Repo | Active | Prepared, inactive |
|---|---|---|
| NFL | shadow-v2 settle `settle-2.0.0`, 2H excludes OT always, week tickers read via expiration year | #288: `NFL_SETTLE_PHASE11_RULES` (date-aware 2H OT, week-ticker season fail-closed), overlay `nfl-settlement-overlay-1.0.0` |
| NBA | `settle-1.0`, V1 pricing `5a4cbda0...` | merged #111 (on main, off): `NBA_SETTLE_1_1`; V2 baseline `2a05589f...` (`ACTIVE_BASELINE_ID` one-line switch) |
| MLB | ingest unchanged | #319 overlay (research), #320 reschedule rule (not wired into ingest) |
| All | no model, trading or scheduled-workflow change from Phase 11 | |

Known live defect while #288 is inactive: future `KXNFLWINSWEEK-26Wnn` contracts can still be stamped season 2025.
Research readers must apply the overlay (and a fresh snapshot after each affected week).

Rights: Kalshi, MLB Stats API, ESPN, sportsdataverse, nflverse, CFBD data are private internal research only
(`sift-data-vault/POLICY.md`). No redistribution, no public dashboards with raw rows, no paid services.

## 4. Market families: research-ready vs blocked

Ready (official labels + certified pregame inputs): NFL game lines/totals/team totals; NHL game lines/totals;
CBB and CFB game totals and spreads (grade ladders on the stated strike); NBA team-level lines and totals (1H, full).
Ready with care: NBA 2H (label = official; engine 2H is settle-1.0 until #111 activates), NFL 2H (same, #288).
Blocked: all MLB families (0 training-ready inputs; starter identity not point-in-time); player props in every sport
(no certified player-level inputs; residual prop disagreements are exchange-vs-box); NFL week-wins (overlay required,
W12 pending); season-long futures (sparse labels).

## 5. Phase 12 priorities

1. **Pattern discovery on ready families** using only the 48 inputs and official labels; preregister each test,
   hold out 2026, report fee-inclusive results. First milestone: one sport (NFL or NHL, the deepest) end to end with a
   reproducible notebook-free script and a frozen evaluation file. Success = results reproducible from the dataset
   hashes above and the vault snapshot.
2. **MLB v1.1** per `docs/certification/MLB_PIT_AUDIT.md` (Pythagorean/luck and games-remaining columns, blind
   re-implementation; starters only with timestamped vintages). Success = >=2 MLB inputs training-ready.
3. **Settlement hygiene** (small): after 2026-11-30 run the second NFL overlay snapshot (new `--as-of`, never overwrite);
   NBA V1-vs-V2 2H out-of-sample evaluation on OT games to support the V2 decision.
4. **Completeness gaps** (only if a pattern needs them): CFB alias table (346 unjoined events), CBB join (1,047),
   CBB half scores (74,944 missing), NBA/NFL vault archives into `vault_overlay`, regenerate CBB ledger with the zero-box fix.
5. **PR triage** (no code): stale pre-Phase-11 drafts Alpha #1 #19 #60 #62 #66 #68; NFL #30 #200 #229 #232 #241 #245;
   NBA #59-#106. Close or rebase; none is needed for Phase 12.

## 6. Reusable tools (all in sift-alpha unless noted)

* `alpha_engine.game_completeness.settlement_reconcile`, `.official_values`, `.vault_overlay`, `.prop_review`
* `scripts/research/mlb_prop_review.py` (official vs computed vs vault box, MLB props)
* `alpha_engine.certify.mlb_game_v1`, `alpha_engine.certify.mlb_pit_audit`
* `alpha_engine.foundation.training_sets`, `training_sets_multi`; `alpha_engine.input_research.regenerate` (catalog)
* nfl-edge-finder `scripts/research/build_settlement_overlay.py`; nba-edge-finder `scripts/nba_2h_overtime_reconciliation.py`;
  edge-finder-api `scripts/edgelab/audit_reschedule_identity.py`
* Commands with arguments: `docs/UNIFIED_CHECKPOINT.md` sections 0 and 5.

## 7. Owner decisions outstanding

1. Merge/activate NFL #288 (`NFL_SETTLE_PHASE11_RULES`) - recommended, it stops the week-ticker fail-open.
2. Activate NBA settle-1.1 (`NBA_SETTLE_1_1`; code merged in #111); separately, V2 pricing (keep V1 until the OT evaluation).
3. Adopt MLB #319 and NFL #286 overlays in evaluation readers; wire the MLB reschedule rule (#320) into ingest before 2027.
4. CFB 2H including overtime in research packets; CFBD raw responses on public branches (remedy in `docs/SPORTS_DATA_FOUNDATION.md`).

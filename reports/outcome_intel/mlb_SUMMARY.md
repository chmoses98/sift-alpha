# MLB 2022-2026 market-first audit (RESEARCH_ONLY)

Source: `chmoses98/edge-finder-api` main @ `5b1ba79253ecf69c849f2c75fc61fdc953be401d` (sha256 of every input file in `mlb_audit.json -> inputs.sha256`).
Machine-readable: `mlb_audit.json` (inventory, settlement verification, per-cell status), `mlb_incremental.json` (Kalshi cells), `mlb_pinnacle.json` (2022-2026 Pinnacle cells).

## What exists
* **Kalshi MLB price history + settlements exist for 2026 only** (captures 2026-08-01..2026-10-29): 812,650 observation rows, 262,520 contracts, 255,097 unique settled-or-attempted tickers, 245,563 model-evaluation rows. **2022-2025: no Kalshi price history or settlement in the repo = MISSING_DATA (coverage gap, not a negative result).**
* Multi-season market data is **sampled Pinnacle only** (178 dates, 18:15/21:15 ET snapshots, h2h + totals, no F5): 815 moneyline / 776 total games with a valid <=60-min pregame snapshot (2022: 162, 2023: 180, 2024: 179, 2025: 150, 2026: 144 for ML).
* Complete MLB schedule with final runs 2022-2026 (12,150 regular-season games; 2026 finals only through ~2026-08-27 in the cached schedule). Postseason (40 game-pks seen on Kalshi) is outside the schedule cache.
* Archived SIFT probabilities with an established pregame run time: 1,283 selections / 621 games (ML, F5 ML, YRFI/NRFI, team total; sources `prospective_snapshot`, `pipeline_recommendations`). No timestamped probability for game total, run line, F3/F7, F5 total, props.

## Findings that change how results must be read
1. **Settlement is derived, never Kalshi-official** (`kalshiOfficialResult` null on all 256,922 rows). Independent re-derivation from final runs agrees 648/648 moneyline, 2,234/2,234 run line, 4,536/4,536 team total; **game_total disagrees on 306 boundary rungs** (total == N stored as NO). Stored game/F3/F5/F7 totals before 2026-09-01 use strict `> N`; Kalshi pays `>= N`. Corrected by re-derivation where a total is derivable; otherwise contracts are dropped (3,226 dropped). F5/F3/F7 outcomes cannot be independently re-derived (no period scores archived).
2. The repo's `isValidPregameObservation` flag is not "captured before scheduled first pitch": 38,575 flagged rows were captured at/after the earliest known scheduled start (median 54 min after). They are excluded here (could be genuine only if first pitch was delayed; actual first-pitch time is not archived).
3. Only 35.5% of settled moneyline contracts have a two-sided quote within 60 min of first pitch (60% within 180 min): price capture is sparse near the close.

## Cell results (all cells attempted are in the JSON; Holm over all OK cells)
* **No cell is VALIDATED_IMPROVEMENT and none is PROMISING.** 71 cells: 34 INCONCLUSIVE_UNDERPOWERED, 10 NO_DEMONSTRATED_IMPROVEMENT, 27 MISSING_DATA (incl. 2022-2025 Kalshi).
* SIFT model vs contemporaneous Kalshi mid (NEAR horizon, holdout = latest third of 2026 games): moneyline 34 holdout games, gain -0.011 logloss [-0.026,+0.004]; F5 ML 38 games, -0.031 [-0.064, 0.000] (model worse than market); YRFI 39 games, -0.0003 [-0.004,+0.004]; team total 49 games, -0.0002 [-0.002,+0.002]. All underpowered (<100 holdout games): **not evidence of no effect**.
* Stale-quote (`price_trajectory`) challenger, 34 family x horizon cells: gains within +-0.004 logloss, no CI above 0 after Holm. The "NO_DEMONSTRATED_IMPROVEMENT" labels apply only to this weak challenger.
* Pinnacle baseline, season split (fit 2022-24, validate 2025, holdout 2026): point-in-time season-to-date runs proxy is **worse** than calibrated Pinnacle on moneyline (holdout gain -0.0065 [-0.0113,-0.0014], Holm p 0.025); totals gain -0.0003 [-0.0019,+0.0012]. Consistent with the repo's own MLB-RSCH-0008 (SHARP_MARKET_DOMINANT / PARITY). This is a proxy, not the production model.
* Controls: negative (game-shuffled) control clean in all but 2 hitter-prop cells (flagged in reason); planted-signal positive control detected in every OK cell.

## Not done / blockers
No Kalshi-vs-Pinnacle comparison (sample overlap 2026-08 is ~6 dates); no lineup/starter/weather/injury challengers (no per-input availability timestamps archived: see `pregame_input_availability`); hitter/pitcher prop projections not tested against price; discovery-extension model probabilities ignored (timestamp not established); F5/F3/F7 totals and period outcomes unverified.
Repairs: archive Kalshi official settled result; capture two-sided quotes at T-60/-30/-5 for every contract; persist `model_probability` + `computed_at` + per-input fetch times for every family; Kalshi candlestick backfill for 2025; daily Pinnacle (incl. F5) per-game pregame sampling.

## Reproduce
```
R=/home/user/data/edge-finder-api   # git init; remote add origin https://github.com/chmoses98/edge-finder-api; fetch --depth=1 --filter=blob:none origin main; sparse-checkout: docs, data/edgelab/{observations,settlements,model_evaluations,games,markets,clv_quotes}, data/research_cache/{bullpen_backtest,batting_backtest,pinnacle_historical}
python3 -I research/outcome_intel/mlb_pinnacle.py --root $R --out reports/outcome_intel/mlb_pinnacle.json
python3 -I research/outcome_intel/mlb_incremental.py --root $R --out reports/outcome_intel/mlb_incremental.json
python3 -I research/outcome_intel/mlb_audit.py --root $R --out reports/outcome_intel/mlb_audit.json
python3 -I -m unittest discover -s tests -p 'test_outcome_intel_mlb.py'   # 24 tests
```

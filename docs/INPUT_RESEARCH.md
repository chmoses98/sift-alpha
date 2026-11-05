# Input research: what predicts each Kalshi market, how much, and does it beat the price

**Status: RESEARCH_ONLY.** No orders, no credentials, no paid services. Nothing here is a betting claim. Added on top of (not beside) the existing registry, verification engine and dashboard.

## What it is

| Layer | File | Role |
|---|---|---|
| Candidate inputs | `research/input_research/catalog/<SPORT>.json` (validated by `alpha_engine/input_research/catalog.py`) | For all 8 sports: every candidate predictive input with mechanism, rationale, measurement, pregame-knowability, free sources, and registry link; per blueprint **and** per market archetype (e.g. `qb_passing_yards`, `pitcher_strikeouts`, `player_assists`) the relevant inputs with a market-specific "why" and hypothesised interactions. A hypothesis list, not evidence. |
| Availability audit | `publish.availability()` joined to `research/audit/verification/*.json` | Collection status, point-in-time status, current-model use. Only an **exact** registry-id match inherits registry status; new candidates are `NOT_IN_REGISTRY` and related registry inputs are shown as context only. |
| Statistics | `alpha_engine/input_research/stats.py` | Walk-forward by season, week-cluster bootstrap, Holm (confirmatory) + Benjamini–Hochberg (discovery) control, de-vig, calibration. Self-tested on planted signal / pure noise / outcome-corruption. |
| NFL paths | `nfl_features.py`, `nfl_game.py`, `qb_passing.py` | Point-in-time features from free nflverse data; game total / spread / moneyline vs the closing market; QB passing yards vs the QB's own history. |
| Publish + queue | `publish.py`, `queue.py`, `refresh.py` | `research/audit/input_research/{index,sport_*,queue,run_log,provenance}.json` for the dashboard. |
| Dashboard | `src/input-research.jsx` | Pick sport → market family (→ archetype) and see inputs, rationale, availability, model use, evidence, performance vs benchmark, gaps, queue. |

Refresh everything (free; downloads ~400 MB of nflverse release assets):

```sh
pip install numpy pandas pyarrow scikit-learn
python -m alpha_engine.input_research.refresh --data-dir /path/to/cache      # add --no-download to reuse a cache, --quick for a smoke run
python -m unittest tests.test_input_research && npm test
```

`.github/workflows/input-research-refresh.yml` does this weekly (and on dispatch) and **uploads an artifact only**: it never commits, merges or deploys. The first run after each refresh records how many new completed games arrived (`run_log.json`).

## Evidence ladder (a family sits at the highest rung actually achieved)

L0 inventory only → L1 tested vs a no-market baseline → L2 tested vs a contemporaneous closing line → L3 tested vs timestamped Kalshi executable prices incl. spread/fees/depth → L4 pre-registered forward confirmation. **Today: no family is above L2; 4 NFL paths are tested; 271 families are L0.** A "DEMONSTRATED_INCREMENTAL" verdict requires the Holm-adjusted CI > 0, both chronological halves > 0 and every leave-one-season-out > 0 — and still means only "predictive information beyond the stated benchmark", never an after-fee edge.

## What was actually validated (nflverse 2013–2026, test seasons 2017–2026, 2026 games to date included as a forward slice)

Benchmark for L2 = the nflverse **closing** consensus line / de-vigged closing price: a sportsbook close, **not a Kalshi price**; no spread, fees or depth; coarse over/under and spread prices.

* **NFL game total, spread and winner vs the close: no input, group or interaction demonstrated incremental value** (≈2,500 games each; all-input ridge/GBM no better or worse than the line; moneyline log-loss gain −0.0001, CI spans zero). Inputs tested: opponent-adjusted pass/rush EPA, success rate, pressure/sack matchups, explosive plays, scoring conversion, turnover regression, penalties, QB quality and change, snap-share-weighted injuries by position group, weather, rest, pace, pass-rate-over-expected, plus market-level controls and 4–6 pre-specified interactions. Without the market, the inputs do carry real information (e.g. all inputs explain ~5% of total-points and ~15% of margin variance out of sample) but the closing line explains more (10% and 20%): the market already absorbs it.
* **NFL QB passing yards vs the QB's own shrunk historical rate (no market, L1):** all inputs cut out-of-sample MSE by ~5% (Holm p≈0.007, both halves and every leave-one-season-out positive). Groups demonstrated: game script (spread/total/implied team total), environment (cold/wind/dome), opponent pass defence, opponent pass-volume faced. Suggestive only: opponent pass rush, team pass-offence quality. Not demonstrated: QB's own efficiency/volume after shrinkage, protection proxies, injuries, interactions (wind × depth of target suggestive, Holm p≈0.13). The game-script inputs are themselves derived from the closing lines, so this shows what a prop model should condition on, not that a prop line is mispriced.

## What remains unproven (do not promote)

* Anything beating a **Kalshi** price after spread, fees and depth. No L3/L4 anywhere.
* Every non-NFL sport and 271 of 275 families: inventory + availability only.
* NFL props vs a market: historical prop lines are not available free; capture Kalshi quotes prospectively (the NFL tape in `nfl-edge-finder` is the intended source) and re-run `qb_passing` with the market as benchmark.
* Untested NFL inputs (no free pregame source): coverage shell/man-zone, time-to-throw, pass-block win rate, route/target-share, CB shadow assignments. FTN charting (2022+) and PFR advanced pressure (2018+) are reachable and are the next feature additions.
* Realised starting QB and observed weather are treated as pregame-knowable; both are tagged `partial`.
* Catalog quality: the 8 catalogs were drafted in an automated pass. Input-level mechanism/rationale text is substantive; per-market `why` strings are partly formulaic (share reported per sport on the dashboard, from 0% NHL to ~65% Tennis). Free-source names were not all probed for reachability (only nflverse was). NFL overtime/tie wording is generic and needs a rulebook check.
* Registry gaps found: `NFL_MISC_UNCLASSIFIED` and four MLB/NHL families have no blueprint (shown as unclassified, never hidden); `NFL/PLAYER_STAT` lumps QB/rush/receiving/TD props (the dashboard offers an archetype selector); `CBB/OTHER` has no blueprint.

## Method notes

* Leakage controls: team ratings are chronological, opponent-adjusted EWMAs updated only after each game (unit-tested: corrupting a game's outcome cannot change its own or earlier features); injuries use the final report plus the player's **prior** snap share via an as-of join (a regression test covers the Out-player-has-no-snap-row case); ridge penalty is chosen on the last training season only.
* Overfitting/false discovery: ~60 inputs × 20 groups × 6 interactions per family are tested; Holm over groups and interactions, BH q-values over single inputs, leave-one-season-out and both-halves stability. Reported as discovery leads (q) vs confirmatory verdicts (Holm).
* Weights are ridge coefficients per +1 SD (bootstrap CI) fit on all history (descriptive, not used for evaluation) plus GBM partial dependence and permutation importance.

## Coordination

Builds on `research/audit/input_registry.json` (families/blueprints/ids), `research/audit/verification/*` (availability, model use) and the existing Verification desk, without altering them. Dashboard changes are one import + one component in `src/main.jsx`. No new infrastructure, branches or paid services; the one added workflow is manual/weekly, read-only and artifact-only.

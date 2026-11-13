# Active-sport priorities after the tennis pause (RESEARCH_ONLY)

**Date:** 2026-11-13. **Sport order (owner):** NBA, CBB, NFL, CFB, NHL.

Every item builds on research that is already done. Nothing here restarts a completed study. M marks a measured result, P a plan or audit status.

**Shared caveats:**
- All model-vs-market results use derived settlement (ESPN or the NHL API), not the official Kalshi result.
- Kalshi data rights are still under review (`docs/KALSHI_RIGHTS_IMPACT_AUDIT.md`).
- The NFL 2025 lab season has already been examined, so it is not an untouched holdout.

## Where projections are failing (measured)

| Sport | Headline failure | Source |
|---|---|---|
| NBA | **Moneyline:** market better by 0.025 Brier [0.011, 0.039], Holm p 0.004, 133 games. Calibration slope 1.85, so the model is underconfident. **Spread/total pooled:** market better by 0.008, 129 games. **Props:** slopes 0.79–0.85, so overconfident. **Graded:** only 23.2% (33,905 of 145,981 in-window markets). **Availability:** 1,626 projected players were absent from the box score; 728 of them had no injury report at all. | `main:docs/alpha_eval/NBA_POSTMORTEM_001.md` §3–5 |
| CBB | **Game winner:** log-loss gain −0.040 [−0.097, +0.006] on 36 holdout games, and all 5 model versions score ≤ 0. **MISSING_DATA:** 17 cells (halves, team totals, OT), because they have no model probability. **Known defect:** roster carryover. | `reports/outcome_intel/cbb_audit.json`, `docs/OUTCOME_INTELLIGENCE.md` §4, `docs/SPORT_TRUTH_AND_PROJECTION_QUALITY.md` |
| NFL | **Market better in 6 of 9 families** (moneyline −0.027 log loss [−0.049, −0.005], 278 games). **Props biased low:** rush_yds model 0.333 vs realised 0.421, caused by the raw P(active) factor of about 0.82–0.89. **Fix validated but not adopted:** the involvement model cuts log loss 0.60 → 0.41 (n=30,391). **Prospective:** 0 settled decision games; capture covered 10.3 of 66.7 window minutes. | `main:research/audit/lab/{dashboard_summary,player_bias_audit,involvement_validation}.json`, `main:research/prospective/*/REPORT.json` |
| CFB | **Brier:** 0.1841 vs market 0.1715, a gap of +0.0127 [0.0019, 0.0227] over 96 games. **Incremental cells:** 11 of 12 INCONCLUSIVE. **No Kalshi price history** for team total, 1H, quarter or props. **QB availability archive:** "very sparse". | `reports/outcome_intel/cfb_audit.json`, `research/audit/verification/CFB_quarter_total_chain.json` |
| NHL | **Holm cells:** 0 of 11 favour the model (308 games). Calibrated (slopes 0.99–1.15) but less sharp than the market. **Coverage:** 87.2%. **Unmodelled:** `game_overtime` (308; `p_overtime` not mapped to KXNHLOT) and `game_early_goal` (308). **Goalie and injury history:** no historical point-in-time source. | `sift-alpha-eval-catalog-38ni9g:docs/alpha_eval/NHL_POSTMORTEM_001.md` |

## Next five highest-impact improvements (ranked)

Ranking: expected accuracy gain × how many markets it touches × whether it can be built now from data in hand. Each item has a pre-registered success metric, scored against the existing postmortem baseline on the same games.

### 1. NBA: point-in-time availability gate and minutes redistribution
- **Problem (M):** 1,626 player-games projected for absent players.
- **Data in hand:** official injury-report history is archived from 2026-10-19 (Phase 13). ESPN stints have been verified against the box score (Phase 14).
- **Work:**
  - Use the latest injury-report record at or before freeze.
  - Zero OUT players, and discount QUESTIONABLE/DOUBTFUL players by their historical play rates.
  - Redistribute minutes to the rotation, then re-derive props and team totals.
- **Metric:**
  - absent-player projections: 1,626 → target < 400 over the same window;
  - prop and game-family Brier/log loss vs the pf-1.3.0 baseline, with Holm correction.
- **Blocker:** `nba.starters_pit` has no free point-in-time history. The gate works without it.

### 2. Cross-sport walk-forward recalibration layer (NBA first, then NHL and props)
- **Problem (M):**
  - NBA moneyline slope 1.85 (underconfident);
  - NBA props slopes 0.79–0.85 (overconfident);
  - NHL is calibrated but blunt.
- **Work:** walk-forward Platt/temperature scaling per sport × family × horizon, fitted only on strictly earlier settled games. The postmortem tooling already measures calibration slopes.
- **Metric:** the calibration slope moves into [0.9, 1.1], and the Brier gap shrinks against the market on the same 133 / 103 / 308 games.
- **Note:** this is cheap and needs no new data. It cannot create an edge, but it removes the self-inflicted part of the gap.

### 3. NFL: adopt the validated involvement model in place of the raw P(active)
- **Problem (M):** props are biased low. The fix already exists: log loss 0.60 → 0.41 on n=30,391.
- **Work:**
  - Wire the involvement model into the prop producer.
  - Repair `nfl:inactives_pit`, the top pending repair (priority 70).
  - Re-run the 2025 lab families.
- **Metric:**
  - the gap between realised and predicted rates per prop family shrinks (rush_yds 0.088 → < 0.02);
  - the 6 MARKET_BETTER families are re-tested.
- **Owner decision that multiplies this:** nflverse "lane C" (NFL-feed terms). It unlocks 55 point-in-time-strict slots: injuries, depth charts, participation and snaps.

### 4. NBA: market coverage, from 23.2% graded upward
- **Problem (M):**
  - 16,214 prop tickers were never linked to a player (the listing archive covers 111 of 182 games);
  - 4,752 PRA markets have frozen pmfs that were never evaluated;
  - 89,371 markets (periods/quarters, steals/blocks, double-doubles, race-to, win margin) have no frozen source.
- **Work:**
  - Link tickers to players from the exchange board itself.
  - Grade the existing PRA pmfs.
  - Derive quarter and half distributions from the game-score model that already exists.
- **Metric:** graded share of in-window markets rises from 23.2%, with each new family reported separately (no pooling).

### 5. CBB: fix roster carryover and derive half/team-total probabilities
- **Problem:**
  - (M) all 5 versions score ≤ market;
  - (M) 17 MISSING_DATA cells;
  - (P) known roster carryover defect.
- **Work:**
  - Fix the roster carryover from season to season.
  - Derive 1H, team-total and OT probabilities from the game model so that those cells become testable.
  - Start `cbb.injuries` prospective capture **only with owner approval** (it is a schedule change).
- **Metric:** game-winner log-loss gain on the expanding holdout (currently 36 games), and the number of cells moved from MISSING_DATA to evaluable.

**Runners-up:**
- **NHL:** map `p_overtime` → KXNHLOT. It is cheap and opens 308 markets.
- **CFB:** QB-status point-in-time capture (prospective, needs approval), plus recalibration from item 2.

## Owner decisions that would unblock the most
1. **nflverse lane C** (NFL-feed terms): 55 point-in-time-strict slots.
2. **ESPN terms:** 27 archived point-in-time-strict slots across CBB/CFB/NBA box, pbp and `nba.lineup_stints`.
3. **Prospective capture approvals:** `cbb.injuries`, `cfb.qb_status_pit`, `nhl.goalie_start`, `nhl.injuries_pit`. Each is a schedule change.
4. **`shadow-ledger.yml`:** see `docs/OPS_SHADOW_LEDGER_SELF_DISPATCH_LOOP.md`.

# Recovered-tape replay: what changed in the execution evidence (RESEARCH_ONLY)

Label **RETROSPECTIVE_BACKFILL_REPLAY**. Fills are `SIMULATED_FROM_TAPE`, never executions. This is a separate series from the PROSPECTIVE shadow ledger and is never merged into it.
Issue: sift-alpha #23, collector: nfl-edge-finder #246. Machine-readable: `reports/exec_track/recovery_replay.json` (aggregates only, input digest pinned).

## Method
The same decisions (contract-side x horizon x limit rule x queue scenario, identical quotes from the same candles) are evaluated twice by `research/exec_track/recovery_replay.py`:
BEFORE on the legacy tape (newest 10,000 prints; a family with no archive is UNKNOWN history), AFTER on the audited recovered tape (`trades_v2`, kickoff-anchored, independently re-verified).
Equal exposure (10 contracts), taker 0.07, maker scenarios M0 / M25 (0.0175) / M100 (0.07), values held to settlement, 95% intervals from resampling **games**. Selection uses weeks 1-12; weeks >= 13 are an untouched holdout; a claim of positive net EV needs holdout CI > 0 and a Bonferroni-corrected p < 0.05, >= 10 games and >= 30 orders.

## Cohort
776 recovered tapes, 4,930,449 prints, 773 joined to a game and quote source, 263 games, 10 families. All 439 legacy tapes capped at exactly 10,000 prints are recovered (434 candle-verified; 4 differ by one hour of volume with exact prices; 1 has no candles to compare).

## What recovery resolved
- Decisions evaluable: **525 -> 4,974 of 4,974** (4,449 newly evaluable, 0 lost).
- Uncertain orders: **43,908 -> 0** (15,488 became supported fills, 28,420 supported no-fills). No previously supported order changed class.
- Supported fills split into 49,813 queue-independent (a print through our price) and 41,071 that need the queue ahead to drain: those depend on the queue scenario, which the 2025 backfill cannot observe (no displayed book sizes).
- The legacy tape could evaluate only 359 of 2,562 moneyline decisions (14%); the old per-cell intervals were +/-10-20 cents, now about +/-1.5.

## Execution economics (24h horizon, rest at the bid, fallback to taker at the close; M25)
Absolute net EV, cents per contract held to settlement, [95% CI]:

| family | games | BUY_NOW | WAIT | LIMIT + taker fallback | LIMIT - WAIT (M0 / M25 / M100) |
|---|---|---|---|---|---|
| moneyline | 253 | -2.70 [-4.06,-1.32] | -2.63 [-3.94,-1.31] | -0.56 [-1.91,+0.65] | +2.50 / +2.07 / +0.98 |
| spread | 36 | -2.36 [-2.82,-2.06] | -2.17 [-2.44,-1.99] | -0.18 [-0.72,+0.16] | +2.36 / +1.98 / +1.04 |
| total | 24 | -2.62 [-3.18,-2.23] | -2.40 [-2.86,-2.10] | -0.67 [-1.43,-0.20] | +2.02 / +1.74 / +0.99 |
| player passing yds | 16 | -3.10 [-4.31,-2.50] | -3.73 [-4.11,-2.93] | -0.62 [-1.82,-0.09] | +3.37 / +3.11 / +2.46 |

Smaller families (team total 4 games, 1H spread/total/winner 6-7 games, rushing/receiving yards 15-16 games) have the same sign but too few games to test.

- **Limit orders beat waiting** in every family and fee scenario, but the margin depends on assumptions: if only queue-independent fills count, moneyline falls to +0.89 / +0.63 / **-0.04** (M0 / M25 / M100) and spread to +1.00 / +0.75 / +0.11.
- **Early taker entry vs waiting:** not better for moneyline, spread, total or the halves (moneyline costs 1.3 cents more at 7 days and is level at 90 minutes). The three player-prop families are the exception in the point estimates (early entry 0.5-1.9 cents cheaper at 6h-72h), but that rests on 15-16 games with no tested interval, so it is unproven.
- Half spread: about 0.6 cents on moneyline, 0.9-1.2 on spread/total/team total, 1.7-3.2 on halves and player props; the taker fee is about 1.2-1.5 cents at the ask.
- **Absolute net EV is negative at the point estimate for every tactic in every family**; for total and passing yards the limit-fallback interval excludes zero on the negative side.

## Out-of-sample gate
Moneyline (selected 24h / at the bid / fallback): holdout +0.41 [-1.38, +2.32], 96 games, p = 0.65, corrected p = 1.0 -> NOT_POSITIVE_AFTER_FEES. Spread: -0.09 [-0.77, +0.25], 21 games -> NOT_POSITIVE_AFTER_FEES. Every other family is INSUFFICIENT (1H, team total and props have all, or nearly all, their archived games in the holdout weeks; total has only 6 holdout games).
43 of the 5,568 cell-by-fee-scenario fallback tests show an uncorrected positive interval (all 1H totals/spreads, 3-7 games, front-of-queue): that is what thousands of tests on a handful of games produce, and none is counted.

## Fee evidence
Taker 0.07 is confirmed (643 of 646 real fees). Maker: KXNFLGAME SCHEDULE_ATTESTED (0.0175); KXNFLSPREAD and KXNFLTOTAL are maker-fee series with **no listed multiplier -> UNVERIFIED**; the taker-only series (team total, halves, quarters, props) are EXCHANGE_FEE_TYPE with maker 0. No maker fill has ever been observed, so every maker number is a scenario.

## Limits
Population = every valid contract-side (no selection signal): this isolates execution cost and says nothing about model edge. Queue ahead is a scenario in 2025 (FRONT is optimistic). 1H, team-total and prop contracts exist for few archived games, so family-level tests are limited by the source, not only by recovery. 2,956 preseason markets have no kickoff anchor and are excluded.

## Next highest-value target
Not more moneyline. Spread, total and the player-prop yardage families have thousands of settled contracts with pre-start quotes still unrecovered (backlog estimates in the coverage report) but only tens recovered each: season-spanning sampling (now the collector default) gives each a discovery, validation and holdout sample. Pair that with the prospective shadow ledger, which is the only source of a real displayed queue.

# Reconciliation: nba-edge-finder PRs #104 and #105 against alpha-nba-avail-0.1 / 0.2 (and what 0.3 should reuse)

RESEARCH_ONLY. Read from `origin/claude/quirky-darwin-zv0rwc@7f61022` (#104) and `origin/claude/quirky-darwin-zv0rwc-calibration@17dad1e` (#105):
`docs/research/AVAILABILITY_OVERLAY_REPLAY.md`, `docs/research/NBA_CALIBRATION.md` and the preregistration. Both are open drafts, not merged.
The sift-alpha side is `research/data_foundation_ops/NBA/alpha-nba-avail-0.1`, `-0.2` and `alpha-nba-rate-0.3`.

The two lines of work score different forecasters. #104/#105 post-process the frozen **shadow arms** (`sim_rotation`, `ewm5`) at their own
`as_of` (pretip and morning slots). 0.1 scores its own model on 2025-26; 0.2 and 0.3 score the frozen **`pf`** production forecasts at T-60.

## What agrees

| Finding | #104 / #105 | sift-alpha |
|---|---|---|
| Official OUT / DOUBTFUL means the player does not play | pretip: 0 of 266 injury OUTs played; DOUBTFUL 0 of 46 (W2) | 0.1: OUT 0 of 3,090; frozen pf roster 2026-27: OUT 0.2% of 931, DOUBTFUL 0 of 37 |
| QUESTIONABLE / PROBABLE rates | caps 0.588 / 0.933 (fitted on 2025-26) | 0.1: 54% / 93%; frozen pf roster 2026-27: 59.9% (n 279) / 89.8% (n 59) |
| A T-60 status gate improves participation and unconditional minutes | pretip `sim_rotation`: Brier -0.047 [-0.056, -0.038], minutes MAE -2.04 | 0.1: Brier -0.0489 [-0.0526, -0.0452], minutes MAE -1.65 |
| The gate does not help props conditional on playing | conditional CRPS and rung Brier unchanged by design (delta 0) | 0.1: at most 0.001, inconclusive on all four families |
| The pretip market is better than the model on props | #105 pretip: +0.0096 [+0.0061, +0.0133], 34 games | 0.2: points +0.0097 [+0.0058, +0.0140], 118 games; 0.3 with restored boards: +0.0087 [+0.0057, +0.0116], 166 games |
| Prop-ladder recalibration does not help | #105 P2 rejected: +0.0005 [+0.0001, +0.0009] | 0.2 F1 rejected by inner validation |
| A record is usable only from its effective time | #104: later of `captured_utc` and snapshot write time; 2 of 144 snapshots had roster evidence stamped 2.3 h and 4.6 h early | 0.1: 118 games had a report stamped T-60 but published 4 s later; 0.2 uses later of capture and source-update time |

## What conflicts, and how to read it

1. **Minutes redistribution.** 0.1 validated it on 2025-26 (minutes MAE -0.19 [-0.23, -0.16]). #104 measured it on the 2026-27 shadow arms and
   recommends against it (conditional minutes CRPS +0.025 to +0.063, bias up to +2.3 minutes: freed minutes belong to players already missing
   from recent games, so they are counted twice). These are different baselines, not contradictory measurements. 0.3 adds a third fact: the
   frozen `pf` roster already sums to 248.8 expected team minutes, not 240. Treat redistribution as **unresolved and off by default**; the
   consistent fix is to normalise expected team minutes, which 0.3 does for its team-points blend.
2. **Level of P(play) for available players.** #105 finds confirmed-available players under-forecast on the shadow arms (P about 0.79, played 89%)
   and adopts an upward recalibration. On the frozen `pf` roster the ACTIVE designation is over-forecast (mean P 0.840, played 0.800, n 4,674).
   The populations differ (#105 excludes players without positive roster evidence; `pf` ACTIVE includes them), and the arms differ. The #105
   maps are arm-specific.
3. **Implicit roster rows.** 0.2 drops implicit ACTIVE rows entirely because of the timestamp defect #104 reported. #104 keeps them with an
   effective-time rule and a positive-evidence requirement. #104's treatment is the more complete one.
4. **Morning slot.** #105 reports the model beating the thin morning quotes (-0.0132 [-0.0202, -0.0068], 50 games). sift-alpha has no morning
   evaluation; nothing here confirms or contradicts it. It is a comparison with a stale mid, not an executable result.

## Which implementation should be canonical

* **Status resolution and suppression: #104's `nba_edge.availability.overlay`.** It lives in the owner's repository with tests, fails closed,
  modifies no frozen file, and encodes the roster-evidence rules that 0.1/0.2 lack. Once #104 merges, sift-alpha should read overlay output
  rather than keep a second status selector (`nba_availability.select_pit_status`, `nba_frozen.pit_status`); those stay as the independent
  check that reproduced the same rates.
* **P(play) calibration for the shadow arms: #105 P1 combined**, subject to its own pending prospective check (calibrators frozen at sha256
  `55dfdfbe...`, no post-freeze outcomes yet).
* **Evaluation against the frozen production forecasts and the T-60 market: sift-alpha 0.2 / 0.3.** #104/#105 do not score `pf`, and their
  market comparison covers 34 pretip games.

## Should alpha-nba-rate-0.3 reuse their P(play)?

No, not the fitted maps. 0.3's player rows are conditional on playing, so P(play) does not enter them; its team-points blend uses the frozen
`pf` P(play) rescaled to 240 team minutes, which removes the level. The #105 maps were fitted to `sim_rotation` / `ewm5` and would move `pf`
further in the wrong direction. What is worth reusing is the **method** (walk-forward ridge-Platt on confirmed-available players, fitted per
arm) if an unconditional market is ever scored, and #104's suppression rules for deciding which players get a quote.

## Open items

* #104's `roster_unconfirmed` rule (not on any roster for 24 h; 331 player-games, none played) is a prospective candidate in both lines.
* Injury-status captures are still written only during forecast runs, so neither line can measure a status change between runs.

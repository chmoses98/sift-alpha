# NFL player-prop batch 5: six certified usage inputs from play-by-play (RESEARCH_ONLY, 2026-11-20)

Builder: `alpha_engine/features/nfl_player_ext5.py`. It reads nflverse play-by-play 2010–2026 and the schedule only, from vault
`archives/NFL/pbp/2010-2026` (already held; no new collection). Nothing is deployed, scheduled or consumed by a projection model.

**Row universe.** A (game, player) row exists for every player who had a target or a carry for the team in any of its 4 previous
played games. Rows are built from prior involvement only. Every value for a game dated d uses plays from games dated strictly
before d. 2010 is warm-up history, so output starts in 2011: 119,955 rows, about 13.7 players per team-game.

| Input | Columns | Level | Not implemented |
|---|---|---|---|
| nfl.carries | carry share, goal-line (≤ 5 yd) and passing-down carry share (EWM, half-life 4 games) | PARTIAL | injury/inactive status, snaps, depth chart |
| nfl.targets | target share, air-yards share, aDOT | PARTIAL | routes / TPRR (FTN), participation |
| nfl.rz_share | red-zone target and carry share | PARTIAL | as above |
| nfl.td_rates | anytime-TD and first-TD game rates (EWM, half-life 8) | PROXY | role-based shrinkage |
| nfl.target_competition | teammates' target-share sum, rank, team HHI | PROXY | roster moves: a traded player stays in old-team rows up to 4 games (share sum mean 1.22) |
| nfl.player_stat_variance | receiving and rushing yards mean / SD / CV over the last 16 games (min 4) | PARTIAL | distribution model beyond moments |

## Certification (same process and ledger rules as batches 1–4)
- **Replay** (`verification/replay_ext/NFL_nfl_player5.json`). Every check passes for all six inputs: determinism, 3 truncation
  cuts, 3 perturbation seeds, own-game and non-vacuity. The perturbation is role-preserving: it shuffles who caught or carried
  within a team-game, so the row universe stays fixed.
- **Blind exact match** (`verification/independent/NFL_nfl_player5.json`).
  - A separate agent worked from the brief (`briefs_nfl_player5.md`, sha256 `1400cf8f…`) and the raw files only, with no repository access.
  - **19/19 columns MATCH on the first comparison**: rtol = atol = 1e-9 over all 119,955 keys.
  - Implementation and notes: `blind_briefs/nfl_player5_blind_runs/`. Agent verification, not human.
- **Ledger:** `regenerate --apply` plus the documented dependent chain.
  - VERIFIED_PARTIAL 226 → 230.
  - VERIFIED_PROXY 37 → 39.
  - **Missing PRIMARY slots 841 → 828** (13 slots, in NFL rushing yards, passing yards, receiving yards/receptions, anytime/first-TD scorer and passing TDs/INTs).
  - Pinned test counts were updated with the reason.

## Evidence of usefulness (input against a naive baseline only, not a model or betting claim)
Walk-forward skill over 2023–25 against the league mean of the realised next-game value (realised value is 0 when the player
was not involved):

| Measure | Skill |
|---|---|
| carry share | +58% |
| target share | +37% |
| air-yards share | +38% |
| aDOT | +38% |
| red-zone carry share | +38% |
| goal-line carry share | +24% |
| passing-down carry share | +16% |
| receiving yards mean | +27% |
| rushing yards mean | +39% |
| SD as a predictor of absolute deviation | +32% (receiving), +54% (rushing) |
| red-zone target share | −2% |
| anytime-TD rate | −2% |
| first-TD rate | −7% |

The last three are **no better than a constant**: they are verified as computed, not as useful.

## Next
These inputs are certified but not consumed by any model. To move up the adoption ladder, a frozen experiment must name their
columns, test player-prop predictions on unseen seasons against the operating model, and then price them against archived prop
quotes. nfl-edge-finder `market-data` holds 2026 books from 2026-09-04.

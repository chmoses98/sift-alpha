# The 5 official-settlement disagreements in the forward study: WKU at MTU, 2026-11-07 (resolved, 2026-11-20)

All 5 contracts where the forward study's ESPN-graded outcome disagrees with Kalshi's official result
(`forward_report.json` → `data_audit.disagree_examples`) are full-game spread rungs MTU4–MTU8 of one game.

| Source | Final | 1H | Notes |
|---|---|---|---|
| ESPN summary (vault `archives/CFB/espn_summary_postgame/2026`, game 401871076) and cfb-edge-finder `team_games.jsonl` | MTU 51 – WKU 42 | MTU 21 – 13 | Q4 scoring: WKU ties 42–42 at 0:31; MTU 48-yd FG at **0:01** (45–42); **Aidan Singleton 0-yd fumble return at 0:00**, no PAT (51–42) |
| Kalshi official settlements (vault `archives/CFB/kalshi_official_settlements`) | **MTU 45 – WKU 42** for every family | margin 8, total 34 | FG spread `expiration_value` 3 (MTU2/MTU3 YES, MTU4+ NO); total 87; team totals "Home: 45, Away: 42"; 1H figures agree with ESPN |

**Reading.** The exchange settled the event on the score before the untimed final play (a fumble return on the
kickoff after the go-ahead field goal). Its first-half figures match ESPN exactly, and its game, spread, total and
team-total settlements are mutually consistent at 45–42. So this is not a grading bug on our side. It is one game
where the exchange's settlement value differs from the box score.

**Handling (unchanged, correct):**
- **P&L and selection results** use Kalshi's official `result`. That is payout truth, and it is what `score_forward.py`
  already does where an official result exists.
- **Outcome-model fitting and evaluation** (margin/total RMSE, calibration of score distributions) use the game's
  actual outcome (ESPN 51–42). An outcome model should learn football, not settlement quirks.
- The two must never be mixed. A study that grades contracts from box scores must report its official-agreement rate
  and use the official result where they differ: 53,500 / 53,505 here, and all 5 differences are this play.

No frozen candidate or past result changes.

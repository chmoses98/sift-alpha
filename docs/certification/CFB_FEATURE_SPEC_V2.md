# CFB feature specification v2.2 (builder `cfb_cfbd_v2`, RESEARCH_ONLY)

This specification is `CFB_FEATURE_SPEC.md` v1.1 with exactly ONE section replaced: the drive-points rule. Everything
else (inputs, game table, advanced-box columns, weighting, windows, priors, both v1.1 amendments, output columns and
ordering) is unchanged and is to be read from the v1.1 document. The v1 builder and its certified dataset
(`a73a3e14…`) are immutable; v2 is a new builder and a new dataset version.

## Replaced section: drive points (v2.2)

For every drive record (season files `drives_regular` followed by `drives_postseason`), let `L` be the drive's
`driveResult` converted to a string (no trimming, no case folding) and `G` be true when the drive's
`endYardsToGoal`, read as a number, equals 0 (missing or non-numeric -> false). Drive points for the `offense`:

| Points | Condition (exact string equality on `L`) |
|---|---|
| 7 | `L` is one of: `TD`, `RUSHING TD`, `PASSING TD` |
| 7 | `G` is true and `L` is one of: `DOWNS TD`, `FUMBLE RETURN TD` |
| 3 | `L` is one of: `FG`, `FG GOOD` |
| 0 | everything else. Known zero-scoring labels that contain `TD` / `FG`: `DOWNS TD` and `FUMBLE RETURN TD` when `G` is false; `INT TD`, `FUMBLE TD`, `PUNT TD`, `PUNT RETURN TD`, `MISSED FG TD`, `FG TD`, `END OF HALF TD`, `END OF GAME TD`, `POSSESSION (FOR OT DRIVES) TD` regardless of `G`; `MISSED FG`, `FG MISSED`, `BLOCKED FG` |

If a label contains `TD` or `FG` and is in none of the lists above, the build must fail rather than score it.

Rationale: a drive's points belong to the offense only when the offense scored. `DOWNS TD` and `FUMBLE RETURN TD` are mixed
classes: the offense's score when the drive itself ended on the goal line, otherwise the defending team's. Every other
qualified TD label is the defending / returning team's score.
v2.0 of this section (never registered) listed `END OF HALF TD`, `END OF GAME TD` and
`POSSESSION (FOR OT DRIVES) TD` as offensive and `DOWNS TD` / `FUMBLE RETURN TD` as always zero; the independent
verifier's evidence contradicted that. v2.1 (never registered) applied the goal-line test to every qualified label; the
verifier showed it wrong for `INT TD` / `FUMBLE TD` / `PUNT RETURN TD` (8 drives, defense scored). v2.2 is the rule above.

Known limitation, unchanged from v1: the drive `scoring` flag is not used (e.g. `END OF HALF` drives flagged scoring).

Per (`gameId`, `offense`): `ppd_o` = mean drive points over that team's drives in the game; `start_ytg_o` = mean
`startYardsToGoal` (unchanged). `ppd_d` = the opponent's `ppd_o` in the same game (unchanged). No points are
credited to the defending team for its return scores: `ppd` measures offensive drive finishing only.

## Expected differences from v1

Only `home_/away_ppd_o_pre` and `home_/away_ppd_d_pre` may differ from dataset `a73a3e14…`. Row set, keys, outcomes
and every other column must be identical cell-for-cell.

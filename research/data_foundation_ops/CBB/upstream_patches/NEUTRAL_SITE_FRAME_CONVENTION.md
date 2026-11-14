# Neutral-site home/away frame in cbb-edge-finder: a convention, not a defect (no patch)

Checked 2026-11-14 against `chmoses98/cbb-edge-finder` main@5ba7daa5 and archive branches kalshi-panel-archive@3288f41a, projections-archive@17d0ef97. Agent finding, not human verified.

## What the challenger saw
In 3 neutral-site games (Nov 8–11 slates), 70 Kalshi panel contracts in all families had `contract_semantics.subject_side` reversed compared with the frozen projection's home/away. 51 of them were full-game winner or spread contracts. `subject_team_id` was correct in every case. After re-labelling by team id, all settled results agree (7,714 of 7,714 full-game winner/spread contracts in `alpha-cbb-venue-prior-0.1`).

## Where it comes from
1. **Two frames.** On a neutral site, a frozen projection (`projections-archive`, `game.site == "neutral"`) can list the two teams in the opposite order from the ESPN schedule archive. Both are legitimate listings. Frozen records are never edited.
2. **The panel uses the schedule frame on purpose.** `cbb_edge/kalshi/semantics.py::parse_contract(series, market, home_team_id, away_team_id)` sets `subject_side` by comparing the resolved subject team with the *mapped game's* (schedule) home/away ids. It also stores `subject_team_id`. `settle` uses the same frame.
3. **Projections are reframed into that frame.** `cbb_edge/kalshi/history.py::_projections` (from PR #47, merged 2026-11-11 01:41Z) applies `cbb_edge/data/ids/orientation.py::reframe_projection` to records that `sift_app/selection.py` marks `reorientable`: same two canonical team ids, reversed, with the record site neutral. Anything else fails closed (UNVERIFIED, skipped).

## Evidence that the archived panel is internally consistent
* For the 15 flipped contracts that carry an incumbent probability (all captured after PR #47), the panel probability equals the incumbent forecast for the team named by `subject_team_id`. The maximum difference is 6e-17. Reading the panel's `subject_side` label against the unreframed projection would be off by as much as 0.64.
* The 53 flipped contracts captured **before** PR #47 have **no** incumbent probability. That was the legacy behaviour: identity-changed records were skipped. The other 2 flipped contracts are post-#47 families that the incumbent does not price. No wrong probability was found in the archive.
* `tests/test_orientation.py`, `tests/test_orientation_scoring.py`, `tests/test_kalshi_semantics.py` and `tests/test_kalshi.py` pass on main (the checkout was left clean).

## The rule for any consumer outside cbb-edge-finder
Panel `subject_side`, `yes_condition` and the panel's model probabilities are in the **schedule frame**. Frozen projection files are in the **projection frame**. To join them, map by `subject_team_id` against the projection's `home.team_id` / `away.team_id`, never by the label. Accept a reversal only when the two id sets are identical and the site is neutral, and fail closed otherwise. `alpha-cbb-joint-periods-0.1` and `alpha-cbb-venue-prior-0.1` both do this.

## Optional hardening (owner decision, not done)
Each panel row could record its frame explicitly, for example `contract_semantics.frame = "schedule"` and `projection_orientation = SAME|SWAPPED`, so that downstream readers do not need to infer it. That would be a schema change to a live capture, so no patch was prepared.

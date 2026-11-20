# From certified input to operating model (six sports)

SIFT Alpha only does research. Producer repositories (nba/cbb/cfb/nfl/nhl/mlb edge finders) run operating models.
Nothing moves from one to the other without the gates below. Each gate has an owner sign-off, and the evidence for
each gate is a committed artifact.

| Stage | Meaning | Evidence | Where |
|---|---|---|---|
| 1. Calculated | the builder's own leak replay, recomputation and coverage pass | `research/audit/derived_inputs.json`, `six_sport_walkforward.json` | Alpha |
| 2. Certified | replay (truncation, perturbation, own-game) + a blind exact match by an isolated session; ledger regenerated | `research/input_research/data_foundation/verified_coverage.json`, `verification/*` | Alpha |
| 3. Predictive | the input improves out-of-sample outcome accuracy in a walk-forward test, on games of the same type | per-sport walk-forward report | Alpha |
| 4. Price-relevant | frozen candidate, scored forward on unseen weeks against executable quotes: conditional calibration vs market, net of rounded fees, game-clustered uncertainty | e.g. `research/cfb_forward_validation/` | Alpha |
| 5. Shadow | the producer computes the candidate beside the incumbent behind a disabled flag; nothing is published or priced | producer branch with `ENABLED = False` (e.g. cfb-edge-finder `scripting/home_effect_experimental.py`) | producer |
| 6. Controlled rollout | owner-approved, versioned methodology bump, limits unchanged, kill switch | producer PR + owner approval | producer |

Rules:
- Reaching stage 3 is not a reason to bet. Margin accuracy and Brier score are diagnostics, and stage 4 decides. A
  candidate that loses to the market price on unseen weeks stays in research, however accurate it is.
- Freeze first, score once. A candidate's spec is committed with a hash before its first scored week. A changed
  candidate is a new candidate with a new freeze.
- Pinned counts change only through `regenerate --apply`, with the reason recorded in the test.
- BLOCKED_CONTESTED and DOWNGRADED_BY_VERIFIER inputs need an owner decision. Passing evidence does not promote them.

## Status at 2026-11-20
- Certified inputs: stages 1–2 complete for 34 new inputs (#94 9, #95 5, #96 20). Missing PRIMARY slots went
  886 → 884 (#94) → 873 (#95) → 841 (#96). No input has reached stage 4 in any sport.
- CFB: the home-effect fix passes stage 3 (margin RMSE 17.75 → 16.13 on 2026) and is at stage 5, disabled.
  Stage 4 fails for every frozen candidate (ROI −13% to −15% across families on weeks 6–12; existing WIN/SPREAD
  process −5.1%, CI includes 0).
- Next sports: NBA and CBB derived inputs (#94) and NFL batch 4 (#95) are certified but untested at stage 4. They
  need the same freeze → forward-quote → official-settlement pipeline. Use committed Kalshi catalog history where a
  producer archives it, and never synthesise absent prices.

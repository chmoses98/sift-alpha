# MLB dataset v1: point-in-time audit and catalog decision (RESEARCH_ONLY)

Dataset `f598384b39f7` (12,148 regular-season games 2022-2026, 22 features) was rebuilt from the vault on 2026-11-16 and
reproduced the certified hash. Tool: `python -m alpha_engine.certify.mlb_pit_audit` (evidence
`research/certification/mlb_v1_pit_audit.json`). Decision: `research/certification/certification_mlb_v1_catalog.json`.
Agent-run, not human verified.

| Group | Columns | Pregame status | Valid decision times |
|---|---|---|---|
| Team form (`n, rs_pg, ra_pg, win_pct, rs_l10, ra_l10` x home/away) | 12 | VERIFIED_PIT (games that ended before first pitch) | from the end of the team's latest prior game. Final by T-90m on 99.4% of rows, T-6h 98.3%, **T-24h only 29.2%** (median lead 21.2 h). Early forecasts must recompute as of the decision time. |
| Starter form (`sp_n, sp_ip_ps, sp_ra9, sp_k_rate, sp_bb_rate` x home/away) | 10 | NOT VERIFIED: statistics are prior-start aggregates, but the starter IDENTITY is the box-score starter | none certified. Timestamped pregame starter captures (edge-finder-api `data/slates`) cover 28.1% of 2026 starter slots and 0% of 2022-2025; where covered, the box-score starter differs from the pregame one in 9 of 1,364 slots (0.66%, late scratches). |

Catalog: no existing MLB catalog input is fully implemented by v1 columns with verified pregame availability
(closest: `mlb.pythag_luck`, `mlb.wins_to_date_and_games_remaining`; reasons in the decision file). Training-ready
inputs stay **48**; the 1,649-input map is unchanged; `dataset_versions.json` keeps MLB `training_ready: false`.

Path to MLB promotion (v1.1, needs a new blind re-implementation; never edit v1):
1. Add Pythagorean expectation and actual-minus-Pythagorean columns (and one-run record) -> `mlb.pythag_luck`.
2. Add games remaining from the schedule and suspended/tie handling -> `mlb.wins_to_date_and_games_remaining`.
3. Starter features only with a timestamped probable-starter vintage per decision time (forward capture from 2027,
   or a recovered historical vintage); keep the box-score starter as a separate, labelled retrospective column.

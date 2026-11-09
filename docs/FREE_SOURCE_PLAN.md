# Free-source acquisition plan (RESEARCH_ONLY, $0)

Status: **claims, not implementations.** Per-sport blind mappers (Claude agents) mapped each candidate input to source, columns, event time, history and computation
(`research/input_research/data_foundation/verification/source_mapping/`). `source_mapping.py` aggregates them into `free_source_plan.json`. SOURCE_MAPPED != built != verified.

| sport | mapped | MEASURED | PARTIAL | no new permission | terms pending | owner action | no free path | prospective capture |
|---|---|---|---|---|---|---|---|---|
| CBB | 153 | 53 | 62 | 0 | 105 | 0 | 34 | 15 |
| CFB | 129 | 34 | 54 | 0 | 24 | 64 | 16 | 13 |
| MLB | 222 | 47 | 107 | 148 | 1 | 0 | 48 | 30 |
| NBA | 158 | 26 | 71 | 2 | 95 | 0 | 43 | 17 |
| NFL | 253 | 118 | 86 | 185 | 0 | 0 | 19 | 66 |
| NHL | 84 | 15 | 36 | 8 | 37 | 0 | 14 | 21 |
| SOCCER | 131 | 7 | 80 | 47 | 38 | 0 | 19 | 14 |
| TENNIS | 57 | 0 | 23 | 23 | 0 | 0 | 21 | 12 |

Access classes: NO_NEW_PERMISSION (nflverse CC-BY-4.0, MLB/ESPN/NHL public endpoints the owner's workflows already use, owner archives); TERMS_PENDING (SportsDataverse releases, football-data.co.uk: private-individual/no-bot terms);
NEEDS_OWNER_ACTION (Open-Meteo Previous/Single Runs, CFBD/CBBD key, MoneyPuck, Retrosheet, Wikidata: hosts not reachable or key required; nothing was requested or created). Vintage-dependent inputs are never filled from observed or later data: they need prospective capture.

## Measured this phase (`source_samples/*.json`)
- nflverse injuries carry `date_modified` 2010-2024 (2009: 0.4%, 2025: absent); snap counts start 2013; depth charts only dated in 2025.
- SportsDataverse bulk assets reachable (NHL shifts/officials, NBA/CBB pbp); licence/upstream terms unverified -> TERMS_PENDING.
- ESPN officials history for CBB/NBA/NHL are as-played (not pregame assignments).
- Open-Meteo vintage audit: host unreachable here, so no vintage was verified; request documented only.

## Independent replay of new builders (`alpha_engine/features/nfl_ext.py`)
`nfl.injuries_pit` (PARTIAL) and `nfl.snaps` (PARTIAL): determinism, truncation (3 cuts), future-outcome perturbation (3 cuts/seeds), own-game, post-kickoff-injury scramble, non-vacuity all pass.
The first injuries run FAILED the perturbation test (a season-wide timestamp-share gate let future rows change earlier features); fixed by per-team-game availability and rerun. Evidence: `verification/replay_ext/NFL.json`.
Coverage: injuries 85.3% (2010-2025), snaps 76.6% (2013-). Agent verification only; not human expert verification.

# Scientific truth gates: game context, players, projections

**P0 parallel to Kalshi warehouse [#4](https://github.com/chmoses98/sift-alpha/issues/4)** and governed by [sports truth #5](https://github.com/chmoses98/sift-alpha/issues/5). The existing sports repositories have sophisticated research and several identified data defects. Running a model on unverified roster, lineup, pitch or game-state inputs can make a false pattern look predictive or profitable.

## Reality check from existing audits

| Sport | Existing concrete evidence | What Alpha must verify |
|---|---|---|
| NBA | `nba-edge-finder/docs/research/w1_nba/player_team_identity_roster_audit.json`: 501 historical games; v1 244 stale third-team roster entries; comparative `both` configuration removes them, with 1 wrong-team box case remaining | Whether fix is in **published forecast path**, current player identity and minute/usage inputs, and independently confirmed holdout |
| CBB | `cbb-edge-finder/docs/ROSTER_SOURCE_AUDIT.md`: inconsistent ESPN prior-season carryover | Roster membership, transfers and season truth at capture time; no copied roster as independently fresh |
| MLB | `edge-finder-api/data/edgelab/analytics/latest_research_research_data_quality.json` (Aug 1–20): 0/23,295 observed hitter-hits contracts evaluated by model; unequal horizon coverage | Pitcher/batter/lineup/park/pitch-mix records, publication time, family-by-family projection and outcome coverage |
| Tennis | `Tennis-Edge-Finder/docs/FIRST_BALL_TRUTH.md`: nominal exchange occurrence time is not reliable first ball | independent bounded start evidence; C/unknown cannot qualify strict pregame |
| NFL | `nfl-edge-finder/nfl_edge/projection/quality.py`: horizon quality classes and separate validation flags | audit whether source timestamps, minutes/players, outcomes and calibration carry through actual publications |
| Soccer | `soccer-edge-finder/docs/TEMPORAL_INTEGRITY.md`: point-in-time guard | verify freshness, source truth and available lineup data independently (a temporal check is not comprehensive accuracy) |
| NHL | `NHL-edge-finder/docs/research/INTEGRITY_REGISTRY.json`: file hashes | validate independent roster/goalie confirmations, player minute modeling, genuine game state |
| CFB | `cfb-edge-finder/data/scripting/validation/control_prospective_2026/protocol.json`: preregistered context/control evidence | lineage, opponent/tempo/personal matchup features, source scores and forecast coverage |

## What has actually been implemented in Alpha

`alpha_engine/science_quality.py` is an offline, deterministic **structural** game-state and projection gate. It catches:
- Unknown game/team identity, player assigned to wrong team, conflicting roster membership, unsupported starter claims.
- Sources or individual facts observed after prediction cutoff; later model fit, training outcome, forecast input or publication; unrecorded or uncertain actual-start bracket.
- Apparent two-provider corroboration using the **same original provider**; unchecked usage rights and estimated/not-confirmed injuries, starters and lineups.
- Missing model artifact identifiers, mismatched event IDs and incoherent probability distributions (binary, categorical and quantile crossings).

Results: `QUARANTINED`, `LIMITED`, or `STRUCTURE_PASS_UNCERTIFIED`. **The last category does NOT mean data is correct.** Declared source metadata, fake provider identifiers and simulated test records are not independent proof. Even a clean shape never permits a validated scientific result or trading authority. Adversarial fixture tests live in `tests/test_science_quality.py`.

## Next: real factual certification, not green-looking fixtures

1. Build original-provider data audits with immutable raw evidence, timing clocks, identity mappings and independent cross-provider comparisons; detect common-mode data lineage. Respect rights and $0 constraints.
2. Run actual sport-specific quality checks on frozen pregame snapshots—NBA player-team membership and minutes against authentic boxes/lineups; MLB confirmed starters, pitch-by-pitch Statcast and opponent batter/pitch-matchup values if legally available; then parallel workers for all other sports.
3. Compare model snapshots with published inputs/model versions/fit clocks, reconcile team/player distributions and lineup availability, and evaluate forecasting bias/calibration on untouched chronological holdouts.
4. Link certified sport truth to exact historical Kalshi ticker and official contract settlement, then preregister profitability tests at executable prices with valid event-level denominators.
5. Feed detected defects into the autonomous director with explicit stop/repair priorities, **not fabricated discoveries**. Report each sport's data coverage, freshness, quality and known gaps.

Zero-cost, no trading, no approval of money or live deployment.

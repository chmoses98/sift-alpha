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

## Point-in-time availability hardening (P0)

The sport-side gate now distinguishes **when a source or fact was observed** from **when it was actually available** to the historical decision maker. A late-arriving lineup, delayed feed, corrected outcome or model feature cannot become a valid earlier input just because its original observation clock predates the decision. The source and fact contracts include `observed_at` and `available_at`; forecasts additionally include `latest_input_available_at` and `last_training_label_available_at`. These clocks are compared against decision, publication and model-fit cutoffs as applicable.

A missing availability clock yields `LIMITED`, not structural clearance. Future availability, fact observation later than its purported source capture, corrected training labels unavailable by model fit, duplicate source identifiers, and malformed identities yield `QUARANTINED`. This is a **synthetic contract and adversarial test** improvement, not evidence that existing eight-sport pipelines actually archive the required clocks. An upstream `observed_at` should be the time the fact was recorded by that source; a source's capture time cannot precede the observations it purports to contain. When a sport cannot establish these clocks from its original archive, mark that record unavailable/limited instead of inventing timestamps.

**Retrospective actual-start verification is separate from pregame feature availability.** A postgame verified start may be used to classify historical eligibility, but must never be smuggled into the forecast's pregame feature set. The current start bracket still lacks independent raw-provider authentication; `STRUCTURE_PASS_UNCERTIFIED` never certifies actual kickoff, roster accuracy, projections, calibration, market settlement or execution.

## Historical MLB model-coverage denominator reconciliation (P0 #5)

The pinned August 1–20, 2026 MLB source-side report contains **138,158 market opportunity rows**, **80,526 reported unique market tickers**, and **353 reported unique games**. These are *different units* and must never be used interchangeably or summed as independent events. Across the report's 14 market families, **694/138,158 opportunity rows (0.5023%)** were model-evaluated; **137,464 (99.4977%)** lacked a model evaluation. The same 137,464 rows lacked a temporally valid model evaluation. **120,765** rows are reported settled, **14,074** not settled, and **3,319** unresolved. For hitter_hits, **0/23,295** market observations were model-evaluated. These counts are historical *reported* evidence, not a statement about today's published model coverage.

The Alpha sports_quality_evidence audit now fails closed if the total opportunity denominator, per-family observed/evaluated/settled counts, report row count, settlement-status partition, missing forecast totals, or claimed family rates disagree. Adversarial tests attack missing families, corrupted denominators, wrong coverage rates, NaN, bool-as-int, impossible identity counts, and impossible chronology-eligibility counts. The CLI's real hash-pinned MLB audit must pass these checks in CI. No synthetic row is represented as an observed market.

**Scientific limitation:** Even the source report's rowsLackingExecutablePregamePrice: 0 is not independent proof that quotes were actually executable with available size and fees. modelEvaluated is not equivalent to a validated pregame forecast, SETTLED is not independent exchange certification, and one physical game can generate thousands of correlated rows. This audit exposes denominator completeness and a major model-coverage hole; it does not certify original-provider MLB pitch/lineup accuracy, calibration, current production deployment, or profitability.

## Next: real factual certification, not green-looking fixtures

1. Build original-provider data audits with immutable raw evidence, timing clocks, identity mappings and independent cross-provider comparisons; detect common-mode data lineage. Respect rights and $0 constraints.
2. Run actual sport-specific quality checks on frozen pregame snapshots—NBA player-team membership and minutes against authentic boxes/lineups; MLB confirmed starters, pitch-by-pitch Statcast and opponent batter/pitch-matchup values if legally available; then parallel workers for all other sports.
3. Compare model snapshots with published inputs/model versions/fit clocks, reconcile team/player distributions and lineup availability, and evaluate forecasting bias/calibration on untouched chronological holdouts.
4. Link certified sport truth to exact historical Kalshi ticker and official contract settlement, then preregister profitability tests at executable prices with valid event-level denominators.
5. Feed detected defects into the autonomous director with explicit stop/repair priorities, **not fabricated discoveries**. Report each sport's data coverage, freshness, quality and known gaps.

Zero-cost, no trading, no approval of money or live deployment.

# Prospective NFL experiments (RESEARCH_ONLY)

Two forward-only experiments, each frozen before the games they score. No orders, no paid services, no market price as a model input.

| experiment | what is frozen | label |
|---|---|---|
| `nfl_totals_v1` | strict point-in-time ridge model (config id in `FREEZE.json`), coefficients fitted on seasons <= 2025, 2014-2025 reproduction digest in `FREEZE_DIGEST.json` | market-independent inputs, all games |
| `nfl_player_v3_listed_emp` | declared player variant, coefficients fitted <= 2024 | **MARKET_SELECTED_POPULATION** (only exchange-listed players; listed and not Out => involved) |

## Cycle (`python -m alpha_engine.lab.prospective cycle`)
refresh free nflverse data -> rebuild the frozen model and **abort if its 2014-2025 predictions no longer match the digest** -> append a new time-stamped prediction only when `mu` changed ->
ingest the verified Kalshi collector's snapshots (`market-data:data/kalshi/capture`, read-only) -> evaluate -> publish append-only to the `prospective-data` branch.

* Predictions are immutable; a decision uses the **latest prediction generated before the decision time**.
* Quotes: collector runs (with their `observed_at`, completeness, source path and git blob ids) and a **fail-closed** public-REST capture (`capture`, every page or nothing, each page time-stamped). The first 266 quotes (single timestamp, completeness unverifiable) are tagged `legacy_unverified` and are never decision inputs.
* Freshness = age of the last **complete** observation of the contract's series at the decision time (<= 30 min), not the age of the row. Missed captures are reported (`capture_gaps`, per-game reason codes in `decision_audit.json`); a missing capture is never reconstructed.
* Publishing is append-only: every ledger already on the branch must be a byte-prefix of the new file or nothing is pushed.

## Claim gate (`prospective.claim_gate`)
T-6h decisions, unit = game. PASS_PROVISIONAL requires: >= 60 independent games with bets and scored; Holm over {primary after-fee EV, secondary log-loss gain}; Bonferroni over the pre-registered looks (60, 120, 272); positive lower bound of the one-sided 95% interval on after-fee EV; verified chains; no data-quality flags. It never states profitability; a pass needs independent replication on later games. Null-world simulation (tests) keeps the pass rate <= 5%.

## Operating status is not assumed
GitHub starts scheduled runs hours late under load and runs schedules only from the default branch, so `.github/workflows/nfl-prospective-cycle.yml` is inert until merged. The collector's own recorded staleness is reported in `REPORT.json`. Read `REPORT.json` and `decision_audit.json`, not the dashboard panel, for what actually exists.

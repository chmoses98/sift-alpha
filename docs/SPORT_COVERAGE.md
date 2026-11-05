# Alpha — sport coverage and the path to a unified research engine

**Status (2026-10-30): scope registry + intake UI implemented in the initial migrated research-desk branch; per-sport evidence adapters and automated discovery are not yet built.** This is the source of truth for what Alpha *recognizes*, not what Alpha can currently *forecast* or trade.

## Product principle

A sport must never disappear because we have not written a model for it. Any supported or custom sport can enter Alpha's research queue with a single question. Alpha shows exactly which work already exists, what data is missing, and whether model or pricing evidence has ever earned authority.

Public SIFT Sports Intelligence can show projections and analysis where available. Private Alpha research tests what adds information. There is no automatic promotion from a displayed forecast to a trade.

## The starting portfolio

| Sport / market | Existing SIFT research repo | Near-term question |
|---|---|---|
| NFL | yes | Can a selection rule improve CLV and net returns after point-in-time availability corrections? |
| CFB (FBS) | yes | Which script/control signals genuinely forecast outcomes or price moves? |
| CFB (FCS) | no standalone engine | Does CFB's market catalogue cover the contracts, and do we have sufficient quality for a separate model? |
| NBA | yes | Do market-anchored selectors mitigate winner's-curse selection? |
| CBB (men) | yes | Do pre-tip opponent-adjusted forecasts beat the contemporaneous available market? |
| CBB (women) | no | Find roster truth, matchup and market history; never borrow men's calibration. |
| WNBA | no | Build and independently validate its own minutes/usage and market baselines. |
| MLB | yes | Explore information-lag mechanisms while recognizing existing sharp-market pricing evidence is negative. |
| **NCAA Baseball** | **no standalone engine yet** | Start with game identity, pitching/lineup truth, historical prices, settlement and data rights. Kalshi listed `KXNCAABBGAME` game contracts in 2026. |
| NCAA Softball | no | Verify schedule, pitchers, run distribution, historical market coverage. |
| NHL | yes | Establish stronger player-minute/goalie inputs and test against sharp price before selecting bets. |
| Soccer | yes | Validate competition-specific models, motivation, lineups and 1X2 contract semantics. |
| Tennis | yes | Preserve tour/format splits, validated start time and matched market benchmark. |
| Golf, MMA, boxing, F1, esports, cricket | not yet | Feasibility first: event taxonomy, independent results, pre-event market data, and modeled mechanisms. |
| Rugby, lacrosse, college volleyball, darts, chess, other disciplines | not yet | Opportunistic discovery; no prior claim that attractive prices or reliable data exist. |
| Newly listed / custom | no | Accept a new research question without code changes; later link the true exchange series once verified. |

The detailed grouped inventory lives in `src/sport-registry.mjs`. The labels `Core`, `Expansion`, and `Exploratory` indicate **coverage priorities**, not confidence, profitability, market depth or an order to place a bet.

Kalshi's public [sports directory](https://kalshi.com/category/sports/all-sports/all/combos) visibly includes a broad range of categories. The [college baseball game example](https://kalshi.com/markets/kxncaabbgame/college-baseball-game/kxncaabbgame-26may292100arsole) establishes historic market availability only. Neither source promises a continuously populated contract family or a liquid bid/ask today.

## One common contract for every sport (planned)

Instead of bespoke lab pages and custom code every time a sport is added, adapters should produce this unified interface:

- `sport_id`, `competition_id`, `event_id`: stable sport/league/event identity with aliases and source attribution.
- `event_start`, `state`, `retrieved_at`, `published_at`: explicit event and point-in-time clock.
- `market_catalogue`: series, events and exact contract/settlement family, including unknown/unclassified items.
- `data_capabilities`: game results, confirmed participants/lineups, availability, history, market quotes, reference prices; each with status and coverage rather than missing-as-zero.
- `model_capabilities`: prediction type, input cutoff, version, evaluated sample, reliability and authority. **Not built** is a normal state.
- `market_execution`: side-specific available ask, depth, fees, slippage and quote observation time.
- `hypothesis`: falsifiable question, immutable protocol, control, selection, rule cutoff and registered outcome.
- `evidence`: source commit/hash, independent events, split (development/holdout/prospective), estimates/intervals, audit results and interpretation.
- `next_action`: one clear action, assigned cause, and blockers.

A market contract can be *discovered*, *mapped*, *priced*, *backtested*, *prospectively validated*, and *approved for an execution pilot*. These are separate states. A sport with available research is **not** a sport with a validated strategy.

## Automated expansion must discover, not assume

1. Periodically read the actual sports filter taxonomy and series catalogue using point-in-time exchange responses.
2. Match series by authoritative competition metadata, not guessed ticker substrings. Isolate esports vs baseball collisions and other lookalikes.
3. Import recognized sport/competition IDs into the registry; quarantine new or ambiguous series in the **Other / Newly Listed** research intake.
4. Detect sources, odds and outcome coverage; never convert missing prices into zero or make a missing model look like a negative edge.
5. Create an actionable research card **only** when a distinct testable hypothesis and a reproducible source are present.
6. Validate reference contract equivalence, pregame timestamps and settlement rules before any profitability testing.
7. Score opportunities on **ability to test**, **potential information advantage**, **execution costs**, **market depth**, **data burden**, and **research uncertainty** — never on the largest raw discrepancy alone.
8. Keep research data and private trading credentials in a protected service, not GitHub Pages or browser localStorage.

**Not implemented yet:** auto-sync from Kalshi, college baseball projections, an automatic research runner, real-time data quality dashboards, sportsbook consensus, live funds, or AutoBet.

## UX acceptance requirements

- Find CFB, CBB or NCAA Baseball from the single **Browse sports** control; open its real record.
- Pick any other registered sport and start its first research question from the same flow.
- Add a completely new sport without modifying code or confusing it with a validated model.
- Filter by sport or search ordinary names like `College Baseball`, not hidden ticker IDs.
- One source click to verify every seeded finding; unsupported sports clearly say research not built.
- iPhone: no horizontal scroll, controls work, notes and task checklist survive reload, and research can be exported.
- Keep the coverage inventory collapsed when the user is doing a specific task.

## First engineering priority after this branch

Produce the **NCAA Baseball Data Feasibility Report** (schedule/results, pitcher availability, historical Kalshi game coverage and depth, independent reference prices if available, leakage and data rights). In parallel, ingest CFB and CBB research reports through the same read-only interface. Do not build a college baseball predictive model first and only then discover the available market evidence is unusable.

Sport expansion should be informed by real opportunities. Listing 28 sports is coverage readiness, **not** having 28 profitable engines.

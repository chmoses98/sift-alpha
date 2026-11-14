# SIFT Alpha

**All-sport research laboratory** — start with a question, inspect the evidence, challenge a projection, and preserve the result. Usability comes before visual decoration.

This repository is **public research code**, **not an automated betting system**. No bankroll records, private strategies, keys, or credentials belong in source, GitHub Actions logs, artifacts, or the browser-only research notes.

## What works in the first research desk

- Search, filter and inspect research records with links to the underlying SIFT sport repositories.
- One-click **Browse sports** covering 28 research tracks, including CFB, CBB, NCAA baseball/softball, existing professional sports, and additional exploratory disciplines.
- Create a research question for any listed sport or add an entirely new sport without changing code.
- Read **what the evidence says / what it cannot support / next useful action**.
- Maintain a local checklist and notes; export/import a JSON snapshot; copy a context-rich research brief into an analysis session.
- Touch-friendly responsive layout for iPhone and desktop.

Seven manually curated source-linked research records are included as **dated examples**, not live results. The source code does not currently run simulations, automatically ingest repo updates, compute new projections, or place trades. Existing CFB/CBB research repositories are *sources*, while NCAA baseball remains a feasibility track without a SIFT model.

## Run

Requires Node.js 22+ and npm.

```sh
npm install
npm run dev
npm test
npm run build
```

To test the UI locally:

```sh
npx playwright install chromium webkit
npm run e2e
```

The separate GitHub Actions CI workflow builds and runs unit tests on PRs. It has **no recurring schedule** and does not deploy anything.

## Zero-cost operating policy

**Alpha operates under a $0 incremental spending rule until the owner explicitly approves a specific exception.** Do not enable paid APIs, compute, inference, data, or paid fallbacks; automation must stop safely at free-tier limits. Quality-gated research and honest limitations take priority over volume. See the [full cost policy](docs/COST_POLICY.md).

## Kalshi archive-first research

**Alpha's first research priority is rebuilding our already-collected Kalshi market history across sports.** Captured prices, bids/asks, trades, depth and settlements provide a valuable empirical research laboratory, subject to the strictest point-in-time and execution checks. The starting cross-sport archive inventory is in [research/kalshi_archive_sources.json](research/kalshi_archive_sources.json), with a [$0 read-only inventory tool](alpha_engine/market_inventory.py), [full research plan](docs/KALSHI_MARKET_RESEARCH.md), and [P0 tracking issue](https://github.com/chmoses98/sift-alpha/issues/4). Listing locations is **not** yet reconstructing price histories or verifying profitable edges.

## Input research (what predicts each market)

The dashboard's **Input research** section lets you pick any sport and market family and see every candidate predictive input with its rationale, data source/completeness/freshness, current-model use, learned importance/weight, evidence for or against it, performance against the relevant benchmark, remaining gaps and the ranked next questions. **RESEARCH_ONLY**: hypotheses and availability audits are not evidence; only the NFL game total/spread/winner (vs the near-close line) and NFL QB passing yards (vs the QB's own history) have predictive tests so far, and nothing is above L2. See [docs/INPUT_RESEARCH.md](docs/INPUT_RESEARCH.md).

## Data foundation pipeline

The dashboard's **Data foundation pipeline** section follows every market from its required inputs to datasets, collectors, features, research challengers and evaluations, with ten explicit stages per input (never one percentage). See [docs/DATA_FOUNDATION_OPS.md](docs/DATA_FOUNDATION_OPS.md). **RESEARCH_ONLY**: the three P0 challengers (NBA, CBB, NHL) are research results on archived data; none beats the market price and every incumbent is retained.

## Universal evaluation standard

[Alpha Universal Evaluation Standard v1](docs/ALPHA_EVALUATION_STANDARD_V1.md) (`alpha_eval/`, `python -m alpha_eval ...`) scores every sport, model and market on accuracy, directional calibration, model-vs-market, fee-adjusted hypothetical economics and signed CLV, with explicit GRADED / PENDING / UNSUPPORTED / BLOCKED accounting. See the generated [coverage and adoption matrix](docs/alpha_eval/COVERAGE_MATRIX.md). RESEARCH_ONLY; example reports are synthetic.

## Research standards

A measured projection discrepancy is **not** a proven +EV bet. Strategies must be evaluated against contemporaneous market prices, honest fees and fills, calibrated probabilities, independent out-of-sample observations, and explicit uncertainty. The research lab may reject every candidate.

Future components: versioned evidence ingestion, a reproducible experiment runner, projection and market comparison workspaces, research history, and a separately secured private trading service (if any strategy earns live authority).

See [Sport coverage and unified adapters](docs/SPORT_COVERAGE.md) for scope, roadmap and planned data contracts, and [Research-desk implementation](docs/RESEARCH_DESK.md) for the first prototype's limitations.

## Origin

Migrated from the isolated Alpha code in [SIFT Sports Intelligence PR #159](https://github.com/chmoses98/sift-sports-intelligence/pull/159). The consumer SIFT app and its SIFT 3.0 work remain separate. This repository is the **new canonical home** for Alpha development.

## Dashboard deployment
One source: `main`. Vercel (project `sift-alpha-dashboard`) and the GitHub Pages workflow both build this repository's `main`; there is no separate dashboard branch to keep in sync.
GitHub Pages (free) is the verified path: its workflow stamps the exact commit, deploys, then reads the PUBLISHED site back and checks commit, sections, data vintage, private patterns and desktop/390 px layout.
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

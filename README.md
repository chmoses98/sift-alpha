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

## Research standards

A measured projection discrepancy is **not** a proven +EV bet. Strategies must be evaluated against contemporaneous market prices, honest fees and fills, calibrated probabilities, independent out-of-sample observations, and explicit uncertainty. The research lab may reject every candidate.

Future components: versioned evidence ingestion, a reproducible experiment runner, projection and market comparison workspaces, research history, and a separately secured private trading service (if any strategy earns live authority).

See [Sport coverage and unified adapters](docs/SPORT_COVERAGE.md) for scope, roadmap and planned data contracts, and [Research-desk implementation](docs/RESEARCH_DESK.md) for the first prototype's limitations.

## Origin

Migrated from the isolated Alpha code in [SIFT Sports Intelligence PR #159](https://github.com/chmoses98/sift-sports-intelligence/pull/159). The consumer SIFT app and its SIFT 3.0 work remain separate. This repository is the **new canonical home** for Alpha development.

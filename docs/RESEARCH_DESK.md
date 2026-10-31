# SIFT Alpha — Research Desk v0

**Status: isolated prototype, not shipped; multi-sport discovery and projections are not live.** Alpha is a *lab for doing research*, not an automatic betting recommendations page or trading interface. This is the first interaction slice and contains **only existing public, source-linked research findings** and browser-local drafts.

## The one-minute journey
1. Open the Research Desk. The left side answers **what work exists**, not what numbers are most impressive.
2. Use **Browse sports** to locate CFB, CBB, NCAA Baseball and expansion disciplines; a sport without a study opens an honest new-question form. Tap a question. The right side answers: **what did we test, what did we learn, what can't we claim, what is the next useful action?**
3. Follow the original evidence link, check off the next steps, add a working note, or tap **Copy research brief** to hand the context to an AI coding/research session.
4. Start a question with **+ New question** (only a question and sport required), then fill in hypotheses and a testing plan later.
5. Export a JSON backup (notes, drafts and checklist progress) for another device or restore one with Import.

On phones, the library is followed by the details, and tapping a record scrolls directly to it. No graphs, animations, fake live signals, or betting nudges.

## Run independently

Use the existing SIFT root dependencies:

```bash
npm install
npm run dev
# Open the localhost URL shown by Vite.
npm test
npm run build
npm run e2e   # desktop + iPhone WebKit journeys
```

The dedicated config builds to `dist/`. **It does not replace, alter, or deploy SIFT 2, v4, v3, public Pages, production quote infrastructure, or any projection model.** No new scheduled GitHub runner is introduced. UI acceptance tests are opt-in, so this prototype does not add another recurring job to the already busy Actions queue.

## Comprehensive sport coverage\n\nThe sport registry now covers 28 core, expansion and exploratory tracks, including college football (FBS/FCS), men's and women's college basketball, NCAA baseball, NCAA softball, WNBA, golf, MMA, Formula 1, esports and others. Grouped drop-downs keep the workflow small. A new sport can be added as a local draft without a code change.\n\n**Coverage is not model support.** Only eight sport tracks have existing research repos; NCAA Baseball is a market-verified **discovery** task, not a completed model. See [SPORT_COVERAGE.md](SPORT_COVERAGE.md) for scope, pipeline requirements and evidence gates.\n\n## Evidence integrity

- Every seeded research finding (or clearly labeled discovery hypothesis) is dated and linked to its actual originating GitHub issue or PR.
- The seed records are **point-in-time summaries**, not auto-refreshing evaluations. The PRs' draft status is shown where applicable.
- No paper ROI is represented as personal account profit. No prospective significance is invented.
- Drafts have no conclusion, market edge, trade authority or source until evidence is supplied.
- Data classification is explicit: *curated source-linked snapshots* vs *personal unvalidated drafts*.
- A higher-confidence stage will require immutable source snapshots, as-of timestamps, authorship, and a canonical cross-repo evidence registry. This first cut intentionally does **not** pretend to supply that automation.

## Privacy / persistence boundary

The current UI is local-first: notes and drafts live in this browser's localStorage. Export creates a user-controlled JSON file; Import explicitly confirms replacement. **localStorage is not a secure database**, is not encrypted, and is not synchronized. Do not put strategy secrets, Kalshi credentials, financial account records, or other sensitive information in these notes. Nothing here sends orders or requires a Kalshi API key.

The repository and branch are public, so **only public research metadata belongs in the code**. Future private strategies, authenticated workspaces and trading services must reside behind actual authorization and private persistence; hiding a route, using a client-side password or relying on an unpublished branch would not protect them.

## Experience rules (non-negotiable)
- Research question first, numbers second.
- Show a clear evidence status and what would change the conclusion.
- One action per task; do not require five tabs to finish simple research work.
- Comfortable on iPhone, keyboard-accessible on desktop, 44px minimum interactive controls.
- No fabricated probabilities, rankings, CLV, fees, paper fills or conclusions.
- Preserve a one-click path to original evidence, with research timestamps visible.
- Users can complete ordinary research without understanding GitHub internals.
- No trading execution without an independently validated strategy and explicit operator controls.

## Next engineering slices

**Slice 2 — Evidence ingestion**: a private-capable service importing selected sport-repo reports through a versioned schema; capture source commit, experiment ID, as-of time, parent hypothesis, independent-game sample and validity. No user secrets in the public client.

**Slice 3 — Research execution**: preregister hypothesis/protocol, read-only replay job and comparison against a frozen baseline, per-step diagnostics and a reproducible result attachment. Separate retrospective discovery from forward evidence.

**Slice 4 — Model workbench**: projection comparisons and matchup/market diagnostics, explanation of what changed, provenance and uncertainty. These capabilities can eventually feed the public SIFT projection experience, without exporting private trading logic.

**Slice 5 — Separate private risk/execution system**: not part of the Research Desk. Credentials, controls, fills and strategies must never appear in public Pages output.

This plan is intentionally incremental: use the desk, see where it is confusing or slow, fix that before expanding its feature count.

# Publish the SIFT Alpha research desk (no Vercel)

The Vite research desk lives on `build/alpha-research-desk`, separate from the small
default `main` code-only research repository. The app contains a CLV page built from
`research/audit/clv/clv_summary.json`, which is aggregate-only and **does not include**
individual contract identifiers, order IDs, stake, P&L or ROI.

## Free deployment

`.github/workflows/alpha-pages.yml` builds and deploys the Vite app to GitHub Pages,
triggered by updates to the research branch. This avoids Vercel and all recurring hosting fees.

GitHub Pages may need initial repository configuration by someone with repository settings access:
**Settings -> Pages -> Build and deployment -> Source: GitHub Actions**.
Only a repository administrator can complete that step. Do not call a deployment successful
until the Actions run is green **and** the served URL is inspected.

Expected default URL *after verified deployment* (not evidence the page is already live):
`https://chmoses98.github.io/sift-alpha/`

The workflow:
1. Checkout only the research-desk branch with GitHub's ephemeral token (no repo credentials persisted).
2. Run JS unit tests, validate public dataset schema/privacy, and build the static site.
3. Upload only `dist/` to GitHub Pages.
4. Publish via the GitHub Pages deployment action.

### Safety and accuracy

- The public app may display **research-only** synthetic/model evidence; it must never
  imply betting authority or guaranteed profitability.
- No authenticated Kalshi requests, secrets, trading orders, private ledgers or
  individual stakes are necessary to build or publish.
- The privacy check refuses order/fill IDs, individual market tickers, and private
  per-wager economics in the CLV JSON. It is a limited guard, not an overall
  security audit of all public source files.
- The denominator for the positive hypothetical NFL selection CLV is model-side
  shadow observations; these are **not** real user-selected wagers.
- Deployed static metrics are a dated snapshot and should show the source timestamp.
- Page setup, cache invalidation, served content, and iPhone layout must be verified
  against the actual public site after the GitHub Actions deployment succeeds.

The consumer SIFT application in `chmoses98/sift-sports-intelligence` is
intentionally untouched.

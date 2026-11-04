# SIFT Alpha dashboard deployment

**Canonical production: Vercel** — project `sift-alpha-dashboard` (team `moses-projects4`), production branch `main`.
Canonical URL: the project's production domain (record it here once verified: see "Production URL" below).

## How it deploys
- Vercel builds from the repository root using `vercel.json`: Vite, `npm ci`, `npm run build`, output `dist`, Node 22 (`.nvmrc`, `engines`).
- `package-lock.json` is committed; installs are reproducible.
- SPA fallback is a rewrite to `/index.html` (assets excluded).
- `ignoreCommand` skips builds when a push changes none of the dashboard inputs
  (`package*.json`, `vite.config.mjs`, `index.html`, `src/`, `research/audit/`, `vercel.json`, `.nvmrc`).
  Python/research-only pushes therefore don't redeploy.
- Merging to `main` triggers a production deploy. PRs get preview deploys.

## What is public
Only `dist/` (one HTML file, one JS and one CSS bundle). The bundle embeds the aggregate-only JSON from `research/audit/` that the
dashboard imports. Raw datasets, Python code, reports and tests are never served. `Dashboard CI` fails if the CLV payloads
contain wager-level fields or if `dist/` contains data files.

## Vercel settings (project → Settings)
- Framework Preset: Vite; Root Directory: repo root; Build `npm run build`; Output `dist`; Node 22.x.
- **Deployment Protection → Vercel Authentication must be disabled for Production** (or "Only Preview Deployments"),
  so the public production domain needs no login. Preview deployments can stay protected.
  This exposes only the built dashboard above; the repo is not made public by this setting.

## CI
`.github/workflows/dashboard-ci.yml` (path-filtered) runs prerequisites check, `npm ci`, `npm test`, `npm run build` and the privacy check.

## Fallback: GitHub Pages
`.github/workflows/pages.yml` is manual-only (`workflow_dispatch`) and builds the same app from `main`. It is a fallback,
not a second production; do not link it as the primary URL.

## Production URL
See the top of this file / README after first verified deploy.

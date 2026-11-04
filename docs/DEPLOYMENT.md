# SIFT Alpha dashboard deployment

**One source: `main`.** Vercel and GitHub Pages both build it. Vercel — project `sift-alpha-dashboard` (team `moses-projects4`), production branch `main`.
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

## GitHub Pages (free, verified by the workflow)
`.github/workflows/pages.yml` builds the SAME `main` as Vercel (there is no separate dashboard branch) and publishes it to GitHub Pages on manual dispatch and every 6 hours
(the schedule refreshes the live collector status baked into the build). After deploying it reads the PUBLISHED site back and fails unless: the served
`build-info.json` carries the exact commit built, the expected sections and schemas are in the served bundle, no private pattern (ticker-shaped strings, router keys, UUIDs,
`order_id` keys) is present, and the site loads at 1280 px (light and dark) and 390 px with no console errors and no horizontal scroll. Its log prints the data vintage actually served.
Vercel's free tier caps deployments per day, so it can reject builds; Pages is the path whose result is verified end to end.

## Production URL
See the top of this file / README after first verified deploy.

# SIFT projection feed (schema v1, read-only)

One small JSON file of genuine, timestamped SIFT production forecasts for NBA, NHL, CBB, CFB, NFL, MLB.
Built by `python -m sift_feed.build` (stdlib only) from each sport's public production branch.

**Retrieve:** `https://raw.githubusercontent.com/chmoses98/sift-alpha/projection-feed/feed/v1/index.json`
(live once the publication workflow below is approved). Snapshot committed on the review branch:
`.../sift-alpha/claude/fable-phase-16-production-9u2jw7/feed/v1/index.json`.
Per-sport detail, incl. exact contract probabilities: `feed/v1/<sport>.json`.

## Schema
- Top level: `schema_version`, `generated_at` (UTC), `usage`, `sports{SPORT: summary}`, `games[]`, `research[]`.
- Sport summary: `status` ok | stale | offseason | unavailable, `reason`, `model_version`, `projected_at`,
  `data_age_seconds`, `max_age_hours`, `bet_authority`, `source{repo,ref,commit,committed_at,path}`, `derivations`.
- Game: `sport, game_id, start_time, status="production", approval_status="activated_production_forecast",
  home/away{name,abbr}, projected_winner, win_probability{home,away}, projected_margin_home, home_spread,
  spread ("BOS -8.4", favourite negative; "PK"), projected_total, team_totals{home,away}, period_projections,
  contract_count, model_version, projected_at, data_age_seconds, stale, flags, source` (repo@commit:path).
- `research[]`: rows with `approval_status="research_only_not_activated"`. They are NOT SIFT forecasts.
- `null` = the production model did not publish that number. Nothing is filled in. The only derivations
  (listed per sport) are spread sign/string from the model's own margin, a win-probability complement,
  NHL margin = expected home goals - expected away goals, and NFL margin = -(the packet's home spread).

## What "production" means per sport (as of 2026-11-18)
| Sport | Production artifact | Notes |
|---|---|---|
| NBA | `nba-edge-finder@data-archive:slates/latest/slate.json` (nba-sim) | period-winner probs only |
| NHL | `NHL-edge-finder@data-archive:slates/latest/slate.json` (DATA_ONLY_V1) | slates only ~4h before puck drop; SHADOW blocks excluded |
| CBB | `cbb-edge-finder@projections-archive`, incumbent from `main:models/pure/active.json` | challengers excluded; no abbr/contracts |
| NFL | `nfl-edge-finder@handicap-reports:latest/packet.json` model_view (incumbent "shadow-0.4.0") | full-game only |
| CFB | none: production publishes no model projections | pf-cfb shadow shown only in `research[]` |
| MLB | `edge-finder-api@main:app/latest` | offseason |

Every `projection-data` branch is projection-foundation research (`authority: research_only`) and is never production.
All sources say they carry no betting authority (`bet_authority`); this feed is forecasts, not recommendations.

## How ChatGPT should use it
1. Fetch `index.json` once; find the team in `games[]` (match `abbr` or `name`).
2. Say e.g. "SIFT projects Celtics -3.4 at Nuggets, total 234.7, 58% win probability (model nba-sim-0.1.0,
   forecast 2026-11-18T18:14Z)". Always give `projected_at`; if `stale` is true or the sport status is not ok, say so.
3. Never quote a `research[]` row, a null field, or a number you computed as a SIFT projection.
Local check: `python -m sift_feed.say Celtics` (reads only `feed/v1/index.json`).

## Needs owner approval
- Merge `.github/workflows/projection-feed.yml` (no schedule; writes only the `projection-feed` branch).
- Then either dispatch it manually, or set repo variable `SIFT_FEED_AUTOPUBLISH=true` so it runs after each
  existing 6-hourly Pages run. Until then the only copy is the snapshot on the review branch.
- Confirm the per-sport production definitions above (notably CFB = none, NFL incumbent view).

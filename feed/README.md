# SIFT projection feed (schema v1, read-only)

One small JSON file of timestamped SIFT forecasts for NBA, NHL, CBB, CFB, NFL, MLB, each labelled by what
its own source artifact declares. Built by `python -m sift_feed.build` (stdlib only) from public branches.

**Retrieve:** `https://raw.githubusercontent.com/chmoses98/sift-alpha/projection-feed/feed/v1/index.json`
(live once the manual workflow below is approved and dispatched). Snapshot on the review branch:
`.../sift-alpha/claude/fable-phase-16-production-9u2jw7/feed/v1/index.json`.
Per-sport detail (contract probabilities, source path per game): `feed/v1/<sport>.json`.

## source_class (derived only from the artifact's own fields; missing/ambiguous -> weaker class)
- `production`: the artifact itself declares production / approved authority, with no qualifier.
- `operating_unapproved`: the forecast the sport operates on day to day, whose artifact does NOT declare
  production authority. Its declaration is carried verbatim in `source_declaration`.
- `research`: challengers / shadows; only in `research[]`, never in `games[]`.

As built 2026-11-18 no sport's artifact declares production authority:
| Sport | Source | Declares (verbatim, abridged) | Class |
|---|---|---|---|
| NBA | `nba-edge-finder@data-archive:slates/latest/slate.json` | authority_note "All families are RESEARCH ..." | operating_unapproved |
| NHL | `NHL-edge-finder@data-archive:slates/latest/slate.json` | authority "RESEARCH_ONLY" | operating_unapproved |
| CBB | `cbb-edge-finder@projections-archive` incumbent records | model.research_state "research", role "incumbent" | operating_unapproved |
| NFL | `nfl-edge-finder@handicap-reports:latest/packet.json` model_view | real_money_status "NOT VALIDATED ...", model "shadow-0.4.0", caveat "... behind it on game outcomes ..." | operating_unapproved |
| CFB | `cfb-edge-finder@main:data/live/cfb_execution_index.json` | contains_model_projections false | research (pf-cfb shadow rows only) |
| MLB | `edge-finder-api@main:app/latest/board.json` | bet_authority "MANUAL" | offseason, no games |

## Schema
- Top level: `schema_version`, `generated_at` (UTC), `max_age_note`, `stale_after_hours{SPORT}`, `usage`,
  `sports{SPORT: summary}`, `games[]`, `research[]`.
- Sport summary: `status` ok | stale | offseason | unavailable, `reason`, `source_class`, `source_declaration`,
  `model_version`, `projected_at`, `age_hours_at_build`, `stale_after_hours`, `source_updated_at`, `source`;
  `withheld_games` (only when present): games withheld because their numbers failed validation (non-finite,
  probability outside [0, 1], probabilities that do not sum to 1, spread sign or winner inconsistent with the margin).
  A withheld game is never published; the feed is strict JSON (no NaN / Infinity).
- Game: `sport, game_id, start_time, source_class, source_declaration, home/away{name,abbr}, projected_winner,
  win_probability{home,away}, projected_margin_home, home_spread, spread ("BOS -8.4", favourite negative; "PK"),
  projected_total, team_totals{home,away}, period_projections, model_version, projected_at,
  age_hours_at_build, stale, source_updated_at, flags`.
- `null` = the model did not publish that number. The only derivations (listed per sport) are spread
  sign/string from the model's own margin, a win-probability complement, NHL margin = expected home goals -
  expected away goals, and NFL margin = -(the packet's home spread).

## Freshness
`age_hours_at_build`/`stale` are as of `generated_at` only. Consumers must recompute age = now - `projected_at`,
compare with `stale_after_hours[sport]` (NBA 12, NHL 6, CBB 24, CFB/NFL 48, MLB 24), say so when the feed
itself (`generated_at`) is old, and never present a game whose `start_time` has passed as pre-game.

## How ChatGPT should use it
1. Fetch `index.json`; find the team in `games[]` (match `abbr` or `name`).
2. `production`: "SIFT's current operating NBA model projects Celtics -3.4 at Nuggets ...". `operating_unapproved`: "SIFT's operating
   (not production-approved) NBA model projects ...", plus the declaration. Always give `projected_at`.
3. Never quote a `research[]` row unless explicitly asked, and then label it research.
Local check: `python -m sift_feed.say Celtics [--research]` (reads only `feed/v1/index.json`, ages vs now).

## Publication (needs owner approval)
- `.github/workflows/projection-feed.yml` is `workflow_dispatch` only: build -> validate (schema, size,
  labelling) -> push the orphan `projection-feed` branch (the only job with `contents: write`).
- Automatic publishing is not included; it would be a later, separately approved change.
- Confirm the source definitions and classes above.

## Model promotion (two keys)
`sift_feed/operating_models.json` is the consumer key: `promoted: null` (today, every sport) means each sport is served from its
incumbent. A promotion names an exact `model_version` with `approved_by`, `approved_at` and `approval_ref`. A game is then served
from the promoted model only when its newest pregame block from the producer also declares itself activated as the operating
forecast (producer key: NBA `NBA_PAG_OPERATING=1`, CFB `CFB_OAE_OPERATING=1`); its `source_class` still derives from that block's
own declaration and its numbers pass validation (finite, probability in (0, 1), win probability and margin favouring the
same side, finite non-negative period totals); a producer `available: false` stub is never served. Every other game is served
from the incumbent with a `fallback_incumbent: <reason>` flag (CFB has no incumbent,
so it stays `unavailable` with the reason). `sports.<SPORT>.promotion` reports `state` (`active` / `partial` /
`awaiting_producer_activation`), the approval and the counts. Rollback: revert the manifest entry, or unset the producer key.
Tests: `tests/test_sift_feed_promotion.py`.

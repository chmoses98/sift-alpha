# Prospective capture: what exists, what is disabled, how to activate (RESEARCH_ONLY)

61 of the 180 P1 slots (2026-11-20 ledger) need point-in-time evidence that history cannot supply: injury and availability vintages, confirmed lineups and starters,
probable pitchers, starting goalies, kickoff weather forecasts. **A prospective slot stays missing until its vintages exist and pass certification.**
Nothing in this sprint closed one of them, and nothing was scheduled, deployed or activated.

## What was built (2026-11-20)
`alpha_engine/prospective/` (tests: `tests/test_prospective_capture.py`, synthetic fixtures, no network):
- `vintage.py`: one immutable vintage per fetch.
  - **Stored:** the original payload bytes (gzip) and a manifest line with the feed, rights source and tier, URL, capture UTC and HTTP status.
  - **Also recorded:** attempts, errors, SHA-256, the source publication time (when the payload carries one), entity ids, entity count, per-field completeness and parser version.
  - **Failures are recorded, never hidden.** There is no retry on 403/404/429. An existing vintage can never be overwritten.
  - `as_of(T)` returns the latest vintage captured at or before T, verifies its hash and reports freshness. It never returns a later capture.
- `feeds.py`: adapters for the six largest gaps:

| Feed | Rights source | Allowed today | P1 inputs it would feed |
|---|---|---|---|
| NFL injury-report vintages | ESPN | no | nfl.qb (5), intra-week skill availability, with/without redistribution |
| CBB availability snapshots | ESPN | no | cbb.injuries (7), cbb.player_minutes (4), cbb.starters (2) |
| MLB probable pitchers | MLB Stats API | no | mlb.sp_quality (4), starter-change risk; matching rotation-candidate rows |
| MLB confirmed lineups | MLB Stats API | no | mlb.lineup_pit (4), lineup strength delta |
| NHL starting goalies | NHL API | no | nhl.goalie_quality (2), lineup impact |
| Kickoff weather forecasts | NWS api.weather.gov | not registered | nfl/mlb/cfb.weather_pit, nfl.weather_total_response |

## Why every feed refuses to run
A capture runs only when **all three** hold. Each condition is a separate decision:
1. `SIFT_PROSPECTIVE_ENABLED=1`.
2. The feed is listed in an owner activation file (`SIFT_PROSPECTIVE_ACTIVATION`), with the owner's name and approval time.
3. The source has `collection_allowed: true` in `research/input_research/data_foundation/rights_registry.json`.

Today condition 3 is false for ESPN, the MLB Stats API and the NHL API. NWS is not registered at all. A test proves every feed is refused against the real registry before any fetch.

## Do not duplicate existing suppliers
These suppliers already exist. Activate the matching feeds here only if the owner retires them:
- **MLB:** edge-finder-api slate captures (lineup status, probables, 2026-06-15 onward).
- **NBA:** nba-edge-finder hourly injury captures and starters context.
- **NHL:** the capture-worker's goalie observations.
- **CFB:** cfb-edge-finder availability listings.

## Activation plan (owner decisions, in order)
1. **Rights.** Decide each source's tier: an ESPN injury listing, the MLB Stats API schedule and live feed, the NHL schedule, NWS. Record the decision in the rights registry. Engineering cannot clear this.
2. **One live check per feed.** Under activation, fetch one payload, compare it with the parser and fix field paths. The fixtures here are synthetic.
3. **Scheduling.** Proposed cadence:
   - NFL: every 3 h Wednesday to Sunday, plus about 90 minutes before kickoff.
   - CBB: hourly on game days.
   - Weather: 24 h and 3 h before kickoff.
   
   Scheduling is a workflow change and needs the owner. `docs/capture_workflows/capture-vintage.yml.proposed` is the inactive template.
4. **Builders.** After one full season of vintages, build the prospective inputs against `as_of(kickoff)` and certify them with the usual replay and blind match.
   The replay must also show that a vintage captured after kickoff never changes a feature.

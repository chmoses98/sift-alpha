# Phase 13 (2026-11-13): market-first acquisition for the evaluated NBA/NHL game families (RESEARCH_ONLY, $0)

Agent verification only; **not human verified**. Continues `03da1e2`. No key, account, purchase, order, schedule, workflow, PR or merge. Catalog untouched (1,649 inputs; baseline lock and computed coverage not edited or regenerated). Raw data stays outside the repository; only digests are committed.

## Why these inputs
`alpha_eval` (on `main`) grades the NBA game families `KXNBAGAME / KXNBASPREAD / KXNBATOTAL / KXNBATEAMTOTAL` and notes that "Kalshi's official result is not retained in the archive". Scope here = the inputs of the five NBA/NHL game archetypes (`game_moneyline_spread`, `game_total`, `team_total`, `game_moneyline_puckline`, `game_total_and_team_total`) that are not already FULL/PARTIAL/EXCLUDED_MARKET: **50 (sport, input) pairs**. Record: `research/input_research/data_foundation/phase13_market_first_acquisition.json`.

## Result (50 in scope)
| Status | n | Inputs |
|---|---|---|
| VERIFIED_ACQUIRABLE (rights still UNRESOLVED_INTERNAL_ONLY) | 4 | NBA `m.settlement_truth`, NBA `m.rules_text`, NHL `m.rules_text` (current text only), NHL `nhl.settlement_goal_pmf` (source chain + settlement convention; the pmf itself is not built) |
| BLOCKED_NETWORK | 6 | `nba.referee_crew` (official.nba.com), `nba.lineup_adj_rating`, `nba.onoff`, `nba.player_impact`, `nba.nonadditive_absence_curve`, `nba.replacement_level_minutes_absorption` (stats.nba.com CONNECT 403; cdn.nba.com 403; ESPN play-by-play path not tested) |
| BLOCKED_NO_FREE_PIT_SOURCE | 3 | `nba.starters_pit`, `nhl.goalie_start` (NHL API pregame landing has no designated starter; as-played flag only), `nhl.injuries_pit` |
| PARTIAL_EVIDENCE | 1 | `nhl.goalie_quality` (raw rolling inputs acquirable; starter dependency not PIT) |
| NOT_ADDRESSED_THIS_PHASE | 36 | mostly derived/model inputs (curves, hazards, series models) whose raw data is already sampled or blocked |
Outside the scope list but strengthened: `nba.injuries_pit`, `nba.status_resolution_prob` (official report history), NHL `m.settlement_truth` (Kalshi's own result).

## 1. Kalshi official settlements (`alpha_engine/collect/kalshi_settlements.py`; digest `source_samples/kalshi_settlements_20261113.json`)
Anonymous `GET /trade-api/v2/markets?status=settled` and `/historical/markets` (exchange `/historical/cutoff`: markets settled before 2026-09-13 move to the historical endpoint). Collector: manual only, <= 200 calls/invocation, >= 2 s pause (5 s used), 429 back-off 15/30/60/120 s then stop, any other non-200 stops, cache must be outside the repo. 124 logged calls (34 got 429 and backed off; none failed). 13 offline tests (`tests/test_kalshi_settlements.py`).
* 8 series, 81,626 settled markets: `result`, `settlement_ts`, `settlement_value_dollars`, `rules_primary` 100% filled. `occurrence_datetime` is mostly missing on historical rows (dates come from ticker/close_time).
* Depth (pagination exhausted): KXNBAGAME from 2025-04-16, KXNHLGAME from 2025-04-20, KXNHLTOTAL/SPREAD from 2025-10-23, KXNHLTEAMTOTAL from 2026-09-30. KXNBASPREAD/KXNBATOTAL stopped at the 15-call cap, earliest date **not measured**.
* Independent checks: **NHL** vs NHL API `/v1/score/{date}` (316 dates, 1,911 games): 26,051/26,051 agree when the shootout winner is credited a goal; 130 total/team-total markets in shootout games disagree under the other convention, so **Kalshi NHL totals count the shootout goal** (official final score). **NBA** vs ESPN scoreboard (304 dates): 55,410/55,414 agree; all 52,046 spread/total/team-total markets agree; the 4 misses are 2 **preseason** events (2025-10-10 BOS@TOR, ORL@PHI) that Kalshi settled at 23:58 UTC, about an hour after the 23:00 tip, with the opposite winner to ESPN's final. Grade on Kalshi's result and flag such events.
* Internal: every winner event has exactly one YES (3,589); no threshold ladder is non-monotonic (9,950); 72 markets settled `scalar` (fair price) and are neither YES nor NO.
* Point in time: a settlement is a post-event label known at `settlement_ts`; never a pre-game input. Rules text: the API serves only the current text.

## 2. NBA official injury report (`source_samples/nba_injury_report_20261113.json`)
`ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{HH}{AM|PM}.pdf` fetched for dates from 2019-10-23 to 2025-12-15; from 2026-01-15 at the latest the name is `..._{HH}_{MM}{AM|PM}.pdf` with 15-minute issues (the old names return 403 from then on). Every sample has the issue stamp in its header and all 7 columns (game date/time, matchup, team, player, status, reason). robots.txt does not disallow the path (Crawl-Delay 1). 32 GETs. Not proven: that files are never re-uploaded under the same name (compare sha256 with the owner's archive).

## 3. Rights (unchanged tiers; `rights_registry.json` `phase13_rights_evidence`, `source_samples/rights_and_access_20261113.json`)
Kalshi, NBA, NHL and ESPN terms could **not** be read (kalshi.com / docs / assets, nba.com, nhl.com blocked by the proxy; ESPN robots 403). Everything above stays `UNRESOLVED_INTERNAL_ONLY`: internal research grading only, no redistribution, no commercial claim. api-web.nhle.com robots carries `ai-train=no`: never train models on that data.

## Owner actions (none taken)
1. Read Kalshi's API / market-data terms (or allow `kalshi.com`, `docs.kalshi.com`, `assets.kalshi.com`) before any bulk settlement collection or feeding Kalshi results into `alpha_eval`.
2. Allow `official.nba.com` and `stats.nba.com` (or confirm an alternative) to unblock referee crews and lineup/stint inputs; read nba.com / nhl.com terms.
3. Starter/goalie/injury PIT for history has no free source; only prospective capture (owner decision; nothing activated).

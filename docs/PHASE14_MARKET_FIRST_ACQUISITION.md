# Phase 14 (2026-11-13): market-first acquisition, continued (RESEARCH_ONLY, $0)

Agent verification only; **not human verified**. Continues `0443300` (Phase 13). No key, account, purchase, order, schedule, workflow, PR or merge. Catalog untouched (1,649 inputs; baseline lock and computed coverage not edited or regenerated; no catalog category changed). Raw data stays outside the repository; only digests (with sha256 of every cached file) are committed. Record: `research/input_research/data_foundation/phase14_market_first_acquisition.json` (same 50 in-scope inputs as Phase 13).

## Result (50 in scope)
| Status | Phase 13 | Phase 14 |
|---|---|---|
| VERIFIED_ACQUIRABLE | 4 | **15** |
| PARTIAL_EVIDENCE | 1 | **4** |
| BLOCKED_NETWORK | 6 | **0** (official hosts still blocked; an alternate free host was verified) |
| BLOCKED_NO_FREE_PIT_SOURCE | 3 | 3 |
| NOT_ADDRESSED_THIS_PHASE | 36 | 28 |

Changed (14): BLOCKED_NETWORK -> VERIFIED_ACQUIRABLE: NBA `lineup_adj_rating`, `onoff`, `player_impact`, `replacement_level_minutes_absorption`, `nonadditive_absence_curve`. BLOCKED_NETWORK -> PARTIAL_EVIDENCE: NBA `referee_crew`. NOT_ADDRESSED -> VERIFIED_ACQUIRABLE: NBA `late_game_script`, `rating_blowout_minutes_curve`, `ot_period_distribution`; NHL `score_state`, `third_period_equalizer_hazard`, `ot_sudden_death_hazard_5v5`. NOT_ADDRESSED -> PARTIAL_EVIDENCE: NHL `officials`, `pp_termination_unit_split`. "Acquirable" means raw data fetched and checked; none of these inputs is built, and every one stays `UNRESOLVED_INTERNAL_ONLY`.

## 1. NBA stints from ESPN (`alpha_engine/collect/espn_nba_pbp.py`; `source_samples/espn_nba_stints_20261113.json`)
stats.nba.com / official.nba.com are still proxy CONNECT 403 and cdn.nba.com still answers 403 (rechecked). `site.api.espn.com/.../nba/summary?event=` carries play-by-play with explicit "X enters the game for Y" events, starters, per-player minutes and plus-minus. The on-court five per team is rebuilt from that and **checked against ESPN's own box score**. The sample was 73 games over 14 dates (2005-06 to 2026-27; 87 calls):
* minutes within 1: 1,449 / 1,458 player-games. Plus-minus exact from 2008-09: **1,291 / 1,398 (92.3%)**. 46 of 70 games match on every player.
* Measured conventions: list order is chronological and `sequenceNumber` is not. Within one clock instant, scoring goes **before** substitutions, so free throws count for the five on court at the foul. That order gives 92.3% exact, against 44.3% for raw list order and 23.0% for subs-first.
* Limits: the 2001-02 sample has no plays. Box plus-minus is all zero in the 2005-06 sample, so only minutes can be checked there. The 2015-16 sample is weak (47/92 plus-minus). 2 summaries from 2016-01-15 have an empty box score.
* Officials (as worked): 72/73 games. A pre-game summary fetched 04:58Z, before the game-day assignment release, had no officials. So `referee_crew` is PARTIAL: we have history, but the source does not show which crew was knowable before the game.
* Odds, pickcenter and win-probability blocks are dropped before caching (market-free policy). The `starter` flag is as-played, so it gives no evidence for `nba.starters_pit` (still BLOCKED_NO_FREE_PIT_SOURCE).

## 2. NHL play-by-play (`alpha_engine/collect/nhl_pbp.py`; `source_samples/nhl_pbp_20261113.json`)
`api-web.nhle.com` `/v1/gamecenter/{id}/play-by-play` and `/right-rail`, 85 games: 71 sampled from 2010-11 to 2026-27, plus 14 playoff OT games from 2025 (206 calls).
* The goal events reproduce the official final score on **85/85** games (shootout goal removed). situationCode is present on 99.95% of events. Penalty type and duration are filled 100%.
* 6v5: 38 late pulls by a trailing team, 35 third-period equalizers, 18 empty-net goals. Delayed-penalty extra attackers look the same in situationCode (48 spells), so they must be separated using the delayed-penalty event.
* Playoff OT: 12 of 14 games ended on a 5v5 goal and 3 reached double OT or later. Regular-season OT has been 3v3 (situationCode `1331`) since 2015-16, so only playoff OT feeds `ot_sudden_death_hazard_5v5`.
* Officials: 2 referees + 2 linesmen on 85/85 games (as worked; the catalog's NO_FREE_SOURCE category is not changed). Scratches for both teams on 84/85, but as scratched, not pre-game, so `nhl.injuries_pit` is unchanged.
* `pp_termination_unit_split` is PARTIAL. The play-by-play has no on-ice skaters, and NHL shift charts (`api.nhle.com/stats/rest`) are **proxy CONNECT 403**.
* Full event streams start in the 2010-11 sample; a 2008-09 probe game was sparse. The robots file's `ai-train=no` applies: never train models on this data.

## 3. Kalshi: quote history and settlement depth (`alpha_engine/collect/kalshi_quotes.py`; `source_samples/kalshi_quotes_20261113.json`, `kalshi_settlement_depth_20261113.json`)
* **Timestamped quotes for evaluation.** Hourly YES bid/ask/trade candlesticks can be retrieved after settlement, through `/series/{s}/markets/{t}/candlesticks` or `/historical/markets/{t}/candlesticks` before the 2026-09-13 cutoff (the two use different field names). Results for a deterministic sample of 3 markets per month (97 calls):
  * KXNBAGAME: candles for 42/42 markets, a two-sided quote in the last 24 h before close for 42/42, median spread $0.01.
  * KXNHLGAME: 48/48 and 48/48, median spread $0.02.
  * Coverage runs from 2025-04 to 2026-11.
  * PIT rule: a candle is known at `end_period_ts`.
  * These are evaluation and execution prices. The catalog keeps `m.quote_history` EXCLUDED_MARKET for prediction.
* **Settlement depth (closes the Phase 13 gap).** Pagination was exhausted for KXNBASPREAD (16,937 markets) and KXNBATOTAL (14,787 markets). Both start at the 2025-26 opener (2025-10-22), and no ladder of the 3,887 checked is non-monotonic. KXNBAGAME starts 2025-04-16 and KXNHLGAME 2025-04-20 (re-listed in full). `/historical/markets` ignored `max_close_ts` in a probe.
* These were bounded verification samples. Kalshi's terms are still unread, so bulk collection still waits for the owner.

## 4. Blocked hosts (rechecked 2026-11-13; `source_samples/network_recheck_20261113.json`)
* Proxy CONNECT 403: stats.nba.com, official.nba.com, www.nba.com, api.nhle.com, www.nhl.com, kalshi.com, docs.kalshi.com, www.espn.com, basketball-reference, hockey-reference, naturalstattrick, moneypuck, pbpstats (www and api), darko.app, scoutingtherefs.
* Refused by the origin: cdn.nba.com (403), site.api.espn.com/robots.txt (403).
* None of these was worked around.

## Owner actions (none taken)
1. Read the ESPN, NHL and Kalshi terms, or allow www.espn.com, www.nhl.com, kalshi.com and docs.kalshi.com. Until then, everything above is internal research only.
2. Allow api.nhle.com to unblock the shift charts behind `pp_termination_unit_split` and NHL on-ice inputs.
3. Pre-game referee crews (NBA and NHL) and starters still need prospective capture (an owner decision; nothing activated).

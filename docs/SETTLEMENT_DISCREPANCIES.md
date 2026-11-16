# Settlement discrepancies: NHL and NBA computed settlements vs Kalshi official results (2026-11-16)

Status: agent-run, read-only research. Not human verified. No engine code was changed.
Per-ticker data: `research/settlement_discrepancies/nhl_nba_20261116.json` (178 rows: cause, computed side and value, official result and value, current box value, line, short evidence). No raw Kalshi rows are stored in this repo.

## Method

1. **Disagreements.** I took the 47 NHL and 131 NBA tickers that sift-alpha PR #80's `kalshi_official compare` flagged (from `xcheck.json`).
2. **Computed side.** I read each sport repo's `data-archive` branch, `settlements/*/*.jsonl.gz`, using a sparse, blobless checkout: NHL-edge-finder@8c3c2e0 and nba-edge-finder@c0049b4. For NBA I also read `boxscores/`, the archived ESPN box the engine settled on. Every ticker has exactly one computed record, so no ticker was ever re-settled.
3. **Official side.** I fetched each ticker from Kalshi's public `GET /trade-api/v2/markets/<ticker>` and read `result`, `expiration_value`, `rules_primary`, `settlement_ts` and volume. For the five Sep 29 NHL saves events I also fetched the whole event ladder. Raw responses are kept only under `/tmp/claude-0/data/settle/`.
4. **Box truth.**
   - NHL: the current api-web.nhle.com boxscore and play-by-play, used for game type, goalie saves, assist credits and shootout events.
   - NBA: the current ESPN summary (quarter and OT linescores, player lines). cdn.nba.com returned HTTP 403 (Akamai) from this environment, so NBA was not checked against the league's own box.
5. **Engine code.** NHL-edge-finder main@04ebe15 and nba-edge-finder main@51a9217.

## Causes by sport and series

| Sport | Series | Disagree | Cause | n |
|---|---|---|---|---|
| NBA | KXNBA2HTOTAL | 66 | ENGINE_RULE_SEMANTICS (2H excludes OT) | 66 |
| NBA | KXNBA2HSPREAD | 21 | ENGINE_RULE_SEMANTICS | 21 |
| NBA | KXNBA2H | 6 | ENGINE_RULE_SEMANTICS | 6 |
| NBA | KXNBASTL | 12 | KALSHI_DIFFERS_FROM_BOX 10, STAT_CORRECTION 2 | 12 |
| NBA | KXNBAREB | 11 | KALSHI_DIFFERS_FROM_BOX 10, STAT_CORRECTION 1 | 11 |
| NBA | KXNBABLK | 5 | KALSHI_DIFFERS_FROM_BOX | 5 |
| NBA | KXNBAAST | 4 | KALSHI_DIFFERS_FROM_BOX 3, STAT_CORRECTION 1 | 4 |
| NBA | KXNBAPRA | 4 | KALSHI_DIFFERS_FROM_BOX 2, STAT_CORRECTION 2 | 4 |
| NBA | KXNBA2D | 2 | KALSHI_DIFFERS_FROM_BOX | 2 |
| NHL | KXNHLSAVE | 29 | KALSHI_ADMIN_NO_UNTRADED_STRIKE 24, KALSHI_DIFFERS_FROM_BOX 4, STAT_CORRECTION 1 | 29 |
| NHL | KXNHLAST | 9 | KALSHI_DIFFERS_FROM_BOX | 9 |
| NHL | KXNHLPTS | 9 | KALSHI_DIFFERS_FROM_BOX | 9 |

Totals:
- **NBA (131):** ENGINE_RULE_SEMANTICS 93, KALSHI_DIFFERS_FROM_BOX 32, STAT_CORRECTION 6.
- **NHL (47):** KALSHI_ADMIN_NO_UNTRADED_STRIKE 24, KALSHI_DIFFERS_FROM_BOX 22, STAT_CORRECTION 1.
- **No hits** for PRESEASON_OR_GAME_MATCH, PLAYER_IDENTITY (every player's team matched), THRESHOLD_BOUNDARY (Kalshi's "N+" equals the engine's `gt N-0.5` in every case) or UNRESOLVED.

## Findings

### NBA second-half markets: overtime (hypothesis confirmed, 93 of 93)

- **Kalshi's rules.** `rules_primary` for KXNBA2H, KXNBA2HSPREAD and KXNBA2HTOTAL reads "2nd half (including overtime)". `rules_secondary` adds "2nd half markets are inclusive of overtime."
- **The engine.** It sums only Q3+Q4.
- **The games.** All 93 tickers come from 10 games that went to overtime; DET-WAS on Nov 12 went to two overtimes.
- **The check.** Q3+Q4+OT from the current ESPN linescore reproduces every Kalshi `expiration_value`. Examples: MIN-CLE total 116 → 142, UTA-NOP 2H winner 67-62 → 76-78, ATL-CHI margin +7 → -1.

### NHL Sep 29 saves: Kalshi administrative "No" (hypothesis rejected, 24 tickers)

- **Not preseason, not a wrong match.** The 26SEP29 games are regular-season opening night (NHL gameType 2, game ids 2026020002 to 2026020005). The engine matched the right game.
- **The box agrees with the engine.** Examples: Knight 32 saves, Lankinen 32, Dobes 26.
- **What Kalshi did.** In each goalie's ladder, the one traded strike settled to a number equal to the box (for example Knight 26+ settled with value 32 → yes). Every other strike was batch-settled `no` minutes earlier, with `expiration_value` set to the literal "No".
- **Volume.** 23 of the 24 strikes had zero volume and zero open interest. Knight 20+ traded 2 contracts at 0.99 and was still settled No.
- **Conclusion.** The engine is right on the box. This is a Kalshi listing and settlement artifact, not an engine defect.

### KALSHI_DIFFERS_FROM_BOX (NHL 22, NBA 32)

In these cases the engine's value equals the current official box and Kalshi's settled value is off by exactly 1. Kalshi usually settled 2 to 10 minutes after the game ended.

- **NHL assists and points.**
  - Four games show clean same-team assist swaps, consistent with Kalshi's feed crediting a different assister than NHL.com finally shows (per play-by-play): Sillinger and Severson (CBJ, Oct 20), Zibanejad and Gavrikov (NYR, Oct 6), Beniers and McMann (SEA, Oct 28), Shea and Bouchard (EDM, Nov 1).
  - Chatfield, Forsberg and Palmieri are single cases.
- **NHL saves.**
  - Schmid, Talbot and Markstrom: Kalshi = box − 1.
  - Saros: the engine read 25, the box is now 24 and Kalshi has 26. The game went to a shootout, but the play-by-play shows Saros made no shootout saves, so the shootout does not explain Kalshi's number.
- **NBA player props.**
  - All checked against ESPN only.
  - Six ESPN values changed after the engine read them and moved toward Kalshi (see STAT_CORRECTION below). That suggests ESPN can lag the league feed Kalshi uses, so some of these 32 may really be ESPN-vs-NBA.com differences.
  - Two double-double markets: Jabari Smith's line is 15/9/2/3/1 and Kalshi settled yes; Boozer's is 12 pts / 10 reb and Kalshi settled no, consistent with Kalshi showing 9 reb on his REB market.
  - Doncic's steals market settled with `expiration_value` "Yes" against 2 steals on a 3+ line.

### STAT_CORRECTION (NHL 1, NBA 6)

In each case the engine settled once on an earlier box, the box later changed to agree with Kalshi, and the engine never re-read it.

- **NHL:** Ersson saves 23 → 24.
- **NBA:**
  - Wells REB 1 → 2
  - Nesmith PRA 20 → 19
  - Williamson STL 2 → 1
  - A. Thompson PRA 24 → 25
  - Harper AST 3 → 4 (the engine settled 11 h before Kalshi did)
  - K. George STL 1 → 0
- **McDaniels REB (Oct 28) is counted under KALSHI_DIFFERS_FROM_BOX, not here.** ESPN moved 7 → 6, which is still the engine's side; Kalshi has 8.

## Recommended fixes, by cause

Recommendations only. Nothing was changed.

### 1. ENGINE_RULE_SEMANTICS: NBA 2H must include overtime

- **Settlement.** In `nba-edge-finder/src/nba_edge/settlement/boxscore.py:126-127`, `period_points` returns `_sum_periods(box, ("3Q","4Q"), idx)` for `2H`. Change it so 2H is all points after halftime, including OT:
  - either 3Q + 4Q + every `OT*` key,
  - or, more robustly, `(home_pts|away_pts) − (1Q + 2Q)`, since archived boxes carry `OT1`, `OT2`, ... keys and `n_ot`.
- **Docstring.** Correct `boxscore.py:112-113` ("Quarters and halves EXCLUDE overtime"): halves follow Kalshi's "including overtime", quarters still need their own rules check.
- **Pricing simulator.** `src/nba_edge/sim/result.py:109-110` (`_period_slice` "2H" = periods 2:4) has the same exclusion. It misprices every 2H market in OT-prone spots, so the same rule belongs there.
- **Engine version.** Bump `ENGINE_VERSION` in `settlement/engine.py:27` so the corrected 2H records append rather than collide with the existing idempotency keys. The semantics fingerprint does not include the period rule.
- **Contract parser.** `src/nba_edge/kalshi/contracts.py:188` only flags period markets whose rules do not mention "regulation". It could instead read "including overtime" and set an explicit include-OT flag.

### 2. STAT_CORRECTION: re-read the box during a correction window

- **NBA.** At `src/nba_edge/workflows/settle.py:265`, `box = boxes.get(gid)` short-circuits the fetch once any final box is held, so a correction is never seen. The engine and docstrings already support `stat_correction_version`, but nothing bumps it.
  - Re-fetch held boxes while the game is younger than a window, for example 72 h after tip or until Kalshi settles plus 24 h.
  - When any player line or period score differs, append the box with `stat_correction_version + 1`.
- **NHL.** `src/nhl_edge/workflows/settle.py:339-340` skips any game already ingested whose contracts all have a record. Apply the same window and version bump. `settle_player_contract` already takes `correction`; see `settlement/player.py:71`.
- **NBA box source.** The six ESPN corrections arrived after the engine read the box, and in each case Kalshi's earlier settlement already matched the corrected value. Prefer the NBA CDN official box, which the settle workflow already routes 10-digit ids to, over ESPN as the primary NBA box source.

### 3. KALSHI_ADMIN_NO_UNTRADED_STRIKE and KALSHI_DIFFERS_FROM_BOX: no engine rule change

- **Engine and evaluation.**
  - The engine's job is the box. Keep flagging disagreements; the existing `DISAGREES_WITH_KALSHI:` prefix does this.
  - Any P&L or calibration that pays out must use Kalshi's result, because that is what settles the money.
- **PR #80's compare tool** (`alpha_engine/game_completeness/kalshi_official.py:72-94`). Add a separate bucket, for example `official_administrative`, for rows whose `expiration_value` is not numeric or a score ("No"/"Yes") and that had zero or near-zero volume. That removes the 24 Sep 29 rows (and the Doncic "Yes" row, for review) from `disagree`.

## Still unresolved

- **The 32 NBA KALSHI_DIFFERS_FROM_BOX tickers** were judged against ESPN only. A check against the NBA.com box (blocked here, HTTP 403) would show which are Kalshi using in-game values and which are ESPN lagging the league feed.
- **Kalshi's NHL source.** It is not known why Kalshi's NHL values differ from NHL.com, for example the assist swaps, Saros 26 vs 24 and the three goalies at box − 1. NHL.com publishes no history of scoring changes, so I could not show whether NHL.com ever showed Kalshi's values.
- **Agreement sample.** I did not check whether any *agreeing* 2H contracts came from OT games where the OT happened not to flip the side. The 93 are only the side-flipping subset; the fix in §1 changes the value for every OT game.

# CEO report: priority-one input completion (overnight 2026-11-20)

Research only. No operating model, published probability, bet, stake, schedule, collector or deployment was changed or activated. Protected surfaces
(workflows, `sift_feed`, `feed/`, `sift_exec`, `sift_clv`, deploy config) have no diff against main `917dd63`.

## The scorecard
| | Start of sprint | Now | Change |
|---|---|---|---|
| **Missing priority-one (P1) slots** | **180** | **128** | **−52** |
| Missing PRIMARY slots, all priorities | 828 | 769 | −59 |
| Certified inputs (FULL / PARTIAL / PROXY) | 331 (62 / 230 / 39) | **370 (62 / 255 / 53)** | **+39** |
| Market families (archetypes) with fewer missing inputs | – | 35 (28 of them P1) | |
| Inputs used by production | 0 | 0 | none (not in scope) |

**How the 52 P1 closures break down:**
- **35 by PARTIAL certification.** Part of the catalog definition is implemented exactly, and the missing parts are listed.
- **17 by PROXY.** These measure the same mechanism a different way, for example empirical frequencies instead of a simulation.
- **0 by FULL.** No input was claimed FULL.
- **Not counted as closed:** the 61 slots that need point-in-time capture. History cannot close them, so none was "closed" with a proxy. Projected minutes and confirmed starters stay missing on purpose.

**P1 slots missing, by sport:**

| Sport | Before | After |
|---|---|---|
| CBB | 44 | 31 |
| NFL | 37 | 16 |
| MLB | 31 | 22 |
| NBA | 27 | 22 |
| CFB | 13 | 9 |
| Soccer | 18 | 18 |
| NHL | 6 | 6 |
| Tennis | 4 | 4 |

Tennis is owner-paused (handoff 2026-11-13) and was not touched.

## 1. PRs and merges
See the PR linked in the session summary. One PR on `claude/sift-alpha-p1-completion-2nk8gm` holds two commits:
- builders and evidence;
- ledger regeneration with pins, docs and dashboard.

The PR body records the CI result and the merge SHA.

**Local verification:**
- Python: 1,825 passed, 8 skipped, 0 failed.
- JavaScript: 92 / 92.
- Browser e2e: 112 / 112 (Chromium desktop and phone), including the new P1-tracker test.
- `regenerate --check`: ok and idempotent. Readiness and ladder `--check` are up to date.

## 2–3. What was built, by sport
All of it was built from data **we already held**: sift-data-vault, plus the nba-edge-finder history archive. Nothing was downloaded or bought.

| Sport | New certified inputs | P1 markets helped |
|---|---|---|
| CBB (9) | player usage and per-40 rates; shooting regression (3P/2P/FT luck); per-stat count distributions; three-point volume; probability of making 1–4 threes; assist creation; rebound pool; first-half share of scoring; blowout-vs-close margin mixture | player points, props, threes, rebounds/assists; first half; spread |
| MLB (6) | lineup strikeout rate vs right/left-handed pitchers; team offence vs hand (wOBA index); team-runs distribution; times-through-the-order rates and batters faced; pitcher strikeout/CSW/whiff vs the opposing lineup; first-inning run probability (exact base-out Markov chain) | strikeouts, totals and team totals, first five, first inning, moneyline |
| NFL (15) | drive-model team points and TD means; conditional margin spread; total-plays model; quarter "highest quarter" and zero-quarter odds; paired-score correlation; per-drive TD/FG/no-score lattice; QB expected passing TDs, TD luck, interception rate, completion model; WR/TE/RB usage vacated by players listed out before kickoff; blowout and score-path frequencies; player expected touchdowns | game, team and quarter totals, spread, passing yards and TDs/INTs, rushing yards, anytime TD, score-path |
| CFB (4) | expected combined drives from drive clock; drives per quarter and P(4 or fewer); who receives the opening kickoff and drives per quarter; points per minute when leading by 14+ vs close | game total, quarter and half totals and sides, team total |
| NBA (5) | on-court assist share; on-court rebound percentages; per-100 on-court rates; assisted-three passer dependence; creditable rebound pool | assists, rebounds, threes, combo props |

## 4. What we actually gained, in plain English
- **College basketball player props.** For every player before every game we now know:
  - how much of the offence he uses;
  - his scoring, rebounding and assist rates per 40 minutes;
  - whether his recent shooting is luckier than his history;
  - how spread out his game-to-game numbers are;
  - a full probability of making 1, 2, 3 or 4 threes.
- **Baseball pitching and lineups.**
  - How often each likely starter strikes batters out, and how that rate falls the second and third time through the order.
  - How deep he usually pitches.
  - How strikeout-prone the opposing lineup is against his throwing hand.
- **Football team scoring.**
  - **Drive model:** a market-free team score built as expected drives × points per drive.
  - **Spread of the margin:** how uncertain a matchup's final margin is.
  - **Game tempo:** how many plays to expect.
  - **Score paths:** how often games like this become blowouts.
- **Football quarterbacks:** expected passing TDs from where his throws happen, interception and completion tendencies.
- **Football injuries:** how much target and carry share is missing when a receiver or back is ruled out on the injury report before kickoff.
- **NBA:** who creates assists and grabs rebounds *while actually on the floor*, from two seasons of five-man lineup data.
- **College football tempo:** how many possessions and drives per quarter a matchup should produce (from how long each team's drives take), who is likely to get the ball first, and whether a team keeps scoring once it leads by two touchdowns.

## 5. Historical data used
| Archive | Coverage | Rows built |
|---|---|---|
| sift-data-vault CBB player box | 2012–2027 | 2.17M player-games |
| sift-data-vault CBB schedules | 2006–2027 (line scores 2023+) | 167k team-games |
| sift-data-vault MLB post-game feeds | 2022–2026 (931k plate appearances) | 19.8k team-games, 96.9k rotation-candidate rows |
| sift-data-vault NFL play-by-play and schedules, nflverse injury reports | 2010–2026 | 7.4k team-games, 12.9k QB rows, 102k player-games |
| sift-data-vault CFB ESPN post-game summaries (drives, scoring plays) | 2014–2026 (274k drives) | 18.8k team-games |
| nba-edge-finder stints and events | 2024-25 and 2025-26 | 73.8k player-games |

Nothing new was collected.

## 6. Verification
- **12 builder families. 39 inputs, 176 value columns.**
- **Full replay**, every check passing for every input:
  - determinism;
  - 3 truncation cuts and 3 future perturbations;
  - own game excluded;
  - non-vacuity.
- **Sport-specific required checks:**
  - **MLB:** suspended-game first-pitch availability (the amendment-1 rule).
  - **NFL injuries:** reports modified after kickoff never change anything; future reports permuted change nothing earlier.
  - **NFL relocated teams:** the mapping is enforced, with a test.
- **Blind re-implementation:** a separate agent saw only the written brief and the raw files. **176 / 176 columns matched exactly on the first comparison.** This is agent verification, not human.
- **Defects found and fixed before certification:**
  1. The MLB run EWM was first ordered by first pitch, which could leak a suspended game. It is now ordered by completion.
  2. The replay harness silently dropped 2 CBB games with no output rows. An opt-in, documented date truncation fixes it.
  3. Three builders needed role-preserving non-vacuity perturbations.
- **Point in time.** No starting pitcher is assumed. MLB pitcher inputs are keyed by **rotation candidate**: a pregame probable must be matched to a candidate by whoever uses them.

Details: `docs/P1_COMPLETION_BATCHES.md`.

## 7. Predictive findings (walk-forward on later seasons; not a betting claim)
Source: `research/p1_completion/utility_checks.json`.

**Clear gains:**
- **MLB starter strikeouts.** Pitcher × opposing-lineup log5 is 14% better than league K% (ΔMSE −0.81 [−0.87, −0.74]). It also beats the pitcher-only rate, so the opposing lineup adds information.
- **MLB starter batters faced:** 6% better than the league mean.
- **CBB player points, rebounds and assists:** about 4% better than the player's own last-15-game average, on 957k player-games. The three-point make probabilities also improve.
- **NFL team points.** The drive model averaged with the already-certified points model beats that model alone (ΔMSE −0.48 [−0.76, −0.22]). The gain is small but real.
- **NFL team TDs:** 7% better than the league mean.
- **NFL QB passing TDs:** 2% better.
- **CFB combined drives per game:** 8% better than the league mean (ΔMSE −1.07 [−1.22, −0.91]).

**No gain or worse (certified as computed, not as useful):**
- **NFL QB interception model:** 3% worse than a league constant.
- **NFL QB completion model:** 6% worse than a league constant.
- **NFL conditional margin SD:** carries no heteroskedastic signal (correlation with the absolute error ≈ 0).
- **MLB team-run mean:** not distinguishable from the league mean. Only its ≥4 and ≥5 run probabilities help, slightly.
- **CFB per-quarter drive counts:** no gain for Q2 and 3% worse for Q4 than the league mean. The per-quarter split adds nothing yet.
- **MLB first-inning chain:** runs low (about 22% team scoring vs about 27% actual) because its advancement rules are simplified. This is a PROXY.

Better inputs do not mean winning bets. None of this was priced against Kalshi.

## 8. The 128 P1 slots still missing
The P1 tracker in the dashboard (Operating readiness panel) and `research/input_research/readiness/README.md` give the per-input blocker.

| Next action | P1 slots | Main items |
|---|---|---|
| Prospective capture (vintages from now on) | 61 | cbb.injuries (7), cfb.qb_status_pit (6), nfl.qb (5), cbb.player_minutes (4), mlb.lineup_pit (4), mlb.sp_quality (4, point-in-time quarantined), cbb.starters (2), nhl.goalie_quality (2), weather |
| Free source known, not collected | 25 | weather forecasts and venue geography (NFL, MLB, CFB), Kalshi rules text (tennis settlement), college coaching history, D3 / lower-division results |
| Provider policy blocked | 12 | soccer xG / lineup sources, NBA tracking (potential assists, rebound chances) |
| Owner certification decision | 15 | 9 downgraded NBA/NHL inputs, plus 6 contested (CBB teammate-absence and three shot quality, NBA pace) |
| Data held, builder still missing | 8 | CBB race-to-N and tournament max score, NBA absence curves, NFL rushing-leader simulation, FTN routes (2026 only), MLB ninth inning |
| No permitted free source | 7 | CBB on-floor and zone data, soccer shot data |

**Owner decisions waiting (engineering cannot do these):**
- **Two NBA downgrades are now resolvable.** `nba.margin_heteroscedasticity` and `nba.period_margin_pmf` were downgraded only for having "3 seasons, 5 needed". The vault now holds 7 complete seasons of line scores and 25 of team box scores. Evidence for reconsideration is in `research/input_research/readiness/c_class_reconsideration.json`. Their status is unchanged until you rule.
- **Rights.** 115 of the 128 missing P1 slots depend on a source with unresolved rights: ESPN, MLB Stats API, NHL API.

## 9. Prospective collectors (built, disabled)
`alpha_engine/prospective/` provides:
- **Immutable vintage archive:** payload hash, capture and publication time, entity ids, completeness, errors and retries.
- **Point-in-time reader:** never returns a capture taken after the requested time.

Feeds defined:
- NFL injury reports;
- CBB availability;
- MLB probable pitchers and lineups;
- NHL starting goalies;
- NWS kickoff weather.

**Each feed refuses to run unless all three hold:**
- an environment flag is set;
- an owner activation file lists it;
- the rights registry allows collection.

The registry allows none of them today, and a test proves it. Activation plan: `docs/PROSPECTIVE_CAPTURE.md`. The MLB, NBA, NHL and CFB feeds must not duplicate collectors that already exist in the producer repos.

## 10. Recommended next actions
1. **Rights decisions** for the ESPN injury listing, the MLB Stats API schedule and live feed, the NHL schedule, and NWS weather. These unlock the capture that the 61 prospective slots need. They are owner decisions.
2. **Rule on the two NBA reconsiderations.** If re-opened, build them with the derived engine and run replay plus blind match. That would close 2 P1 slots.
3. **Weather.** Register a rights entry for NWS or Open-Meteo, build stadium coordinates, then capture kickoff forecasts. This would close NFL, MLB and CFB weather slots.
4. **Remaining held-data builders (8 P1).** NFL rushing-leader simulation, CBB race-to-N, NBA absence curves (the 2025-26 pre-tip injury snapshots exist).
5. **Model use.** Freeze an MLB strikeout-prop experiment on `kr_log5_k_pre` and the TTO columns against archived Kalshi strikeout quotes, and a CBB player-prop experiment. Score them forward before any adoption. The ladder's experimental level stays 4 until then.
6. **Improve the NFL QB interception and completion models.** Both are worse than a constant. Use stronger shrinkage and drop the opponent factor, then re-certify as a new version.

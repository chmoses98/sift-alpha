# Phase 16 NHL: starting-goalie information (RESEARCH_ONLY)

Code branch: `claude/fable-phase-16-production-9u2jw7` (resolver, flag, tests, doc). This directory holds the experiment code, data and results; nothing here is committed.

## 1. V2 and the gate (unchanged)
G10 is the registered live non-inferiority gate for V2's overtime fields. It is defined in `docs/research/overtime_promotion/PREREGISTRATION_G7_G10.md` and checked by `src/nhl_edge/research/overtime_gates.py live`. The registry is `data/registry/projection-registry.json`, where overtime is still published by V1. Promotion needs an approval record.
* Rule: Brier difference on P(OT), V2 minus V1, over games from 2026-10-26 onward. Pairs come from the last pregame snapshot taken at least 10 minutes before the drop.
* PASS at 1,050 games: upper 95% bound < +0.0010, mean < 0, calibration within 0.03, coverage at least 90%. Harm looks at 250 / 500 / 750 games use a 99% interval.
* Latest evidence (PR #132 interim, 2026-11-18): 141 / 1,050 games, d = -0.0025, coverage 1.0. Status: IN_PROGRESS.
* The code branch does not touch any of this. CI is green: ruff passes, and pytest ran 1,157 tests with 0 failures and 2 skips.

## 2. Historical starter table: `data/starters_history.csv.gz` (0.43 MB, 43,902 team-games, 2008-09..2026-11-17)
* Official boxscore `starter` flag: 2021-26 from the repo history, plus one api-web refresh of 2026-27 (343 games, provenance URL / time / sha256 per row in `data/raw`).
* MoneyPuck "first goalie to face a shot" for 2008-21 (repo data). It agrees with the official flag on 99.98% of 13,118 overlapping team-games.
* Reachability from this container: api-web schedule, boxscore and club-schedule all returned 200. `api.nhle.com/stats` was not reachable. The boxscore flag exists back to at least 1990-91.
* **I stopped the bulk pull of 2000-25 after about 2k requests.** The repo's position (`docs/research/lineup_sources/NHL_API_TERMS.md`) is "no new automated compilation / no higher request rate" until the NHL answers. Reaching beyond 2008 needs the owner's decision. `fetch_starters.py` is ready if they decide yes.

## 3. Expected-starter resolver: `resolver_eval.py` → `results/resolver_eval.json`
* Model: conditional logit over the team's starters in its last 30 games. Fit 2008-21, validation 2021-24.
* Every rule uses the same candidates. CIs come from a team-game bootstrap.
* Holdout 2024-26 (5,246 team-games), top-1 accuracy:

| rule | top-1 |
|---|---:|
| resolver | **0.658** [0.645, 0.671] |
| production V2 start-share weights | 0.515 |
| most recent starter (projection-foundation fallback) | 0.413 |

* Resolver minus production V2: +0.143 [+0.130, +0.157]. Log loss 0.975 vs 1.200.
* Back-to-backs: resolver 0.762, production V2 0.306, most recent starter 0.076.
* 2026-27 (686 team-games): 0.624 / 0.443 / 0.395. Back-to-backs: 0.684 / 0.228 / 0.000.
* The actual starter was among the candidates in 98% (2024-26) and 96% (2026-27) of team-games.
* The NHL publishes no pregame starter. "Confirmed" therefore comes only from an existing pregame observation (DailyFaceoff). Its last pre-drop observation named the right starter in 100% of 116 team-games (RESULTS_NHL.md).

## 4. Forecast impact: `forecast_impact.py` → `results/forecast_impact.json` (NULL)
* Setup: archived V2 walk-forward, 2024-25 + 2025-26 holdout (2,624 games). Only the goalie factor changes, with the same seed and the same simulator parameters. The G1 arm reproduces the archived SIM2_ST exactly.
* Results (95% date-cluster bootstrap):

| comparison | winner LL | over 6.5 LL | total log score |
|---|---|---|---|
| actual starter vs production mixture | -0.0003 [-0.0013, +0.0007] | -0.0013 [-0.0027, +0.0001] | -0.0014 [-0.0048, +0.0020] |
| resolver mixture vs production mixture | -0.0007 [-0.0014, 0.0000] | -0.0003 [-0.0012, +0.0006] | — |

* Knowing the confirmed starter does not measurably improve V2's game forecasts. Team goals-against already absorbs most of the goalie quality. Starter information matters for saves props and as a correct label.
* Caveat: my rebuilt goalie book differs from the archived actual-starter factor by up to 0.031.

## 5. Period / OT (PR #132; no new prototype)
* Validated:
  * V2's P(OT) vs V1: -0.0027 [-0.0039, -0.0015] in the 2024-26 replay, and 7 of 7 older seasons favourable.
  * Regulation 3-way: -0.0040.
  * p15-goal's full-game spread is reliable.
  * Period families tie V2 in 2025-26. Their small 2026-27 gains do not survive Holm correction.
* What blocks promotion: only the registered G10 sample (141 / 1,050). Its first harm look is at 250 games (around early December). No evidence justifies bypassing it.
* Not promotable: p15-goal for OT, which ties or loses to V2. Its -0.26 goals/game level bias needs a re-validated re-freeze, which is not a small fix.
* I prototyped nothing. No small fix is clearly supported by the existing evidence.

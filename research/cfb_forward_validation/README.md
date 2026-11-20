# CFB forward validation, 2026 weeks 6–12 (RESEARCH_ONLY)

Nothing here is activated, deployed or scheduled. It scores **frozen** candidates on games no earlier CFB study had
seen (PRs #97/#98 stop at 2026 week 5), using executable Kalshi prices that were really on the book.

## What is new
1. **Historical quotes past week 5.** cfb-edge-finder commits the whole public Kalshi CFB catalog (every market,
   yes/no ask and bid, displayed size) about every 30 minutes. `extract_catalog_quotes.py` reads that git history and
   keeps, per game, the last snapshot 15 min–24 h before kickoff, using the **commit time**, which comes after the
   capture. Commit and blob hashes are recorded for lineage. Nothing is interpolated. 796 games / 92,705 quotes in
   all families; **365 completed FBS games / 54,059 contracts scored** (FCS games have no ESPN log, and games from
   Nov 19 on are not final yet).
2. **Freeze before scoring.** `freeze.py` fits every mapping on 2024–2025 only. The single market-recalibration
   candidate is also fitted on 2026 weeks 1–5. The specs are written to `frozen_specs.json` and sha256-stamped
   (committed in `945ed04`, plus an empirical-distribution amendment in `ef432d49`) before any week ≥ 6 outcome was
   computed. `score_forward.py` refuses to run if the hash differs.
3. **All families SIFT intends to recommend.** These are full-game, 1H, 2H and 1Q winners, spreads and totals,
   plus full-game and 1H team totals. Each has its own distribution: `quantity_P ~ alpha + beta·projection + e`,
   where e is either normal or the empirical 2024–25 residual quantiles. The empirical version keeps football's
   discreteness.
4. **Settlement verified.** Outcomes come from ESPN period scores. 53,500 of 53,505 contracts with an official
   Kalshi result agree. The 5 that differ come from one game: ESPN has MTU 51–42, while Kalshi settled on a margin
   of 3. The official result is used. The first fuzzy team matcher paired 6 FCS games with unrelated FBS games
   (55 disagreements). This check caught it, and matching now uses aliases with a 0.9 threshold.
5. **Realistic costs.** The selection rule is the one from PR #97: net edge ≥ 0.05 after the unrounded fee, one bet
   per game × family. P&L is also reported with Kalshi's per-order fee rounded up to the cent, for 1-contract and
   10-contract orders, and with orders capped at min(10, displayed size). For NO orders, the depth is the YES bid
   size.

## Results (unseen weeks, frozen, no refit)
| Candidate | Bets | Net ROI (unrounded fee) | 95% CI (game bootstrap) | 10-contract size-capped ROI | P&L at mid, no fee |
|---|---|---|---|---|---|
| **Existing process**: #97 blend, WIN fix, FG winner + spread only | 457 | **−5.1%** | −18.0% … +7.2% | −5.7% | −0.1 |
| #97 blend, all families | 2,494 | −14.6% | −21.3% … −8.0% | −14.5% | −104.6 |
| #98 frozen A (home effect decoupled) | 2,488 | −13.6% | −20.6% … −7.0% | −13.5% | −94.3 |
| home-effect fix (he), normal | 2,472 | −13.9% | −20.7% … −7.0% | −13.6% | −94.6 |
| he, empirical residuals | 2,335 | −12.8% | −19.4% … −6.3% | −12.6% | −79.2 |
| C: market recalibration (frozen on weeks 1–5) | 2 | n/a | n/a | n/a | n/a |

Priority families (he_emp ROI / bets): FG total −22% / 199, FG team total −12% / 325, 1H total −22% / 172,
1H spread −12% / 259, 1Q total −13% / 162, 1Q spread −10% / 156. **No family is profitable.** Every candidate loses
before costs (the mid P&L is negative), so the problem is the probabilities, not the fees.

## Calibration (all quoted contracts, per family; `forward_report.json` → `calibration`)
- The market mid has a lower Brier score than every model on every family. The fixes move the model toward the
  market without reaching it. On FG spread, Brier goes from 0.1895 (#97 blend) to 0.1873 (he_emp), against 0.1767
  for the market. On FG winner it goes from 0.2181 to 0.2170, against 0.2047.
- `logit(y) ~ 1 + model` has slope 0.6–0.9: the models are overconfident.
- `logit(y) ~ 1 + model + market`: the model coefficient is about 0 on winners and spreads, and **−0.6 to −0.9 on
  game, 1H and 1Q totals**. On totals, the model's disagreement with the market points the wrong way.
- Empirical residual distributions beat normal ones for the he source on most families. Normal tails are not the
  main issue.

## Why the 20+-point "edges" lose
Grouping every contract by |model − market|: when they differ by more than 0.2, the model gives its side 59–66%,
the market 30–37%, and that side actually wins 29–35%, close to the market price. Taking the largest edge across a
ladder therefore picks the model's largest errors. Capping edges would not help: below a 0.05 disagreement the
model agrees with the market, so no bet remains.

## Not promotable
- `lead_gt_120min` (+5.6% on 555 bets, he_emp) was picked out after the fact from 25 subgroups. Treat it as a
  hypothesis for the forward mechanism below, not a finding.
- C barely bets, because its fitted model weight is negative. That matches "no information beyond the price".

## Forward testing from here (no refit)
```
git -C ../cfb-edge-finder fetch --filter=blob:none --shallow-since=<last run> origin main
python research/cfb_forward_validation/extract_catalog_quotes.py --repo ../cfb-edge-finder --ref FETCH_HEAD --since <date> --until <date> --out <new quotes>
python research/cfb_forward_validation/score_forward.py ...    # loads frozen_specs.json; refuses a modified spec
```
A new candidate gets its own freeze commit before its first scored week. Outcomes come from Kalshi official
settlements where available.

## Reproduce
```
python sift-data-vault/tools/vault.py restore --path archives/CFB/espn_summary_postgame/2014-2025/espn_site_api/collected-20261116 --to RAW/a   # and 2026 -> RAW/b
python sift-data-vault/tools/vault.py restore --path archives/CFB/kalshi_official_settlements/all-to-20261116/kalshi_public_api/snapshot-20261116 --to RAW/kalshi
python research/cfb_forward_validation/freeze.py --he-records ../cfb-edge-finder/data/scripting/validation/home_effect_experimental/records.jsonl.gz \
   --cfbd-root <cfb-edge-finder research-data branch>/data/research_cache/v2 --team-cache team.pkl --cfb ../cfb-edge-finder --espn RAW/a,RAW/b --out /tmp/specs.json   # identical except frozen_at_utc
python research/cfb_forward_validation/score_forward.py --he-records ... --team-cache team.pkl --espn-log ../cfb-edge-finder/data/football/2026/team_games.jsonl --kalshi RAW/kalshi --out research/cfb_forward_validation/forward_report.json
python -m unittest tests.test_cfb_forward_validation tests.test_cfb_bet_selection -v
```
The `he` projections come from cfb-edge-finder branch `claude/fable-sprint-completion-2ds7hd`
(`scripts/research_home_effect.py`, `docs/HOME_EFFECT_INVESTIGATION.md`).

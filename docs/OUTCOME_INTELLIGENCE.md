# Outcome Intelligence (Project A) — audit + incremental-gain study — RESEARCH_ONLY

Tracking: issue #27. Based on PR #25 head `aa263fc`. No execution module, betting authority or Project B file is touched; nothing is merged or deployed.

## Scope actually completed vs. blocked
| Priority | Status |
|---|---|
| 1 CFB reproduce/audit | **Done** (independent code, exact reproduction) |
| 1 NFL reproduce/audit | **BLOCKED** — `add_repo` for `chmoses98/nfl-edge-finder` was denied by the session permission classifier; PR #25's NFL numbers are carried forward **unverified** |
| 2 MLB 2022–26 study | **BLOCKED** — same denial for `chmoses98/edge-finder-api`; no MLB data read |
| 3 NBA/NHL/CBB/soccer/tennis | **NOT AUDITED** — repos not attached. In-repo probe branches (`sweep-data`, `tennis-data-probe-data`, `value-probe-data`, …) hold probes/queues, not settled-outcome datasets |
| 4 totals/team totals/periods/props | CFB spread+total tested; team totals/periods/props absent from the CFB corpus (NO_DATA) |
| 5–6 challenger vs market, holdout, CI, multiplicity | **Done on CFB** (`incremental.py`) with positive and negative controls |
| 7 reproducibility | commands + input SHA-256 below |

A blocked or unaudited cell is a **coverage gap, not a negative finding**.

## CFB audit results (inputs: `cfb-edge-finder@research-data`, 44,019 observations, 11,509 settlement rows)
Input digests are in `reports/outcome_intel/cfb_audit.json` (`inputs.*_sha256`).
* **Exact reproduction**: re-running PR #25's `cfb_outcome.py` gives a report identical to the committed one (0 differing fields). My independent recomputation matches its Brier gap mean (+0.01266, n=31,043 rows, 96 games; bootstrap lower bound 0.0019 vs 0.0031 = resampling noise only) and its buy-every-side baseline (−3.0864¢, n=9,104, earliest non-thin snapshot per ticker, 1-lot fee).
* **Settlement joins**: 7,205 evaluated tickers, all have a settlement row; 4,552 settled, 0 conflicting re-settlements; **independent re-derivation from final score + ticker rules agrees on 4,552/4,552**. Pending (2,653 tickers) are kept missing, 1,181 observations `ticker_unresolved` kept out.
* **Caveat (new)**: `official_kalshi_settlement` is null on **all** rows, and **all 4,552 settled tickers use the ESPN fallback score** (CFBD returned HTTP 429). Outcomes are derived, not confirmed against Kalshi's settlement; 97 tickers went to overtime. Treat as high-confidence but unverified settlement.
* **Timestamps**: 0 snapshots at/after kickoff, 0 before their data timestamp, 0 with inconsistent hours-before-kickoff, 0 after settlement capture, 0 duplicate (ticker, label). One game has two kickoff values across captures (rescheduled); the PR's chronological split uses a single kickoff.
* **Denominators**: 96 independent settled games (moneyline/spread/total each 96); median 405 rows and 48 tickers per game ⇒ rows are heavily dependent; every interval resamples games. Chronological split = 32/32/32 games by kickoff (valid; ties at the 23:00 boundary only).
* **Fee inconsistency (new)**: `cfb_outcome` charges a 1-contract ceil-to-cent fee; `nfl_outcome` uses 100 lots. With 100 lots buy-every-side is −2.66¢ (CI −2.78…−2.54), at the close −1.94¢ vs −2.37¢. Conclusions unchanged; absolute levels differ by ≈0.3–0.4¢.

## New study: does the model add information beyond the market? (`cfb_incremental.json`)
Per family × label (T_3D, T_24H, T_6H, CLOSING = 12 cells, all reported). Train = earliest 2/3 of games by kickoff, holdout = latest 1/3 (≈26–31 games per cell), ridge fixed, one pass. Challenger = calibrated market + coefficient on (logit model − logit mid); statistic = holdout logloss gain over the **calibrated market-only** baseline, game-cluster bootstrap, Holm over 12 cells, negative control (game-shuffled challenger).
* **No cell shows a gain** (all point estimates between −0.027 and +0.007; best Holm p = 0.88). Largest negative: total@CLOSING −0.027 (CI −0.057…+0.003). Holdout counts: moneyline 58–62 rows, spread 685–831, total 488–589 (cells' `n_holdout`).
* Conclusion: **no demonstrated incremental information in the CFB model; with ~30 holdout games power is low, so this is "not demonstrated", not proof of no effect.** Unit tests include a planted-signal positive control and a shuffled negative control.

## Reproduce
```
git clone --depth 1 --branch research-data https://github.com/chmoses98/cfb-edge-finder $CFB
python3 -I research/outcome_intel/audit_cfb.py --root $CFB --out reports/outcome_intel/cfb_audit.json
python3 -I research/outcome_intel/cfb_incremental.py --root $CFB --out reports/outcome_intel/cfb_incremental.json
python3 -I research/outcome_intel/coverage_ledger.py reports/outcome_intel/cfb_audit.json reports/outcome_intel/cfb_incremental.json reports/outcome_intel/coverage_ledger.json
python3 -m unittest discover -s tests -p 'test_*.py'   # 163 pass (11 new)
```
The corpus keeps growing; digests in the audit identify the exact snapshot used (44,019 obs / 11,509 settlement rows).

## Blockers / next steps
1. Grant read access to `nfl-edge-finder`, `edge-finder-api`, `nba-edge-finder`, `NHL-edge-finder`, `cbb-edge-finder`, `soccer-edge-finder`, `Tennis-Edge-Finder` (or mount them); `incremental.py` is sport-agnostic (rows = game, time, market prob, challenger prob, outcome).
2. Then: reproduce NFL (settlement join vs nflverse, 100-lot fees), MLB 2022–26 chronological season-holdout study, per-sport coverage matrices.
3. CFB: confirm settlements against Kalshi's official result when available; add totals-by-team/period families to the capture.

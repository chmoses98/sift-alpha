# CFB head-to-head: preregistered study model vs production pf-cfb (RESEARCH_ONLY)

Written 2026-11-17. Agent-run, not human verified. Nothing is promoted; no sport repository, model, workflow or schedule was changed.
Preregistration `research/discovery/cfb_production_h2h/prereg.json` (sha256 `8797be28a695`, committed in `5412b01` before any
2026 challenger prediction was compared with an outcome or with production). Results `results.json`; selection and dataset evidence
next to it. Code `alpha_engine/discovery/cfb_production_h2h.py` (mirrors `production_h2h`, CBB), test `tests/test_cfb_production_h2h.py`.

## Answer

**Production pf-cfb is more accurate than every study-model variant on the same 241 games, on margin, total and win probability,
at kickoff and at kickoff - 4 h.** Primary (all_certified vs production, kickoff, game bootstrap, Holm m = 3): margin squared error
+67.7 (95% CI 33.0 to 104.9, p_holm 0.001), total squared error +62.3 (39.0 to 86.0, p_holm 0.001), Brier +0.0227 (0.0037 to 0.0421,
p_holm 0.02); positive = challenger worse. ISO-week-clustered CIs and the 4 h cutoff agree. This is a negative result for the
challenger **as archived data allows it to be run**, not a test of the study model at full information (see Limits): the 2026
in-season statistics it needs are not archived, so its 2026 features are stale. It says nothing against the inputs that passed Holm
on 2022-24.

## Data extent

| Item | Value |
|---|---|
| Extended dataset | `54d650627db1` (11,124 rows, 2014-2026); its 2014-2025 rows hash to the certified v2 dataset `0b9226c089fa` (reproduced bit-exact) |
| 2026 outcomes | 751 final games 2026-08-29..2026-11-15 UTC from the vault ESPN postgame summaries (`collected-20261116`); all 751 joined to the CFBD 2026 schedule by game id with home/away ESPN team ids equal (0 disagreements, 0 score conflicts); 137 scheduled games not final at collection |
| 2026 in-season features | **not archived**: the CFBD cache for 2026 (vault `v1-292f3aac`, identical to cfb-edge-finder `research-data`) holds games, talent, recruiting, returning production, portal, coaches, rankings only: no advanced box, no drives, no lines. In-season columns of 2026 games come from 2025 games in the builder's 400-day window; 2026 priors are complete |
| Production | `cfb-edge-finder` `projection-data` @ `677e10df`, `forecasts/cfb` (2026-10-20..2026-11-14 runs), pf-cfb families margin / game_total / team_points. 241 games forecast, all FBS-involved, all final in the ESPN archive; 241 usable at kickoff and at kickoff - 4 h |
| Selection | per game and family the latest record with generated, archived and git-commit time all before the cutoff (kickoff from ESPN). Median lead at kickoff 4.1 h (quartiles 1.8 / 24.8 h); at the 4 h cutoff 22.2 h. Margin = home - away equals team-points difference in the same run on 241/241 |
| Closing lines | none archived for 2026: no market benchmark for these games |

The study never scored 2026 (dev 2017-21, test 2022-24, holdout 2025 only), so the 2026 games are untouched for this comparison.
Training is the discovery engine's season-level walk-forward: 2026 is predicted by ridge fitted on 2014-2025 (lambda chosen on 2025,
sigma from 2017-25 out-of-sample residuals); the study has no in-season refit, so none is added. The code reproduces the study's
all_certified test RMSE (16.687).

## Results, kickoff cutoff, n = 241 (2026-10-20..2026-11-14 ET)

| Model | Margin MAE / RMSE / bias | Total MAE / RMSE / bias | Brier / log loss / slope / accuracy |
|---|---|---|---|
| **Production pf-cfb** | **13.06 / 16.59 / +2.67** | **13.54 / 16.72 / +0.07** | **0.2098 / 0.606 / 0.82 / 66.0%** |
| all_certified (study full model) | 14.76 / 18.52 / +2.99 | 15.31 / 18.49 / +3.01 | 0.2325 / 0.657 / 0.68 / 59.8% |
| adj_efficiency (study reference) | 17.24 / 21.82 / +11.39 | 15.18 / 18.46 / +2.72 | 0.2757 / 0.759 / 0.94 / 56.4% |
| Holm union (adj + drive + success + pass/rush + roster) | 14.70 / 18.55 / +3.19 | 15.23 / 18.54 / +2.31 | 0.2326 / 0.659 / 0.66 / 63.1% |
| adj + drive_scoring | 15.86 / 20.08 / +7.42 | 15.40 / 18.65 / +3.73 | 0.2501 / 0.703 / 0.62 / 58.1% |
| adj + success_rate | 16.10 / 20.20 / +8.13 | 15.34 / 18.64 / +2.82 | 0.2524 / 0.703 / 0.74 / 57.7% |
| adj + pass_rush_split | 16.11 / 20.53 / +8.90 | 15.38 / 18.62 / +3.47 | 0.2557 / 0.712 / 0.82 / 58.1% |
| adj + roster_priors | 14.71 / 18.86 / +4.86 | 14.78 / 18.24 / +0.57 | 0.2391 / 0.674 / 0.75 / 62.2% |

Paired differences, challenger minus production (game bootstrap 95% CI; every one excludes 0, every one is worse for the challenger):

| Model | Margin abs err | Total abs err | Brier |
|---|---|---|---|
| all_certified | +1.70 (0.85, 2.58) | +1.77 (1.13, 2.39) | +0.0227 (0.0037, 0.0421) |
| Holm union | +1.63 (0.74, 2.55) | +1.70 (1.06, 2.30) | +0.0228 (0.0028, 0.0430) |
| adj + roster_priors | +1.65 (0.70, 2.61) | +1.24 (0.66, 1.80) | +0.0293 (0.0075, 0.0511) |
| adj_efficiency | +4.18 (2.91, 5.46) | +1.65 (1.00, 2.27) | +0.0659 (0.0365, 0.0967) |

Kickoff - 4 h: production 13.07 / 13.53 / Brier 0.2101; all_certified deltas +1.69 (0.84, 2.57), +1.78 (1.13, 2.40), +0.0225
(0.0034, 0.0419). The last 4 h of production updates change nothing material.

Exploratory 50/50 margin blend (production + all_certified): MAE 13.55, worse than production alone (13.06).

## Home-field check

238 of 241 games are non-neutral; actual mean home margin 2.84. Production predicts 5.46 on those games: home bias **+2.62
(CI 0.65 to 4.64)**, i.e. production over-credits the home side by about 2.6 points over this sample (also +6.2 on the 3 neutral
games). all_certified has the same tilt (+2.96, CI 0.74 to 5.20). Production win probabilities are over-confident (calibration
slope 0.82, mean p_home 0.610 vs home win rate 0.568). Both are worth a preregistered production-side check
on more games; 241 games over four weeks is one sample of one season.

## Limits

* The challenger is information-starved: late-2026 rows have decayed window weight n_pre about 1 vs about 8 in training and adjusted
  ratings shrunk toward 0 (`diagnostics_exploratory.json`), so the rows are outside the training distribution. The reference model's
  +11.4 home bias is that extrapolation. A fair test of the study model needs the 2026 CFBD advanced box and drives archived (or a
  certified ESPN-play-by-play builder for the same columns, which does not exist yet).
* Production is scored as archived: 20 pf-cfb builds (pf-1.2.1, pf-1.3.0+...) over four weeks; role on the branch is research_only /
  shadow. The script-engine incumbent was not scored (no margin distribution or win probability).
* 241 games, 4 ISO weeks, mostly FBS vs FBS; CIs are game-level (primary) with week-clustered CIs reported in `results.json`.
* No market data: no closing lines for 2026 in the vault; no Kalshi prices used.

## Reproduce

    S=<scratch>; cd sift-data-vault
    python tools/vault.py restore --path archives/CFB/cfbd_api_cache/2014-2026/cfbd/v1-292f3aac --to $S/v/cfbd
    python tools/vault.py restore --path archives/CFB/espn_summary_postgame/2026/espn_site_api/collected-20261116 --to $S/v/espn2026
    cd ../cfb-edge-finder && git fetch origin projection-data:refs/remotes/origin/projection-data && mkdir -p $S/prod && git archive 677e10df | tar -x -C $S/prod
    cd ../sift-alpha
    python -m alpha_engine.discovery.cfb_production_h2h build --cfbd $S/v/cfbd --espn $S/v/espn2026 --out $S/ds.parquet --evidence $S/ev.json   # about 1 min
    python -m alpha_engine.discovery.cfb_production_h2h prod --root $S/prod --repo ../cfb-edge-finder --ref 677e10df --espn $S/v/espn2026 --out $S/p0.parquet
    python -m alpha_engine.discovery.cfb_production_h2h prod --root $S/prod --repo ../cfb-edge-finder --ref 677e10df --espn $S/v/espn2026 --out $S/p4.parquet --lead-hours 4
    python -m alpha_engine.discovery.cfb_production_h2h h2h --prereg research/discovery/cfb_production_h2h/prereg.json --dataset $S/ds.parquet \
        --production $S/p0.parquet --production-4h $S/p4.parquet --out research/discovery/cfb_production_h2h/results.json

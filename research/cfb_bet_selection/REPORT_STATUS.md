# Which CFB bet-selection numbers are current (2026-11-20)

| File | Status | Why |
|---|---|---|
| `report_2026.json` | **SUPERSEDED** (kept unchanged as evidence) | PR #97's original output. Its WIN probabilities used threshold −0.5 for both teams, so P(home)+P(away)=1.024 and every WIN edge was inflated by ~1.2 points. Its headline (blend −5.03 contracts / −4.2% ROI on 326 bets; 5–10-point edge bucket +28.2% on 73 bets) must not be quoted. |
| `report_2026_corrected.json` | current for 2026 weeks 1–5 | PR #98's re-run with the WIN fix: blend −6.52 / −5.6% on 317 bets; 5–10-point bucket +16.5% on 70 bets (exploratory, under one SE from zero). |
| `audit_report_2026.json` | current | PR #98's settlement audit (5,674/5,674 quoted tickers agree with Kalshi official results), calibration diagnostics and walk-forward corrections. None of the corrections is profitable. |
| `../cfb_forward_validation/forward_report.json` | current, independent | PR #99. Frozen candidates scored once on unseen weeks 6–12: 365 games / 54,059 contracts. No candidate is profitable. The existing WIN/SPREAD process is −5.1% (CI −18%…+7%); all-family candidates are −13% to −15% (CI excludes 0). |

The weeks 1–5 studies (#97/#98) and the forward study (#99) used `cfbx_mar_pre` / `cfbx_tot_pre`. These are
intermediate ridge columns of the certified CFB builder, **not certified catalog inputs** (see
`research/pipeline/adoption_registry.json`). The certified `pml_lead_half_pre` is loaded by `evaluate.py` but never enters a model.

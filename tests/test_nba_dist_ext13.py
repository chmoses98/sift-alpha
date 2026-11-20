"""Batch 13 (RESEARCH_ONLY): NBA margin quantiles + period pmf — unit checks of the deterministic pieces and of the owner-reopen gate."""
import numpy as np
import pandas as pd

from alpha_engine.features import nba_dist_ext13 as X


def test_pmf_mass_and_grid_mle_recovers_scale():
    y, p = X.pmf(1.3, 8.0, 0.2, 2.0, -200, 200)
    assert abs(p.sum() - 1) < 1e-9 and np.all(p >= 0)
    rng = np.random.default_rng(0); n = 4000
    ep = rng.uniform(95, 105, n); pair = rng.uniform(0.8, 1.2, n); mean = rng.normal(0, 2, n)
    yy = np.round(mean + rng.normal(0, 8.0, n))
    s0, t1, g, w, k = X.grid_mle(yy, mean, ep, pair)
    assert 7.0 < s0 * np.mean((ep / 100) ** t1 * pair ** g) < 9.0
    assert X.grid_mle(yy, mean, ep, pair) == (s0, t1, g, w, k)           # deterministic


def test_periods_ot_and_short_linescores():
    s = pd.DataFrame({"game_id": [1, 2], "home_linescores": ["[{'value': 30.0} {'value': 25.0} {'value': 20.0} {'value': 22.0} {'value': 10.0}]", "[{'value': 30.0}]"],
                      "away_linescores": ["[{'value': 28.0} {'value': 27.0} {'value': 21.0} {'value': 21.0} {'value': 8.0}]", None]})
    o = X._periods(s)
    assert list(o.game_id) == [1] and o.h_ot.iloc[0] == 10 and o.a_q4.iloc[0] == 21


def test_pair_covariate_uses_only_earlier_rows():
    f = pd.DataFrame({"team": [1, 1, 1, 1], "season": [2024, 2025, 2025, 2025], "date": pd.to_datetime(["2024-01-01", "2024-11-01", "2024-11-03", "2024-11-05"]),
                      "margin": [10.0, 0.0, 20.0, 5.0], "exp_margin_pre": [0.0] * 4, "sd_margin_pre": [10.0] * 4})
    vr = X._pair(f).to_numpy()
    np.testing.assert_allclose(vr, [20 / 20, (1 + 20) / 21, (1 + 0 + 20) / 22, (1 + 0 + 4 + 20) / 23])
    f2 = f.copy(); f2.loc[3, "margin"] = 99.0
    assert np.array_equal(X._pair(f2).to_numpy(), vr)                    # own / later outcomes never enter


def test_specs_full_and_owner_reopen_registered():
    from alpha_engine.input_research.data_foundation import verified_coverage as VC
    from alpha_engine.features import nba_pmf_ext13 as P
    assert all(s.level == "FULL" and not s.missing for s in X.specs() + P.specs())
    assert [s.catalog_id for s in X.specs() + P.specs()] == ["nba.margin_heteroscedasticity", "nba.period_margin_pmf"]
    assert {"nba.margin_heteroscedasticity", "nba.period_margin_pmf"} <= VC.load_owner_reopen()
    assert "DOWNGRADED_BY_VERIFIER" not in VC.PROMOTABLE                 # reopening is per listed input, never a blanket rule

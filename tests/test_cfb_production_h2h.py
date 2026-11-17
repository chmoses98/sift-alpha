"""CFB production head-to-head helpers: forecast selection before the cutoff, per-family latest record, identity, p_home."""
import numpy as np
import pandas as pd

from alpha_engine.discovery import cfb_production_h2h as H

T = lambda s: pd.Timestamp(s, tz="UTC")


def _runs():
    rows = []
    def add(gen, commit, fam, ent, mean, p=np.nan):
        rows.append({"file": "f", "commit_utc": T(commit), "model_id": "pf-cfb", "model_version": "v", "family": fam, "game_id": "1", "entity_id": ent,
                     "generated_utc": T(gen), "archived_utc": T(gen), "prod_start_utc": T("2026-11-01 20:00"), "mean": mean, "p_home": p, "gate": "PASS"})
    for gen, commit, m in (("2026-10-30 10:00", "2026-10-30 10:10", 3.0), ("2026-11-01 17:00", "2026-11-01 17:10", 5.0), ("2026-11-01 19:00", "2026-11-01 21:00", 9.0)):
        add(gen, commit, "team_points", "10", 20 + m); add(gen, commit, "team_points", "20", 20.0)
        add(gen, commit, "margin", "MARGIN", m, 0.6); add(gen, commit, "game_total", "TOTAL", 40 + m)
    return pd.DataFrame(rows)


def test_selection_respects_generation_and_commit_time():
    res = pd.DataFrame({"game_id": ["1"], "kickoff_utc": [T("2026-11-01 20:00")], "final": [True], "home_id": ["10"], "away_id": ["20"]})
    t, ev = H.production_table(_runs(), res, 0.0)
    assert len(t) == 1 and t.margin.iloc[0] == 5.0          # the 19:00 run was committed after kickoff
    t4, _ = H.production_table(_runs(), res, 4.0)
    assert t4.margin.iloc[0] == 3.0 and t4.lead_hours_actual.iloc[0] > 4


def test_identity_mismatch_is_left_out():
    res = pd.DataFrame({"game_id": ["1"], "kickoff_utc": [T("2026-11-01 20:00")], "final": [True], "home_id": ["10"], "away_id": ["99"]})
    t, ev = H.production_table(_runs(), res, 0.0)
    assert t.empty and ev["identity_mismatch"] == 1


def test_p_home_from_margin_distribution():
    probs = np.zeros(201); probs[100] = 0.2; probs[110] = 0.5; probs[90] = 0.3   # lo = -100: index 100 is margin 0
    assert abs(H._p_home(probs, -100) - 0.6) < 1e-12


def test_compare_identical_forecasts_have_zero_difference():
    n = 40; rng = np.random.default_rng(0)
    y = rng.normal(3, 14, n)
    d = pd.DataFrame({"date": pd.date_range("2026-10-01", periods=n), "neutral": 0.0, "y_home_margin": y, "y_total": 50 + y,
                      "margin": y + 1, "total": 51 + y, "p_home": 0.5, "c_m": y + 1, "c_s": 1e9, "c_t": 51 + y})
    r = H.compare(d, {"c": ("c_m", "c_s", "c_t")}, {"game": np.arange(n)})
    assert r["c"]["paired"]["margin_sq_err_challenger_minus_production"]["mean"] == 0
    assert abs(r["c"]["paired"]["brier_challenger_minus_production"]["mean"]) < 1e-6
    assert r["production"]["margin"]["bias_pred_minus_actual"] == 1.0

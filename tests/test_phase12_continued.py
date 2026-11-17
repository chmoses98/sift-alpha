"""Phase 12 continued: dataset-certification route in the replay ledger, NBA player-box builder, production head-to-head."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from alpha_engine.discovery import production_h2h as H
from alpha_engine.features import nba_player_box as B
from alpha_engine.input_research.data_foundation import verified_coverage as V


def _cert(tmp_path, ok_leak=True, mism=0):
    c = {"catalog_inputs_eligible_for_promotion": {"NBA": ["nba.x"]},
         "sports": {"NBA": {"verdict": "CERTIFIED", "blind_reimplementation": {"identical": mism == 0, "cells_mismatched": mism}, "truncation_check": True,
                            "leakage": {"d": {"future_scramble_identical": True, "own_game_identical": ok_leak}}}}}
    (tmp_path / "certification_t.json").write_text(json.dumps(c))
    return V.load_dataset_certifications(tmp_path)


def test_certification_gates(tmp_path):
    assert _cert(tmp_path)[("NBA", "nba.x")]["passed"] is True
    assert _cert(tmp_path, ok_leak=False)[("NBA", "nba.x")]["passed"] is False
    assert _cert(tmp_path, mism=3)[("NBA", "nba.x")]["passed"] is False


def test_certification_never_overrides_failure_or_downgrades(tmp_path):
    ev = _cert(tmp_path)[("NBA", "nba.x")]
    assert V.apply_dataset_certification("REQUIRES_COLLECTION", {}, ev)[0] == "VERIFIED_DATASET_CERTIFIED"
    assert V.apply_dataset_certification("DOWNGRADED_BY_VERIFIER", {}, ev)[0] == "DOWNGRADED_BY_VERIFIER"
    assert V.apply_dataset_certification("VERIFIED_FULL", {}, ev)[0] == "VERIFIED_FULL"
    bad = _cert(tmp_path, ok_leak=False)[("NBA", "nba.x")]
    assert V.apply_dataset_certification("REQUIRES_COLLECTION", {}, bad)[0] == "REQUIRES_COLLECTION"
    assert V.HEADLINE["VERIFIED_DATASET_CERTIFIED"] == "PARTIAL"


def _raw():
    rows = []
    rng = np.random.default_rng(0)
    for g in range(12):
        date = f"2025-11-{g + 1:02d}"
        for team in (1, 2):
            for a in range(8):
                m = float(rng.integers(0, 40)) if a < 7 else None
                rows.append({"game_id": 100 + g, "season": 2026, "season_type": 2, "game_date": date, "athlete_id": team * 100 + a, "team_id": team,
                             "minutes": m, "points": float(rng.integers(0, 35)) if m else None, "rebounds": float(rng.integers(0, 12)) if m else None,
                             "assists": float(rng.integers(0, 9)) if m else None, "starter": a < 5})
    return pd.DataFrame(rows)


def test_player_box_point_in_time_and_brute_force():
    raw = _raw()
    d = B.build(raw)
    assert list(d.columns) == B.COLUMNS and not d["key"].duplicated().any()
    r = d[d["n_app_pre"] >= 6].iloc[0]
    p, _ = B.rows(raw)
    h = p[(p.athlete_id == r.athlete_id) & (p.date < r.date) & p.appeared]
    assert np.isclose(r.min_mean_pre, h.minutes.mean()) and np.isclose(r.cov_pts_reb_pre, np.cov(h.points_z, h.rebounds_z)[0, 1])
    # perturbing the last date never changes earlier rows
    raw2 = raw.copy()
    last = raw2.game_date == raw2.game_date.max()
    raw2.loc[last, "points"] = 99.0
    d2 = B.build(raw2)
    early = d.date < raw.game_date.max()
    assert B._same(d[early].reset_index(drop=True), d2[early].reset_index(drop=True))


def test_production_h2h_identical_inputs_give_zero_delta():
    data = pd.DataFrame({"game_id": [1, 2, 3, 4], "date": ["2026-11-01", "2026-11-01", "2026-11-02", "2026-11-03"],
                         "y_home_margin": [5, -3, 10, -1], "y_total": [140, 150, 160, 130]})
    pred = pd.DataFrame({"game_id": [1, 2, 3, 4], "season": 2027, "margin_mu": [4, -2, 6, 1], "total_mu": [145, 145, 150, 140],
                         "margin_sigma": 12.0, "total_sigma": 18.0})
    prod = pred.rename(columns={"margin_mu": "margin", "total_mu": "total"})[["game_id", "margin", "total"]].assign(p_home=0.6)
    r = H.compare(pred, data, prod)
    assert r["n_games"] == 4 and r["margin"]["delta_mae_challenger_minus_production"][0] == 0.0

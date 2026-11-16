"""Phase 8: upcoming-game NFL features equal completed-game features (truncation), CBB builder is point-in-time, manifests are consistent."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "research/data_foundation_ops"


def _j(p):
    return json.loads(p.read_text())


def test_phase8_log_matches_manifests():
    p8 = _j(OPS / "phase8_acquisition.json")
    for t in p8["training_sets"]:
        m = _j(ROOT / t["file"])
        assert m["rows"] == t["rows"] and m["checks"]["canonical_sha256"] == t["canonical_sha256"]
        assert t["deterministic"] and t["keys_unique"]
    assert {t["sport"] for t in p8["training_sets"]} >= {"NFL", "NHL", "NBA", "CBB"}
    cbb = next(t for t in p8["training_sets"] if t["sport"] == "CBB")
    assert "CERTIFIED_TRAINING_READY" in cbb["admission"] and cbb["truncation_check"] is True
    assert p8["upcoming"]["equivalence_all_equal"] is True
    plan = _j(OPS / "acquisition_plan.json")["totals"]
    assert p8["totals"]["training_ready_inputs"] <= plan["training_ready_inputs"] and p8["totals"]["missing_primary_slots"] == plan["missing_primary_slots"]


def test_certified_sets_admit_only_training_ready_inputs():
    acq = _j(OPS / "acquisition_inputs.json")["inputs"]
    for sp in ("NHL", "NBA"):
        m = _j(OPS / f"training_sets/{sp}.json")
        ready = {k.split(":", 1)[1] for k, v in acq.items() if v["s"] == sp and v["tr"]["state"] == "TRAINING_READY"}
        assert {k.split(" ")[0] for k in m["inputs"]} <= ready
        assert not any(c.split("_", 1)[1].startswith("y_") for c in m["column_coverage"])


def test_nfl_upcoming_manifest():
    m = _j(OPS / "training_sets/NFL_upcoming.json")
    assert m["equivalence_check"]["all_equal"] and all(v["max_abs_diff"] == 0.0 for v in m["equivalence_check"]["dates"].values())
    assert m["n_feature_columns"] == _j(OPS / "training_sets/NFL.json")["n_feature_columns"]


def test_next_games_are_next_for_both_teams_and_current_season():
    from alpha_engine.features import nfl_upcoming as U
    g = pd.DataFrame({"game_id": ["old", "a1", "a2", "b1"], "season": [2022, 2026, 2026, 2026], "gameday": ["2023-01-02", "2026-11-15", "2026-11-22", "2026-11-22"],
                      "home_team": ["BUF", "BUF", "KC", "NYJ"], "away_team": ["CIN", "MIA", "BUF", "NE"], "home_score": [np.nan, np.nan, np.nan, np.nan]})
    g = pd.concat([g, pd.DataFrame({"game_id": ["done"], "season": [2026], "gameday": ["2026-11-08"], "home_team": ["KC"], "away_team": ["NE"], "home_score": [20.0]})])
    n = U.next_games(g)
    assert set(n.game_id) == {"a1", "b1"}          # a2 is not BUF's next game; 'old' is a never-played 2022 game


def test_cbb_features_use_only_earlier_dates():
    from alpha_engine.features import cbb_box as C
    rng = np.random.default_rng(0); rows = []
    dates = pd.date_range("2024-11-01", periods=60, freq="D"); teams = list(range(30))
    gid = 0
    for d in dates:
        perm = rng.permutation(teams)
        for i in range(0, 30, 2):
            gid += 1
            for t, o, ha in ((perm[i], perm[i + 1], "home"), (perm[i + 1], perm[i], "away")):
                rows.append({"game_id": gid, "season": 2025, "season_type": 2, "game_date": d.date(), "team_id": int(t), "opponent_team_id": int(o), "team_home_away": ha,
                             "field_goals_attempted": 60, "field_goals_made": int(rng.integers(20, 32)), "three_point_field_goals_made": 7, "free_throws_attempted": 20,
                             "offensive_rebounds": 10, "defensive_rebounds": 25, "turnovers": 12, "team_score": int(rng.integers(55, 90)), "opponent_team_score": 0})
    tb = pd.DataFrame(rows)
    sc = tb.groupby("game_id").first().reset_index()[["game_id"]].assign(neutral_site=False, conference_competition=False, home_id=np.nan, away_id=np.nan,
                                                                         home_conference_id=np.nan, away_conference_id=np.nan)
    tb["opponent_team_score"] = tb.merge(tb[["game_id", "team_id", "team_score"]].rename(columns={"team_id": "opponent_team_id", "team_score": "os"}), on=["game_id", "opponent_team_id"]).os.values
    full = C.compute({"team_box": tb, "schedule": sc})["team"]
    d = dates[40]
    tb2 = tb.copy(); tb2.loc[pd.to_datetime(tb2.game_date) > d, "team_score"] += 30          # change the future only
    part = C.compute({"team_box": tb2, "schedule": sc})["team"]
    a = full[full.date <= d].sort_values(["game_id", "team_id"])[C.PRE_COLS].to_numpy(float)
    b = part[part.date <= d].sort_values(["game_id", "team_id"])[C.PRE_COLS].to_numpy(float)
    assert np.allclose(np.nan_to_num(a), np.nan_to_num(b))

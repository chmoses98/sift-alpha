"""Phase 7 (data acquisition + training datasets): the committed evidence must agree with itself. No raw data is needed."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "research/data_foundation_ops"
VD = ROOT / "research/input_research/data_foundation/verification"


def _j(p):
    return json.loads(Path(p).read_text())


def test_phase7_built_inputs_pass_every_gate():
    p7 = _j(OPS / "phase7_acquisition.json")
    assert {b["input"] for b in p7["built"]} == {"NFL:nfl.pass_run_split_epa_both_sides", "NFL:nfl.rush_yardage_tail"}
    for b in p7["built"]:
        n = len(b["columns"])
        assert b["replay_ok"] and b["blind_match"] == f"{n}/{n}"
        assert b["verified_status"] == "VERIFIED_FULL" and b["pit"] == "PIT_SAFE" and b["training_state"] == "TRAINING_READY"


def test_phase7_counts_are_recomputed_not_typed():
    p7 = _j(OPS / "phase7_acquisition.json"); plan = _j(OPS / "acquisition_plan.json")
    assert p7["after"]["training_ready_inputs"] == plan["totals"]["training_ready_inputs"] == p7["baseline"]["training_ready_inputs"] + 2
    assert sum(p7["training_ready_by_sport"].values()) == p7["after"]["training_ready_inputs"]


def test_nfl_training_set_manifest():
    m = _j(OPS / "training_sets/NFL.json")
    ready = {k.split(":", 1)[1] for k, v in _j(OPS / "acquisition_inputs.json")["inputs"].items() if v["s"] == "NFL" and v["tr"]["state"] == "TRAINING_READY"}
    assert set(m["inputs"]) <= ready and "nfl.pass_run_split_epa_both_sides" in m["inputs"]
    assert m["checks"]["keys_unique"] and m["checks"]["deterministic_regeneration"]
    assert m["outcome_reconciliation"]["outcome_mismatches"] <= 0.005 * m["outcome_reconciliation"]["games_with_pbp"]
    assert set(m["rows_by_split"]) == {"train", "validate", "test", "prospective"}
    assert not any(c.split("_", 1)[1].startswith("y_") for c in m["column_coverage"])     # outcomes are never feature columns


def test_rusher_perturbation_preserves_universe():
    import pandas as pd
    from alpha_engine.features import nfl_rush_ext3 as R
    pbp = pd.DataFrame({"game_id": ["g1"] * 4 + ["g2"] * 2, "rush_attempt": [1, 1, 0, 1, 1, 1], "rushing_yards": [3.0, 12.0, None, -1.0, 40.0, 5.0], "rusher_player_id": list("ABxCAB")})
    out = R.perturb({"pbp": pbp}, {"g1"}, 7)["pbp"]
    assert out.rusher_player_id.tolist() == pbp.rusher_player_id.tolist()
    assert sorted(out.rushing_yards[:4].dropna()) == sorted(pbp.rushing_yards[:4].dropna()) and out.rushing_yards[4:].tolist() == [40.0, 5.0]

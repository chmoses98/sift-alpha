"""Phase 6 NFL builders: spec hygiene and the committed verification evidence (no raw data needed)."""
import json
from pathlib import Path

from alpha_engine.features import nfl_part_ext, nfl_pbp_ext2

V = Path(__file__).resolve().parents[1] / "research/input_research/data_foundation"


def test_specs_unique_partial_and_documented():
    ids = []
    for m in (nfl_pbp_ext2, nfl_part_ext):
        for s in m.specs():
            ids.append(s.catalog_id)
            assert s.level == "PARTIAL" and s.missing and s.pit == "pregame_rolling"
            assert len(set(s.columns)) == len(s.columns) and all(c.endswith("_pre") for c in s.columns)
    assert len(ids) == len(set(ids)) == 13


def test_independent_match_is_exact_and_keys_identical():
    for f in ("NFL_pbp2", "NFL_part"):
        d = json.loads((V / f"verification/independent/{f}.json").read_text())
        assert d["keys_identical"]
        for v in d["inputs"].values():
            assert v["columns"] and all(c["verdict"] == "MATCH" and c["nan_pattern_mismatch"] == 0 and c["match"] == c["n"] for c in v["columns"].values())


def test_promoted_inputs_in_matrix():
    rows = {r["id"]: r for r in json.loads((V / "verified_coverage.json").read_text())["rows"]}
    for m in (nfl_pbp_ext2, nfl_part_ext):
        for s in m.specs():
            assert rows[s.catalog_id]["verified_status"] == "VERIFIED_PARTIAL"

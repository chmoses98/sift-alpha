"""Phase 7 builders (NBA, NHL, tennis) and the market-completeness measure: spec hygiene, committed verification evidence, an Elo chronology property test and the 170-archetype partition (no raw data needed)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.features import nba_ext, nba_player_ext, nhl_ext, tennis_ext2, tennis_ext3
from alpha_engine.input_research.data_foundation import market_completeness as MC

V = Path(__file__).resolve().parents[1] / "research/input_research/data_foundation"
MODS = (nba_ext, nba_player_ext, nhl_ext, tennis_ext2, tennis_ext3)
FULL_IDS = {"nhl.loser_point_rate", "ten.major_winner_concentration", "ten.home_slam_depth_prior", "ten.second_serve_vulnerability"}      # specs that claim FULL (whole definition implemented)
CANDIDATES = FULL_IDS - {"ten.home_slam_depth_prior"}                                                                                  # home_slam_depth_prior is defined only for the four majors: coverage < 50 % is a recorded limit, so it is not a full candidate


def _specs():
    return [s for m in MODS for s in m.specs()]


def test_specs_unique_and_honest_levels():
    ids = [s.catalog_id for s in _specs()]
    assert len(ids) == len(set(ids)) == 34
    for s in _specs():
        assert s.pit == "pregame_rolling" and len(set(s.columns)) == len(s.columns) and all(c.endswith("_pre") or c.startswith(("s2s_", "hsdp_home")) for c in s.columns)
        if s.catalog_id in FULL_IDS:
            assert s.level == "FULL" and not s.missing
        else:
            assert s.level == "PARTIAL" and s.missing          # a PARTIAL must say what is missing; nothing else may claim FULL


def test_independent_match_is_exact_and_keys_identical():
    for f in ("NBA_nba_team", "NBA_nba_player", "NHL_nhl", "TENNIS_tennis2", "TENNIS_tennis3"):
        d = json.loads((V / f"verification/independent/{f}.json").read_text())
        assert d["keys_identical"] and d["inputs"]
        for v in d["inputs"].values():
            assert v["columns"] and all(c["verdict"] == "MATCH" and c["nan_pattern_mismatch"] == 0 and c["match"] == c["n"] for c in v["columns"].values())


def test_replay_gates_all_pass_and_are_non_vacuous():
    for f in ("NBA_nba_team", "NBA_nba_player", "NHL_nhl", "TENNIS_tennis2", "TENNIS_tennis3"):
        d = json.loads((V / f"verification/replay_ext/{f}.json").read_text())
        assert not d["quick"]
        for iid, r in d["inputs"].items():
            t = r["tests"]
            assert t["determinism"]["ok"] and t["own_game"]["ok"] and all(x["ok"] for x in t["truncation"]) and all(x["ok"] for x in t["perturbation"]) and len(t["truncation"]) == 3, iid
            assert t["pit_check_perturbation_not_vacuous"]["ok"], iid


def test_promoted_inputs_in_matrix_certified_only_with_evidence():
    """Phase 8: the former unconditional cap is replaced by evidence-based certification (tests/test_extension_gate.py). The three full candidates are FULL with certification evidence; every other Phase 7 input stays PARTIAL."""
    rows = {r["id"]: r for r in json.loads((V / "verified_coverage.json").read_text())["rows"]}
    for s in _specs():
        r = rows[s.catalog_id]
        if s.catalog_id in CANDIDATES:
            assert r["verified_status"] == "VERIFIED_FULL" and r["evidence"].get("full_certified"), s.catalog_id
        else:
            assert r["verified_status"] == "VERIFIED_PARTIAL" and not r["evidence"].get("full_certified"), s.catalog_id


def _matches(rng, n=400):
    d = pd.DataFrame({"tour": rng.choice(["atp", "wta"], n), "date": pd.to_datetime("2000-01-03") + pd.to_timedelta(rng.integers(0, 12, n) * 7, unit="D"), "tourney_id": "t", "match_num": np.arange(n),
                      "winner_id": rng.integers(1, 15, n), "loser_id": rng.integers(15, 30, n), "surface": rng.choice(["Hard", "Clay", "Grass"], n), "score": "6-4 6-4"})
    d["game_id"] = d.tour + "|" + d.index.astype(str)
    return d


def test_elo_pre_ratings_use_only_strictly_earlier_dates():
    """Regression for the ordering defect found by the blind comparison: (tour, date) batches must be processed chronologically, so flipping every LATER result can never change an earlier pre-match rating."""
    rng = np.random.default_rng(7); base = _matches(rng)
    a = tennis_ext2._elo(base.copy())
    cut = pd.Timestamp("2000-02-14")
    flip = base.copy(); late = flip.date >= cut
    flip.loc[late, ["winner_id", "loser_id"]] = flip.loc[late, ["loser_id", "winner_id"]].to_numpy()
    b = tennis_ext2._elo(flip)
    idx = a.set_index("game_id"); ea = idx.loc[(idx.date < cut).to_numpy(), ["elo_w", "elo_l", "selo_w", "p_fav", "bin"]]
    eb = b.set_index("game_id").loc[ea.index, ["elo_w", "elo_l", "selo_w", "p_fav", "bin"]]
    assert np.allclose(ea.to_numpy(float), eb.to_numpy(float), equal_nan=True)
    first = a[a.date == a.date.min()]
    assert (first.elo_w == 1500).all() and (first.elo_l == 1500).all()                        # nothing is known before the first batch


def test_market_completeness_partition_and_universe():
    rows = MC.measure({f"{a['sport']}:{i}": "REQUIRES_COLLECTION" for a in MC.archetypes() for i, _ in a["inputs"]}, {})
    assert len(rows) == 170 and len({(r["sport"], r["archetype"]) for r in rows}) == 170
    for r in rows:
        assert r["n_required"] == sum(r[k] for k in ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "UNMAPPED"))
    live = json.loads((V.parent / "market_completeness/market_completeness.json").read_text())["rows"]
    assert len(live) == 170 and sorted(r["rank"] for r in live) == list(range(1, 171)) and all(r["UNMAPPED"] == 0 for r in live)
    assert all(0 <= (r["completeness_score"] or 0) <= 1 and 0 <= (r["critical_score"] or 0) <= 1 for r in live)

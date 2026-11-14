"""Phase 15 builders (NBA team/player, NHL results/events/skaters) from the owner's archives: spec hygiene, committed verification evidence (replay gates + blind exact match),
matrix promotion, and chronology property tests on synthetic data (no raw data needed)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.features import nba_ext3, nba_player_ext3, nhl_ev_ext2, nhl_ext2, nhl_player_ext2

V = Path(__file__).resolve().parents[1] / "research/input_research/data_foundation"
MODS = (nba_ext3, nba_player_ext3, nhl_ext2, nhl_ev_ext2, nhl_player_ext2)
FILES = ("NBA_nba_team3", "NBA_nba_player3", "NHL_nhl2", "NHL_nhl_ev2", "NHL_nhl_player2")
PROXY_IDS = {"nba.lineup_adj_rating"}          # stand-ins for BOTH the impact metric and the expected-active set: a different measurement of the same mechanism
N_INPUTS = {"NBA": 11, "NHL": 19}


def _specs():
    return [s for m in MODS for s in m.specs()]


def test_specs_unique_honest_levels_and_no_full_claim():
    ids = [s.catalog_id for s in _specs()]
    assert len(ids) == len(set(ids)) == 30
    assert {sp: sum(1 for s in _specs() if s.sport == sp) for sp in N_INPUTS} == N_INPUTS
    cols = [c for s in _specs() for c in s.columns]
    assert len(cols) == len(set(cols))                                   # no column is claimed by two inputs
    for s in _specs():
        assert s.pit == "pregame_rolling" and s.columns and all(c.endswith("_pre") for c in s.columns)
        assert s.missing and s.done and s.raw                           # nothing claims FULL: every spec says what is missing
        assert s.level == ("PROXY" if s.catalog_id in PROXY_IDS else "PARTIAL"), s.catalog_id


def test_phase15_ids_do_not_collide_with_earlier_extension_builders():
    from alpha_engine.features import cbb_ext, nba_ext, nba_player_ext, nhl_ext
    old = {s.catalog_id for m in (nba_ext, nba_player_ext, nhl_ext, cbb_ext) for s in m.specs()}
    assert not old & {s.catalog_id for s in _specs()}


def test_independent_match_is_exact_and_keys_identical():
    seen = set()
    for f, m in zip(FILES, MODS):
        d = json.loads((V / f"verification/independent/{f}.json").read_text())
        assert d["keys_identical"] and set(d["inputs"]) == {s.catalog_id for s in m.specs()}
        for s in m.specs():
            c = d["inputs"][s.catalog_id]["columns"]
            assert set(c) == set(s.columns)
            assert all(x["verdict"] == "MATCH" and x["nan_pattern_mismatch"] == 0 and x["match"] == x["n"] > 0 for x in c.values()), s.catalog_id
            seen.add(s.catalog_id)
    assert len(seen) == 30


def test_replay_gates_all_pass_and_are_non_vacuous():
    for f, m in zip(FILES, MODS):
        d = json.loads((V / f"verification/replay_ext/{f}.json").read_text())
        assert not d["quick"] and set(d["inputs"]) == {s.catalog_id for s in m.specs()}
        for iid, r in d["inputs"].items():
            t = r["tests"]
            assert t["determinism"]["ok"] and t["own_game"]["ok"] and all(x["ok"] for x in t["truncation"]) and all(x["ok"] for x in t["perturbation"]), iid
            assert len(t["truncation"]) == 3 and len({x["seed"] for x in t["perturbation"]}) == 3, iid
            assert t["pit_check_perturbation_not_vacuous"]["ok"] and not t["coverage_replay"]["constant_columns"], iid


def test_promoted_inputs_in_matrix_are_partial_or_proxy_never_full():
    rows = {r["id"]: r for r in json.loads((V / "verified_coverage.json").read_text())["rows"]}
    for s in _specs():
        r = rows[s.catalog_id]
        want = "VERIFIED_PROXY" if s.catalog_id in PROXY_IDS else "VERIFIED_PARTIAL"
        assert r["verified_status"] == want and not r["evidence"].get("full_certified"), s.catalog_id
        assert r["evidence"]["promoted_from"] in ("REQUIRES_COLLECTION", "DATA_IN_HAND_CONFIRMED", "DATA_IN_HAND_SCHEMA_ONLY")
        assert set(r["evidence"]["independent"].values()) == {"MATCH"}


def test_no_downgraded_or_quarantined_input_was_touched():
    """DOWNGRADED_BY_VERIFIER and PIT_QUARANTINED inputs are not promotable; Phase 15 builds none of them."""
    audit = {r["id"]: r for r in json.loads((V / "input_audit.json").read_text())["rows"]}
    rows = {r["id"]: r for r in json.loads((V / "verified_coverage.json").read_text())["rows"]}
    for s in _specs():
        assert audit[s.catalog_id]["sport"] == s.sport
        assert rows[s.catalog_id]["verified_status"] not in ("DOWNGRADED_BY_VERIFIER", "PIT_QUARANTINED", "REPLAY_FAILED")


# ---------------------------------------------------------------- chronology property tests on synthetic data
def _nba_raw(rng, n_dates=70):
    teams = list(range(1, 7)); tg, pg = [], []
    for k in range(n_dates):
        season = "2023-24" if k < n_dates // 2 else "2024-25"
        date = (pd.Timestamp("2023-11-01" if k < n_dates // 2 else "2024-11-01") + pd.Timedelta(days=2 * (k % (n_dates // 2)))).strftime("%Y-%m-%d")
        order = rng.permutation(teams)
        for g in range(3):
            h, a = int(order[2 * g]), int(order[2 * g + 1]); gid = f"g{k:03d}{g}"
            hp, ap = int(rng.integers(90, 130)), int(rng.integers(90, 130)); ap += int(ap == hp); poss = float(rng.uniform(92, 104)); ot = int(rng.random() < 0.06)
            for t, o, home, p, q in ((h, a, True, hp, ap), (a, h, False, ap, hp)):
                tg.append({"game_id": gid, "game_date_et": date, "season": season, "season_type": "regular", "team_id": t, "opp_team_id": o, "home": home, "pts": p, "opp_pts": q, "n_ot": ot, "possessions": poss})
                for j in range(9):
                    played = rng.random() < 0.9
                    pg.append({"game_id": gid, "game_date_et": date, "season": season, "season_type": "regular", "team_id": t, "nba_id": t * 100 + j, "played": bool(played), "started": bool(played and j < 5),
                               "minutes": float(rng.integers(8, 38)) if played else 0.0, "pts": int(rng.integers(0, 30)), "reb": int(rng.integers(0, 12)), "ast": int(rng.integers(0, 9)), "stl": int(rng.integers(0, 3)),
                               "blk": int(rng.integers(0, 3)), "fg3m": int(rng.integers(0, 5)), "fg3a": int(rng.integers(5, 11)), "plus_minus": int(rng.integers(-20, 21))})
    return {"team_games": pd.DataFrame(tg), "player_games": pd.DataFrame(pg)}


def _scramble(df, late, cols, rng):
    d = df.copy(); ix = np.flatnonzero(late)
    for c in cols:
        v = d[c].to_numpy(copy=True); v[ix] = rng.permutation(v[ix]); d[c] = v
    return d


def _early_equal(mod, raw, raw2, cut, date_col):
    a = mod.compute(raw)["team"]; b = mod.compute(raw2)["team"].set_index(["game_id", "team"]).reindex(a.set_index(["game_id", "team"]).index).reset_index()
    sel = (a.date < cut).to_numpy(); cols = [c for s in mod.specs() for c in s.columns]
    assert sel.sum() > 50 and (~sel).sum() > 50
    assert np.allclose(a.loc[sel, cols].to_numpy(float), b.loc[sel, cols].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)
    moved = [c for c in cols if not np.allclose(a.loc[~sel, c].to_numpy(float), b.loc[~sel, c].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)]
    return cols, moved


def test_nba_team_features_use_only_strictly_earlier_dates():
    rng = np.random.default_rng(15); raw = _nba_raw(rng); cut = pd.Timestamp("2024-11-21")
    late_t = (pd.to_datetime(raw["team_games"].game_date_et) >= cut).to_numpy(); late_p = (pd.to_datetime(raw["player_games"].game_date_et) >= cut).to_numpy()
    raw2 = {"team_games": _scramble(raw["team_games"], late_t, nba_ext3.TG_CONTENT, rng), "player_games": _scramble(raw["player_games"], late_p, nba_ext3.PG_CONTENT, rng)}
    cols, moved = _early_equal(nba_ext3, raw, raw2, cut, "game_date_et")
    assert len(moved) >= len(cols) - 6          # the scramble is not vacuous: later rows of (nearly) every column move (previous-season-only and near-zero tail columns may not)


def test_nba_player_features_use_only_strictly_earlier_dates():
    rng = np.random.default_rng(16); raw = {"player_games": _nba_raw(rng)["player_games"]}; cut = pd.Timestamp("2024-11-21")
    late = (pd.to_datetime(raw["player_games"].game_date_et) >= cut).to_numpy()
    cols, moved = _early_equal(nba_player_ext3, raw, {"player_games": _scramble(raw["player_games"], late, nba_player_ext3.PG_CONTENT, rng)}, cut, "game_date_et")
    assert len(moved) >= len(cols) - 1          # rm_p_any_pre saturates at 1 on the synthetic volume


def _nhl_games(rng, n_dates=120):
    teams = list(range(1, 9)); rows = []
    for k in range(n_dates):
        season = 2010 + k // 60; date = (pd.Timestamp(f"{season}-10-05") + pd.Timedelta(days=2 * (k % 60))).strftime("%Y-%m-%d"); order = rng.permutation(teams)
        for g in range(4):
            hs, as_ = int(rng.integers(0, 6)), int(rng.integers(0, 6)); lpt = "REG"
            if hs == as_: hs += 1; lpt = str(rng.choice(["OT", "SO"]))
            rows.append({"game_id": 1000000 * season + 10 * k + g, "season": season, "game_type": 2, "game_date": date, "home_team_id": int(order[2 * g]), "away_team_id": int(order[2 * g + 1]), "home_score": hs, "away_score": as_,
                         "last_period_type": lpt, "final": True})
    return pd.DataFrame(rows)


def test_nhl_result_features_use_only_strictly_earlier_dates():
    rng = np.random.default_rng(17); g = _nhl_games(rng); cut = pd.Timestamp("2011-11-20")
    mp = pd.concat([pd.DataFrame({"game_id": g.game_id, "team_id": g[c], "situation": "all", "iceTime": 3600.0, "scoreVenueAdjustedxGoalsFor": rng.uniform(1.5, 4.0, len(g)), "scoreVenueAdjustedxGoalsAgainst": rng.uniform(1.5, 4.0, len(g))})
                    for c in ("home_team_id", "away_team_id")], ignore_index=True)
    raw = {"games": g, "mp": mp}; late = set(g.loc[pd.to_datetime(g.game_date) >= cut, "game_id"])
    raw2 = {"games": _scramble(g, g.game_id.isin(late).to_numpy(), nhl_ext2.G_CONTENT, rng), "mp": _scramble(mp, mp.game_id.isin(late).to_numpy(), nhl_ext2.MP_CONTENT, rng)}
    a = nhl_ext2.compute(raw)["team"]; b = nhl_ext2.compute(raw2)["team"]; sel = (a.date < cut).to_numpy()
    cols = [c for s in nhl_ext2.specs() for c in s.columns if not c.startswith(("sc_", "pc_"))]        # no playoff games in the synthetic schedule
    assert np.allclose(a.loc[sel, cols].to_numpy(float), b.loc[sel, cols].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)
    assert all(not np.allclose(a.loc[~sel, c].to_numpy(float), b.loc[~sel, c].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True) for c in cols)


def test_series_win_probability_recursion():
    f = nhl_ext2._series_p
    assert f(0, 0, 1, 0.5) == 0.5 and f(4, 1, 6, 0.6) == 1.0 and f(2, 4, 7, 0.6) == 0.0
    assert abs(f(3, 3, 7, 0.55) - 0.55) < 1e-12                          # game 7 is hosted by the team that hosted game 1
    assert abs(f(3, 2, 6, 0.55) - (0.45 + 0.55 * 0.55)) < 1e-12          # game 6 away, then game 7 at home
    assert f(0, 0, 1, 0.6) > 0.5 > 1 - f(0, 0, 1, 0.6)


def test_win_streak_recursion():
    p20 = nba_ext3._p20
    assert p20(20, 0, 0.5) == 1.0 and p20(0, 19, 0.9) == 0.0 and abs(p20(0, 20, 0.9) - 0.9 ** 20) < 1e-15 and abs(p20(19, 1, 0.7) - 0.7) < 1e-15
    assert p20(5, 40, 0.8) > p20(0, 40, 0.8) > p20(0, 30, 0.8)

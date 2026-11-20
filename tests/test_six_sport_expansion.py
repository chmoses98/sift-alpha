"""Six-sport expansion builders (score_core, cfb_espn_ext, nhl_period_ext, mlb_line_ext): point-in-time behaviour on synthetic data and the committed certification evidence. RESEARCH_ONLY."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha_engine.features import cfb_espn_ext as CF, mlb_line_ext as ML, nhl_period_ext as NH, score_core as C

ROOT = Path(__file__).resolve().parents[1]
VD = ROOT / "research/input_research/data_foundation/verification"
FAM = {"CFB_cfb_espn": CF, "NHL_nhl_period": NH, "MLB_mlb_line": ML}


def _games(mod, seed=0, seasons=(2020, 2021, 2022)):
    rng = np.random.default_rng(seed); rows = []; gid = 0
    for s in seasons:
        for wk in range(14):
            o = rng.permutation(8); d = pd.Timestamp(f"{s}-09-01") + pd.Timedelta(days=7 * wk)
            for k in range(4):
                gid += 1; r = {"game_id": gid, "season": s, "game_date": d, "home": int(o[2 * k]), "away": int(o[2 * k + 1]), "ne": 1.0}
                r.update({c: float(rng.integers(0, 9)) for c in mod.CONTENT}); rows.append(r)
    return {"games": pd.DataFrame(rows)}


@pytest.mark.parametrize("mod", [CF, NH, ML])
def test_strictly_prior_information(mod, monkeypatch):
    monkeypatch.setattr(mod, "MIN_REF", 40); monkeypatch.setattr(mod, "MIN_COND", 5, raising=False)
    raw = _games(mod); full = mod.compute(raw)["team"]; cols = [c for s in mod.specs() for c in s.columns]
    assert len(cols) == len(set(cols)) and set(cols) <= set(full.columns) and len(full) == 2 * len(raw["games"])
    g = raw["games"]; cut = pd.Timestamp("2022-10-15")
    a = mod.compute({"games": g[g.game_date < cut]})["team"].set_index(["game_id", "team"])[cols]; b = full.set_index(["game_id", "team"])
    np.testing.assert_allclose(a.to_numpy(float), b.loc[a.index, cols].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)      # later games never change earlier rows
    late = (g.game_date >= cut).to_numpy(); g2 = g.copy(); g2.loc[late, mod.CONTENT] = 99.0
    c = mod.compute({"games": g2})["team"].set_index(["game_id", "team"]); first = c.index[c.date == c.date[c.date >= cut].min()]
    np.testing.assert_allclose(c.loc[first, cols].to_numpy(float), b.loc[first, cols].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)   # a game's own result never enters its own row
    assert full.loc[full.season == 2020, [c for c in cols if c in getattr(mod, "PML", []) + getattr(mod, "PES", []) + getattr(mod, "HOOK", [])]].isna().all().all()   # no earlier season -> no conditional frequency


def test_ridge_recovers_team_effects_and_absent_team_is_zero():
    rng = np.random.default_rng(3); off = rng.normal(0, 2, 6); rows = []
    for i in range(400):
        h, a = rng.choice(6, 2, replace=False); rows.append((i, 2020, pd.Timestamp("2020-01-01") + pd.Timedelta(days=i // 3), h, a, 1.0, 20 + off[h] + rng.normal(), 20 + off[a] + rng.normal()))
    rows.append((400, 2020, pd.Timestamp("2021-01-01"), 6, 0, 1.0, np.nan, np.nan))
    g = pd.DataFrame(rows, columns=["game_id", "season", "date", "home", "away", "ne", "yh", "ya"]); f = C.fit(g, {"y": (g.yh, g.ya)}, 1.0, 1e9, se="y")
    last = f.iloc[-1]; assert abs(last.y_off_a - (20 + off[0])) < 1.0 and np.isfinite(last.y_se)
    assert abs(last.y_off_h - last.y_def_h) < 1e-12                                                                     # team 6 never played: a = d = 0


def test_committed_certification_evidence():
    led = {r.split(",")[1]: r.split(",")[3] for r in (ROOT / "research/input_research/data_foundation/coverage_matrix.csv").read_text().splitlines()[1:]}
    for fam, mod in FAM.items():
        ind = json.loads((VD / f"independent/{fam}.json").read_text()); rep = json.loads((VD / f"replay_ext/{fam}.json").read_text())["inputs"]
        want = {s.catalog_id: "VERIFIED_" + s.level for s in mod.specs()}
        assert set(ind["inputs"]) == set(rep) == set(want) and ind["keys_identical"]
        assert all(v["verdict"] == "MATCH" for i in ind["inputs"].values() for v in i["columns"].values())
        assert {k: led[k] for k in want} == want                                                                         # the ledger never holds more than the claimed level


def _suspended_case(monkeypatch):
    """MLB synthetic season with one game suspended on day 40 and completed on day 60 (amendment 1: first-pitch chronology)."""
    monkeypatch.setattr(ML, "MIN_REF", 40)
    raw = _games(ML, seed=5); g = raw["games"].copy(); g["avail_date"] = g.game_date
    sid = int(g.loc[(g.season == 2021) & (g.game_date == g.loc[g.season == 2021, "game_date"].unique()[5]), "game_id"].iloc[0])
    fp = g.loc[g.game_id == sid, "game_date"].iloc[0]; g.loc[g.game_id == sid, "avail_date"] = fp + pd.Timedelta(days=20)
    return g, sid, fp


def test_mlb_suspended_game_uses_first_pitch_chronology(monkeypatch):
    g, sid, fp = _suspended_case(monkeypatch); cols = [c for s in ML.specs() for c in s.columns]
    full = ML.compute({"games": g})["team"].set_index(["game_id", "team"])
    assert (full.loc[sid, "date"] == fp).all()                                                                     # row dated by first pitch, not completion
    # 1) its own pre-game row uses nothing played on/after first pitch: drop every other game from first pitch on -> identical
    pre = ML.compute({"games": g[(g.game_date < fp) | (g.game_id == sid)]})["team"].set_index(["game_id", "team"])
    np.testing.assert_allclose(pre.loc[sid, cols].to_numpy(float), full.loc[sid, cols].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)
    # 2) games played between first pitch and completion never see its result; the first game after completion does
    g2 = g.copy(); g2.loc[g2.game_id == sid, ML.CONTENT] = 99.0; alt = ML.compute({"games": g2})["team"].set_index(["game_id", "team"])
    av = fp + pd.Timedelta(days=20); between = full.index[(full.date > fp) & (full.date < av)]; after = full.index[(full.date > av) & (full.season == 2021)]
    assert len(between) and len(after)
    np.testing.assert_allclose(alt.loc[between, ML.FI + ML.SPW].to_numpy(float), full.loc[between, ML.FI + ML.SPW].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)
    assert not np.allclose(alt.loc[after, ML.SPW].to_numpy(float), full.loc[after, ML.SPW].to_numpy(float), equal_nan=True)


def test_mlb_v1_resume_dating_would_fail_the_check(monkeypatch):
    """Regression guard: dating the suspended game by its completion (version 1) changes its pre-game row, i.e. uses post-first-pitch games."""
    g, sid, fp = _suspended_case(monkeypatch); cols = ML.FI + ML.SPW
    v1 = g.assign(game_date=g.avail_date).drop(columns="avail_date"); a = ML.compute({"games": v1})["team"].set_index(["game_id", "team"])
    b = ML.compute({"games": g})["team"].set_index(["game_id", "team"])
    assert not np.allclose(a.loc[sid, cols].to_numpy(float), b.loc[sid, cols].to_numpy(float), equal_nan=True)


def test_score_core_avail_absent_is_unchanged_and_rejects_inverted_dates():
    g = _games(ML, seed=9)["games"].rename(columns={"game_date": "date"}).sort_values(["date", "game_id"]).reset_index(drop=True)
    t = {"run": (g.h_r.to_numpy(float), g.a_r.to_numpy(float))}
    pd.testing.assert_frame_equal(C.fit(g, t, 10.0, 30.0), C.fit(g.assign(avail=g.date), t, 10.0, 30.0))
    with pytest.raises(ValueError):
        C.fit(g.assign(avail=g.date - pd.Timedelta(days=1)), t, 10.0, 30.0)


def test_mlb_first_pitch_check_is_required_and_committed():
    from alpha_engine.input_research.data_foundation import verified_coverage as VC
    rep = json.loads((VD / "replay_ext/MLB_mlb_line.json").read_text())["inputs"]
    for iid, r in rep.items():
        fp = r["tests"]["pit_check_first_pitch_availability"]
        assert fp["ok"] and fp["n_straddling_games"] == 16 and any(c["label"].startswith("straddle:746942") for c in fp["cuts"])
        assert VC.pit_check_failures(iid, r["tests"]) == []
        t = {k: v for k, v in r["tests"].items() if k != "pit_check_first_pitch_availability"}
        assert "pit_check_first_pitch_availability" in VC.pit_check_failures(iid, t)                                  # fail closed when absent
    v1 = json.loads((VD / "superseded/mlb_line_v1_resume_date/v1_under_new_check.json").read_text())["results"]
    assert set(v1) == set(rep) and not any(x["ok"] for x in v1.values())                                                 # the old dating fails the new check

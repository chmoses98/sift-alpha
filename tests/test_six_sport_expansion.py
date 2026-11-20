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

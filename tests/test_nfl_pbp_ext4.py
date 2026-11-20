"""NFL batch 4 builder (alpha_engine.features.nfl_pbp_ext4): point-in-time behaviour on synthetic data, and the committed certification evidence. RESEARCH_ONLY."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.features import nfl_pbp_ext4 as X

ROOT = Path(__file__).resolve().parents[1]
VD = ROOT / "research/input_research/data_foundation/verification"
IDS = {"nfl.own_team_rating_market_free": "VERIFIED_PARTIAL", "nfl.team_points_for_against_rates": "VERIFIED_PARTIAL", "nfl.proe": "VERIFIED_PARTIAL",
       "nfl.team_score_pmf_own_mean": "VERIFIED_PROXY", "nfl.model_margin_lattice": "VERIFIED_PROXY"}


def _raw(seed=0):
    rng = np.random.default_rng(seed); teams = [f"T{i}" for i in range(8)]; g = []; p = []
    for season in (2020, 2021, 2022):
        for wk in range(1, 15):
            o = rng.permutation(8); d = pd.Timestamp(f"{season}-09-01") + pd.Timedelta(days=7 * wk)
            for k in range(4):
                gid = f"{season}_{wk:02d}_{k}"; h, a = teams[o[2 * k]], teams[o[2 * k + 1]]
                g.append(dict(game_id=gid, season=season, week=wk, game_type="REG", gameday=str(d.date()), home_team=h, away_team=a, home_score=float(rng.integers(3, 40)),
                              away_score=float(rng.integers(3, 40)), overtime=int(rng.random() < 0.1), location="Home"))
                for t in (h, a):
                    for _ in range(12):
                        p.append(dict(game_id=gid, posteam=t, qtr=2, **{"pass": float(rng.random() < 0.6)}, rush=1.0, qb_kneel=0.0, qb_spike=0.0, wp=0.5, xpass=float(rng.random())))
    return {"games": pd.DataFrame(g), "pbp": pd.DataFrame(p)}


def test_columns_and_strictly_prior_information(monkeypatch):
    monkeypatch.setattr(X, "MIN_REF", 40)
    raw = _raw(); full = X.compute(raw)["team"]
    cols = [c for s in X.specs() for c in s.columns]
    assert len(cols) == len(set(cols)) == 24 and set(cols) <= set(full.columns) and len(full) == 2 * len(raw["games"])
    assert full[cols].notna().any().all()
    cut = "2022-10-15"; early = {"games": raw["games"][raw["games"].gameday < cut], "pbp": raw["pbp"][raw["pbp"].game_id.isin(raw["games"][raw["games"].gameday < cut].game_id)]}
    a = X.compute(early)["team"].set_index(["game_id", "team"])[cols]; b = full.set_index(["game_id", "team"]).loc[a.index, cols]
    np.testing.assert_allclose(a.to_numpy(float), b.to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)     # later games never change earlier rows
    late = raw["games"].gameday >= cut; raw2 = {"pbp": raw["pbp"], "games": raw["games"].assign(home_score=np.where(late, 99.0, raw["games"].home_score))}
    c = X.compute(raw2)["team"].set_index(["game_id", "team"])
    first = c.loc[c.date == c.date[c.date >= cut].min(), cols]                                                     # a game's own score never enters its own row
    np.testing.assert_allclose(first.to_numpy(float), full.set_index(["game_id", "team"]).loc[first.index, cols].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True)


def test_first_season_has_no_conditional_distribution(monkeypatch):
    monkeypatch.setattr(X, "MIN_REF", 40)
    t = X.compute(_raw(1))["team"]
    assert t.loc[t.season == 2020, X.TSP_COLS + X.MML_COLS].isna().all().all()
    v = t[X.TSP_COLS + X.MML_COLS].to_numpy(float); assert np.nanmin(v) >= 0 and np.nanmax(v) <= 1


def test_committed_certification_evidence():
    ind = json.loads((VD / "independent/NFL_nfl_pbp4.json").read_text())["inputs"]; rep = json.loads((VD / "replay_ext/NFL_nfl_pbp4.json").read_text())["inputs"]
    assert set(ind) == set(rep) == set(IDS)
    assert all((v if isinstance(v, str) else v.get("verdict", v.get("status"))) == "MATCH" for i in ind.values() for v in i["columns"].values())
    led = (ROOT / "research/input_research/data_foundation/coverage_matrix.csv").read_text().splitlines()
    got = {r.split(",")[1]: r.split(",")[3] for r in led[1:] if r.split(",")[1] in IDS}
    assert got == IDS                                                                                                # certified level is never above the claimed level
    assert {s.catalog_id: s.level for s in X.specs()} == {k: v.replace("VERIFIED_", "") for k, v in IDS.items()}

"""Fast tests for research/phase14_mlb (synthetic data; no vault needed)."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from research.phase14_mlb import engine as E
from research.phase14_mlb import extract as X
from research.phase14_mlb import metrics as M
from research.phase14_mlb import sim as S


def synth(n_days=12, seed=0):
    rng = np.random.default_rng(seed)
    teams = [1, 2, 3, 4]
    games, pas = [], []
    pk = 100
    for d in range(n_days):
        date = f"2023-04-{d + 1:02d}"
        for h, a in ((1, 2), (3, 4)) if d % 2 == 0 else ((2, 3), (4, 1)):
            pk += 1
            ho = [h * 100 + i for i in range(9)]
            ao = [a * 100 + i for i in range(9)]
            hs, as_ = h * 1000 + d % 3, a * 1000 + d % 3
            games.append(dict(game_pk=pk, season=2023, gtype="R", date=date, start_utc=date + "T23:00:00Z",
                              home_id=h, away_id=a, venue_id=h, home_runs=int(rng.integers(0, 9)),
                              away_runs=int(rng.integers(0, 9)), n_inn=9, prob_home=hs, prob_away=as_,
                              home_order=ho, away_order=ao, home_sp=hs, away_sp=as_, bats_home=["R"] * 9,
                              bats_away=["L"] * 9, thr_home_sp="R", thr_away_sp="L", home_sp_bf=20.0,
                              away_sp_bf=22.0))
            for top in (True, False):
                order, pit = (ao, hs) if top else (ho, as_)
                for i in range(30):
                    pas.append(dict(game_pk=pk, date=date, inn=1 + i // 4, top=top, bat=order[i % 9], pit=pit,
                                    stand="L" if top else "R", throws="R" if top else "L",
                                    ev=int(rng.integers(0, 8)), pre_base=0, pre_outs=0, post_base=0, outs_add=1,
                                    runs=0, is_sp=i < 20, bat_team=a if top else h, pit_team=h if top else a))
    return pd.DataFrame(games), pd.DataFrame(pas)


def test_no_leakage_same_and_future_dates():
    """Predictions for date D must not change when outcomes on dates >= D are altered."""
    G, P = synth()
    last = G.date.max()
    p1, inp1, _ = E.run(G, P, bats_lookup={})
    P2 = P.copy()
    m = P2.date == last
    P2.loc[m, "ev"] = 6  # every PA on the final date becomes a HR
    G2 = G.copy()
    G2.loc[G2.date == last, ["home_runs", "away_runs", "home_sp_bf"]] = [30, 0, 40.0]
    p2, inp2, _ = E.run(G2, P2, bats_lookup={})
    assert np.allclose(p1, p2)  # PA probabilities (all dates incl. the altered one) unchanged
    for pk in G.game_pk:
        for side in ("home", "away"):
            assert np.allclose(inp1[pk][side]["posted"]["sp"], inp2[pk][side]["posted"]["sp"])
            assert inp1[pk][side]["bf_mu"] == inp2[pk][side]["bf_mu"]
    # sanity: altering an EARLIER date does change later predictions
    P3 = P.copy()
    P3.loc[P3.date == G.date.min(), "ev"] = 6
    p3, _, _ = E.run(G, P3, bats_lookup={})
    assert not np.allclose(p1[(P.date == last).values], p3[(P.date == last).values])


def test_first_day_is_prior_only():
    G, P = synth()
    p, _, _ = E.run(G, P, bats_lookup={})
    first = (P.date == P.date.min()).values
    assert np.allclose(p[first], p[first][0])  # no history: everyone gets the same (prior) distribution
    assert np.allclose(p.sum(1), 1)


def test_typical_lineup_uses_history_only():
    hist = [[1, 2, 3, 4, 5, 6, 7, 8, 9]] * 5 + [[1, 2, 3, 4, 5, 6, 7, 8, 10]]
    lu = E.typical_lineup(hist, 7)
    assert lu[:8] == [1, 2, 3, 4, 5, 6, 7, 8] and lu[8] == 9
    assert E.typical_lineup([], 7) == []


def test_extract_uses_starting_slots_not_end_of_game_order(tmp_path):
    def pl(pid, order):
        return {"id": pid, "pos": "X", "order": order, "bat": {"hits": 1, "doubles": 0, "triples": 0, "homeRuns": 0,
                                                                "plateAppearances": 4}, "pit": None}
    box_side = lambda base: {"batting_order": [base + 1] + [base + i for i in range(2, 10)][:8] + [base + 99],
                             "pitchers": [base + 50], "players": [pl(base + i, f"{i}00") for i in range(1, 10)] +
                             [pl(base + 99, "901")]}
    feed = {"pk": 1, "game": {"type": "R", "season": "2024"}, "status": {"codedGameState": "F"},
            "datetime": {"officialDate": "2024-05-01", "dateTime": "2024-05-01T23:00:00Z"},
            "teams": {"home": {"id": 10}, "away": {"id": 20}}, "venue": {"id": 5},
            "linescore": {"teams": {"home": {"runs": 1}, "away": {"runs": 0}}, "innings": [{}] * 9},
            "probables": {}, "players": {}, "box": {"home": box_side(1000), "away": box_side(2000)}, "plays": []}
    f = tmp_path / "1.json"
    f.write_text(json.dumps(feed))
    g, _, bats, _ = X.parse_game(str(f))
    assert g["home_order"] == [1000 + i for i in range(1, 10)]  # the pinch hitter 1099 is excluded
    assert 1099 not in g["home_order"] and len(bats) == 18


def test_sim_extremes():
    rng = np.random.default_rng(0)
    pa = pd.DataFrame(dict(inn=[1] * 4, pre_outs=[0, 0, 1, 2], ev=[7, 6, 7, 7], pre_base=[0, 0, 0, 0],
                           post_base=[0, 0, 0, 0], outs_add=[1, 0, 1, 1], runs=[0, 1, 0, 0]))
    cells, cdf = S.build_transitions(pa)
    allout = np.zeros((2, 9, 8))
    allout[..., 7] = 1
    runs, k, H, TB, HR = S.simulate_offense(allout, allout, np.array([20.0, 20.0]), 1.0, cells, cdf, 50, rng)
    assert runs.sum() == 0 and H.sum() == 0
    allk = np.zeros((1, 9, 8))
    allk[..., 0] = 1
    _, k, _, _, _ = S.simulate_offense(allk, allout[:1], np.array([12.0]), 0.01, cells, cdf, 20, rng)
    assert (k == 12).all()  # starter strikes out exactly his batters-faced limit, then bullpen


def test_metrics():
    pmf = np.eye(5)[[2, 3]]
    assert np.allclose(M.crps_pmf(pmf, np.array([2, 3])), 0)
    assert M.crps_pmf(pmf, np.array([0, 3]))[0] > 0
    r = M.paired_ci(np.ones(100), np.zeros(100), np.repeat(np.arange(50), 2), B=200)
    assert r["diff"] == -1 and r["hi"] < 0 and r["games"] == 50
    rng = np.random.default_rng(1)
    p = rng.uniform(0.05, 0.95, 20000)
    y = (rng.random(20000) < p).astype(float)
    assert abs(M.calib_slope(p, y) - 1) < 0.1
    assert np.allclose(M.nb_pmf(np.array([4.0]), 5, 30).sum(), 1)


@pytest.mark.skipif(not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "research", "phase14_mlb",
                                                    "frozen_params.json")), reason="not frozen")
def test_frozen_params_hash():
    import hashlib
    path = os.path.join(os.path.dirname(__file__), "..", "research", "phase14_mlb", "frozen_params.json")
    fz = json.load(open(path))
    sha = fz.pop("sha256")
    assert hashlib.sha256(json.dumps(fz, sort_keys=True).encode()).hexdigest() == sha
    assert fz["splits"]["holdout"] == [2026] and 2026 not in fz["splits"]["dev"]

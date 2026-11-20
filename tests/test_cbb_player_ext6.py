"""CBB batch 6 player builder (alpha_engine.features.cbb_player_ext6): point-in-time behaviour on synthetic box scores. RESEARCH_ONLY."""
import numpy as np
import pandas as pd
from scipy import stats

from alpha_engine.features import cbb_player_ext6 as X

COLS = [c for s in X.specs() for c in s.columns]


def _raw(seed=0):
    """4 teams x 8 players, seasons 2012-2013, 12 game days per season; every game day two games."""
    rng = np.random.default_rng(seed); rows = []; gid = 1000
    pos = ["G", "G", "F", "F", "C", "G", "F", "PG"]
    for season in (2012, 2013):
        for day in range(12):
            d = pd.Timestamp(f"{season - 1}-11-10") + pd.Timedelta(days=3 * day); o = rng.permutation([1, 2, 3, 4])
            for k in range(2):
                gid += 1; a, b = int(o[2 * k]), int(o[2 * k + 1])
                for t, opp in ((a, b), (b, a)):
                    for j in range(8):
                        played = rng.random() < 0.85
                        fga = float(rng.integers(0, 15)); fg3a = float(rng.integers(0, int(fga) + 1)); fgm = float(rng.binomial(int(fga), 0.45)); fg3m = float(min(fgm, rng.binomial(int(fg3a), 0.35)))
                        fta = float(rng.integers(0, 8)); ftm = float(rng.binomial(int(fta), 0.7)); oreb = float(rng.integers(0, 4)); dreb = float(rng.integers(0, 7))
                        rows.append(dict(game_id=gid, season=season, season_type=2, game_date=d, athlete_id=float(t * 100 + j), team_id=t, opponent_team_id=opp,
                                         minutes=float(rng.integers(5, 38)) if played else np.nan, athlete_position_abbreviation=pos[j],
                                         points=2 * fgm + fg3m + ftm, rebounds=oreb + dreb, offensive_rebounds=oreb, defensive_rebounds=dreb, assists=float(rng.integers(0, 6)),
                                         turnovers=float(rng.integers(0, 4)), field_goals_made=fgm, field_goals_attempted=fga, three_point_field_goals_made=fg3m,
                                         three_point_field_goals_attempted=fg3a, free_throws_made=ftm, free_throws_attempted=fta))
    return {"box": pd.DataFrame(rows)}


def _idx(f):
    return f.set_index(["game_id", "team"])


def test_columns_and_later_games_never_change_earlier_rows():
    raw = _raw(); full = X.compute(raw)["team"]
    assert set(COLS) <= set(full.columns) and len(COLS) == len(set(COLS)) and not full.duplicated(["game_id", "team"]).any()
    assert (full.season >= X.OUT_FIRST).all() and full[COLS].notna().any().all()
    cut = pd.Timestamp("2012-11-25"); b0 = raw["box"]
    early = {"box": b0[b0.game_date < cut]}
    a = _idx(X.compute(early)["team"]); b = _idx(full[full.date < cut])
    assert set(a.index) == set(b.index)
    np.testing.assert_allclose(a.loc[b.index, COLS].to_numpy(float), b[COLS].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)


def test_own_game_box_never_changes_own_row():
    raw = _raw(1); full = X.compute(raw)["team"]
    d = sorted(full.date.unique())[4]; gids = set(full.loc[full.date == d, "game_id"])
    bx = raw["box"].copy(); m = bx.game_id.isin(gids)
    bx.loc[m, "points"] = 99.0; bx.loc[m, "minutes"] = 40.0; bx.loc[m, "three_point_field_goals_attempted"] = 30.0; bx.loc[m, "rebounds"] = 25.0
    new = X.compute({"box": bx})["team"]
    a = _idx(full[full.date <= d]); b = _idx(new[new.date <= d])
    assert set(a.index) == set(b.index)
    np.testing.assert_allclose(b.loc[a.index, COLS].to_numpy(float), a[COLS].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
    later = _idx(new[new.date > d]); base_later = _idx(full[full.date > d])
    common = later.index.intersection(base_later.index)
    assert not np.allclose(later.loc[common, "pu_pts40_pre"].to_numpy(float), base_later.loc[common, "pu_pts40_pre"].to_numpy(float))


def test_compound_distribution_matches_scipy_mixture():
    mu = np.array([0.0, 0.7, 2.5, 6.0]); a = np.array([40.0, 35.0, 60.0, 80.0]); b = np.array([70.0, 65.0, 110.0, 130.0])
    got = X._bb_ge(X.NMAX, mu, a, b)
    for i in range(len(mu)):
        exp = []
        for k in (1, 2, 3, 4):
            if mu[i] == 0:
                exp.append(0.0); continue
            n = 2 * mu[i]; tot = 0.0
            for N in range(0, X.NMAX + 1):
                tot += stats.nbinom.pmf(N, n, 2 / 3) * stats.betabinom.sf(k - 1, N, a[i], b[i])
            exp.append(tot)
        np.testing.assert_allclose(got[i], exp, rtol=1e-9, atol=1e-12)


def test_wsum_is_recursive_and_resets_per_entity():
    k = np.array([1, 1, 1, 2, 2]); x = np.array([1.0, 2.0, 3.0, 5.0, 1.0]); r = 0.5 ** (1 / 10)
    np.testing.assert_allclose(X._wsum(k, x, 10.0), [1.0, 1 * r + 2, (1 * r + 2) * r + 3, 5.0, 5 * r + 1])


def test_specs_are_honest_partials():
    sp = {s.catalog_id: s for s in X.specs()}
    assert set(sp) == {"cbb.player_usage", "cbb.player_shooting_regression", "cbb.stat_dist", "cbb.player_three_volume", "cbb.three_makes_compound_distribution", "cbb.assist_creation", "cbb.rebound_pool"}
    assert all(s.level == "PARTIAL" and s.missing for s in sp.values())
    assert "cbb.player_minutes" not in sp and "cbb.starters" not in sp          # prospective inputs are not certified from box history


def _sched(seed=0):
    from alpha_engine.features import cbb_team_ext9 as T9
    rng = np.random.default_rng(seed); rows = []; gid = 1
    for season in range(2006, 2016):
        for day in range(20):
            d = pd.Timestamp(f"{season - 1}-11-10") + pd.Timedelta(days=3 * day); o = rng.permutation(np.arange(1, 9))
            for k in range(4):
                gid += 1; h1a, h2a, h1b, h2b = (float(x) for x in rng.integers(20, 45, 4))
                ls = (lambda a, b: f"[{{'value': {a}}} {{'value': {b}}}]") if season < 2014 else (lambda a, b: f"[{{'period': 1.0, 'value': {a}}}\n {{'period': 2.0, 'value': {b}}}]")
                rows.append(dict(game_id=gid, season=season, season_type=2, game_date=d, home_id=int(o[2 * k]), away_id=int(o[2 * k + 1]), home_score=h1a + h2a, away_score=h1b + h2b,
                                 neutral_site=bool(rng.random() < 0.1), status_type_completed=True, status_period=2.0 + (rng.random() < 0.06),
                                 home_linescores=ls(h1a, h2a) if season >= 2012 else None, away_linescores=ls(h1b, h2b) if season >= 2012 else None))
    s = pd.DataFrame(rows); w = s.season < T9.OUT_FIRST
    return T9, {"sched": s[~w].reset_index(drop=True), "sched_warm": s[w].reset_index(drop=True)}


def test_cbb_team9_truncation_and_positional_linescores():
    T9, raw = _sched()
    full = T9.compute(raw)["team"]; cut = pd.Timestamp("2014-12-01")
    part = T9.compute({**raw, "sched": raw["sched"][raw["sched"].game_date < cut]})["team"]
    a = full[full.date < cut].set_index(["game_id", "team"]); b = part[part.date < cut].set_index(["game_id", "team"])
    assert set(a.index) == set(b.index) and len(a)
    np.testing.assert_allclose(b.loc[a.index, T9.ALL].to_numpy(float), a[T9.ALL].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
    assert full.fhp_pair_ratio_pre.notna().any() and full.mrm_p_win_pre.notna().any()
    assert T9._periods("[{'value': 31.0} {'value': 40.0}]") == {1: 31.0, 2: 40.0}
    assert T9._periods("[{'displayValue': '40', 'period': 2.0, 'value': 40.0}\n {'period': 1.0, 'value': 33.0}]") == {2: 40.0, 1: 33.0}

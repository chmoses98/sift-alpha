"""NFL batch 5 player builder (alpha_engine.features.nfl_player_ext5): point-in-time behaviour on synthetic data. RESEARCH_ONLY."""
import numpy as np
import pandas as pd

from alpha_engine.features import nfl_player_ext5 as X

COLS = [c for s in X.specs() for c in s.columns]


def _raw(seed=0, oak=True):
    """4 teams, seasons 2010-2011, 10 weeks each; team 'LV' is coded 'OAK' in 2010 (schedule and posteam). Each team has 6 skill players."""
    rng = np.random.default_rng(seed); g = []; p = []
    for season in (2010, 2011):
        for wk in range(1, 11):
            d = pd.Timestamp(f"{season}-09-01") + pd.Timedelta(days=7 * wk); o = rng.permutation(["KC", "LV", "DEN", "LAC"])
            for k in range(2):
                gid = f"{season}_{wk:02d}_{k}"; h, a = o[2 * k], o[2 * k + 1]
                code = lambda t: "OAK" if (oak and t == "LV" and season == 2010) else t  # noqa: E731
                g.append(dict(game_id=gid, season=season, week=wk, game_type="REG", gameday=str(d.date()), home_team=code(h), away_team=code(a), home_score=float(rng.integers(3, 40))))
                pid = 0
                for t in (h, a):
                    for _ in range(40):
                        pid += 1; tgt = rng.random() < 0.55; pl = f"{t}_{rng.integers(0, 6)}"; yl = float(rng.integers(1, 99)); ytd = rng.random() < 0.05
                        p.append(dict(game_id=gid, play_id=float(pid), posteam=code(t), play_type="pass" if tgt else "run", two_point_attempt=0.0, qb_scramble=float((not tgt) and rng.random() < 0.05),
                                      receiver_player_id=pl if tgt else None, rusher_player_id=None if tgt else pl, yardline_100=yl, down=float(rng.integers(1, 5)),
                                      air_yards=float(rng.integers(-3, 30)) if tgt else np.nan, receiving_yards=float(rng.integers(0, 40)) if tgt else np.nan,
                                      rushing_yards=np.nan if tgt else float(rng.integers(-2, 20)), touchdown=float(ytd), pass_touchdown=float(ytd and tgt), rush_touchdown=float(ytd and not tgt)))
    return {"games": pd.DataFrame(g), "pbp": pd.DataFrame(p)}


def _idx(f):
    return f.set_index(["game_id", "team"])


def test_columns_and_later_games_never_change_earlier_rows():
    raw = _raw(); full = X.compute(raw)["team"]
    assert set(COLS) <= set(full.columns) and len(COLS) == len(set(COLS)) and not full.duplicated(["game_id", "team"]).any()
    assert (full.season >= X.OUT_FIRST).all() and full[COLS].notna().any().all()
    cut = "2011-10-01"; keep = raw["games"][raw["games"].gameday < cut]
    early = {"games": keep, "pbp": raw["pbp"][raw["pbp"].game_id.isin(keep.game_id)]}
    a = _idx(X.compute(early)["team"]); b = _idx(full[full.date < cut])
    assert set(a.index) == set(b.index)                                                                    # row universe of earlier games unchanged
    np.testing.assert_allclose(a.loc[b.index, COLS].to_numpy(float), b[COLS].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)


def test_own_game_plays_never_change_own_row():
    raw = _raw(1); full = X.compute(raw)["team"]
    d = sorted(full.date.unique())[5]; gids = set(full.loc[full.date == d, "game_id"])
    p = raw["pbp"].copy(); m = p.game_id.isin(gids)
    p.loc[m, "receiver_player_id"] = "NEWGUY"; p.loc[m, "rusher_player_id"] = "NEWGUY"; p.loc[m, "receiving_yards"] = 99.0; p.loc[m, "touchdown"] = 1.0; p.loc[m, "pass_touchdown"] = 1.0
    new = X.compute({**raw, "pbp": p})["team"]
    a = _idx(full[full.date <= d]); b = _idx(new[new.date <= d])
    assert set(a.index) == set(b.index) and "NEWGUY" not in set(b.index.get_level_values(1))
    np.testing.assert_allclose(b.loc[a.index, COLS].to_numpy(float), a[COLS].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
    later = new[new.date > d]; assert "NEWGUY" in set(later.team)                                         # ... but it enters the next game's universe


def test_row_universe_from_prior_involvement_only():
    raw = _raw(2); g = raw["games"]; p = raw["pbp"].copy()
    # a debutant in the team's 3rd game of 2011: no row in that game, a row in the team's next game
    tg = g[(g.season == 2011) & ((g.home_team == "KC") | (g.away_team == "KC"))].sort_values("gameday")
    g3, g4 = tg.game_id.iloc[2], tg.game_id.iloc[3]
    ix = p.index[(p.game_id == g3) & (p.posteam == "KC") & (p.play_type == "pass")][:1]
    p.loc[ix, "receiver_player_id"] = "ROOKIE"
    # a veteran involved only in KC's 1st 2011 game: in the universe for KC's games 2-5, not for game 6
    ix2 = p.index[(p.game_id == tg.game_id.iloc[0]) & (p.posteam == "KC") & (p.play_type == "run")][:1]
    p.loc[ix2, "rusher_player_id"] = "VET"
    f = X.compute({**raw, "pbp": p})["team"]
    rk = f[f.team == "ROOKIE"]; assert g3 not in set(rk.game_id) and g4 in set(rk.game_id)
    vet = set(f.loc[f.team == "VET", "game_id"]); assert vet == set(tg.game_id.iloc[1:5])
    assert (f.loc[f.team == "ROOKIE", "pteam"] == "KC").all()


def test_team_codes_normalised():
    a = X.compute(_raw(3, oak=True))["team"]; b = X.compute(_raw(3, oak=False))["team"]
    assert "OAK" not in set(a.pteam) and "OAK" not in set(a.opp) and "LV" in set(a.pteam)
    first = a[(a.pteam == "LV") & (a.week == 1)]; assert len(first) > 0 and first[COLS].notna().any().all()  # 2011 week-1 LV rows read the 2010 'OAK' history
    pd.testing.assert_frame_equal(a, b)


def test_role_preserving_perturbation_keeps_universe_and_moves_values():
    raw = _raw(4); base = X.compute(raw)["team"]
    blk = set(raw["games"].loc[raw["games"].season == 2011, "game_id"].iloc[:6])
    mv = X.compute(X.perturb(raw, blk, 7))["team"]
    assert base[["game_id", "team"]].equals(mv[["game_id", "team"]])
    assert all(not np.allclose(base[c].fillna(-1), mv[c].fillna(-1)) for c in COLS)

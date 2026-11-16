"""The first MLB dataset uses only games that had ENDED before first pitch, and says so with tests."""
from datetime import datetime, timedelta, timezone

import numpy as np

from alpha_engine.certify import mlb_game_v1 as M

T0 = datetime(2026, 4, 1, 17, 0, tzinfo=timezone.utc)


def game(gid, day, home, away, hr, ar, hsp, asp, *, season=2026, hours=3.0, start_h=0.0, hline=(18, 2, 6, 2, 24), aline=(15, 4, 3, 3, 23)):
    start = T0 + timedelta(days=day, hours=start_h)
    return {"game_id": gid, "season": season, "official_date": start.strftime("%Y-%m-%d"), "start": start,
            "end": start + timedelta(hours=hours), "game_number": 1, "home_id": home, "away_id": away, "home_runs": hr,
            "away_runs": ar, "home_sp_id": hsp, "away_sp_id": asp, "home_sp_line": hline, "away_sp_line": aline}


def row(d, gid):
    return d.set_index("game_id").loc[gid]


def test_first_game_of_a_season_has_no_history_and_missing_features():
    d = M.build([game(1, 0, 10, 20, 5, 3, 100, 200)])
    r = row(d, 1)
    assert r["home_n_pre"] == 0 and r["away_sp_n_pre"] == 0
    assert np.isnan(r["home_rs_pg_pre"]) and np.isnan(r["away_sp_ra9_pre"]) and r["y_home_win"] == 1 and r["total_runs"] == 8
    assert list(d.columns) == M.COLUMNS


def test_team_and_starter_form_come_from_prior_games_only():
    games = [game(1, 0, 10, 20, 5, 3, 100, 200), game(2, 1, 20, 10, 2, 6, 201, 101), game(3, 5, 10, 30, 1, 0, 100, 300)]
    r = row(M.build(games), 3)
    assert (r["home_n_pre"], r["home_rs_pg_pre"], r["home_ra_pg_pre"], r["home_win_pct_pre"]) == (2, 5.5, 2.5, 1.0)
    assert r["away_n_pre"] == 0
    # pitcher 100 started game 1 only: 18 outs, 2 runs, 6 K, 2 BB, 24 BF
    assert (r["home_sp_n_pre"], r["home_sp_ip_ps_pre"], r["home_sp_ra9_pre"]) == (1, 6.0, 3.0)
    assert (r["home_sp_k_rate_pre"], r["home_sp_bb_rate_pre"]) == (0.25, 2 / 24)


def test_a_game_still_in_progress_at_first_pitch_is_not_history():
    """Game 1 of a doubleheader runs long: it has not ended when game 2 starts, so game 2 may not use it."""
    g1 = game(1, 0, 10, 20, 9, 0, 100, 200, hours=5.0)
    g2 = game(2, 0, 10, 20, 1, 2, 101, 201, start_h=4.0)
    g3 = game(3, 0, 10, 20, 1, 2, 102, 202, start_h=5.0)        # starts exactly when game 1 ends: still not strictly before
    g4 = game(4, 1, 10, 20, 1, 2, 100, 203)
    d = M.build([g1, g2, g3, g4])
    assert row(d, 2)["home_n_pre"] == 0 and row(d, 3)["home_n_pre"] == 0
    assert row(d, 4)["home_n_pre"] == 3 and row(d, 4)["home_sp_n_pre"] == 1


def test_a_suspended_game_finished_later_is_not_visible_in_between():
    susp = game(1, 0, 10, 20, 9, 0, 100, 200, hours=24 * 20)     # first pitch on day 0, last play on day 20
    mid = game(2, 5, 10, 30, 1, 2, 100, 300)
    late = game(3, 25, 10, 30, 1, 2, 100, 300)
    d = M.build([susp, mid, late])
    assert row(d, 2)["home_n_pre"] == 0 and row(d, 2)["home_sp_n_pre"] == 0
    assert row(d, 3)["home_n_pre"] == 2 and row(d, 3)["home_sp_n_pre"] == 2


def test_other_seasons_and_relief_appearances_are_ignored():
    games = [game(1, 0, 10, 20, 5, 3, 100, 200, season=2025), game(2, 400, 10, 20, 5, 3, 100, 200, season=2026)]
    r = row(M.build(games), 2)
    assert r["home_n_pre"] == 0 and r["home_sp_n_pre"] == 0
    # a pitcher is in a starter history only as the FIRST pitcher of a side; read_game takes pitchers[0]
    doc = {"pk": 9, "game": {"type": "R", "season": "2026", "gameNumber": 1}, "datetime": {"officialDate": "2026-04-01"},
           "game_info": {"firstPitch": "2026-04-01T17:00:00.000Z"}, "plays": [{"end": "2026-04-01T19:58:10.120Z"}],
           "teams": {"home": {"id": 10}, "away": {"id": 20}}, "linescore": {"teams": {"home": {"runs": 4}, "away": {"runs": 2}}},
           "box": {s: {"pitchers": [p, p + 1], "players": [{"id": p, "pit": {"outs": 15, "runs": 2, "strikeOuts": 5, "baseOnBalls": 1, "battersFaced": 21}},
                                                             {"id": p + 1, "pit": {"outs": 12, "runs": 0}}]} for s, p in (("home", 100), ("away", 200))}}
    g, why = M.read_game(doc)
    assert why is None and g["home_sp_id"] == 100 and g["home_sp_line"] == (15, 2, 5, 1, 21) and M._fmt(g["end"]) == "2026-04-01T19:58:10.120Z"
    assert M.read_game({**doc, "game": {**doc["game"], "type": "W"}}) == (None, "not_regular_season")
    assert M.read_game({**doc, "plays": []})[1] == "missing_first_pitch_or_last_play_end"


def test_last_ten_window_and_zero_denominators():
    games = [game(i, i, 10, 20, i, 0, 100 + i, 200, hline=(0, 3, 0, 0, 0)) for i in range(1, 13)] + [game(99, 30, 10, 20, 0, 0, 101, 200)]
    r = row(M.build(games), 99)
    assert r["home_n_pre"] == 12 and r["home_rs_pg_pre"] == 6.5 and r["home_rs_l10_pre"] == 7.5
    # pitcher 101 started once and recorded no out and faced no batter: rate features are missing, count is not
    assert r["home_sp_n_pre"] == 1 and r["home_sp_ip_ps_pre"] == 0.0 and np.isnan(r["home_sp_ra9_pre"]) and np.isnan(r["home_sp_k_rate_pre"])


def test_leakage_checks_pass_on_a_small_season_and_catch_a_leak(monkeypatch):
    rng = np.random.default_rng(0)
    games = [game(i, i // 3, 10 + i % 4, 20 + i % 3, int(rng.integers(0, 9)), int(rng.integers(0, 9)), 100 + i % 5, 200 + i % 4,
                  start_h=float(i % 3) * 4) for i in range(60)]
    games.sort(key=lambda g: (g["start"], g["game_id"]))
    d = M.build(games)
    c = M.leakage_checks(games, d, n_cutoffs=6)
    assert c["truncation_identical"] and c["future_scramble_identical"] and c["own_outcome_scramble_identical"]
    # a builder that also counts games in progress (end >= start) must be caught
    monkeypatch.setattr(M._History, "prior", lambda self, key, start: self.vals.get(key, []))
    leaky = M.build(games)
    monkeypatch.undo()
    assert not M.leakage_checks(games, leaky, n_cutoffs=6)["truncation_identical"]

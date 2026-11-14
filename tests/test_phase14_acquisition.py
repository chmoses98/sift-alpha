"""Offline tests for the Phase 14 acquisition samplers (ESPN NBA stints, NHL play-by-play, Kalshi candlesticks). No network."""
import gzip
import io
import json
import urllib.error

import pytest

from alpha_engine.collect import espn_nba_pbp as nba
from alpha_engine.collect import kalshi_quotes as kq
from alpha_engine.collect import nhl_pbp as nhl


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ------------------------------------------------------------------ ESPN NBA
def _ath(i, starter, mins, pm):
    return {"athlete": {"id": i}, "starter": starter, "didNotPlay": False, "stats": [str(mins), str(pm)]}


def _play(per, clock, text, home, away, parts=(), scoring=False, kind=None):
    return {"period": {"number": per}, "clock": {"displayValue": clock}, "type": {"text": kind or ("Substitution" if "enters" in text else "Shot")},
            "text": text, "homeScore": home, "awayScore": away, "scoringPlay": scoring, "participants": [{"athlete": {"id": p}} for p in parts]}


def _game(plays, home_box, away_box, final=(0, 0)):
    keys = ["minutes", "plusMinus"]
    return {"header": {"id": "1", "competitions": [{"date": "2025-01-15T00:00Z", "competitors": [
        {"homeAway": "home", "team": {"id": "H"}, "score": str(final[0])}, {"homeAway": "away", "team": {"id": "A"}, "score": str(final[1])}]}]},
            "boxscore": {"players": [{"team": {"id": "H"}, "statistics": [{"keys": keys, "athletes": home_box}]},
                                     {"team": {"id": "A"}, "statistics": [{"keys": keys, "athletes": away_box}]}]},
            "plays": plays, "gameInfo": {"officials": [{}, {}, {}]}, "pickcenter": {"x": 1}, "odds": [1]}


def _simple_game(order_sub_first: bool):
    """H scores 2 FTs at 6:00 of Q1; H6 replaces H1 at the same instant. Convention: FTs belong to the five on court at the foul (H1)."""
    hb = [_ath(f"H{i}", i <= 5, 0, 0) for i in range(1, 7)]
    ab = [_ath(f"A{i}", True, 0, 0) for i in range(1, 6)]
    sub = _play(1, "6:00", "H6 enters the game for H1", 0, 0, ("H6", "H1"))
    ft = _play(1, "6:00", "H2 makes free throw", 2, 0, ("H2",), scoring=True)
    plays = [_play(1, "12:00", "tip", 0, 0, ("H1", "A1"))] + ([sub, ft] if order_sub_first else [ft, sub])
    for p in range(2, 5):
        plays.append(_play(p, "12:00", "start", 2, 0, ()))
    return _game(plays, hb, ab, final=(2, 0))


def test_clock_and_elapsed():
    assert nba.clock_s("6:52") == 412 and nba.clock_s("45.3") == 45.3
    assert nba.elapsed({"period": {"number": 5}, "clock": {"displayValue": "5:00"}}) == 2880
    assert nba.elapsed({"period": {"number": 2}, "clock": {"displayValue": "0.0"}}) == 1440


def test_free_throws_credited_before_same_instant_subs():
    for sub_first in (True, False):
        rec = nba.reconstruct(_simple_game(sub_first))
        assert rec["players"]["H1"]["pm"] == 2 and rec["players"]["H6"]["pm"] == 0
        assert rec["players"]["A1"]["pm"] == -2
        assert rec["players"]["H1"]["sec"] == 360 and rec["players"]["H6"]["sec"] == 2880 - 360
        assert not rec["issues"]


def test_non_scoring_rows_with_later_score_are_ignored():
    g = _simple_game(False)
    g["plays"].insert(1, _play(1, "8:00", "rebound", 0, 3, ("A2",)))      # bogus running score on a non-scoring row
    rec = nba.reconstruct(g)
    assert rec["players"]["A1"]["pm"] == -2


def test_verify_game_pass_and_market_blocks_dropped():
    g = _simple_game(True)
    hb = g["boxscore"]["players"][0]["statistics"][0]["athletes"]
    for a in hb:
        i = a["athlete"]["id"]
        a["stats"] = ["6", "2"] if i == "H1" else (["42", "0"] if i == "H6" else ["48", "2"])
    for a in g["boxscore"]["players"][1]["statistics"][0]["athletes"]:
        a["stats"] = ["48", "-2"]
    v = nba.verify_game(g)
    assert v["game_pass"] and v["pm_match"] == v["players_played"] == 11 and v["final_matches_pbp"] and v["officials"] == 3
    s = nba.strip_market(g)
    assert "pickcenter" not in s and "odds" not in s and "plays" in s


def test_period_starters_inferred_from_activity_and_subs():
    roster = {i: {"team": "H"} for i in ("H1", "H2", "H3", "H4", "H5", "H6", "H7")}
    plays = [_play(2, "11:00", "H7 enters the game for H1", 0, 0, ("H7", "H1")), _play(2, "10:00", "shot", 0, 0, ("H2",)),
             _play(2, "9:00", "shot", 0, 0, ("H7",))]
    st = nba.period_starters(plays, 2, "H", roster, prev_end={"H2", "H3", "H4", "H5", "H6"})
    assert st == {"H1", "H2", "H3", "H4", "H5"}


def test_nba_fetch_refuses_repo_cache_and_caps(tmp_path):
    with pytest.raises(PermissionError):
        nba.fetch_dates(["2025-01-15"], nba.REPO_ROOT / "research" / "x", opener=lambda *a, **k: None, sleep=lambda s: None)
    with pytest.raises(ValueError):
        nba.fetch_dates(["2025-01-15"], tmp_path, max_calls=nba.HARD_MAX_CALLS + 1)


def test_nba_fetch_strips_market_blocks_and_stops_on_403(tmp_path):
    sb = {"events": [{"id": "9", "status": {"type": {"completed": True}}}]}
    summ = _simple_game(True)
    bodies = iter([json.dumps(sb).encode(), json.dumps(summ).encode()])
    nba.fetch_dates(["2025-01-15"], tmp_path, max_calls=5, opener=lambda *a, **k: _Resp(next(bodies)), sleep=lambda s: None)
    cached = json.loads(gzip.decompress((tmp_path / "summary_9.json.gz").read_bytes()))
    assert "odds" not in cached and "pickcenter" not in cached

    def deny(*a, **k):
        raise urllib.error.HTTPError("u", 403, "x", {}, None)
    m = nba.fetch_dates(["2025-01-16"], tmp_path / "b", max_calls=5, opener=deny, sleep=lambda s: None)
    assert m["log"][-1]["stop"] == "http_403" and m["calls"] == 0


def test_nba_digest_counts():
    r = {"game_id": "1", "date": "2025-01-15T00:00Z", "n_plays": 10, "n_subs": 1, "n_stints": 2, "players_played": 10, "pm_match": 9, "min_match": 10,
         "game_pass": False, "final_matches_pbp": True, "issues": [], "mismatch_examples": [], "officials": 3, "wallclock_fill": 1.0, "starters_flagged": 10}
    d = nba.digest([r, r | {"game_id": "2", "pm_match": 10, "game_pass": True}])
    assert d["overall"]["games_pass"] == 1 and d["overall"]["pm_exact"] == 19 and d["by_season"]["2024-25"]["games"] == 2


# ------------------------------------------------------------------ NHL
def _ev(sort, kind, per, t, sit="1551", ptype="REG", **det):
    return {"sortOrder": sort, "typeDescKey": kind, "periodDescriptor": {"number": per, "periodType": ptype}, "timeInPeriod": t,
            "situationCode": sit, "details": det}


def _nhl(plays, a_score, h_score, last="REG"):
    return {"id": 2024020001, "gameDate": "2025-01-15", "gameType": 2, "awayTeam": {"id": 1, "score": a_score}, "homeTeam": {"id": 2, "score": h_score},
            "gameOutcome": {"lastPeriodType": last}, "plays": plays}


def test_situation_code():
    assert nhl.situation("1451") == {"away_goalie": 1, "away_sk": 4, "home_sk": 5, "home_goalie": 1}
    assert nhl.situation("15") is None and nhl.situation(None) is None


def test_nhl_goals_match_final_with_shootout_goal_excluded():
    plays = [_ev(1, "goal", 1, "05:00", eventOwnerTeamId=1, awayScore=1, homeScore=0),
             _ev(2, "goal", 3, "18:30", sit="1560", eventOwnerTeamId=2, awayScore=1, homeScore=1),
             _ev(3, "goal", 5, "00:00", ptype="SO", eventOwnerTeamId=2)]
    f = nhl.game_facts(_nhl(plays, 1, 2, last="SO"), {"gameInfo": {"referees": [1, 2], "linesmen": [1, 2], "awayTeam": {"scratches": [1]}, "homeTeam": {"scratches": [2]}}})
    assert f["goals_pbp"] == [1, 1] and f["final_expected"] == [1, 1] and f["goals_match_final"] and f["running_score_consistent"]
    assert f["third_period_equalizers_t"] == [1110] and f["referees"] == 2 and f["scratches_listed"] == 2
    assert f["goalie_pulls_reg"] == [{"period": 3, "t": 1110, "side": "home", "margin": -1}]
    d = nhl.digest([f])
    assert d["overall"]["late_trailing_pulls_p3"] == 1 and d["overall"]["so_games"] == 1


def test_nhl_empty_net_goal_and_mismatch():
    plays = [_ev(1, "goal", 3, "19:00", sit="0651", eventOwnerTeamId=2, awayScore=0, homeScore=1)]
    f = nhl.game_facts(_nhl(plays, 0, 2), None)
    assert f["empty_net_goals"] == 1 and not f["goals_match_final"] and not f["rail_present"]


def test_nhl_fetch_guards(tmp_path):
    with pytest.raises(PermissionError):
        nhl.fetch_dates(["2025-01-15"], nhl.REPO_ROOT / "x", opener=lambda *a, **k: None, sleep=lambda s: None)
    calls = []

    def op(req, timeout=60):
        calls.append(req.full_url)
        if "/score/" in req.full_url:
            return _Resp(json.dumps({"games": [{"id": 5, "gameState": "OFF"}, {"id": 6, "gameState": "FUT"}]}).encode())
        return _Resp(b"{}")
    m = nhl.fetch_dates(["2025-01-15"], tmp_path, max_calls=10, opener=op, sleep=lambda s: None)
    assert m["calls"] == 3 and all("/6/" not in u for u in calls)
    assert (tmp_path / "play-by-play_5.json.gz").exists() and (tmp_path / "right-rail_5.json.gz").exists()


# ------------------------------------------------------------------ Kalshi candlesticks
def test_candle_url_live_and_historical():
    u = kq.candle_url("KXNBAGAME", "KXNBAGAME-26NOV12TORPHI-PHI", 1, 2, historical=False)
    assert u.endswith("/series/KXNBAGAME/markets/KXNBAGAME-26NOV12TORPHI-PHI/candlesticks?start_ts=1&end_ts=2&period_interval=60")
    assert "/historical/markets/KXNBAGAME-26NOV12TORPHI-PHI/candlesticks" in kq.candle_url("KXNBAGAME", "KXNBAGAME-26NOV12TORPHI-PHI", 1, 2, True)
    with pytest.raises(ValueError):
        kq.candle_url("KXNBAGAME", "KXNHLGAME-X", 1, 2, False)


def test_norm_candle_both_schemas_and_stats():
    live = {"end_period_ts": 7200, "yes_bid": {"close_dollars": "0.4000"}, "yes_ask": {"close_dollars": "0.4300"}, "price": {}, "volume_fp": "5.00"}
    hist = {"end_period_ts": 3600, "yes_bid": {"close": "0.0000"}, "yes_ask": {"close": "1.0000"}, "price": {"close": "0.5"}, "volume": "0"}
    assert kq.norm_candle(live) == {"ts": 7200, "bid": 0.4, "ask": 0.43, "last": None, "volume": 5.0}
    assert not kq.two_sided(kq.norm_candle(hist)) and kq.two_sided(kq.norm_candle(live))
    s = kq.market_quote_stats([live, hist], open_ts=0, close_ts=7200)
    assert s["candles"] == 2 and s["two_sided"] == 1 and s["two_sided_hours_last24"] == 1 and s["ts_monotonic"] and s["median_spread"] == 0.03


def test_sample_markets_is_deterministic_and_stratified():
    rows = [{"ticker": f"KXNBAGAME-X{i}", "result": "yes", "open_time": "2025-01-01T00:00:00Z", "close_time": f"2025-0{1 + i % 2}-02T00:00:00Z"} for i in range(10)]
    rows.append({"ticker": "KXNBAGAME-S", "result": "scalar", "open_time": "a", "close_time": "2025-01-03T00:00:00Z"})
    a, b = kq.sample_markets(rows, 2), kq.sample_markets(list(reversed(rows)), 2)
    assert a == b and len(a) == 4 and all(r["result"] == "yes" for r in a)

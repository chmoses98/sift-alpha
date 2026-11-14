"""Offline tests for the Kalshi official-settlement collector (no network)."""
import gzip
import io
import json
import urllib.error
from pathlib import Path

import pytest

from alpha_engine.collect import kalshi_settlements as ks


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _m(ticker, event, result, **kw):
    d = {"ticker": ticker, "event_ticker": event, "status": "finalized", "result": result, "settlement_ts": "2026-11-13T03:00:00Z",
         "occurrence_datetime": "2026-11-13T00:00:00Z", "close_time": "2026-11-13T03:00:00Z"}
    d.update(kw)
    return d


def test_page_url_validates_and_filters_settled():
    u = ks.page_url("live", "KXNHLGAME")
    assert "status=settled" in u and "series_ticker=KXNHLGAME" in u and "limit=1000" in u
    assert "status=" not in ks.page_url("historical", "KXNHLGAME")
    with pytest.raises(ValueError):
        ks.page_url("live", "NHL; rm -rf")
    with pytest.raises(ValueError):
        ks.page_url("other", "KXNHLGAME")


def test_cache_dir_inside_repo_refused(tmp_path):
    with pytest.raises(PermissionError):
        ks.fetch_series("KXNHLGAME", "live", ks.REPO_ROOT / "research" / "x", max_calls=1, opener=lambda *a, **k: None)


def test_call_cap_and_pause_floor(tmp_path):
    with pytest.raises(ValueError):
        ks.fetch_series("KXNHLGAME", "live", tmp_path, max_calls=ks.HARD_MAX_CALLS + 1)
    pages = [{"markets": [_m("A-1", "A", "yes")], "cursor": "c1"}, {"markets": [_m("A-2", "A", "no")], "cursor": "c2"}, {"markets": [], "cursor": ""}]
    sleeps = []
    it = iter(pages)
    meta = ks.fetch_series("KXNHLGAME", "live", tmp_path, max_calls=2, pause=0.0, opener=lambda *a, **k: _Resp(json.dumps(next(it)).encode()),
                           sleep=sleeps.append)
    assert meta["calls"] == 2 and meta["log"][-1]["stop"] == "max_calls_reached"
    assert sleeps and min(sleeps) >= ks.MIN_PAUSE
    assert len(list((tmp_path / "KXNHLGAME" / "live").glob("page_*.json.gz"))) == 2


def test_429_backs_off_then_stops(tmp_path):
    def opener(*a, **k):
        raise urllib.error.HTTPError("u", 429, "too many", {}, None)
    sleeps = []
    meta = ks.fetch_series("KXNHLGAME", "live", tmp_path, max_calls=50, opener=opener, sleep=sleeps.append)
    assert sleeps == list(ks.BACKOFF_429)
    assert meta["log"][-1]["status"] == 429 and meta["log"][-1]["stop"] == "http_error"
    assert meta["calls"] == ks.MAX_429 + 1


def test_other_http_error_stops_immediately(tmp_path):
    def opener(*a, **k):
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, None)
    meta = ks.fetch_series("KXNHLGAME", "live", tmp_path, max_calls=50, opener=opener, sleep=lambda s: None)
    assert meta["calls"] == 1 and meta["log"][-1]["stop"] == "http_error"


def test_load_rows_dedup_live_wins(tmp_path):
    for src, res in (("historical", "no"), ("live", "yes")):
        d = tmp_path / "KXNHLGAME" / src
        d.mkdir(parents=True)
        (d / "page_000.json.gz").write_bytes(gzip.compress(json.dumps({"markets": [_m("A-X", "A", res)]}).encode()))
    rows = ks.load_rows(tmp_path, "KXNHLGAME")
    assert len(rows) == 1 and rows[0]["result"] == "yes" and rows[0]["source"] == "live"


def test_event_consistency_and_ladder():
    rows = [_m("E1-A", "E1", "yes"), _m("E1-B", "E1", "no"), _m("E2-A", "E2", "yes"), _m("E2-B", "E2", "yes")]
    c = ks.event_consistency(rows)
    assert c["events_checked"] == 2 and c["events_not_exactly_one_yes"] == 1 and c["examples"] == ["E2"]
    lad = [_m("T-5", "T", "yes", strike_type="greater", floor_strike=5.5), _m("T-6", "T", "no", strike_type="greater", floor_strike=6.5),
           _m("T-7", "T", "yes", strike_type="greater", floor_strike=7.5)]
    assert ks.ladder_monotonic(lad)["non_monotonic"] == 1
    assert ks.ladder_monotonic(lad[:2])["non_monotonic"] == 0


def test_summarize_seasons_and_fill():
    rows = [_m("E1-A", "E1", "yes"), dict(_m("E0-A", "E0", "no"), occurrence_datetime="2026-03-01T00:00:00Z")]
    for r in rows:
        r["source"] = "live"
    s = ks.summarize(rows)
    assert s["events_by_season"] == {"2025-26": 1, "2026-27": 1}
    assert s["field_fill"]["result"] == 1.0 and s["field_fill"]["floor_strike"] == 0.0


def test_nhl_crosscheck_shootout_conventions():
    scores = ks.nhl_scores_from_payload({"games": [
        {"gameState": "OFF", "gameDate": "2026-11-12", "id": 1, "awayTeam": {"abbrev": "WPG", "score": 3}, "homeTeam": {"abbrev": "DAL", "score": 2},
         "gameOutcome": {"lastPeriodType": "SO"}},
        {"gameState": "LIVE", "gameDate": "2026-11-12", "id": 2, "awayTeam": {"abbrev": "BUF", "score": 1}, "homeTeam": {"abbrev": "CHI", "score": 0}}]})
    assert list(scores) == [("2026-11-12", "WPGDAL")]
    ev = "KXNHLTOTAL-26NOV12WPGDAL"
    assert ks.nhl_event_key(ev) == ("2026-11-12", "WPGDAL")
    total = [_m(ev + "-5", ev, "no", strike_type="greater", floor_strike=4.5)]     # 3-2 SO: 5 with the SO goal, 4 without
    cc = ks.nhl_crosscheck(total, scores, "game_total")
    assert cc["shootout_goal_excluded"]["agree"] == 1 and cc["shootout_goal_counts"]["disagree"] == 1
    gev = "KXNHLGAME-26NOV12WPGDAL"
    game = [_m(gev + "-WPG", gev, "yes"), _m(gev + "-DAL", gev, "no")]
    g = ks.nhl_crosscheck(game, scores, "game_winner")
    assert g["shootout_goal_counts"]["agree"] == 2 and g["shootout_goal_excluded"]["agree"] == 2
    sev = "KXNHLSPREAD-26NOV12WPGDAL"
    spread = [_m(sev + "-WPG1", sev, "no", strike_type="greater", floor_strike=1.5)]
    assert ks.nhl_crosscheck(spread, scores, "game_spread")["shootout_goal_excluded"]["agree"] == 1


def test_no_schedule_entrypoint_or_workflow():
    root = Path(ks.__file__).resolve().parents[2]
    wf = root / ".github" / "workflows"
    for p in wf.glob("*.yml"):
        assert "kalshi_settlements" not in p.read_text(), p


def test_nba_cross_family_from_game_score():
    ev = "KXNBAGAME-26NOV12TORPHI"
    game = [_m(ev + "-TOR", ev, "no", expiration_value="123-112"), _m(ev + "-PHI", ev, "yes", expiration_value="123-112")]
    sc = ks.nba_scores_from_game_rows(game)
    assert sc == {"26NOV12TORPHI": {"PHI": 123, "TOR": 112}}
    tev = "KXNBATOTAL-26NOV12TORPHI"
    tot = [_m(tev + "-235", tev, "no", floor_strike=235.5), _m(tev + "-230", tev, "yes", floor_strike=230.5)]
    assert ks.nba_cross_family(tot, sc, "game_total")["agree"] == 2
    sev = "KXNBASPREAD-26NOV12TORPHI"
    sp = [_m(sev + "-PHI10", sev, "yes", floor_strike=10.5), _m(sev + "-PHI12", sev, "yes", floor_strike=12.5)]
    r = ks.nba_cross_family(sp, sc, "game_spread")
    assert r["agree"] == 1 and r["disagree"] == 1
    tt = [_m("KXNBATEAMTOTAL-26NOV12TORPHI-TOR110", "KXNBATEAMTOTAL-26NOV12TORPHI", "yes", floor_strike=110.5)]
    assert ks.nba_cross_family(tt, sc, "team_total")["agree"] == 1
    assert ks.nba_scores_from_game_rows([dict(game[0], expiration_value="New York"), game[1]]) == {}


def test_nhl_two_letter_kalshi_codes_match():
    sc = ks.nhl_scores_from_payload({"games": [{"gameState": "FINAL", "gameDate": "2026-04-10", "id": 3, "awayTeam": {"abbrev": "COL", "score": 2},
                                                 "homeTeam": {"abbrev": "LAK", "score": 4}, "gameOutcome": {"lastPeriodType": "REG"}}]})
    assert ("2026-04-10", "COLLA") in sc
    ev = "KXNHLGAME-26APR10COLLA"
    r = ks.nhl_crosscheck([_m(ev + "-LA", ev, "yes"), _m(ev + "-COL", ev, "no")], sc, "game_winner")
    assert r["matched_markets"] == 2 and r["shootout_goal_counts"]["agree"] == 2


def test_nba_espn_scores_and_winner_check():
    pay = {"events": [{"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
        {"homeAway": "home", "team": {"abbreviation": "SA"}, "score": "101"}, {"homeAway": "away", "team": {"abbreviation": "NY"}, "score": "99"}]}]},
        {"competitions": [{"status": {"type": {"completed": False}}, "competitors": []}]}]}
    sc = ks.nba_scores_from_espn(pay, "2026-06-13")
    assert sc == {"26JUN13NYKSAS": {"NYK": 99, "SAS": 101}}
    ev = "KXNBAGAME-26JUN13NYKSAS"
    r = ks.nba_cross_family([_m(ev + "-SAS", ev, "yes"), _m(ev + "-NYK", ev, "yes")], sc, "game_winner")
    assert r["agree"] == 1 and r["disagree"] == 1

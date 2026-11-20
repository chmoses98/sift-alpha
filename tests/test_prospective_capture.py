"""Prospective vintage capture (alpha_engine.prospective): disabled by default, rights-gated, immutable, point-in-time reads. Synthetic fixtures only; no network. RESEARCH_ONLY."""
import datetime as dt
import json

import pytest

from alpha_engine.prospective import feeds as F
from alpha_engine.prospective import vintage as V

NFL_FIX = {"injuries": [{"team": {"id": "12"}, "injuries": [
    {"athlete": {"id": "4040", "position": {"abbreviation": "WR"}}, "status": "Out", "date": "2026-11-20T21:05Z", "details": {"type": "Hamstring"}},
    {"athlete": {"id": "4041", "position": {"abbreviation": "QB"}}, "status": "Questionable", "date": "2026-11-21T15:00Z"}]}]}


def _allow(tmp_path, source="espn_scoreboard_and_archives", allowed=True):
    reg = {"sources": [{"id": source, "tier": "TEST", "collection_allowed": allowed}]}
    p = tmp_path / "rights.json"; p.write_text(json.dumps(reg)); a = tmp_path / "act.json"
    a.write_text(json.dumps({"feeds": {"nfl.injury_report_vintages": {"owner": "test-owner", "approved_utc": "2026-11-20T00:00:00Z"}}}))
    return p, {"SIFT_PROSPECTIVE_ENABLED": "1", "SIFT_PROSPECTIVE_ACTIVATION": str(a)}


def test_disabled_by_default_and_against_the_real_registry(tmp_path):
    feed = F.FEEDS["nfl.injury_report_vintages"]
    with pytest.raises(V.CaptureRefused) as e:
        V.capture(tmp_path, feed, fetch=lambda u: (_ for _ in ()).throw(AssertionError("must not fetch")), env={})
    assert "disabled by default" in str(e.value) and "collection_allowed" in str(e.value)
    # even fully enabled and owner-activated, the REAL rights registry blocks every ESPN / MLB / NHL feed today
    _, env = _allow(tmp_path)
    for name in F.FEEDS:
        with pytest.raises(V.CaptureRefused):
            V.capture(tmp_path, F.FEEDS[name], fetch=lambda u: (_ for _ in ()).throw(AssertionError("must not fetch")), env=env, date="2026-11-20", game_pk=1, office="X", x=1, y=1)
    assert not (tmp_path / "MANIFEST.jsonl").exists()


def test_capture_stores_immutable_payload_and_metadata(tmp_path):
    rights, env = _allow(tmp_path)
    feed = F.FEEDS["nfl.injury_report_vintages"]; body = json.dumps(NFL_FIX).encode()
    rec = V.capture(tmp_path / "vault", feed, fetch=lambda u: (200, body), env=env, rights_path=rights)
    assert rec["http"] == 200 and rec["n_entities"] == 2 and rec["entity_ids"] == ["4040", "4041"] and rec["source_published_utc"] == "2026-11-21T15:00Z"
    assert rec["rights_tier"] == "TEST" and len(rec["sha256"]) == 64 and rec["completeness"]["status"] == 1.0
    with pytest.raises(FileExistsError):                                       # same capture timestamp can never overwrite a vintage
        V.store(tmp_path / "vault", feed, body, rec["url"], _same_ts(tmp_path / "vault", rec), 200, 1, [], "TEST")


def _same_ts(root, rec):
    f = rec["file"].rsplit("_", 1)[1].replace(".json.gz", "")
    return dt.datetime.strptime(f, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=dt.timezone.utc)


def test_failures_are_recorded_and_retries_bounded(tmp_path):
    rights, env = _allow(tmp_path); calls = []
    def fetch(u):
        calls.append(u); return 429, None
    rec = V.capture(tmp_path / "v", F.FEEDS["nfl.injury_report_vintages"], fetch=fetch, env=env, rights_path=rights)
    assert rec["http"] == 429 and len(calls) == 1 and "file" not in rec            # never retry a 429
    assert V.manifest(tmp_path / "v")[-1]["http"] == 429


def test_as_of_never_returns_a_later_vintage(tmp_path):
    feed = F.FEEDS["nfl.injury_report_vintages"]; root = tmp_path / "v"
    early = dict(NFL_FIX); late = {"injuries": [{"team": {"id": "12"}, "injuries": [{"athlete": {"id": "4040"}, "status": "Active", "date": "2026-11-22T10:00Z"}]}]}
    t1 = dt.datetime(2026, 11, 21, 12, tzinfo=dt.timezone.utc); t2 = dt.datetime(2026, 11, 22, 12, tzinfo=dt.timezone.utc)
    V.store(root, feed, json.dumps(early).encode(), "u", t1, 200, 1, [], "TEST"); V.store(root, feed, json.dumps(late).encode(), "u", t2, 200, 1, [], "TEST")
    a = V.as_of(root, feed, "2026-11-22T11:59:59Z")
    assert a["record"]["capture_utc"] == "2026-11-21T12:00:00Z" and a["rows"][0]["status"] == "Out" and a["freshness_minutes"] > 1400
    assert V.as_of(root, feed, "2026-11-21T11:00:00Z") is None
    assert V.as_of(root, feed, "2026-11-23T00:00:00Z")["rows"][0]["status"] == "Active"


def test_parsers_on_synthetic_fixtures():
    mlb = {"dates": [{"games": [{"gamePk": 1, "gameDate": "2027-04-01T17:05:00Z", "status": {"detailedState": "Scheduled"},
                                 "teams": {"home": {"team": {"id": 147}, "probablePitcher": {"id": 543037}}, "away": {"team": {"id": 111}}}}]}]}
    r = F.FEEDS["mlb.probable_pitchers"].parse(mlb); assert {x["pitcher_id"] for x in r} == {543037, None}
    nws = {"properties": {"updateTime": "2026-11-20T10:00:00+00:00", "periods": [{"startTime": "2026-11-22T13:00:00-05:00", "temperature": 41, "windSpeed": "14 mph", "windDirection": "NW",
                                                                                  "probabilityOfPrecipitation": {"value": 20}}]}}
    assert F.FEEDS["env.weather_forecast_pit"].parse(nws)[0]["wind_speed"] == "14 mph" and F.FEEDS["env.weather_forecast_pit"].published(nws).startswith("2026-11-20")
    assert F.FEEDS["nhl.starting_goalies"].parse({"games": [{"id": 9, "homeTeam": {"abbrev": "BOS", "startingGoalie": {"playerId": 7, "confirmed": True}}, "awayTeam": {"abbrev": "TOR"}}]})[0]["goalie_id"] == 7

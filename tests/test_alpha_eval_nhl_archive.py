"""NHL data-archive adapter: freeze attestation from git history, ticker/player identity, independent outcome join and conflicts."""
from collections import Counter
from datetime import datetime, timezone

from alpha_eval import nhl_archive as H
from alpha_eval.grading import grade_all
from alpha_eval.schema import BLOCKED, GRADED, R

START = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
REL = "predictions/dt=2026-11-13/predictions_20261113T024146Z_43351958977.jsonl.gz"


def _log(subject="capture: 43351958977 at 2026-11-13T02:54:30Z", when="2026-11-13T02:55:01+00:00", extra=""):
    return f"C abc123 {when} {when} {subject}\nA\t{REL}\n{extra}"


def test_parse_ticker():
    p = H.parse_ticker("KXNHLGOAL-26NOV11NSHANA-NSHSWRIGHT51-2")
    assert p == dict(series="KXNHLGOAL", date="2026-11-11", teams="NSHANA", rest="NSHSWRIGHT51-2")
    assert H.parse_ticker("KXNHLHART-27-TSTUTZLE18") is None          # season-long: not game bound


def test_attestation_rules():
    assert H.attest(REL, H.parse_git_log(_log()), START) == "ATTESTED"
    assert H.attest(REL, H.parse_git_log(_log(when="2026-11-13T03:00:00+00:00")), START) == "COMMITTED_AT_OR_AFTER_START"
    assert H.attest(REL, H.parse_git_log(_log(subject="capture: 999 at x")), START) == "RUN_ID_MISMATCH"
    mod = _log(extra=f"C def456 2026-11-14T00:00:00+00:00 2026-11-14T00:00:00+00:00 capture: 1 at y\nM\t{REL}\n")
    assert H.attest(REL, H.parse_git_log(mod), START) == "MODIFIED_OR_DELETED"
    assert H.attest("predictions/other.jsonl.gz", H.parse_git_log(_log()), START) == "NOT_IN_HISTORY"


GAME = dict(date="2026-11-12", away="NYI", home="LAK")


def test_identity_game_and_player():
    assert H.check_identity("KXNHLGAME-26NOV12NYILA-LA", GAME) == "IDENTITY_VERIFIED"      # LAK -> LA mapping
    assert H.check_identity("KXNHLGAME-26NOV13NYILA-LA", GAME) == "MISMATCH_DATE"
    assert H.check_identity("KXNHLGAME-26NOV12LANYI-LA", GAME) == "MISMATCH_TEAMS"
    t = "KXNHLAST-26NOV12NYILA-LAAKEMPE9-1"
    assert H.check_identity(t, GAME, ("LAK", 9, "A. Kempe")) == "IDENTITY_VERIFIED"
    assert H.check_identity(t, GAME, ("LAK", 10, "A. Kempe")) == "MISMATCH_PLAYER"        # sweater
    assert H.check_identity(t, GAME, ("NYI", 9, "A. Kempe")) == "MISMATCH_PLAYER"         # team
    assert H.check_identity(t, GAME, ("LAK", 9, "Q. Byfield")) == "MISMATCH_PLAYER"       # surname
    assert H.check_identity(t, GAME, "ABSENT") == "PLAYER_NOT_IN_OFFICIAL_BOX"


def _api(home_final=3, away_final=2, lpt="REG"):
    res = dict(game_id="g1", status="final", home_team_id=26, away_team_id=2, home_final=home_final, away_final=away_final,
               last_period_type=lpt)
    return {"g1": dict(game=dict(GAME, start="2026-11-13T03:00:00Z"), res=res, goals=[], players={}, goalies={}, roster={},
                       fetched_at="2026-11-13T07:00:00Z")}


def _prod(home_final=3, away_final=2, settle="YES", lpt="REG"):
    res = dict(game_id="g1", status="final", home_team_id=26, away_team_id=2, home_final=home_final, away_final=away_final,
               last_period_type=lpt, fetched_at_utc="x")
    return dict(results={"g1": res}, goals={}, players={}, goalies={},
                settlements={"T": dict(outcome=settle, settled_at_utc="x")} if settle else {})


C_ML = dict(family="game_winner", team_id=26, threshold=0.0, comparator="gt")


def test_outcome_agreement_and_conflicts():
    x = Counter()
    rows = H.outcome_rows("T", C_ML, "g1", _api(), _prod(), "IDENTITY_VERIFIED", x)
    assert [r["value"] for r in rows] == [1] and x["ARCHIVE_AGREE"] == 1 and x["SETTLE_ENGINE_AGREE"] == 1
    x = Counter()
    rows = H.outcome_rows("T", C_ML, "g1", _api(), _prod(home_final=1), "IDENTITY_VERIFIED", x)   # producer archive disagrees
    assert sorted(r["value"] for r in rows) == [0, 1] and x["ARCHIVE_DISAGREE"] == 1
    x = Counter()
    rows = H.outcome_rows("T", C_ML, "g1", _api(), _prod(settle="NO"), "IDENTITY_VERIFIED", x)    # settle engine disagrees
    assert sorted(r["value"] for r in rows) == [0, 1] and x["SETTLE_ENGINE_DISAGREE"] == 1
    rows = H.outcome_rows("T", C_ML, "g1", _api(), None, "MISMATCH_TEAMS", Counter())
    assert rows[0]["event_id"] == "g1#TICKER_IDENTITY_MISMATCH"


def test_shootout_ambiguity_is_blocked_by_the_standard():
    c = dict(family="game_total", team_id=None, threshold=5.5, comparator="gt")
    x = Counter()
    rows = H.outcome_rows("T", c, "g1", _api(4, 2, "SO"), None, "IDENTITY_VERIFIED", x)       # 6 incl. SO goal, 5 excl.
    assert x["SO_AMBIGUOUS_BLOCKED"] == 1 and sorted(r["value"] for r in rows) == [0, 1]
    f = dict(schema="sift-alpha-eval/1", forecast_id="f", sport="NHL", event_id="g1", market_id="T", model_id="m", model_version="v",
             model_independence="sports_only", frozen_at="2026-11-13T02:00:00Z", event_start="2026-11-13T03:00:00Z",
             evidence_class="PROSPECTIVE", scoring_type="BINARY", payload=dict(p_yes=0.5), native_family="game_total")
    g = grade_all([f], rows)
    assert g["rows"][0]["accuracy"]["status"] == BLOCKED and g["rows"][0]["accuracy"]["reason"] == R.OUTCOME_CONFLICT


def test_identity_mismatch_blocks_join():
    rows = H.outcome_rows("T", C_ML, "g1", _api(), None, "MISMATCH_DATE", Counter())
    f = dict(schema="sift-alpha-eval/1", forecast_id="f", sport="NHL", event_id="g1", market_id="T", model_id="m", model_version="v",
             model_independence="sports_only", frozen_at="2026-11-13T02:00:00Z", event_start="2026-11-13T03:00:00Z",
             evidence_class="PROSPECTIVE", scoring_type="BINARY", payload=dict(p_yes=0.5), native_family="game_winner")
    g = grade_all([f], rows)
    assert g["rows"][0]["accuracy"]["status"] != GRADED


def test_independent_player_resolution():
    roster = {8477960: ("LAK", 9, "A. Kempe"), 1: ("LAK", 99, "Q. Byfield"), 2: ("NYI", 9, "B. Nelson")}
    assert H.resolve_player("KXNHLAST-26NOV12NYILA-LAAKEMPE9-1", GAME, roster) == 8477960
    assert H.resolve_player("KXNHLAST-26NOV12NYILA-LAAKEMPE10-1", GAME, roster) is None        # sweater not in box
    assert H.resolve_player("KXNHLAST-26NOV12NYILA-NYIBNELSON9-1", GAME, roster) == 2          # same sweater, other team

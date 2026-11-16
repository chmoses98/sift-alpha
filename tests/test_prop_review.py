"""prop_review: classification of player-prop settlement disagreements (no network)."""
from alpha_engine.game_completeness import prop_review as pr

BOX = {"awayTeam": {"abbrev": "NYI"}, "homeTeam": {"abbrev": "LAK"},
       "playerByGameStats": {"awayTeam": {"forwards": [{"sweaterNumber": 21, "assists": 1, "points": 1}],
                                          "defense": [], "goalies": [{"sweaterNumber": 30, "saves": 24}]},
                             "homeTeam": {"forwards": [{"sweaterNumber": 11, "assists": 0, "points": 2}], "defense": [],
                                          "goalies": [{"sweaterNumber": 30, "saves": 26}]}}}


def row(ticker, outcome, value, reason):
    return {"ticker": ticker, "game_id": "1", "outcome": outcome, "value": value, "reason": reason}


def test_parsers():
    assert pr.parse_reason("saves=27 gt 25.5 (team+jersey+name)") == ("saves", 27.0, "gt", 25.5)
    assert pr.parse_reason("player not in box score") is None
    assert pr.parse_player("KXNHLSAVE-26NOV14WPGCHI-CHISKNIGHT30-26") == ("CHI", 30)
    assert pr.parse_player("KXNHLAST-26NOV12NYILA-LAAKOPITAR11-1") == ("LA", 11)
    assert pr.parse_player("KXNHLAST-26NOV12NYILA-BOSXX11-1") is None          # team not in the event
    assert pr.nhl_stat(BOX, "LA", 11, "points") == (2.0, None)
    assert pr.nhl_stat(BOX, "NYI", 99, "points")[0] is None


def test_review_classes():
    t1, t2, t3, t4, t5 = ("KXNHLSAVE-26NOV12NYILA-NYIISOROKIN30-24", "KXNHLAST-26NOV12NYILA-NYIKPALMIERI21-1",
                          "KXNHLPTS-26NOV12NYILA-LAAKOPITAR11-2", "KXNHLPTS-26NOV12NYILA-LAAKOPITAR99-2",
                          "KXNHLAST-26NOV12NYILA-LAAKOPITAR11-1")
    computed = {t1: row(t1, "NO", 23.0, "saves=23 gt 23.5"),       # league now 24 -> YES, exchange yes
                t2: row(t2, "YES", 1.0, "assists=1 gt 0.5"),       # league still 1, exchange no
                t3: row(t3, "NO", 1.0, "points=1 gt 1.5"),         # league now 2 -> YES, exchange... still 'no' below
                t4: row(t4, "NO", 1.0, "points=1 gt 1.5"),         # sweater not found
                t5: row(t5, "NO", 0.0, "assists=0 gt 0.5")}        # agrees with the exchange: not reviewed
    official = {t1: {"result": "yes"}, t2: {"result": "no"}, t3: {"result": "yes"}, t4: {"result": "yes"},
                t5: {"result": "no"}}
    r = pr.review(official, computed, lambda gid: BOX)
    by = {i["ticker"]: i["class"] for i in r["items"]}
    assert by == {t1: "league_corrected_after_engine_read", t2: "exchange_differs_from_league",
                  t3: "league_corrected_after_engine_read", t4: "not_reviewable"}
    assert r["disagreements"] == 4 and r["counts"]["KXNHLSAVE:league_corrected_after_engine_read"] == 1


def test_league_changed_but_engine_result_stands():
    t = "KXNHLSAVE-26NOV12NYILA-LAXGOALIE30-24"
    r = pr.review({t: {"result": "no"}}, {t: row(t, "YES", 25.0, "saves=25 gt 23.5")}, lambda gid: BOX)
    assert r["items"][0]["class"] == "league_changed_but_still_disagrees" and r["items"][0]["league_value_now"] == 26.0

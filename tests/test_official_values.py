"""official_values: join, period arithmetic, value parsing and ladder grading (no network, synthetic rows)."""
import json
from collections import Counter

from alpha_engine.game_completeness import official_values as ov


def game(sport="CFB", pa=(7, 3, 0, 7), ph=(0, 7, 7, 3), date="2026-10-03T19:30Z"):
    side = lambda ab, names, p: {"abbr": ab, "names": {ov.norm_name(n) for n in names}, "periods": list(p),  # noqa: E731
                                 "score": sum(p)}
    return ov._game("1", date, side("WSU", ["Washington State"], pa), side("MIA", ["Miami"], ph))


def ev(**series):
    return {"26OCT03WSUMIA": {k: Counter(v) for k, v in series.items()}}


def test_classify_series_and_names():
    assert ov.classify_series("CFB", "KXNCAAF2HTOTAL") == ("2H", "TOTAL")
    assert ov.classify_series("CFB", "KXNCAAFGAME") == ("FG", "GAME")
    assert ov.classify_series("CBB", "KXNCAAMB1H") == ("1H", "GAME")
    assert ov.classify_series("CFB", "KXNCAAFFIRSTTDTEAM") is None
    assert ov.norm_name("Washington St. wins 1st Half") == "washington state"
    assert ov.norm_name("Miami (FL)") == "miami"


def test_period_points_overtime_only_in_second_half():
    a, h = (7, 3, 0, 7, 7), (0, 7, 7, 3, 3)
    assert ov.period_points("CFB", a, h, "4Q") == (7, 3)                      # 4Q never includes overtime
    assert ov.period_points("CFB", a, h, "2H") == (14, 13)
    assert ov.period_points("CFB", a, h, "2H", include_ot=False) == (7, 10)
    assert ov.period_points("CFB", a, h, "FG") == (24, 20)
    assert ov.period_points("CBB", (30, 40, 9), (35, 35, 5), "2H") == (49, 40)
    assert ov.period_points("CFB", (7, 3), (0, 7), "1H") is None              # incomplete box score: no figure


def test_join_by_abbreviation_then_by_winner_name():
    g = game()
    assert ov.join(ev(KXNCAAFTOTAL=["34"]), [g])["26OCT03WSUMIA"][1] == "abbr"
    e = {"26OCT03WASTMIA": {"KXNCAAFGAME": Counter(["Washington St."])}}      # exchange abbreviation differs
    assert ov.join(e, [g])["26OCT03WASTMIA"][1] == "name"
    assert ov.join({"26OCT03WASTMIA": {"KXNCAAFTOTAL": Counter(["34"])}}, [g]) == {}   # no name: never guessed
    assert ov.join(ev(KXNCAAFTOTAL=["34"]), [g, game()]) == {}                # two candidates: ambiguous


def test_values_agree_and_disagree():
    r = ov.check("CFB", ev(KXNCAAFTOTAL=["34"], KXNCAAFSPREAD=["0"], KXNCAAFGAME=["Tie"], KXNCAAF1HTOTAL=["17"],
                           KXNCAAF1Q=["Washington St. wins 1st Quarter"], KXNCAAF4QSPREAD=["5"],
                           KXNCAAFTEAMTOTAL=["Home: 17, Away: at least 14"], KXNCAAFOT=["0"]), [game()])
    assert r["totals"] == {"agree": 7, "disagree": 1} and r["disagreements"][0]["series"] == "KXNCAAF4QSPREAD"


def test_second_half_reports_which_overtime_reading_matched():
    g = game(pa=(7, 3, 0, 7, 7), ph=(0, 7, 7, 3, 3))
    r = ov.check("CFB", ev(KXNCAAF2HTOTAL=["27"], KXNCAAFOT=["1"]), [g])
    assert r["second_half_in_overtime_games_by_date"] == {"2026-10-03": {"including_ot": 1}}
    r = ov.check("CFB", ev(KXNCAAF2HTOTAL=["17"]), [g])
    assert r["second_half_in_overtime_games_by_date"] == {"2026-10-03": {"regulation_only": 1}}


def test_total_ladder_is_graded_per_contract():
    lad = {"26OCT03WSUMIA": {"KXNCAAFTOTAL": [(33, "yes"), (34, "yes"), (35, "no"), (36, "yes")]}}
    r = ov.check("CFB", ev(KXNCAAFTOTAL=["34"]), [game()], lad)
    c = r["by_series"]["KXNCAAFTOTAL"]
    assert (c["contracts_agree"], c["contracts_disagree"]) == (3, 1)


def test_cbb_opaque_winner_and_signed_spread(tmp_path):
    g = game(pa=(30, 40), ph=(35, 30))
    e = ev(KXNCAAMB1H=["fbb925f2-f829-4d76-9cd5-ad05cfdf64b3"], KXNCAAMB2HSPREAD=["10", "-10"],
           KXNCAAMBTEAMTOTAL=["70", "65"])
    r = ov.check("CBB", e, [g])
    assert r["totals"] == {"official_value_opaque_id": 1, "agree": 2}


def test_official_events_reads_only_settled_known_series(tmp_path):
    rows = [{"ticker": "KXNCAAFTOTAL-26OCT03WSUMIA-34", "event_ticker": "KXNCAAFTOTAL-26OCT03WSUMIA", "result": "yes",
             "expiration_value": "34"},
            {"ticker": "KXNCAAFTOTAL-26OCT03WSUMIA-35", "event_ticker": "KXNCAAFTOTAL-26OCT03WSUMIA", "result": "",
             "expiration_value": ""},
            {"ticker": "KXNCAAFDSTTD-26OCT03WSUMIA-Y", "event_ticker": "KXNCAAFDSTTD-26OCT03WSUMIA", "result": "no",
             "expiration_value": "none"}]
    (tmp_path / "x.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    events, ladders = ov.official_events([tmp_path], "CFB")
    assert dict(events["26OCT03WSUMIA"]) == {"KXNCAAFTOTAL": Counter({"34": 1})}
    assert ladders["26OCT03WSUMIA"]["KXNCAAFTOTAL"] == [(34, "yes")]

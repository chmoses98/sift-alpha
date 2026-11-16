from alpha_engine.game_completeness import protected_props as pp


def test_base_ticker_and_resolution():
    assert pp.base_ticker("KXNBAPTSPROT-26NOV15OKCSAC-OKCACARUSO9-25") == "KXNBAPTS-26NOV15OKCSAC-OKCACARUSO9-25"
    assert pp.base_ticker("KXNBAPTS-26NOV15OKCSAC-OKCACARUSO9-25") is None
    assert pp.resolution({"result": "yes", "settlement_value_dollars": "1.0000"}) == "yes"
    assert pp.resolution({"result": "", "settlement_value_dollars": "0.4200"}) == "fair_price"
    assert pp.resolution({"result": "void", "settlement_value_dollars": None}) == "other"


def test_measure_pairs_each_protected_contract_with_the_engine_base_result():
    off = {"KXNBAPTSPROT-E-P1-25": {"result": "yes", "settlement_value_dollars": "1.0000"},
           "KXNBAPTSPROT-E-P2-25": {"result": "no", "settlement_value_dollars": "0.0000"},
           "KXNBAPTSPROT-E-P3-25": {"result": "", "settlement_value_dollars": "0.3100"},
           "KXNBAPTSPROT-E-P4-25": {"result": "no", "settlement_value_dollars": "0.0000"},
           "KXNBAPTSPROT-E-P5-25": {"result": "no", "settlement_value_dollars": "0.0000"},
           "KXNBAPTS-E-P1-25": {"result": "yes"}}
    eng = {"KXNBAPTS-E-P1-25": "YES", "KXNBAPTS-E-P2-25": "YES", "KXNBAPTS-E-P3-25": "NO",
           "KXNBAPTS-E-P4-25": "UNSETTLEABLE"}
    r = pp.measure(off, eng)
    assert r["by_series"] == {"KXNBAPTSPROT": {"agree": 1, "disagree|exchange_no_engine_yes": 1, "engine_no_base_row": 1,
                                               "engine_unsettleable": 1, "fair_price|engine_no": 1}}

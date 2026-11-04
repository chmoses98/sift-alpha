import importlib.util, json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vfs", os.path.join(HERE, "..", "scripts", "validate_fee_schedule.py"))
vfs = importlib.util.module_from_spec(spec); spec.loader.exec_module(vfs)
REPORT = os.path.join(HERE, "..", "reports", "clv_recalc", "fee_validation_2026-11-04.json")


def test_taker_fee_classified():
    assert vfs.classify(1.75, 100, 0.5, 0.03) == "TAKER_0.07"


def test_quarter_maker_fee_classified():
    assert vfs.classify(0.44, 100, 0.5, 0.03) == "MAKER_0.0175"


def test_zero_and_other():
    assert vfs.classify(0, 10, 0.5, 0.03) == "ZERO_FEE"
    assert vfs.classify(0.9, 100, 0.5, 0.03) == "OTHER"


def test_report_is_aggregate_only_and_taker_dominant():
    d = json.load(open(REPORT)); text = json.dumps(d)
    assert not re.search(r"KX[A-Z0-9]+-\d{2}[A-Z]{3}", text) and "kalshi:v1" not in text
    n = sum(v["n"] for v in d["by_series"].values()); t = sum(v.get("TAKER_0.07", 0) for v in d["by_series"].values())
    assert n >= 600 and t / n > 0.99
    assert sum(v.get("MAKER_0.0175", 0) for v in d["by_series"].values()) == 0   # no maker fill observed: maker rate stays UNVERIFIED

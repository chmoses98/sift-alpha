"""Six-sport official-vs-computed reconciliation: layers stay separate, nonstandard settlements are never judged."""
import gzip
import json

import pytest

from alpha_engine.game_completeness import settlement_reconcile as R


def off(ticker, result="yes", ev="5", sv="1.0000", vol="10", tier="live", ts="2026-11-01T00:00:00Z"):
    return {"ticker": ticker, "result": result, "expiration_value": ev, "settlement_value_dollars": sv,
            "volume_fp": vol, "_tier": tier, "settlement_ts": ts}


def write(path, rows, gz=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    op = gzip.open if gz else open
    with op(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_official_classes_match_the_vault_summary():
    assert R.official_class(off("A")) == "VALUE_SETTLED"
    assert R.official_class(off("A", ev="No", vol="0", result="no", sv="0.0000")) == "ADMIN_LITERAL_UNTRADED"
    assert R.official_class(off("A", ev="Yes")) == "LITERAL_VALUE_TRADED"
    assert R.official_class(off("A", sv="0.4300")) == "FAIR_PRICE_SETTLEMENT"
    assert R.official_class(off("A", result="scalar")) == "VOID_OR_SCALAR"
    assert R.official_class(off("A", result="")) == "NO_RESULT"
    assert R.official_class(off("A", ev="")) == "NO_EXPIRATION_VALUE"


def test_computed_dialects():
    assert R._side({"outcome": "YES"}) == "YES"
    assert R._side({"marketTicker": "X", "result": "no"}) == "NO"
    assert R._side({"outcome": "UNSETTLEABLE"}) == "UNSETTLEABLE"
    assert R._side({"settlement_status": "SETTLED", "settled_yes": 1.0}) == "YES"
    assert R._side({"settlement_status": "SETTLED", "settled_yes": 0.0}) == "NO"
    assert R._side({"settlement_status": "REFUSED_SEASON_INCOMPLETE", "settled_yes": None}) == "REFUSED_SEASON_INCOMPLETE"
    assert R._side({"settlement_status": "SETTLED", "settlement_kind": "scalar", "settled_yes": 0.4}) == "SETTLED"


def test_reconcile_end_to_end(tmp_path):
    root = tmp_path / "official"
    write(root / "NBA" / "NBA" / "KXA.historical.jsonl", [off("KXA-1-X", result="no", tier="historical")])
    write(root / "NBA" / "NBA" / "KXA.live.jsonl", [
        off("KXA-1-X"),                                           # live replaces historical; computed YES -> agree
        off("KXA-1-Y", result="no"),                              # computed YES -> disagree
        off("KXA-1-Z", result="no", ev="No", vol="0", sv="0.0000"),  # administrative: never judged
        off("KXA-1-U"),                                           # engine unsettled, exchange settled
        off("KXA-1-W")])                                          # never computed
    comp = tmp_path / "c" / "dt=1" / "a.jsonl.gz"
    write(comp, [{"ticker": "KXA-1-X", "outcome": "NO"}, {"ticker": "KXA-1-X", "outcome": "YES"},
                 {"ticker": "KXA-1-Y", "outcome": "YES"}, {"ticker": "KXA-1-Z", "outcome": "YES"},
                 {"ticker": "KXA-1-U", "outcome": "UNSETTLEABLE"}, {"ticker": "KXA-9-Q", "outcome": "NO"}], gz=True)
    known = tmp_path / "known.json"
    known.write_text(json.dumps({"tickers": [{"ticker": "KXA-1-Y", "cause": "STAT_CORRECTION"}]}))
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"corrections": {"KXA-1-Y": {"archived": "YES", "regraded": "NO"}}}))
    doc = R.run(root, {"NBA": str(tmp_path / "c" / "*" / "*.jsonl.gz")}, {"NBA": str(overlay)}, [known], "t", sports=["NBA"])
    b = doc["sports"]["NBA"]
    assert b["official"]["contracts"] == 5 and b["official"]["nonstandard"] == 1
    assert b["official"]["archive_rows"] == {"rows": 6, "served_by_both_tiers": 1, "tiers_disagree_on_result_or_value": 1}
    k = b["computed"]["counts"]
    assert (k["agree"], k["disagree"], k["official_nonstandard"], k["computed_unsettled_official_settled"],
            k["computed_without_official"]) == (1, 1, 1, 1, 1)
    assert b["computed"]["archive"]["self_conflict"] == 1
    assert b["computed"]["official_in_computed_series_without_computed"] == 1
    assert b["disagreements"]["tickers"] == ["KXA-1-Y"]
    assert b["disagreements"]["by_prior_research_cause"] == {"STAT_CORRECTION": 1}
    assert b["with_overlay"]["disagree"] == 0 and b["with_overlay"]["disagreements_fixed"] == 1
    assert b["by_series"]["KXA"]["nonstandard_differs_from_computed"] == 1
    assert "rules_primary" not in json.dumps(doc) and "settlement_value" not in json.dumps(doc)


def test_stale_overlay_is_refused():
    with pytest.raises(ValueError):
        R.apply_overlay({"T": "NO"}, {"corrections": {"T": {"archived": "YES", "regraded": "NO"}}})


def test_sport_without_computed_archive_reports_official_only(tmp_path):
    write(tmp_path / "CFB" / "CFB" / "KXC.live.jsonl", [off("KXC-1-A")])
    b = R.run(tmp_path, {}, {}, [], "t", sports=["CFB"])["sports"]["CFB"]
    assert b["computed"] is None and b["official"]["by_class"] == {"VALUE_SETTLED": 1}


def test_nfl_overlay_dialect_corrects_settled_and_withdraws_pending_labels():
    """The NFL correction overlay carries dict entries; a pending or refused correction removes the label."""
    ov = {"corrections": {
        "A": {"archived": {"settled_yes": 1.0}, "corrected": {"status": "CORRECTED_SETTLED", "settled_yes": 0.0}},
        "B": {"archived": {"settled_yes": 1.0}, "corrected": {"status": "CORRECTED_PENDING"}},
        "C": {"archived": {"settled_yes": 0.0}, "corrected": {"status": "INVALIDATED_REFUSED"}},
        "Z": {"archived": {"settled_yes": 0.0}, "corrected": {"status": "CORRECTED_SETTLED", "settled_yes": 1.0}}}}
    out, applied = R.apply_overlay({"A": "YES", "B": "YES", "C": "NO", "D": "NO"}, ov)
    assert out == {"A": "NO", "B": "CORRECTED_PENDING", "C": "INVALIDATED_REFUSED", "D": "NO"} and applied == 3
    with pytest.raises(ValueError):
        R.apply_overlay({"A": "NO"}, ov)

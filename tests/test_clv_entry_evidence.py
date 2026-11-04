import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from sift_clv import canonical as C, executable as X, entry_conditions as E, evidence_import as EV, linkage as L

T0 = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
TK = "KXNFLGAME-26NOV01AAABBB-AAA"


def snap(dt, yb="0.48", ya="0.50", ticker=TK, book=None):
    return E.Snapshot.of(ticker, T0 + timedelta(seconds=dt), yb, ya, book)


def fills(price="0.50", n=10, fee="0.17", taker=True):
    return [C.Fill.of(price, n, fee, taker)]


def ev(snaps, **kw):
    return E.evaluate_entry(ticker=TK, side="YES", first_fill_at=T0, fills=kw.pop("fills", fills()), snapshots=snaps, **kw)


def test_entry_quote_uses_only_prior_snapshot_and_computes_costs():
    r = ev([snap(-120, "0.46", "0.48"), snap(-60)])             # latest prior one wins
    assert r.status == E.ENTRY_OK and r.snapshot_age_seconds == 60
    assert (r.entry_bid, r.entry_ask, r.entry_spread) == (D("0.48"), D("0.50"), D("0.02"))
    assert r.paid_vs_entry_ask == D("0.00") and r.paid_vs_entry_mid == D("0.01")
    assert r.taker_share == D(1) and r.maker_share == D(0) and r.entry_fee_per_contract == D("0.017")


def test_future_snapshot_is_refused_never_used():
    r = ev([snap(+1)])
    assert r.status == E.SNAPSHOT_AFTER_FILL and r.entry_ask is None
    r2 = ev([snap(+1), snap(-30)])                              # a prior one still wins over a later one
    assert r2.status == E.ENTRY_OK and r2.snapshot_age_seconds == 30


def test_missing_stale_wrong_ticker_and_one_sided_stay_unavailable():
    assert ev([]).status == E.NO_SNAPSHOT
    assert ev([snap(-30, ticker="KXNFLGAME-26NOV01AAABBB-BBB")]).status == E.TICKER_MISMATCH
    assert ev([snap(-5000)]).status == E.SNAPSHOT_STALE
    assert ev([snap(-30, yb=None, ya="0.5")]).status == E.ONE_SIDED
    assert ev([snap(-30, "0.60", "0.50")]).status == E.ONE_SIDED          # crossed
    assert E.evaluate_entry(ticker=TK, side="YES", first_fill_at=T0, fills=[], snapshots=[snap(-1)]).status == E.NO_FILLS


def test_no_side_is_derived_from_yes_book():
    r = E.evaluate_entry(ticker=TK, side="NO", first_fill_at=T0, fills=fills("0.52"), snapshots=[snap(-10, "0.48", "0.50")])
    assert (r.entry_bid, r.entry_ask) == (D("0.50"), D("0.52"))


def test_depth_walk_is_reported_only_with_a_real_prior_book():
    book = X.Book.of(TK, [("0.48", 5)], [("0.48", 4), ("0.47", 100)], T0 - timedelta(seconds=30))   # YES ask ladder: 0.52, 0.53
    r = E.evaluate_entry(ticker=TK, side="YES", first_fill_at=T0, fills=fills("0.52", 8), snapshots=[snap(-30, "0.48", "0.52", book=book)])
    assert r.depth_status == X.DEPTH_FULL and r.depth_walk_premium_over_best_ask == D("0.005")
    r2 = ev([snap(-30)])
    assert r2.depth_status == X.DEPTH_NOT_AVAILABLE and r2.depth_walk_ask_vwap is None


def test_coverage_counts_unavailable_without_imputing_and_is_private():
    rs = [ev([snap(-30)]), ev([]), ev([snap(+9)])]
    c = E.coverage(rs)
    assert c["fills"] == 3 and c["status_counts"][E.ENTRY_OK] == 1 and c["status_counts"][E.NO_SNAPSHOT] == 1
    assert c["entry_quote_coverage"] == pytest.approx(1 / 3, abs=1e-3)
    blob = json.dumps(c) + json.dumps(E.public_row(rs[0]))
    assert "KXNFL" not in blob and "0.50" not in blob


# ------------------------------------------------------------------------------------------- evidence importer
KEY = "kalshi:v1:" + "ab" * 32


def row(**kw):
    r = {"schema_version": EV.SCHEMA, "kind": "EXECUTION", "producer": "router", "source_bet_key": KEY,
         "recorded_at": "2026-11-01T18:05:00Z", "order_id_digest": "a" * 32, "fill_id_digests": ["b" * 32],
         "fill_count": 1, "first_fill_ts": 1793556000, "last_fill_ts": 1793556005, "execution_action": "BUY",
         "all_taker": True, "flags": []}
    r.update(kw)
    return r


def test_importer_refuses_raw_ids_and_wrong_shapes():
    assert EV.refusal_reason(row()) is None
    assert EV.refusal_reason(row(order_id="ORDER-1")) == "RAW_ID_FIELD_NAME"
    assert EV.refusal_reason(row(flags=["12345678-1234-1234-1234-123456789abc"])) == "UUID_SHAPED_VALUE"
    assert EV.refusal_reason(row(source_bet_key="kalshi:v1:short")) == "SOURCE_KEY"
    assert EV.refusal_reason(row(first_fill_ts=5, last_fill_ts=1)) == "FILL_WINDOW"
    assert EV.refusal_reason(row(kind="CLOSE")) == "NOT_EXECUTION_KIND"


def test_load_is_idempotent_conflicts_are_dropped_not_merged(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [row(), row(recorded_at="2026-11-02T00:00:00Z"), row(all_taker=False),
                                                   row(source_bet_key="kalshi:v1:" + "cd" * 32), {"junk": 1}]) + "\n")
    good, c = EV.load_evidence(p)
    assert KEY not in good and len(good) == 1 and c["conflict"] == 1 and c["refused_SCHEMA_VERSION"] == 1


def test_order_needs_evidence_and_never_borrows_wager_time():
    f = (C.Fill.of("0.5", 10, "0.17", None),)
    with pytest.raises(ValueError):
        EV.order_with_evidence(order_key=KEY, ticker=TK, side="YES", fills=f, evidence=None)
    o, src = EV.order_with_evidence(order_key=KEY, ticker=TK, side="YES", fills=f, evidence=row())
    assert o.first_fill_at.tzinfo is not None and o.fills[0].is_taker is True and src == "EXECUTION_EVIDENCE"
    assert o.client_order_id is None                 # evidence never fabricates a client_order_id


def test_evidence_alone_never_creates_a_verified_link():
    f = (C.Fill.of("0.5", 10, "0.17", None),)
    o, _ = EV.order_with_evidence(order_key=KEY, ticker=TK, side="YES", fills=f, evidence=row())
    rec = L.Recommendation("rec-1", o.first_fill_at - timedelta(minutes=5), TK, "YES", D("0.48"), D("0.5"))
    start = {TK: o.first_fill_at + timedelta(hours=1)}
    assert [k for k in L.link_all([rec], [o], [], start) if k.verified] == []            # exact ticker/time coincidence is not attribution
    unique = [k for k in L.link_all([rec], [o], [], start, window_seconds=3600) if k.tier == L.UNIQUE_WINDOW]
    assert unique and not any(k.verified for k in unique)                                # window match: sensitivity only
    tagged = L.Order(o.order_key, o.ticker, o.side, o.first_fill_at, o.fills, None, L.client_order_token("rec-1"))
    assert [k.verified for k in L.link_all([rec], [tagged], [], start)] == [True]       # explicit client_order_id is what verifies


def test_coverage_is_counts_only():
    good = {KEY: row()}
    c = EV.coverage([KEY, "kalshi:v1:" + "cd" * 32], good, {"accepted": 1})
    assert c["with_execution_evidence"] == 1 and c["evidence_share"] == 0.5 and c["all_taker"] == 1
    assert "kalshi:v1" not in json.dumps(c)

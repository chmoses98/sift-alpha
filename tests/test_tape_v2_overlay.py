"""Recovered pre-kickoff tape (nfl-edge-finder #246) as an input to execution research: provenance, truncation semantics, guard rails.
Research only: nothing here can place an order; a recovered print is an OBSERVED market print, never a fill of ours."""
import datetime as dt, json, os, tempfile, unittest

from sift_exec import nfl_data as D

ANCHOR = 1_768_791_807


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def pr(i, t, **kw):
    r = dict(trade_id=f"t{i}", created_time=iso(t), yes_price_dollars="0.4200", count_fp="3.00", taker_side="no", is_block_trade=False)
    r.update(kw)
    return r


def write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def meta(root, **kw):
    row = dict(ticker="TK", status="COMPLETE", anchor_kind="kickoff", anchor_ts=ANCHOR)
    row.update(kw)
    write(os.path.join(root, "tape_meta.jsonl"), [row])


class V2Overlay(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        D._META.clear()
        write(f"{self.d}/trades/S/TK.jsonl", [pr(i, ANCHOR + 100 - i) for i in range(10_000)])          # legacy: capped, includes post-kickoff

    def tick(self, src):
        t = D.Tick("TK", "S", {}, 1)
        t.raw_lines, t.tape_source, t.v2_status = src[4], src[5], src[6]
        return t

    def test_no_audit_row_keeps_legacy_and_its_cap(self):
        src = D.read_tape(self.d, "S", "TK")
        self.assertEqual((src[5], src[4], self.tick(src).capped), (D.SRC_LEGACY, 10_000, True))

    def test_complete_recovered_tape_replaces_legacy_and_is_not_capped(self):
        write(f"{self.d}/trades_v2/S/TK.jsonl", [pr(i, ANCHOR - 1 - i) for i in range(23_774)])
        meta(self.d)
        src = D.read_tape(self.d, "S", "TK"); t = self.tick(src)
        self.assertEqual((src[5], len(src[0]), t.capped), (D.SRC_V2, 23_774, False))
        self.assertTrue(max(src[0]) <= ANCHOR)

    def test_partial_recovered_tape_is_still_truncated(self):
        write(f"{self.d}/trades_v2/S/TK.jsonl", [pr(i, ANCHOR - 1 - i) for i in range(50_000)])
        meta(self.d, status="INCOMPLETE_RESUMABLE")
        t = self.tick(D.read_tape(self.d, "S", "TK"))
        self.assertEqual((t.tape_source, t.capped), (D.SRC_V2, True))          # 50,000 newest prints, older history still missing
        t.first_ts = ANCHOR - 5000
        self.assertTrue(D.tape_complete(t, ANCHOR - 100))                       # a window inside the retained span is observable
        self.assertFalse(D.tape_complete(t, ANCHOR - 10_000))                   # a window older than the oldest retained print is not

    def test_source_gap_is_not_complete(self):
        write(f"{self.d}/trades_v2/S/TK.jsonl", [pr(1, ANCHOR - 5)])
        meta(self.d, status="COMPLETE_WITH_SOURCE_GAP")
        self.assertTrue(self.tick(D.read_tape(self.d, "S", "TK")).capped)

    def test_close_time_anchored_or_unknown_anchor_is_never_used(self):
        write(f"{self.d}/trades_v2/S/TK.jsonl", [pr(1, ANCHOR - 5)])
        for kind in ("close_time", None, "garbage"):
            D._META.clear(); meta(self.d, anchor_kind=kind)
            self.assertEqual(D.read_tape(self.d, "S", "TK")[5], D.SRC_LEGACY)

    def test_empty_recovered_tape_never_overrides_legacy(self):
        write(f"{self.d}/trades_v2/S/TK.jsonl", [])
        meta(self.d)
        src = D.read_tape(self.d, "S", "TK")
        self.assertEqual((src[5], src[4], src[6]), (D.SRC_LEGACY, 10_000, "COMPLETE"))

    def test_post_anchor_dedupe_and_block_trades_are_dropped(self):
        write(f"{self.d}/trades_v2/S/TK.jsonl", [pr(1, ANCHOR - 5), pr(1, ANCHOR - 5), pr(2, ANCHOR + 5), pr(3, ANCHOR - 9, is_block_trade=True), pr(4, ANCHOR - 20)])
        meta(self.d)
        src = D.read_tape(self.d, "S", "TK")
        self.assertEqual(len(src[0]), 2)

    def test_source_counts(self):
        a = D.Tick("A", "S", {}, 1); b = D.Tick("B", "S", {}, 1, tape_source=D.SRC_V2, v2_status="COMPLETE"); c = D.Tick("C", "S", {}, 1, tape_source=D.SRC_V2, v2_status="INCOMPLETE_RESUMABLE")
        self.assertEqual(D.tape_source_counts([a, b, c]), {D.SRC_LEGACY: 1, D.SRC_V2: 2, D.SRC_NONE: 0, "truncated": 1})


class TapeModes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        D._META.clear()

    def test_missing_legacy_file_is_unknown_history_not_complete_and_empty(self):
        src = D.read_tape(self.d, "KXNFLTOTAL", "TK")
        t = D.Tick("TK", "KXNFLTOTAL", {}, 1, tape_source=src[5]); t.raw_lines = src[4]
        self.assertEqual((src[5], len(src[0]), t.capped), (D.SRC_NONE, 0, True))

    def test_empty_legacy_file_is_a_real_empty_tape(self):
        write(f"{self.d}/trades/S/TK.jsonl", [])
        src = D.read_tape(self.d, "S", "TK")
        t = D.Tick("TK", "S", {}, 1, tape_source=src[5]); t.raw_lines = src[4]
        self.assertEqual((src[5], t.capped), (D.SRC_LEGACY, False))

    def test_legacy_mode_ignores_an_audited_recovered_tape(self):
        write(f"{self.d}/trades/S/TK.jsonl", [pr(i, ANCHOR - 1 - i) for i in range(10_000)])
        write(f"{self.d}/trades_v2/S/TK.jsonl", [pr(i, ANCHOR - 1 - i) for i in range(30_000)])
        meta(self.d)
        self.assertEqual(D.read_tape(self.d, "S", "TK", "legacy")[5:5 + 1], (D.SRC_LEGACY,))
        self.assertEqual(len(D.read_tape(self.d, "S", "TK", "legacy")[0]), 10_000)
        self.assertEqual(len(D.read_tape(self.d, "S", "TK", "auto")[0]), 30_000)

    def test_candles_v2_fallback_for_contracts_without_a_legacy_candle_file(self):
        from sift_research import nfl25 as N
        os.makedirs(f"{self.d}/candles_v2/KXNFLTOTAL")
        json.dump({"h60": [{"end_period_ts": 1}], "m1": []}, open(f"{self.d}/candles_v2/KXNFLTOTAL/A.json", "w"))
        json.dump({"h60": None, "m1": None}, open(f"{self.d}/candles_v2/KXNFLTOTAL/B.json", "w"))
        self.assertEqual(N.load_candles("KXNFLTOTAL", "A", self.d)["h60"][0]["end_period_ts"], 1)
        self.assertIsNone(N.load_candles("KXNFLTOTAL", "B", self.d))
        os.makedirs(f"{self.d}/candles/KXNFLTOTAL"); json.dump({"h60": [{"end_period_ts": 9}], "m1": []}, open(f"{self.d}/candles/KXNFLTOTAL/A.json", "w"))
        self.assertEqual(N.load_candles("KXNFLTOTAL", "A", self.d)["h60"][0]["end_period_ts"], 9)       # legacy wins


if __name__ == "__main__":
    unittest.main()

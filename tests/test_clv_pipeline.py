import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from sift_clv import canonical as C, entry_conditions as E, executable as X, linkage as L, pipeline as P

T0 = datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
TK = "KXNFLGAME-26NOV01AAABBB-AAA"


def order(key="kalshi:v1:" + "a" * 64, coid=None, taker=True, price="0.50"):
    return L.Order(key, TK, "YES", T0 + timedelta(minutes=30), (C.Fill.of(price, 10, "0.17", taker),), None, coid)


def snap(sec_before_placement, placed):
    return E.Snapshot.of(TK, placed - timedelta(seconds=sec_before_placement), "0.48", "0.50")


def item(o, placed=None, snaps=(), close=True, result="yes"):
    cl = C.Quote.of(TK, "0.51", "0.53", START - timedelta(minutes=5)) if close else None
    return P.Item(o, placed, START, snaps, cl, None, result)


def rec(created):
    return L.Recommendation("rec-1", created, TK, "YES", D("0.48"), D("0.50"))


class PipelineTests(unittest.TestCase):
    placed = T0 + timedelta(minutes=29, seconds=58)

    def test_complete_chain_requires_explicit_link_fresh_entry_close_and_settlement(self):
        o = order(coid=L.client_order_token("rec-1"))
        rows = P.run([item(o, self.placed, [snap(10, self.placed)])], [rec(T0)])
        r = rows[0]
        self.assertEqual((r.link, r.entry, r.close, r.settlement), ("VERIFIED", E.ENTRY_OK, "CLOSE_OK", "SETTLED"))
        self.assertAlmostEqual(r.paid_vs_entry_ask_cents, 0.0)
        self.assertAlmostEqual(r.executable_purchase_clv_cents, 3.0)            # close ask 0.53 - fill 0.50
        self.assertAlmostEqual(r.net_per_contract_cents, (1 - 0.50 - 0.017) * 100)   # payout - vwap - fee once
        self.assertEqual(P.funnel(rows)["stages"]["complete_chain"], 1)

    def test_window_match_is_never_a_verified_link(self):
        o = order()
        rows = P.run([item(o, self.placed, [snap(10, self.placed)])], [rec(T0)], window_seconds=3600)
        self.assertEqual(rows[0].link, "UNVERIFIED_WINDOW")
        f = P.funnel(rows)["stages"]
        self.assertEqual(f.get("link_verified", 0), 0)
        self.assertEqual(f.get("complete_chain", 0), 0)

    def test_stale_or_future_snapshots_are_not_entry_books(self):
        o = order()
        stale = P.run([item(o, self.placed, [snap(600, self.placed)])], [])[0]
        self.assertEqual((stale.entry, stale.entry_is_fresh, stale.paid_vs_entry_ask_cents), (E.SNAPSHOT_STALE, False, None))
        future = P.run([item(o, self.placed, [E.Snapshot.of(TK, self.placed + timedelta(seconds=3), "0.48", "0.50")])], [])[0]
        self.assertEqual(future.entry, E.SNAPSHOT_AFTER_FILL)

    def test_missing_placement_time_blocks_the_entry_stage_instead_of_using_fill_time(self):
        o = order()
        r = P.run([item(o, None, [snap(1, T0 + timedelta(minutes=30))])], [])[0]
        self.assertEqual((r.entry, r.entry_is_fresh), (P.PLACEMENT_UNKNOWN, False))

    def test_each_stage_fails_independently(self):
        o = order()
        r = P.run([item(o, self.placed, [], close=False, result=None)], [])[0]
        self.assertEqual((r.entry, r.close, r.settlement), (E.NO_SNAPSHOT, C.NO_CLOSE, "UNSETTLED_OR_UNKNOWN"))
        self.assertEqual(r.link, "UNLINKED")
        f = P.funnel([r])
        self.assertEqual(f["stages"]["orders"], 1)
        self.assertEqual(f["stages"].get("complete_chain", 0), 0)

    def test_losing_side_settles_negative_and_fee_counted_once(self):
        o = order()
        r = P.run([item(o, self.placed, [snap(5, self.placed)], result="no")], [])[0]
        self.assertAlmostEqual(r.net_per_contract_cents, (0 - 0.50 - 0.017) * 100)

    def test_funnel_is_private(self):
        o = order()
        blob = str(P.funnel(P.run([item(o, self.placed, [snap(5, self.placed)])], [])))
        for secret in ("kalshi:v1", "KXNFLGAME", "0.50", "0.17"):
            self.assertNotIn(secret, blob)


if __name__ == "__main__":
    unittest.main()

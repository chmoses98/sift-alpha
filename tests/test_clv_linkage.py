import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dm

from sift_clv import canonical as C, linkage as L

START = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
T = "KXNFLSPREAD-26NOV01AAABBB-AAA3"


def rec(rid="r1", minutes_before=120, ticker=T, side="YES", bid="0.49", ask="0.51"):
    return L.Recommendation(rid, START - timedelta(minutes=minutes_before), ticker, side, Dm(bid), Dm(ask))


def order(key="o1", minutes_before=60, ticker=T, side="YES", cid=None, price="0.51", fee="1.75", n=100):
    return L.Order(key, ticker, side, START - timedelta(minutes=minutes_before),
                   (C.Fill.of(price, n, fee),), None, cid)


def att(rid="r1", key="o1"):
    return L.Attestation(rid, key, START - timedelta(minutes=30))


def run(recs, orders, atts=(), starts=None):
    return L.link_all(recs, orders, atts, {T: START} if starts is None else starts)


class Tiers(unittest.TestCase):
    def test_exact_client_order_id_verifies(self):
        links = run([rec()], [order(cid=L.client_order_token("r1"))])
        self.assertEqual([(l.tier, l.verified) for l in links], [(L.EXACT, True)])

    def test_owner_attestation_verifies(self):
        links = run([rec()], [order()], [att()])
        self.assertEqual([(l.tier, l.verified) for l in links], [(L.ATTESTED, True)])

    def test_same_ticker_and_time_alone_is_only_a_candidate_never_verified(self):
        links = run([rec()], [order()])
        self.assertEqual([(l.tier, l.verified) for l in links], [(L.CANDIDATE, False)])
        m = L.measure(links[0], rec(), order(), C.Quote.of(T, "0.49", "0.51", START - timedelta(minutes=2)), START)
        self.assertNotIn("clv", m)                     # no actual-execution numbers for an unverified link
        self.assertFalse(L.public_row(m)["verified"])

    def test_ambiguous_candidates_flagged(self):
        links = run([rec("r1"), rec("r2", 90)], [order()])
        self.assertTrue(all(not l.verified and l.quarantine == L.AMBIGUOUS_CANDIDATE for l in links))

    def test_token_for_unknown_recommendation_is_ignored(self):
        links = run([rec()], [order(cid="sift:does-not-exist")])
        self.assertTrue(all(not l.verified for l in links))


class Quarantine(unittest.TestCase):
    def test_wrong_side_or_ticker(self):
        self.assertEqual(run([rec(side="NO")], [order()], [att()])[0].quarantine, L.TICKER_SIDE_MISMATCH)
        r = rec(ticker="KXNFLSPREAD-26NOV01AAABBB-AAA6")      # different threshold = different contract
        self.assertEqual(run([r], [order()], [att()])[0].quarantine, L.TICKER_SIDE_MISMATCH)

    def test_recommendation_after_fill(self):
        self.assertEqual(run([rec(minutes_before=30)], [order(minutes_before=60)], [att()])[0].quarantine,
                         L.REC_NOT_BEFORE_FILL)

    def test_fill_after_start_is_not_pregame(self):
        self.assertEqual(run([rec()], [order(minutes_before=-5)], [att()])[0].quarantine, L.FILL_NOT_PREGAME)

    def test_missing_start(self):
        self.assertEqual(run([rec()], [order()], [att()], starts={})[0].quarantine, L.NO_START)

    def test_order_claimed_by_two_recommendations(self):
        links = run([rec("r1"), rec("r2", 90)], [order()], [att("r1"), att("r2")])
        self.assertTrue(links and all(l.quarantine == L.ORDER_CLAIMED_TWICE and not l.verified for l in links))

    def test_attestation_naming_unknown_ids(self):
        self.assertEqual(run([rec()], [order()], [att("nope")])[0].quarantine, L.UNKNOWN_REC)
        self.assertEqual(run([rec()], [order()], [att("r1", "nope")])[0].quarantine, L.UNKNOWN_ORDER)


class Measures(unittest.TestCase):
    def test_verified_link_yields_all_four_measures_fee_once(self):
        links = run([rec()], [order(price="0.50", fee="1.75")], [att()])
        close = C.Quote.of(T, "0.49", "0.51", START - timedelta(minutes=2))
        m = L.measure(links[0], rec(), order(price="0.50", fee="1.75"), close, START)
        r = m["clv"]
        self.assertEqual(r.selection_clv, 0)
        self.assertEqual(r.quoted_execution_clv, Dm("-0.01"))          # close mid .50 - rec ask .51
        self.assertEqual(r.actual_execution_clv, 0)
        self.assertEqual(r.fee_adjusted_difference, Dm("-0.0175"))
        self.assertEqual(r.fee_adjustment_count, 1)

    def test_no_side_link(self):
        r_, o_ = rec(side="NO", bid="0.49", ask="0.51"), order(side="NO", price="0.50", fee="1.75")
        links = run([r_], [o_], [att()])
        close = C.Quote.of(T, "0.44", "0.46", START - timedelta(minutes=2))   # NO mid 0.55 vs rec NO mid 0.50
        res = L.measure(links[0], r_, o_, close, START)["clv"]
        self.assertEqual(res.selection_clv, Dm("0.05"))
        self.assertEqual(res.actual_execution_clv, Dm("0.05"))

    def test_missing_close_keeps_link_but_withholds_measures(self):
        links = run([rec()], [order()], [att()])
        res = L.measure(links[0], rec(), order(), None, START)["clv"]
        self.assertEqual(res.status, C.NO_CLOSE)

    def test_public_row_has_no_private_fields(self):
        links = run([rec()], [order(price="0.50")], [att()])
        close = C.Quote.of(T, "0.49", "0.51", START - timedelta(minutes=2))
        row = L.public_row(L.measure(links[0], rec(), order(price="0.50"), close, START))
        blob = repr(row)
        for secret in (T, "r1", "o1", "0.50", "0.51"):
            self.assertNotIn(secret, blob)

    def test_coverage_counts(self):
        links = run([rec(), rec("r9", 100, ticker="X")], [order(), order("o2", ticker="Y")], [att()])
        cov = L.coverage(links, 2, 2)
        self.assertEqual(cov["verified_links"], 1)


if __name__ == "__main__":
    unittest.main()

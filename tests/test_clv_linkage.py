import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dm

from sift_clv import canonical as C, linkage as L

START = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
T = "KXNFLSPREAD-26NOV01AAABBB-AAA3"
WINDOW = 4 * 3600.0


def rec(rid="r1", minutes_before=120, ticker=T, side="YES", bid="0.49", ask="0.51"):
    return L.Recommendation(rid, START - timedelta(minutes=minutes_before), ticker, side, Dm(bid), Dm(ask))


def order(key="o1", minutes_before=60, ticker=T, side="YES", cid=None, price="0.51", fee="1.75", n=100):
    return L.Order(key, ticker, side, START - timedelta(minutes=minutes_before),
                   (C.Fill.of(price, n, fee),), None, cid)


def att(rid="r1", key="o1"):
    return L.Attestation(L.recommendation_ref(rid), key, START - timedelta(minutes=30))


def run(recs, orders, atts=(), starts=None, window=None):
    return L.link_all(recs, orders, atts, {T: START} if starts is None else starts, window_seconds=window)


class RouterAgreement(unittest.TestCase):
    def test_golden_vectors_match_the_router_cross_repository_agreement(self):
        # Asserted verbatim in kalshi-bet-router tests/test_execution_evidence.py (GOLDEN_DIGESTS).
        for kind, value, want in (("order", "ORDER-X", "70b17cbeb58152c522d8be2a9a30ac34"),
                                  ("fill", "FILL-X", "b34311e543285f452dd37dc618573dcb"),
                                  ("recommendation", "rec_0001", "34284d398be9830fd5ca1d76f8a673f1"),
                                  ("model_run", "run_0001", "6e039e855b3d236b125624c33b87427b")):
            self.assertEqual(L.id_digest(kind, value), want)
        with self.assertRaises(ValueError):
            L.id_digest("client_order_id", "x")

    def test_token_and_ledger_carry_digests_never_raw_recommendation_ids(self):
        self.assertEqual(L.client_order_token("rec_0001"), "sift:34284d398be9830fd5ca1d76f8a673f1")
        self.assertNotIn("rec_0001", L.client_order_token("rec_0001"))


class Tiers(unittest.TestCase):
    def test_exact_client_order_id_verifies(self):
        links = run([rec()], [order(cid=L.client_order_token("r1"))])
        self.assertEqual([(l.tier, l.verified, l.grade) for l in links], [(L.EXACT, True, "EXPLICIT")])

    def test_raw_recommendation_id_in_client_order_id_is_not_a_link(self):
        self.assertEqual(run([rec()], [order(cid="sift:r1")]), [])

    def test_owner_attestation_verifies(self):
        links = run([rec()], [order()], [att()])
        self.assertEqual([(l.tier, l.verified) for l in links], [(L.ATTESTED, True)])

    def test_without_an_explicit_window_ticker_and_time_produce_no_link_at_all(self):
        self.assertEqual(run([rec()], [order()]), [])
        with self.assertRaises(ValueError):
            run([rec()], [order()], window=0)

    def test_unique_window_match_is_never_verified(self):
        links = run([rec()], [order()], window=WINDOW)
        self.assertEqual([(l.tier, l.verified, l.grade) for l in links], [(L.UNIQUE_WINDOW, False, "UNIQUE_WINDOW")])
        m = L.measure(links[0], rec(), order(), C.Quote.of(T, "0.49", "0.51", START - timedelta(minutes=2)), START)
        self.assertNotIn("clv", m)

    def test_sensitivity_view_is_labelled_and_off_by_default(self):
        links = run([rec()], [order(price="0.50")], window=WINDOW)
        close = C.Quote.of(T, "0.49", "0.51", START - timedelta(minutes=2))
        m = L.measure(links[0], rec(), order(price="0.50"), close, START, include_unique_window=True)
        self.assertFalse(m["verified"])
        self.assertEqual(m["evidence_grade"], "UNIQUE_WINDOW")
        self.assertEqual(m["clv"].actual_execution_clv, 0)
        self.assertEqual(L.public_row(m)["evidence_grade"], "UNIQUE_WINDOW")

    def test_two_recommendations_in_the_window_are_ambiguous_not_nearest(self):
        links = run([rec("r1"), rec("r2", 90)], [order()], window=WINDOW)
        self.assertTrue(links and all(l.quarantine == L.AMBIGUOUS_CANDIDATE and l.grade == "UNLINKED" for l in links))

    def test_recommendation_outside_the_window_or_after_the_fill_does_not_match(self):
        self.assertEqual(run([rec(minutes_before=600)], [order()], window=3600.0), [])
        self.assertEqual(run([rec(minutes_before=30)], [order(minutes_before=60)], window=WINDOW), [])

    def test_explicit_claim_blocks_window_matching_for_that_order(self):
        links = run([rec("r1"), rec("r2", 90)], [order()], [att("r1")], window=WINDOW)
        self.assertEqual([(l.tier, l.verified) for l in links], [(L.ATTESTED, True)])


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
        r = L.measure(links[0], rec(), order(price="0.50", fee="1.75"), close, START)["clv"]
        self.assertEqual(r.selection_clv, 0)
        self.assertEqual(r.quoted_execution_clv, Dm("-0.01"))
        self.assertEqual(r.actual_execution_clv, 0)
        self.assertEqual(r.fee_adjusted_difference, Dm("-0.0175"))
        self.assertEqual(r.fee_adjustment_count, 1)

    def test_no_side_link(self):
        r_, o_ = rec(side="NO"), order(side="NO", price="0.50", fee="1.75")
        links = run([r_], [o_], [att()])
        close = C.Quote.of(T, "0.44", "0.46", START - timedelta(minutes=2))
        res = L.measure(links[0], r_, o_, close, START)["clv"]
        self.assertEqual(res.selection_clv, Dm("0.05"))
        self.assertEqual(res.actual_execution_clv, Dm("0.05"))

    def test_missing_close_keeps_link_but_withholds_measures(self):
        links = run([rec()], [order()], [att()])
        self.assertEqual(L.measure(links[0], rec(), order(), None, START)["clv"].status, C.NO_CLOSE)

    def test_public_row_has_no_private_fields_only_digests(self):
        links = run([rec()], [order(price="0.50")], [att()])
        close = C.Quote.of(T, "0.49", "0.51", START - timedelta(minutes=2))
        blob = repr(L.public_row(L.measure(links[0], rec(), order(price="0.50"), close, START)))
        for secret in (T, "'r1'", "o1", "0.50", "0.51", L.recommendation_ref("r1")):
            self.assertNotIn(secret, blob)

    def test_coverage_counts(self):
        links = run([rec(), rec("r9", 100, ticker="X")], [order(), order("o2", ticker="Y")], [att()], window=WINDOW)
        cov = L.coverage(links, 2, 2)
        self.assertEqual(cov["verified_links"], 1)


if __name__ == "__main__":
    unittest.main()

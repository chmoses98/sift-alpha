"""Matched before/after replay: identical-decision comparison, transition accounting and the out-of-sample claim gate.  Synthetic rows only."""
import os, sys, unittest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "exec_track"))
import recovery_replay as RR           # noqa: E402


def row(tk, side="YES", hz="24h", rule="AT_BID", q="FRONT", det=True, lo=0.0, hi=0.0, fills=(), fam="moneyline", game="g", week=14, win=0, filled=None):
    f = lo if filled is None else filled
    return dict(ticker=tk, side=side, horizon=hz, rule=rule, queue=q, determinate=det, filled_lo=lo, filled_hi=hi, fills=list(fills), family=fam, game=game, week=week,
                split={True: None}.get(False) or ("discovery" if week <= 6 else "validation" if week <= 12 else "holdout"),
                win=win, limit=40, bid=40, ask=42, close_bid=40, close_ask=42, filled=f)


class Compare(unittest.TestCase):
    def test_transitions_on_identical_ids_and_newly_evaluable_decisions(self):
        before = [row("A", det=False, lo=0, hi=10), row("B", det=True, lo=10, hi=10, fills=[(40, 10, "THROUGH")]), row("C", det=False, lo=0, hi=10, rule="MID")]
        after = [row("A", det=True, lo=0, hi=0), row("B", det=True, lo=10, hi=10, fills=[(40, 10, "THROUGH")]),
                 row("C", det=True, lo=4, hi=4, filled=4, rule="MID", fills=[(41, 4, "AT_LEVEL")])]
        c = RR.compare(before, after)
        self.assertEqual(c["identical_order_ids"], 3)
        self.assertEqual(c["transitions"], {"FILL_SUPPORTED->FILL_SUPPORTED": 1, "UNCERTAIN->FILL_SUPPORTED": 1, "UNCERTAIN->NO_FILL_SUPPORTED": 1})
        self.assertEqual((c["orders_uncertain_before"], c["orders_uncertain_after"], c["uncertainty_resolved_share"]), (2, 0, 1.0))
        self.assertEqual((c["decisions_newly_evaluable"], c["decisions_lost_evaluability"]), (2, 0))
        self.assertEqual(c["supported_fills_after_by_evidence"], {"through_only": 1, "needs_queue_to_drain": 1})

    def test_a_decision_that_loses_evaluability_is_reported(self):
        c = RR.compare([row("A", det=True)], [row("A", det=False, lo=0, hi=10)])
        self.assertEqual(c["decisions_lost_evaluability"], 1)

    def test_decision_sets_that_differ_are_surfaced_not_hidden(self):
        c = RR.compare([row("A"), row("B")], [row("A"), row("C")])
        self.assertEqual((c["identical_order_ids"], c["only_before"], c["only_after"]), (1, 1, 1))


def cohort(n_games, win, week0=1):
    rows = []
    for g in range(n_games):
        for k in range(2):
            rows.append(row(f"T{g}-{k}", game=f"G{g}", week=week0 + g % 18, win=win, lo=0.0, hi=0.0, filled=0.0))
    return rows


class ClaimGate(unittest.TestCase):
    def test_losing_cohort_is_not_positive_after_fees(self):
        rows = cohort(120, win=0)
        res = RR.holdout_protocol(rows, list(range(len(rows))))
        self.assertEqual(res["moneyline"]["status"], "NOT_POSITIVE_AFTER_FEES")

    def test_even_an_extreme_winning_cohort_needs_holdout_and_correction(self):
        rows = cohort(120, win=1)
        res = RR.holdout_protocol(rows, list(range(len(rows))))["moneyline"]
        self.assertEqual(res["status"], "POSITIVE_ABSOLUTE_NET_EV_OUT_OF_SAMPLE")          # synthetic: every contract wins, so the gate must open
        self.assertGreater(res["holdout"]["lo"], 0)

    def test_small_samples_never_claim_anything(self):
        rows = cohort(4, win=1)
        self.assertTrue(RR.holdout_protocol(rows, list(range(len(rows))))["moneyline"]["status"].startswith("INSUFFICIENT"))

    def test_selection_never_sees_the_holdout(self):
        rows = cohort(120, win=0)
        sel = [r for r in rows if r["split"] != "holdout"]
        for r in rows:
            if r["split"] == "holdout":
                r["win"] = 1                       # holdout outcomes differ from selection: the selection value must be unchanged
        a = RR.holdout_protocol(cohort(120, win=0), list(range(len(rows))))["moneyline"]["selection_mean_cents"]
        b = RR.holdout_protocol(rows, list(range(len(rows))))["moneyline"]["selection_mean_cents"]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()

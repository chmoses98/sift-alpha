"""Dashboard payload for tape-recovery completeness and replay validity: unmeasured is never zero, a claim needs the out-of-sample gate, no tickers leak."""
import os, re, sys, json, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "exec_track"))
import build_dashboard_summary as B      # noqa: E402


def cov(measured):
    t = dict(legacy_measured=measured, legacy_capped_exact=439 if measured else None, legacy_capped_recovered=5 if measured else None,
             legacy_capped_recovered_verified=5 if measured else None, legacy_capped_remaining=434 if measured else None,
             recovered_nonempty=21, recovered_candle_verified=21, recovered_prints=249742, empty_both_tiers=6, empty_historical_only=0, recovered_tape_no_kickoff_anchor=2956)
    return dict(totals=t, collection=dict(requests=100, retries=0, runs=3), series={
        "KXNFLGAME": dict(unique_contracts=666, settled=658, recovery_backlog_estimate=560, recovered_tape=dict(attempted=9, with_prints=5, candle_verified=3, capped_legacy_recovered=5, empty_both_tiers=4, prints=189628)),
        "KXNFLOTHER": dict(unique_contracts=5, settled=5, recovered_tape=dict(attempted=0))})


class Recovery(unittest.TestCase):
    def test_unmeasured_legacy_is_null_not_zero(self):
        r = B.tape_recovery(cov(False))
        self.assertEqual(r["legacy_basis"], "NOT_MEASURED")
        for k in ("legacy_capped_exact", "legacy_capped_recovered", "legacy_capped_recovered_verified", "legacy_capped_remaining"):
            self.assertIsNone(r[k], k)
        self.assertIsNone(r["by_family"][0]["capped_legacy_recovered"])

    def test_exact_baseline_adds_up(self):
        r = B.tape_recovery(cov(True))
        self.assertEqual((r["legacy_basis"], r["legacy_capped_exact"]), ("exact_lines_manifest", r["legacy_capped_recovered"] + r["legacy_capped_remaining"]))
        self.assertEqual([f["family"] for f in r["by_family"]], ["KXNFLGAME"])           # families with nothing attempted and no backlog are omitted

    def test_empty_means_cursor_exhausted_note_is_present(self):
        self.assertIn("not proof of a complete traded history", B.tape_recovery(cov(True))["note"])


class Validity(unittest.TestCase):
    def rp(self, status):
        return dict(label="RETROSPECTIVE_BACKFILL_REPLAY", fills="SIMULATED_FROM_TAPE", cohort=dict(tapes=21, games=4, families=["moneyline"]),
                    comparison=dict(decisions=33, decisions_determinate_before=8, decisions_determinate_after=33, decisions_newly_evaluable=25, orders_uncertain_before=320, orders_uncertain_after=0),
                    holdout_before={"moneyline": dict(status="INSUFFICIENT_HOLDOUT_SAMPLE")}, holdout_after={"moneyline": dict(status=status)})

    def test_no_claim_without_the_out_of_sample_gate(self):
        v = B.replay_validity(self.rp("NOT_POSITIVE_AFTER_FEES"))
        self.assertEqual(v["families_with_positive_absolute_net_ev"], []); self.assertEqual(v["absolute_net_ev"], "NOT DEMONSTRATED")
        self.assertIn("never merged into the prospective", v["separation"])

    def test_a_gate_pass_is_reported_but_flagged_for_verification(self):
        v = B.replay_validity(self.rp("POSITIVE_ABSOLUTE_NET_EV_OUT_OF_SAMPLE"))
        self.assertEqual(v["families_with_positive_absolute_net_ev"], ["moneyline"]); self.assertIn("verify before any use", v["absolute_net_ev"])

    def test_payload_has_no_tickers(self):
        txt = json.dumps(B.replay_validity(self.rp("NOT_POSITIVE_AFTER_FEES"))) + json.dumps(B.tape_recovery(cov(True)))
        self.assertFalse(re.search(r"KX[A-Z0-9]+-\d{2}[A-Z]{3}", txt))


if __name__ == "__main__":
    unittest.main()

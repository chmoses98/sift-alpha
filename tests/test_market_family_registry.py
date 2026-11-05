"""Adversarial offline tests for real-source market-family registry guardrails."""
import copy
import unittest

from alpha_engine.market_family_registry import (
    cfb_quarter_total, cfb_source, compose, row, timestamp,
)


def shard():
    event = "KXNCAAF1QTOTAL-26OCT31AUBMISS"
    rule = "If the teams collectively score more than 10.5 points in the 1st quarter, resolves Yes."
    secondary = ("Only points scored during the 1st quarter count. "
                 "If postponed but begins within 48 hours, remains open. "
                 "Otherwise resolves to a fair price.")
    markets = []
    for idx in (1, 2):
        markets.append({"market_ticker": event + "-" + str(idx),
                        "event_ticker": event, "family": "quarter_total",
                        "period": "first_quarter", "market_type": "binary",
                        "strike_type": "greater", "floor_strike": 10.5 + idx,
                        "rules_primary": rule, "rules_secondary": secondary})
    return {"artifact": "event_detail_shard",
            "event": {"event_ticker": event, "series_ticker": "KXNCAAF1QTOTAL"},
            "market_count": 2, "event_market_count": 2, "markets": markets}


def source():
    return {"repo": "chmoses98/cfb-edge-finder", "commit": "a" * 40,
            "sha": "b" * 40, "sha256": "c" * 64, "kind": "one_archived_event_shard"}


class FamilyRegistryTests(unittest.TestCase):
    def test_exact_first_quarter_rule_sample_and_unverified_clock(self):
        r = cfb_quarter_total(shard())
        self.assertEqual(r["observed"], 2)
        self.assertEqual(r["rule_text_status"], "ARCHIVED_LITERAL_UNVERIFIED_SETTLEMENT")
        self.assertIsNone(r["market_capture_at_utc"])
        self.assertIn("fair price", r["sample_rule_secondary"])

    def test_duplicate_contract_and_wrong_period_quarantined(self):
        for change in ("duplicate", "wrong_period", "wrong_family", "bad_strike",
                       "no_primary_rule", "no_postponement_rule", "bad_count"):
            x = shard()
            if change == "duplicate":
                x["markets"][1]["market_ticker"] = x["markets"][0]["market_ticker"]
            elif change == "wrong_period":
                x["markets"][1]["period"] = "full_game"
            elif change == "wrong_family":
                x["markets"][1]["family"] = "quarter_spread"
            elif change == "bad_strike":
                x["markets"][1]["floor_strike"] = True
            elif change == "no_primary_rule":
                x["markets"][0]["rules_primary"] = "unrelated result"
            elif change == "no_postponement_rule":
                x["markets"][0]["rules_secondary"] = "No fair price"
            else:
                x["market_count"] = 3
            with self.subTest(change=change), self.assertRaises(ValueError):
                cfb_quarter_total(x)

    def test_no_denominator_inflation_or_independent_validity_claim(self):
        s = source()
        for bad in ({"observed": 1, "evaluated": 2},
                    {"observed": 1, "settled": 2},
                    {"observed": True}, {"observed": -1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                row("CFB", "quarter_total", s, **bad)
        r = row("CFB", "quarter_total", s, observed=2, evaluated=0)
        self.assertIsNone(r["independently_valid_evaluations"])
        self.assertEqual(r["point_in_time_pregame_eligibility"], "UNVERIFIED")
        self.assertEqual(r["source_provider_independence"], "NOT_INDEPENDENTLY_VERIFIED")

    def test_future_or_ambiguous_timestamp_rejected(self):
        for bad in ("2026-11-01", "2026-11-01T10:00:00",
                    "2026-11-01T10:00:00-05:00", "nonsense"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                timestamp(bad)

    def test_pinned_event_source_hash_cannot_be_forged(self):
        with self.assertRaises(ValueError):
            cfb_source(lambda: b'{"artifact":"event_detail_shard"}')

    def test_missing_sport_metadata_never_certifies_all_eight(self):
        with self.assertRaises(ValueError):
            compose({}, {}, shard(), "2026-11-01T23:59:59Z")

    def test_rule_text_not_promoted_to_settlement_join(self):
        x = row("CFB", "quarter_total", source(), observed=2,
                rule_status="ARCHIVED_LITERAL_UNVERIFIED_SETTLEMENT",
                projected_outcome="first_quarter_combined_points_greater_than_contract_strike",
                candidate_inputs=[{"name": "first_quarter_pace", "evidence": "HYPOTHESIS"}])
        self.assertEqual(x["settlement_outcome_join"], "NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(x["candidate_inputs"][0]["evidence"], "HYPOTHESIS")
        self.assertIsNone(x["source_reported_model_evaluated"])


if __name__ == "__main__":
    unittest.main()

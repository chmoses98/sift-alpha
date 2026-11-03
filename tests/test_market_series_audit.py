"""Adversarial tests: real manifest, synthetic tape, no invented model authority."""
import copy
import json
from pathlib import Path
import unittest

from alpha_engine.market_series_audit import audit_series, combine


MANIFEST = json.loads(Path("research/verified_chain_pilot.json").read_text())


def fixture():
    sports, rows = {}, []
    for sport, chain in MANIFEST["chains"].items():
        src = chain["checkpoint"]
        t = "2026-10-25T00:10:00Z"
        sports[sport] = {
            "base_at": "2026-10-25T00:00:00Z",
            "last_verified_at": "2026-10-25T00:30:00Z",
            "source_files": [
                {"path": s["path"], "blob_sha1": s["sha"]}
                for s in [src, *chain["deltas"]]
            ],
        }
        rows.append({
            "sport": sport, "ticker": sport + "-MARKET-1",
            "observed_at_utc": t,
            "source_path": src["path"], "source_blob_sha1": src["sha"],
            "source_kind": "CHECKPOINT", "lifecycle": "PRESENT",
            "direct_quotes_dollars": {"yes_bid": "0.45", "yes_ask": "0.49",
                                       "no_bid": "0.51", "no_ask": "0.55"},
            "direct_quote_changed_since_previous_ticker_record": None,
            "contract_terms_as_observed": {
                "series_ticker": "KX" + sport + "TOTAL",
                "event_ticker": "KX" + sport + "TOTAL-EVENT",
                "strike_type": "greater", "floor_strike": 5.5,
            },
        })
    return {"authority": "RESEARCH_ONLY", "full_day_or_season": False,
            "sports": sports}, rows


def audited(tape, rows):
    # In production the real verified_tape_ticks performs full hash/clock/
    # board completeness verification. The fake isolates this module's checks.
    return audit_series(tape, rows, MANIFEST, verify=lambda *_: {"verified": True})


class MarketSeriesAuditTests(unittest.TestCase):
    def test_literal_series_and_denominator_without_model_claim(self):
        tape, rows = fixture()
        result = audited(tape, rows)
        self.assertEqual(set(result), {"NBA", "NHL"})
        for sport in result:
            x = result[sport]
            self.assertEqual((x["n_unique_tickers_in_prefix"],
                              x["n_tickers_with_literal_series"],
                              x["n_tickers_quarantined"], x["n_literal_series"]),
                             (1, 1, 0, 1))
            record = x["series_rows"][0]
            self.assertEqual(record["market_collection_status"], "COLLECTED_VALID")
            self.assertEqual(record["model_usage_status"], "UNKNOWN")
            self.assertEqual(record["exact_settlement_rule_status"],
                             "UNKNOWN_NO_INDEPENDENT_CONTRACT_RULES")
            self.assertIsNone(record["independently_valid_evaluations"])

    def test_missing_or_conflicting_series_quarantined_not_fabricated(self):
        for bad in ("missing", "conflict"):
            tape, rows = fixture()
            if bad == "missing":
                del rows[0]["contract_terms_as_observed"]["series_ticker"]
            else:
                changed = copy.deepcopy(rows[0])
                changed["observed_at_utc"] = "2026-10-25T00:20:00Z"
                changed["source_kind"] = "DELTA_TOUCHED"
                changed["direct_quote_changed_since_previous_ticker_record"] = False
                changed["contract_terms_as_observed"]["series_ticker"] = "KXDIFFERENT"
                changed["source_path"] = MANIFEST["chains"]["NBA"]["deltas"][0]["path"]
                changed["source_blob_sha1"] = MANIFEST["chains"]["NBA"]["deltas"][0]["sha"]
                rows.append(changed)
            x = audited(tape, rows)["NBA"]
            self.assertEqual(x["n_tickers_quarantined"], 1)
            self.assertEqual(x["n_literal_series"], 0)

    def test_duplicate_tick_and_unpinned_path_fail_closed(self):
        for bad in ("duplicate", "path", "future", "bad_price"):
            tape, rows = fixture()
            if bad == "duplicate":
                rows.append(copy.deepcopy(rows[0]))
            elif bad == "path":
                rows[0]["source_blob_sha1"] = "f" * 40
            elif bad == "future":
                rows[0]["observed_at_utc"] = "2026-10-25T00:31:00Z"
            else:
                rows[0]["direct_quotes_dollars"]["yes_bid"] = "1.5"
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audited(tape, rows)

    def test_tampered_source_file_manifest_rejected(self):
        tape, rows = fixture()
        tape["sports"]["NBA"]["source_files"][0]["blob_sha1"] = "0" * 40
        with self.assertRaises(ValueError):
            audited(tape, rows)

    def test_dashboard_merge_retains_original_denominators_and_unknowns(self):
        tape, rows = fixture()
        source = {
            "authority": "RESEARCH_ONLY_NOT_LIVE_COLLECTION",
            "all_market_families_certified": False,
            "family_rows": [{"sport": "MLB", "family": "hitter_hits",
                             "observed_denominator": 23295,
                             "source_reported_model_evaluated": 0}],
            "missing_input_queue": [{"sport": "MLB", "family": "hitter_hits"}],
            "live_capture_running": False,
        }
        combined = combine(source, audited(tape, rows))
        self.assertEqual(source["family_rows"][0]["observed_denominator"], 23295)
        self.assertEqual(combined["family_rows"][0]["observed_denominator"], 23295)
        self.assertEqual(combined["family_rows"][0]["source_reported_model_evaluated"], 0)
        self.assertEqual(len(combined["family_rows"]), 3)
        self.assertFalse(combined["all_market_families_certified"])
        self.assertFalse(combined["live_capture_running"])
        self.assertEqual(combined["discovered_literal_series_count"], 2)

    def test_rejects_unverified_research_authority(self):
        tape, rows = fixture()
        tape["full_day_or_season"] = True
        with self.assertRaises(ValueError):
            audited(tape, rows)


if __name__ == "__main__":
    unittest.main()

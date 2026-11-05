"""Adversarial contract identity and historical lookahead checks."""
import copy
import unittest
from alpha_engine.contract_lineage import audit_contract_lineage, lineage_asof

def fixture():
    base, end = "2026-10-25T00:00:00Z", "2026-10-25T00:05:00Z"
    report = {"authority": "RESEARCH_ONLY", "full_day_or_season": False, "sports": {}}
    rows = []
    for sport in ("NBA", "NHL"):
        ticker = f"KX{sport}GAME-26OCT25-AB"
        paths, hashes = [f"{sport}/checkpoint", f"{sport}/delta"], ["a"*40, "b"*40]
        report["sports"][sport] = {
            "base_at": base, "last_verified_at": end,
            "n_sparse_tape_rows": 2, "n_verified_delta_ticks": 1,
            "source_files": [{"path": p, "blob_sha1": h} for p, h in zip(paths, hashes)]}
        terms = {"event_ticker": f"KX{sport}GAME-26OCT25",
                 "series_ticker": f"KX{sport}GAME", "title": "Winner"}
        for i, at in enumerate((base, end)):
            rows.append({
                "sport": sport, "ticker": ticker, "observed_at_utc": at,
                "source_path": paths[i], "source_blob_sha1": hashes[i],
                "source_kind": "CHECKPOINT" if i == 0 else "DELTA_TOUCHED",
                "lifecycle": "PRESENT", "contract_terms_as_observed": copy.deepcopy(terms),
                "direct_quotes_dollars": {"yes_bid": "0.43" if i == 0 else "0.44",
                                          "yes_ask": "0.46", "no_bid": None, "no_ask": None},
                "direct_quote_changed_since_previous_ticker_record": None if i == 0 else True,
                "pregame_status": "UNVERIFIED", "quote_execution_authority": "NONE"})
    return report, rows

class ContractLineageTests(unittest.TestCase):
    def test_exact_literal_identity_never_game_or_settlement(self):
        report, rows = fixture()
        out = audit_contract_lineage(report, rows)
        self.assertEqual(set(out["sports"]), {"NBA", "NHL"})
        self.assertEqual(out["sports"]["NBA"]["n_literal_identity_observed_at_end"], 1)
        self.assertEqual(out["sports"]["NBA"]["contract_to_physical_game"], "NOT_ESTABLISHED")
        self.assertEqual(out["sports"]["NHL"]["exchange_settlement"], "NOT_VERIFIED")

    def test_future_conflict_does_not_poison_past(self):
        report, rows = fixture()
        rows[1]["contract_terms_as_observed"]["event_ticker"] = "DIFFERENT"
        out = audit_contract_lineage(report, rows)
        self.assertEqual(out["sports"]["NBA"]["n_literal_identity_observed_at_base"], 1)
        self.assertEqual(out["sports"]["NBA"]["n_term_conflict_tickers"], 1)
        self.assertEqual(out["sports"]["NBA"]["n_literal_identity_observed_at_end"], 0)
        self.assertEqual(lineage_asof(rows[:2], report["sports"]["NBA"]["base_at"])["status"],
                         "LITERAL_CONTRACT_IDENTITY_OBSERVED")
        self.assertEqual(lineage_asof(rows[:2], report["sports"]["NBA"]["last_verified_at"])["status"],
                         "QUARANTINED_TERM_CONFLICT")

    def test_strike_type_changes_are_not_silently_coerced(self):
        report, rows = fixture()
        rows[0]["contract_terms_as_observed"]["floor_strike"] = 10
        rows[1]["contract_terms_as_observed"]["floor_strike"] = "10"
        self.assertEqual(audit_contract_lineage(report, rows)["sports"]["NBA"]["n_term_conflict_tickers"], 1)

    def test_descriptive_title_edit_not_semantic_mutation(self):
        report, rows = fixture()
        rows[1]["contract_terms_as_observed"]["title"] = "Updated winner"
        out = audit_contract_lineage(report, rows)["sports"]["NBA"]
        self.assertEqual(out["n_descriptive_text_changed"], 1)
        self.assertEqual(out["n_term_conflict_tickers"], 0)

    def test_missing_event_is_not_inferred_from_ticker(self):
        report, rows = fixture()
        for row in rows[:2]:
            row["contract_terms_as_observed"].pop("event_ticker")
        self.assertEqual(audit_contract_lineage(report, rows)["sports"]["NBA"]["n_unresolved_identity_tickers"], 1)

    def test_source_result_not_exchange_settlement(self):
        report, rows = fixture()
        rows[1]["contract_terms_as_observed"]["result"] = "yes"
        out = audit_contract_lineage(report, rows)["sports"]["NBA"]
        self.assertEqual(out["n_with_literal_result_field"], 1)
        self.assertEqual(out["exchange_settlement"], "NOT_VERIFIED")

    def test_duplicate_tick_rejected(self):
        report, rows = fixture()
        report["sports"]["NBA"]["n_sparse_tape_rows"] += 1
        rows.append(copy.deepcopy(rows[1]))
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)

    def test_hash_tamper_and_missing_rows_fail(self):
        report, rows = fixture()
        rows[1]["source_blob_sha1"] = "f"*40
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)
        report, rows = fixture()
        rows.pop()
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)

    def test_cross_sport_ticker_collision_quarantined(self):
        report, rows = fixture()
        for row in rows[2:]:
            row["ticker"] = rows[0]["ticker"]
        out = audit_contract_lineage(report, rows)
        self.assertEqual(out["n_cross_sport_literal_ticker_collisions"], 1)
        self.assertEqual(out["sports"]["NBA"]["n_literal_identity_observed_at_end"], 0)

    def test_removal_cannot_retain_quotes(self):
        report, rows = fixture()
        rows[1]["lifecycle"] = "REMOVED"
        rows[1]["contract_terms_as_observed"] = None
        rows[1]["direct_quotes_dollars"] = None
        self.assertEqual(audit_contract_lineage(report, rows)["sports"]["NBA"]["n_removed_at_end"], 1)
        rows[1]["direct_quotes_dollars"] = {"yes_bid": "0.9"}
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)

    def test_invalid_price_or_inferred_side_rejected(self):
        report, rows = fixture()
        rows[1]["direct_quotes_dollars"]["no_ask"] = "1.01"
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)
        report, rows = fixture()
        rows[1]["direct_quotes_dollars"].pop("no_bid")
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)

    def test_future_tick_not_eligible(self):
        report, rows = fixture()
        rows[0]["observed_at_utc"] = "2026-10-26T00:00:00Z"
        with self.assertRaises(ValueError):
            audit_contract_lineage(report, rows)

if __name__ == "__main__":
    unittest.main()

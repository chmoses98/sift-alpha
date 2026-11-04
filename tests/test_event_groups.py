"""Adversarial literal event grouping: no future leakage or invented games."""
import copy
import unittest
from alpha_engine.event_groups import audit_event_groups

BASE, END = "2026-10-25T00:00:00Z", "2026-10-25T00:05:00Z"

def fixture():
    report = {"authority": "RESEARCH_ONLY", "full_day_or_season": False, "sports": {}}
    rows = []
    for sport in ("NBA", "NHL"):
        paths = [f"{sport}/checkpoint", f"{sport}/delta"]
        hashes = ["a"*40, "b"*40]
        report["sports"][sport] = {
            "base_at": BASE, "last_verified_at": END,
            "n_sparse_tape_rows": 4, "n_verified_delta_ticks": 1,
            "source_files": [{"path": p, "blob_sha1": h} for p,h in zip(paths, hashes)],
        }
        for i, at in enumerate((BASE, END)):
            for name in ("A", "B"):
                rows.append({
                    "sport": sport, "ticker": f"KX{sport}GAME-{name}",
                    "observed_at_utc": at, "source_path": paths[i],
                    "source_blob_sha1": hashes[i],
                    "source_kind": "CHECKPOINT" if i == 0 else "DELTA_TOUCHED",
                    "lifecycle": "PRESENT",
                    "contract_terms_as_observed": {
                        "event_ticker": f"KX{sport}GAME-E1",
                        "series_ticker": f"KX{sport}GAME",
                        "title": "Winner"},
                    "direct_quotes_dollars": {
                        "yes_bid": "0.42", "yes_ask": "0.44",
                        "no_bid": None, "no_ask": None},
                    "direct_quote_changed_since_previous_ticker_record":
                        None if i == 0 else False,
                    "pregame_status": "UNVERIFIED",
                    "quote_execution_authority": "NONE",
                })
    return report, rows

class EventGroupsTests(unittest.TestCase):
    def test_literal_group_ledger_and_authority(self):
        report, rows = fixture()
        out, groups = audit_event_groups(report, rows)
        self.assertEqual(out["n_group_rows"], 4)
        self.assertEqual({x["sport"] for x in groups}, {"NBA","NHL"})
        for x in groups:
            self.assertEqual(x["n_active_contract_tickers"], 2)
            self.assertEqual(x["group_status"], "LITERAL_EVENT_GROUP_OBSERVED")
            self.assertEqual(x["contract_to_physical_game"], "NOT_ESTABLISHED")
            self.assertEqual(x["pregame_or_execution_authority"], "NONE")
        self.assertEqual(out["sports"]["NBA"]["snapshots"][0]["n_multi_contract_events"], 1)

    def test_future_series_conflict_never_poison_earlier_group(self):
        report, rows = fixture()
        rows[3]["contract_terms_as_observed"]["series_ticker"] = "OTHER"
        out, groups = audit_event_groups(report, rows)
        nba = [x for x in groups if x["sport"] == "NBA"]
        self.assertEqual(nba[0]["group_status"], "LITERAL_EVENT_GROUP_OBSERVED")
        self.assertEqual(nba[1]["n_active_contract_tickers"], 1)
        self.assertEqual(out["sports"]["NBA"]["snapshots"][-1][
            "n_unresolved_or_conflicted_active_contracts"], 1)

    def test_multiple_series_same_event_quarantined(self):
        report, rows = fixture()
        for i in (1, 3):
            rows[i]["contract_terms_as_observed"]["series_ticker"] = "KXOTHER"
        out, groups = audit_event_groups(report, rows)
        self.assertEqual(groups[0]["group_status"], "QUARANTINED_EVENT_MULTIPLE_LITERAL_SERIES")
        self.assertIsNone(groups[0]["series_ticker"])
        self.assertEqual(out["sports"]["NBA"]["snapshots"][0][
            "n_quarantined_multi_series_events"], 1)

    def test_future_cross_sport_collision_only_quarantines_when_observed(self):
        report, rows = fixture()
        added = copy.deepcopy(rows[7])
        added["ticker"] = "KXNHLGAME-C"
        added["contract_terms_as_observed"]["event_ticker"] = "KXNBAGAME-E1"
        rows.append(added)
        report["sports"]["NHL"]["n_sparse_tape_rows"] += 1
        out, groups = audit_event_groups(report, rows)
        nba = [x for x in groups if x["sport"] == "NBA"]
        self.assertEqual(nba[0]["group_status"], "LITERAL_EVENT_GROUP_OBSERVED")
        self.assertEqual(nba[1]["group_status"], "QUARANTINED_EVENT_CROSS_SPORT_COLLISION")

    def test_removed_contract_not_counted_active(self):
        report, rows = fixture()
        rows[3]["lifecycle"] = "REMOVED"
        rows[3]["contract_terms_as_observed"] = None
        rows[3]["direct_quotes_dollars"] = None
        out, groups = audit_event_groups(report, rows)
        self.assertEqual(groups[1]["n_active_contract_tickers"], 1)
        self.assertEqual(out["sports"]["NBA"]["snapshots"][-1]["n_removed_contracts"], 1)

    def test_missing_event_is_never_inferred_from_ticker(self):
        report, rows = fixture()
        for i in (0, 2):
            rows[i]["contract_terms_as_observed"].pop("event_ticker")
        out, groups = audit_event_groups(report, rows)
        self.assertEqual(groups[0]["n_active_contract_tickers"], 1)
        self.assertEqual(out["sports"]["NBA"]["snapshots"][-1][
            "n_unresolved_or_conflicted_active_contracts"], 1)

    def test_duplicate_and_source_tamper_fail_closed(self):
        report, rows = fixture()
        rows[0]["source_blob_sha1"] = "f"*40
        with self.assertRaises(ValueError):
            audit_event_groups(report, rows)
        report, rows = fixture()
        rows.append(copy.deepcopy(rows[0]))
        report["sports"]["NBA"]["n_sparse_tape_rows"] += 1
        with self.assertRaises(ValueError):
            audit_event_groups(report, rows)

    def test_unknown_board_time_and_missing_sport_rejected(self):
        report, rows = fixture()
        report["sports"]["NBA"]["last_verified_at"] = "2026-10-25T00:06:00Z"
        with self.assertRaises(ValueError):
            audit_event_groups(report, rows)
        report, rows = fixture()
        rows = [r for r in rows if r["sport"] == "NBA"]
        with self.assertRaises(ValueError):
            audit_event_groups(report, rows)

if __name__ == "__main__":
    unittest.main()

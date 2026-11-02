import json, math, unittest
from pathlib import Path

A = Path(__file__).resolve().parents[1] / "research" / "audit"
J = lambda p: json.load(open(A / p))


class SweepResults(unittest.TestCase):
    def test_every_queued_series_is_complete_without_errors(self):
        for q, n in (("mlb", 215), ("soccer", 48)):
            d = J(f"sweep_results/{q}.json"); rows = d["series"]
            self.assertEqual(len(rows), n)
            self.assertEqual([r["s"] for r in rows], json.load(open(A.parents[1] / "kalshi_sweep/queues" / ("mlb_queue.json" if q == "mlb" else "soccer_ambiguous_queue.json")))["series"])
            for r in rows:
                for s in ("open", "unopened", "closed", "settled"):
                    self.assertTrue(r[s]["complete"], (q, r["s"], s)); self.assertIsNone(r[s]["error"])

    def test_resumed_runs_neither_duplicate_nor_lose_pages(self):
        for q in ("mlb", "soccer"):
            d = J(f"sweep_results/{q}.json")
            minimal = sum(max(1, math.ceil(r[s]["markets"] / 1000)) for r in d["series"] for s in ("open", "unopened", "closed", "settled"))
            self.assertEqual(d["meta"]["requests_total"], minimal, q)       # one request per page, none repeated, none skipped
            self.assertNotIn("rate_limited", d["meta"]); self.assertNotIn("errors", d["meta"])

    def test_classification_is_validated_against_exchange_titles(self):
        v = J("sweep_results/validated_families.json")["MLB"]
        self.assertEqual((v["unmapped_with_markets"], v["title_mismatch"]), ([], []))
        for f in v["families"].values():
            for s in f["series"]:
                self.assertTrue(s["title_validated"] and s["title"], s["ticker"])
        e = v["families"]["non_baseball_esports"]["series"][0]
        self.assertEqual(e["ticker"], "KXMLBBGAME"); self.assertIn("Mobile Legends", e["rules_sample"])      # resolved from the exchange's own settlement rules: MLBB esports, not baseball

    def test_soccer_ambiguity_resolved_by_title_not_ticker(self):
        s = J("sweep_results/summary.json")["soccer"]
        self.assertEqual(sum(s["classes"].values()), 48)
        self.assertEqual(s["not_soccer_by_title"], ["KXSORONDO"])
        self.assertLess(s["predicted_and_title_confirmed"], s["grammar_or_name_predicted_soccer"])    # grammar over-predicted: 20 empty series

    def test_inventory_gained_swept_families(self):
        fams = {f["native_family"]: f for f in J("inventory/MLB.json")["families"]}
        for n in ("hitter_home_runs", "pitcher_hits_allowed", "pitcher_earned_runs", "pitcher_walks_allowed", "game_spread", "first5_total", "extra_innings", "first_inning_runs"):
            self.assertTrue(fams[n]["new_in_sweep"], n); self.assertGreater(fams[n]["exchange_history"]["settled"], 0)
        self.assertEqual(fams["SWEPT_EMPTY_SERIES"]["observed"]["state"], "EMPTY_ALL_STATUSES_AT_SWEEP")
        self.assertNotIn("SERIES_LISTED_NOT_QUERIED", fams)


    def test_every_new_mlb_family_has_market_specific_inputs_in_the_registry(self):
        reg = J("input_registry.json")["sports"]["MLB"]; fams = {f["native_family"]: f for f in J("inventory/MLB.json")["families"]}
        new = [n for n, f in fams.items() if f.get("new_in_sweep")]
        self.assertGreaterEqual(len(new), 26)
        for n in new:
            self.assertIn(fams[n]["id"], reg["families"], n)
            self.assertTrue([i for i in reg["families"][fams[n]["id"]]["inputs"] if i.startswith("mlb.")], n)
        specific = {"hitter_home_runs": "mlb.hr_environment", "pitcher_hits_allowed": "mlb.contact_defense", "pitcher_earned_runs": "mlb.leash", "pitcher_walks_allowed": "mlb.plate_discipline",
                    "first_inning_runs": "mlb.first_inning_splits", "game_delay": "mlb.delay_risk", "extra_innings": "mlb.extras_prob", "postseason_series": "mlb.series_context",
                    "season_leaders": "mlb.leader_race", "awards": "mlb.award_voting", "transactions": "mlb.roster_moves"}
        for n, i in specific.items():
            self.assertEqual(reg["families"][fams[n]["id"]]["inputs"].get(i), "E", (n, i))


if __name__ == "__main__":
    unittest.main()

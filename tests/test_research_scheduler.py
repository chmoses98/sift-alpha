"""Hostile tests: no invented market availability or eight-sport certification."""
import unittest
from alpha_engine.research_scheduler import plan, SPORTS

NOW = "2026-11-01T22:00:00Z"
SHA = "a"*64
OTHER = "b"*64


def obs(sport="NFL", family="game_total", count=20,
        captured="2026-11-01T21:45:00Z", start="2026-11-01T23:00:00Z"):
    row = {"sport": sport, "family": family, "observed_contracts": count,
           "captured_at_utc": captured, "source_sha256": SHA}
    if start is not None:
        row.update(scheduled_start_utc=start, start_source_sha256=OTHER)
    return row


def defect(sport="NFL", family="game_total", ident="d", ready=True):
    return {"id": ident, "sport": sport, "family": family, "severity": 5,
            "affected_rows": 25, "denominator": 100,
            "evidence_ready": ready, "estimated_minutes": 20,
            "source_sha256": SHA}


class SchedulerTests(unittest.TestCase):
    def test_minimum_qa_every_sport_without_market_invention(self):
        p = plan(NOW, [], [])
        self.assertEqual({x["sport"] for x in p["tasks"]}, set(SPORTS))
        self.assertEqual(p["observed_market_families"], 0)
        self.assertFalse(p["capture_daemon_running"])
        self.assertEqual(p["authority"], "RESEARCH_ONLY_NOT_LIVE_COLLECTION")

    def test_capture_precedes_repair_but_does_not_certify_pregame(self):
        p = plan(NOW, [obs()], [defect()])
        self.assertEqual(p["next"]["lane"], "PIT_CAPTURE")
        self.assertFalse(p["actual_game_starts_or_pregame_eligibility_verified"])
        self.assertEqual(len([x for x in p["tasks"] if x["lane"] == "COLLECTION_QA"]), 8)

    def test_no_market_evidence_routes_historical_case_not_live(self):
        p = plan(NOW, [], [defect("MLB")])
        self.assertEqual(p["next"]["lane"], "ARCHIVAL_REPAIR")
        self.assertEqual(p["observed_contracts_by_sport"]["MLB"], 0)

    def test_soft_prior_never_hard_quota(self):
        p = plan(NOW, [obs("MLB", count=500, start=None),
                       obs("NFL", count=1, start=None)],
                 [defect("MLB", ident="m"), defect("NFL", ident="n")])
        self.assertEqual(p["next"]["id"], "REPAIR:m")

    def test_stale_missing_or_far_future_start_cannot_trigger_capture(self):
        for x in (obs(captured="2026-11-01T15:00:00Z"),
                  obs(start=None), obs(start="2026-11-02T04:00:00Z"),
                  obs(count=0)):
            with self.subTest(x=x):
                self.assertNotEqual(plan(NOW, [x], [defect()])["next"]["lane"], "PIT_CAPTURE")

    def test_tampered_clocks_hashes_denominators_and_duplicates(self):
        for x in ({**obs(), "captured_at_utc": "2026-11-02T00:00:00Z"},
                  {**obs(), "source_sha256": "bad"},
                  {**obs(), "start_source_sha256": None},
                  {**obs(), "observed_contracts": True}):
            with self.subTest(x=x), self.assertRaises(ValueError):
                plan(NOW, [x], [])
        for markets, defects, limit in (
            ([obs(), obs()], [], 32),
            ([], [{**defect(), "affected_rows": 101}], 32),
            ([], [defect(), defect()], 32),
            ([], [], 7),
        ):
            with self.assertRaises(ValueError):
                plan(NOW, markets, defects, limit=limit)

    def test_deterministic(self):
        self.assertEqual(plan(NOW, [obs()], [defect()]),
                         plan(NOW, [obs()], [defect()]))


if __name__ == "__main__":
    unittest.main()

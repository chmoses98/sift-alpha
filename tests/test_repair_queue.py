import unittest
from alpha_engine.repair_queue import choose_next

class RepairQueueTests(unittest.TestCase):
    def test_blocked_mlb_advances_to_next_real_case(self):
        cases=[{"id":"mlb-historical-hits"},{"id":"mlb-future-forecast-publication"}]
        r=choose_next(cases,{"mlb-historical-hits":[{"status":"BLOCKED"}]})
        self.assertEqual(r["next_id"],"mlb-future-forecast-publication")
    def test_bounded_failures(self):
        cases=[{"id":"a"},{"id":"b"}]
        self.assertEqual(choose_next(cases,{"a":[{"status":"FAILED"},{"status":"FAILED"}]})["next_id"],"b")
    def test_no_fake_success(self):
        self.assertEqual(choose_next([{"id":"a"}],{"a":[{"status":"REPAIRED_VERIFIED"}]})["status"],"NO_ACTIONABLE_CASE")
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError): choose_next([{"id":"a"},{"id":"a"}],{})
    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError): choose_next([{"id":"a"}],{"a":[{"status":"SUCCESS"}]})
if __name__=="__main__": unittest.main()

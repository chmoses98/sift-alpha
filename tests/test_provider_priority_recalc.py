"""Provider priority recalculation (RESEARCH_ONLY): byte-for-byte reproducibility of priority_recalc.json and the
need-level / PIT / build-readiness rules introduced in revision 2. Read-only: imports the module, never writes."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "research/provider_licensing"
spec = importlib.util.spec_from_file_location("priority_recalc", DIR / "priority_recalc.py")
PR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PR)
RES = PR.res


class Reproducible(unittest.TestCase):
    def test_committed_json_matches(self):
        self.assertEqual((DIR / "priority_recalc.json").read_text(), PR.render())

    def test_pinned_universe(self):
        self.assertEqual(RES["rights_group_datasets"], 86)
        self.assertEqual(RES["distinct_missing_primary_slots"], 857)
        self.assertEqual(RES["distinct_missing_primary_slots_all_queue_groups"], 949)


class NeedLevelRules(unittest.TestCase):
    def test_baseline_zero_without_clearance(self):
        self.assertTrue(all(v == 0 for v in RES["need_level_baseline_complete"].values()))

    def test_alternatives_never_reduce(self):
        ba = RES["before_after"]
        for p, v2 in ba["rev2_with_candidate_alternatives"]["per_provider"].items():
            v1 = ba["rev1_satisfied_by_only"]["per_provider"].get(p, {})
            self.assertGreaterEqual(v2["need_level_rights_only"], v1.get("need_level_rights_only", 0), p)

    def test_gates_nest(self):
        for v in RES["providers"].values():
            if "need_level_rights_only" not in v:
                continue
            self.assertLessEqual(v["need_level_archived_only"], v["need_level_reachable_or_archived"])
            self.assertLessEqual(v["need_level_reachable_or_archived"], v["need_level_rights_only"])
            self.assertLessEqual(v["need_level_archived_and_pit"], v["need_level_archived_only"])
            self.assertLessEqual(v["need_level_reachable_and_pit"], v["need_level_reachable_or_archived"])

    def test_pit_is_checked_per_satisfying_dataset(self):
        # a PIT-supported slot needs, for every need, a usable dataset with a strict-PIT edge for that exact need
        P = set(PR.TOP8)
        g = PR.GATES["reachable_or_archived"]
        for s in PR.level(P)["reachable_and_pit"]:
            i = s[1]
            for n in PR.SB[i]:
                self.assertTrue(any(PR.usable(d, P, g) and PR.strict(d, i, n) for d in PR.cands(i, n, False)), (s, n))

    def test_candidate_alternatives_are_rights_gated(self):
        # with no clearance, a blocked candidate alternative must never complete a need
        for i in PR.CA:
            for n, ds in PR.CA[i].items():
                for d in ds:
                    if PR.blk(d):
                        self.assertFalse(PR.usable(d, set(), PR.GATES["rights_only"]))


class BuildReadiness(unittest.TestCase):
    def test_build_ready_uses_no_hypothetical_clearance(self):
        for r in RES["first_10_zero_cost_inputs"]:
            if r["build_ready"]:
                self.assertEqual(r["rights_blockers_of_best_path"], [])
                self.assertTrue(all(n["cost"] == "free" and not n["blockers"] for n in r["needs"]))
            else:
                self.assertEqual(r["tier"], "RIGHTS_BLOCKED")
                self.assertTrue(r["rights_blockers_of_best_path"])

    def test_build_ready_counts(self):
        self.assertEqual(RES["build_ready_input_count"], 7)
        self.assertEqual(RES["build_ready_today"]["build_ready_archived"]["slots"], 8)
        self.assertEqual(len(RES["first_10_zero_cost_inputs"]), 10)

    def test_openfootball_snapshot_label(self):
        J = json.loads((DIR / "soc_fixtures_intl_openfootball.json").read_text())
        self.assertEqual(J["slots_fully_satisfied_by_archive"], 0)
        row = next(r for r in J["rows"] if r["input"] == "SOCCER:soc.h2h_zero_sum_fixtures")
        self.assertEqual(row["verdict"], "ARCHIVED_HISTORY_ONLY_CURRENT_SNAPSHOT_MISSING")
        self.assertEqual(sum(J["counts"].values()), J["slots"])


if __name__ == "__main__":
    sys.exit(unittest.main())

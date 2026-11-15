"""Game-by-game completeness engine: classification rules, denominators, and the committed evidence's arithmetic."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpha_engine.game_completeness import (COMPLETE, MISSING, NOT_APPLICABLE, PARTIAL, RIGHTS_BLOCKED, STALE, STATUSES,
                                            UNVERIFIED, DatasetSpec, Game, Observation, classify, evaluate, rollup)
from alpha_engine.game_completeness.engine import game_status
from alpha_engine.game_completeness.impact import InputMap
from alpha_engine.game_completeness.model import PROSPECTIVE_ONLY, RECOVERABLE, SCHEDULED, parse_ts
from alpha_engine.game_completeness.report import tier

T0 = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)
G = Game("NFL", "2026", "g1", "2026-11-08", T0)
BOX = DatasetSpec(key="box", sport="NFL", category="B_PLAYER", title="box", source="s", recoverability=RECOVERABLE,
                  required_fields=("minutes",), min_records=10)
PRE = DatasetSpec(key="inj", sport="NFL", category="D_PREGAME", title="inj", source="s", recoverability=PROSPECTIVE_ONLY,
                  pregame=True, max_age_hours=6)


class Classify(unittest.TestCase):
    def test_absent_is_missing_never_complete(self):
        self.assertEqual(classify(G, BOX, None)[0], MISSING)
        self.assertEqual(classify(G, BOX, Observation(0))[0], MISSING)

    def test_complete_needs_rows_and_fields(self):
        self.assertEqual(classify(G, BOX, Observation(22, frozenset({"minutes"})))[0], COMPLETE)
        self.assertEqual(classify(G, BOX, Observation(4, frozenset({"minutes"})))[0], PARTIAL)
        self.assertEqual(classify(G, BOX, Observation(22, frozenset()))[0], PARTIAL)

    def test_existence_only_is_unverified(self):
        self.assertEqual(classify(G, BOX, Observation(22, frozenset({"minutes"}), verified=False))[0], UNVERIFIED)

    def test_rights_blocked_only_when_absent(self):
        rb = DatasetSpec(key="x", sport="NFL", category="C_EVENTS", title="x", source="s", recoverability=RECOVERABLE,
                         rights_blocked=True)
        self.assertEqual(classify(G, rb, None)[0], RIGHTS_BLOCKED)
        self.assertEqual(classify(G, rb, Observation(5))[0], COMPLETE)

    def test_unplayed_game_is_outside_the_denominator(self):
        g = Game("NFL", "2026", "g2", "2026-11-22", T0, state=SCHEDULED)
        self.assertEqual(classify(g, BOX, None)[0], NOT_APPLICABLE)

    def test_pregame_fresh_stale_and_post_start(self):
        ok = Observation(1, observed_at=T0 - timedelta(hours=2))
        old = Observation(1, observed_at=T0 - timedelta(hours=30))
        after = Observation(1, observed_at=T0 + timedelta(minutes=5))
        self.assertEqual(classify(G, PRE, ok)[0], COMPLETE)
        self.assertEqual(classify(G, PRE, old)[0], STALE)
        self.assertEqual(classify(G, PRE, after)[0], MISSING)
        self.assertEqual(classify(G, PRE, Observation(0, post_start_only=True))[0], MISSING)

    def test_pregame_without_clock_is_unverified(self):
        self.assertEqual(classify(G, PRE, Observation(1))[0], UNVERIFIED)
        g = Game("NFL", "2026", "g3", "2026-11-08", None)
        self.assertEqual(classify(g, PRE, Observation(1, observed_at=T0))[0], UNVERIFIED)


class Rollup(unittest.TestCase):
    def test_denominator_and_rate(self):
        games = [Game("NFL", "2026", f"g{i}", "2026-11-08", T0) for i in range(4)] + \
                [Game("NFL", "2026", "fut", "2026-12-01", T0, state=SCHEDULED)]
        obs = {("g0", "box"): Observation(22, frozenset({"minutes"})), ("g1", "box"): Observation(3, frozenset({"minutes"})),
               ("g2", "box"): Observation(22, frozenset({"minutes"}), verified=False)}
        cells = evaluate(games, [BOX], obs)
        r = rollup(cells, [BOX])[0]
        self.assertEqual(r["expected"], 4)
        self.assertEqual((r[COMPLETE], r[PARTIAL], r[UNVERIFIED], r[MISSING], r["not_applicable"]), (1, 1, 1, 1, 1))
        self.assertEqual(r["complete_rate"], 0.25)
        self.assertEqual(sum(r[s] for s in STATUSES), r["expected"])
        gs = game_status(cells)
        self.assertEqual(gs["g0"], COMPLETE)
        self.assertEqual(gs["g3"], MISSING)
        self.assertNotIn("fut", gs)


class Misc(unittest.TestCase):
    def test_parse_ts(self):
        self.assertEqual(parse_ts("20261115T204835Z"), datetime(2026, 11, 15, 20, 48, 35, tzinfo=timezone.utc))
        self.assertEqual(parse_ts("2026-11-15T20:48:35Z"), datetime(2026, 11, 15, 20, 48, 35, tzinfo=timezone.utc))
        self.assertIsNone(parse_ts("not a time"))
        self.assertIsNone(parse_ts(None))

    def test_tier(self):
        self.assertEqual([tier(x) for x in (0.99, 0.93, 0.5, 0.1, None)],
                         ["COMPLETE_DATA", "MOSTLY_COMPLETE", "PARTIAL_DATA", "INSUFFICIENT_DATA", "NOT_ASSESSED"])

    def test_impact_reads_the_approved_map_without_changing_it(self):
        m = InputMap()
        self.assertEqual(m.n_inputs, 1649)
        r = m.impact(["nfl.pbp", "no.such_dataset"])
        self.assertGreater(r["n_inputs"], 0)
        self.assertEqual(r["unknown_map_datasets"], ["no.such_dataset"])


class CommittedEvidence(unittest.TestCase):
    """The committed summaries must be internally consistent: counts add up and name only registered datasets."""
    ROOT = Path(__file__).resolve().parents[1] / "research" / "game_completeness"

    def test_arithmetic(self):
        found = 0
        for p in sorted(self.ROOT.glob("*/summary.json")):
            found += 1
            s = json.loads(p.read_text())
            self.assertEqual(s["status"], "RESEARCH_ONLY")
            self.assertEqual(s["ledger"]["rows"], s["expected_games"]["total"])
            for d in s["datasets"]:
                self.assertEqual(sum(d[k] for k in STATUSES), d["expected"], (p.parent.name, d["dataset"]))
                self.assertLessEqual(d["expected"], s["expected_games"]["total"])
                self.assertEqual(sum(b["expected"] for b in d["by_season"].values()), d["expected"])
                self.assertEqual(d["impact"]["unknown_map_datasets"], [], (p.parent.name, d["dataset"]))
        self.assertEqual(found, 6)


if __name__ == "__main__":
    unittest.main()

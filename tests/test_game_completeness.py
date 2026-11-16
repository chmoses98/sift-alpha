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


class OfficialSettlement(unittest.TestCase):
    def test_compare_never_forces_non_binary_into_agreement(self):
        from alpha_engine.game_completeness.kalshi_official import compare
        off = {"A": {"result": "yes"}, "B": {"result": "no"}, "C": {"result": "yes"}, "D": {"result": ""}, "Z": {"result": "no"}}
        comp = {"A": "YES", "B": "YES", "C": "UNSETTLEABLE", "D": "NO", "E": "NO"}
        r = compare(off, comp)
        self.assertEqual(r["counts"]["agree"], 1)
        self.assertEqual(r["counts"]["disagree"], 1)
        self.assertEqual(r["disagreements"], ["B"])
        self.assertEqual(r["counts"]["computed_not_binary"], 1)
        self.assertEqual(r["counts"]["official_available_for_unsettleable"], 1)
        self.assertEqual(r["counts"]["official_not_binary"], 1)
        self.assertEqual(r["counts"]["computed_without_official"], 1)
        self.assertEqual(r["counts"]["official_without_computed"], 1)

    def test_fetch_pages_until_cursor_ends(self):
        import io, tempfile
        from alpha_engine.game_completeness.kalshi_official import fetch_series
        pages = [{"markets": [{"ticker": "T1", "result": "yes"}], "cursor": "c"}, {"markets": [{"ticker": "T2", "result": "no"}], "cursor": ""}]
        calls = []

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            calls.append(req.full_url)
            return R(json.dumps(pages[len(calls) - 1]).encode())
        with tempfile.TemporaryDirectory() as d:
            r = fetch_series("KXTEST", d, pause=0, opener=opener)
            rows = [json.loads(x) for x in open(Path(d) / "KXTEST.jsonl")]
        self.assertEqual((r["contracts"], r["pages"], r["truncated"]), (2, 2, False))
        self.assertIn("cursor=c", calls[1])
        self.assertTrue(all(x["_retrieved_at_utc"] for x in rows))


    def test_historical_endpoint_has_no_status_filter_and_own_file(self):
        import io, tempfile
        from alpha_engine.game_completeness.kalshi_official import HISTORICAL_API, fetch_series
        calls = []

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            calls.append(req.full_url)
            return R(json.dumps({"markets": [{"ticker": "H1", "result": "no"}], "cursor": ""}).encode())
        with tempfile.TemporaryDirectory() as d:
            fetch_series("KXTEST", d, pause=0, opener=opener, historical=True)
            self.assertTrue((Path(d) / "KXTEST__historical.jsonl").exists())
            row = json.loads(open(Path(d) / "KXTEST__historical.jsonl").readline())
        self.assertTrue(calls[0].startswith(HISTORICAL_API + "?"))
        self.assertNotIn("status=", calls[0])
        self.assertEqual(row["_source"], HISTORICAL_API)

    def test_fetch_scope_resumes_marks_only_complete_and_verifies(self):
        import tempfile
        from alpha_engine.game_completeness.kalshi_official import fetch_scope, verify_manifest
        calls = []

        def fake(series, out, max_pages=0, pause=0, **kw):
            calls.append(series)
            Path(out).mkdir(parents=True, exist_ok=True)
            with open(Path(out) / f"{series}.jsonl", "w") as fh:
                fh.write(json.dumps({"ticker": series + "-1", "result": "yes", "close_time": "2026-10-01T00:00:00Z"}) + "\n")
            return {"series": series, "contracts": 1, "pages": 1, "truncated": series == "KXCUT"}
        scope = {"sports": {"NBA": ["KXA", "KXCUT"], "NHL": ["KXB"]}}
        with tempfile.TemporaryDirectory() as d:
            man = fetch_scope(scope, d, fetch=fake)
            self.assertEqual(man["series"]["NBA/KXA"]["rows"], 1)
            self.assertEqual(man["series"]["NBA/KXA"]["close_min"], "2026-10-01")
            self.assertFalse((Path(d) / "NBA" / "KXCUT.done").exists())     # truncated -> never marked complete
            fetch_scope(scope, d, fetch=fake)                                # resume: only the truncated one again
            self.assertEqual(calls, ["KXA", "KXCUT", "KXB", "KXCUT"])
            self.assertEqual(verify_manifest(d)["problems"], [])
            (Path(d) / "NHL" / "KXB.jsonl").write_text("{}\n")              # tamper -> read-back fails
            self.assertEqual(verify_manifest(d)["problems"], [("NHL/KXB", "hash mismatch")])

    def test_compare_by_series_and_value_delta(self):
        from alpha_engine.game_completeness.kalshi_official import compare
        off = {"KXNBA2HTOTAL-G-129": {"result": "yes", "expiration_value": "142"},
               "KXNBA2HTOTAL-G-131": {"result": "yes", "expiration_value": "142"}}
        comp = {"KXNBA2HTOTAL-G-129": "NO", "KXNBA2HTOTAL-G-131": "YES"}
        r = compare(off, comp, {"KXNBA2HTOTAL-G-129": 127, "KXNBA2HTOTAL-G-131": 127})
        self.assertEqual(r["by_series"]["KXNBA2HTOTAL"], {"agree": 1, "disagree": 1})
        self.assertEqual(r["official_minus_computed_value_on_disagreement"], {"KXNBA2HTOTAL:15.0": 1})


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

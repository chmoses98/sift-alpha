import json, tempfile, unittest
from datetime import date, datetime, timezone
from pathlib import Path
from alpha_engine import period_scoring as ps

OBS = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def comp(h, a, completed=True, hs=None, as_=None, eid="1"):
    def side(ha, lines, score, abbr, tid):
        c = {"homeAway": ha, "team": {"abbreviation": abbr, "id": tid}, "score": str(score)}
        if lines is not None:
            c["linescores"] = [{"value": v} for v in lines]
        return c
    return {"id": eid, "date": "2026-10-31T16:00Z", "competitions": [{"neutralSite": False, "status": {"type": {"completed": completed}},
            "competitors": [side("home", h, sum(h) if hs is None and h else hs, "AUB", "2"), side("away", a, sum(a) if as_ is None and a else as_, "MISS", "145")]}]}


class Parse(unittest.TestCase):
    def test_complete_game_reconciles(self):
        rows, rej = ps.parse_scoreboard({"events": [comp([7, 3, 0, 7], [0, 10, 3, 0])]}, "cfb", OBS, "u")
        self.assertEqual(len(rows), 1); self.assertEqual(rej, {})
        r = rows[0]
        self.assertEqual((r["reconciliation"], r["overtime"], r["home_final"], r["observed_at"]), ("RECONCILED", False, 17, "2026-11-03T12:00:00Z"))

    def test_unreconciled_kept_but_flagged_and_excluded_from_distribution(self):
        rows, _ = ps.parse_scoreboard({"events": [comp([7, 3, 0, 7], [0, 10, 3, 0], hs=21)]}, "cfb", OBS, "u")
        self.assertEqual(rows[0]["reconciliation"], "SCORE_UNRECONCILED")
        self.assertEqual(ps.period_distribution(rows, 0)["n"], 0)
        self.assertEqual(ps.period_distribution(rows, 0, include_unreconciled=True)["n"], 1)

    def test_nothing_is_fabricated(self):
        body = {"events": [comp([7, 3], [0, 10], eid="a"), comp(None, None, eid="b"), comp([7, 3, 0, 7], [0, 10, 3, 0], completed=False, eid="c")]}
        rows, rej = ps.parse_scoreboard(body, "cfb", OBS, "u")
        self.assertEqual(rows, [])
        self.assertEqual(rej, {"FEWER_THAN_REGULATION_PERIODS": 1, "MALFORMED_OR_NO_LINESCORES": 1, "NOT_COMPLETED": 1})

    def test_overtime_flag_and_regulation_only_distribution(self):
        rows, _ = ps.parse_scoreboard({"events": [comp([7, 3, 0, 7, 6], [0, 10, 3, 4, 0])]}, "cfb", OBS, "u")
        self.assertTrue(rows[0]["overtime"])
        self.assertEqual(ps.period_distribution(rows, 0)["pmf"], {"7": 1.0})

    def test_distribution_pmf(self):
        evs = [comp([7, 0, 0, 0], [0, 0, 0, 0], eid="1"), comp([0, 0, 0, 0], [0, 0, 0, 0], eid="2"), comp([3, 0, 0, 0], [7, 0, 0, 0], eid="3"), comp([7, 0, 0, 0], [0, 0, 0, 0], eid="4")]
        rows, _ = ps.parse_scoreboard({"events": evs}, "cfb", OBS, "u")
        d = ps.period_distribution(rows, 0)
        self.assertEqual((d["n"], d["p_zero"], d["pmf"]), (4, 0.25, {"0": 0.25, "7": 0.5, "10": 0.25}))


class Collect(unittest.TestCase):
    def test_append_only_idempotent_and_failures_recorded(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if "20261102" in url:
                raise OSError("boom")
            return {"events": [comp([7, 3, 0, 7], [0, 10, 3, 0], eid="9")]}
        with tempfile.TemporaryDirectory() as t:
            s1 = ps.collect("cfb", date(2026, 11, 1), date(2026, 11, 2), t, fetch=fetch)
            s2 = ps.collect("cfb", date(2026, 11, 1), date(2026, 11, 2), t, fetch=fetch)
            self.assertEqual((s1["rows_new"], s1["failed_days"] != []), (1, True))
            self.assertEqual((s2["rows_new"], s2["rows_existing"]), (0, 1))     # never duplicated / overwritten
            self.assertEqual(len(ps.load(t, "cfb")), 1)
            self.assertEqual(list(ps.manifest(t)), ["cfb/2026-11-01.jsonl"])


if __name__ == "__main__":
    unittest.main()

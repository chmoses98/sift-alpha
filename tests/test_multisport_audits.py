import json
import tempfile
import unittest
from pathlib import Path

from alpha_engine import model_use_probe as mp
from alpha_engine import projection_output_audit as po
from alpha_engine import verification_engine as ve

OUT = Path(__file__).resolve().parents[1] / "research" / "audit" / "verification"


class Probe(unittest.TestCase):
    def repo(self, files):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        for rel, txt in files.items():
            p = Path(d.name) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt)
        return Path(d.name)

    def test_docstring_and_comment_mentions_do_not_count(self):
        r = self.repo({"src/model/predict.py": '"""uses kicker accuracy"""\n# kicker here\ndef f():\n    """kicker"""\n    return 1\n',
                       "src/collect/fetch.py": "def g():\n    return 2\n"})
        res = mp.probe(r, {"x.kicker": "kicker"})["x.kicker"]
        self.assertEqual(res["model_files"], 0)
        self.assertFalse(res["static_consumption_candidate"])

    def test_identifier_read_in_model_plus_collector_is_candidate_not_proof(self):
        r = self.repo({"src/model/predict.py": "def f(row):\n    return row['kicker_pct'] * 2\n", "src/collect/fetch.py": "def g():\n    kicker_pct = 1\n    return kicker_pct\n"})
        res = mp.probe(r, {"x.kicker": "kicker"})["x.kicker"]
        self.assertTrue(res["static_consumption_candidate"])
        self.assertEqual(res["model_read_files"], 1)

    def test_candidate_without_collector_is_not_candidate(self):
        r = self.repo({"src/model/predict.py": "def f(kicker):\n    return kicker\n"})
        self.assertFalse(mp.probe(r, {"x.kicker": "kicker"})["x.kicker"]["static_consumption_candidate"])

    def test_static_evidence_never_gives_transform_pass(self):
        e = {"verification_class": "VERIFIED_COLLECTION", "collection": "PIT_ARCHIVED", "model_use": "USED", "evidence": ["doc:x"], "code": {}}
        st = {"static_consumption_candidate": True, "collector_files": 2, "model_read_files": 3, "repo": "o/r", "commit": "a" * 40}
        self.assertEqual(ve.input_stages(e, None, st)["transform"]["state"], "PARTIAL")


class OutputAudit(unittest.TestCase):
    def player(self, i, status="LIKELY_ACTIVE", fac=1.0):
        return {"family": "points", "readiness": "READY", "actionable": True, "gate": {"status": "PASS"}, "adjustments": ["Participation: x", "Opponent X allows: y"],
                "participation": {"status": status, "source": "s", "certainty": "PROJECTED", "implicit": False, "age_minutes": 1.0}, "opportunity": {"mean": 20 + i},
                "opponent_adjustment": {"factor": fac, "sample_games": 5}, "thresholds": {"10": 0.5, "15": 0.2}, "p10": 0, "median": 5, "p90": 10, "mean": 6}

    def raw(self, players):
        return json.dumps({"players": players, "generated_utc": "2026-11-04T10:00:10Z", "data_asof_utc": "2026-11-04T10:00:00Z", "model": {"id": "m"}, "mode": "x", "reconciliation": [{"status": "PASS"}]}).encode()

    def test_visibility_requires_population_and_variation(self):
        ps = [self.player(i, status="LIKELY_ACTIVE" if i % 2 else "CONFIRMED_OUT", fac=0.9 + i / 100) for i in range(10)]
        a = po.audit(self.raw(ps), {"commit": "c"})
        self.assertTrue(a["input_visibility"]["nba.injuries_pit"]["visible_in_output"])
        self.assertFalse(a["input_visibility"]["nba.starters_pit"]["visible_in_output"])      # field absent
        const = [self.player(i, status="LIKELY_ACTIVE") for i in range(10)]
        for p in const: p["opportunity"]["mean"] = 20.0
        self.assertFalse(po.audit(self.raw(const), {"commit": "c"})["input_visibility"]["nba.injuries_pit"]["visible_in_output"])   # constant -> no evidence of use

    def test_incoherent_distribution_is_reported(self):
        ps = [self.player(i) for i in range(4)]; ps[0]["thresholds"] = {"10": 0.1, "15": 0.4}
        self.assertLess(po.audit(self.raw(ps), {"commit": "c"})["distribution_coherence"]["thresholds_monotone"], 1.0)

    def test_visible_but_unused_record_gets_no_consumption_pass(self):
        e = {"verification_class": "VERIFIED_COLLECTION", "collection": "PIT_ARCHIVED", "model_use": "UNKNOWN", "evidence": ["doc:x"], "code": {}}
        vis = {"visible_in_output": True, "visible_leaves": ["a.b"]}
        self.assertEqual(ve.input_stages(e, None, None, vis)["consumption"]["state"], "PARTIAL")
        used = dict(e, model_use="USED")
        self.assertEqual(ve.input_stages(used, None, None, vis)["consumption"]["state"], "PASS")
        self.assertEqual(ve.input_stages(used, None, None, None)["consumption"]["state"], "PARTIAL")    # repo-reported alone is not verified


class Committed(unittest.TestCase):
    def test_published_projection_never_means_reproduced(self):
        ctx, *_ = ve.run(write=False)
        for k, f in ctx["fams"].items():
            if f["projection"].get("published"):
                self.assertFalse(f["projection"]["independently_reproduced"], k)
                self.assertEqual(f["stages"]["projection"]["state"], "PARTIAL", k)

    def test_projection_outputs_are_aggregate_only(self):
        txt = (OUT / "projection_outputs.json").read_text()
        for bad in ('"name"', "entity_name", "player_id", "Javonte"):
            self.assertNotIn(bad, txt)

    def test_nba_starters_not_visible_is_recorded(self):
        d = json.loads((OUT / "projection_outputs.json").read_text())
        self.assertFalse(d["NBA"]["input_visibility"]["nba.starters_pit"]["visible_in_output"])


if __name__ == "__main__":
    unittest.main()

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


class SourceVerification(unittest.TestCase):
    base = {"verification_class": "UNKNOWN", "collection": "UNKNOWN", "model_use": "UNKNOWN", "evidence": [], "code": {}, "note": "n", "label": "l"}
    sv = {"verification_class": "COLLECTED_UNVERIFIED_PIT", "collection": "COLLECTED_NOT_PIT_ARCHIVED", "why": "w", "measured": {"source": {"repo": "o/r", "commit": "a" * 40, "path": "p"}}}

    def test_lifts_weak_input_but_never_to_verified(self):
        e = ve.apply_source_verification(self.base, self.sv)
        self.assertEqual(ve.input_status(e), "COLLECTED_UNVERIFIED")
        bad = dict(self.sv, verification_class="VERIFIED_COLLECTION")
        self.assertEqual(ve.apply_source_verification(self.base, bad), self.base)

    def test_never_downgrades_or_overrides_verified(self):
        v = dict(self.base, verification_class="VERIFIED_COLLECTION", collection="PIT_ARCHIVED")
        self.assertEqual(ve.apply_source_verification(v, self.sv), v)
        s = dict(self.base, verification_class="STALE_OR_PARTIAL")
        self.assertEqual(ve.apply_source_verification(s, self.sv), s)

    def test_requires_pinned_source(self):
        nosrc = dict(self.sv, measured={})
        self.assertEqual(ve.apply_source_verification(self.base, nosrc), self.base)
        nocommit = dict(self.sv, measured={"source": {"repo": "o/r"}})
        self.assertEqual(ve.apply_source_verification(self.base, nocommit), self.base)

    def test_committed_sources_do_not_change_verified_counts(self):
        _, rec, _, summ = ve.run(write=False)
        self.assertEqual((rec["essential_links"], rec["essential_links_verified"], rec["families_with_all_essentials_verified"]), (1762, 775, 5))
        cfb = summ["sports"]["CFB"]
        self.assertGreater(cfb["inputs_by_status"].get("COLLECTED_UNVERIFIED", 0), cfb["inputs_by_status_before_measured_evidence"].get("COLLECTED_UNVERIFIED", 0))
        self.assertEqual(cfb["inputs_by_status"].get("VERIFIED"), cfb["inputs_by_status_before_measured_evidence"].get("VERIFIED"))

    def test_sidecar_measurements_are_consistent(self):
        d = json.loads((OUT / "source_verifications.json").read_text())["inputs"]
        w = d["CFB:cfb.weather_pit"]["measured"]
        self.assertEqual(w["git_commit_minus_fetched_minutes"]["rows_committed_before_fetched"], 0)
        self.assertLess(w["coverage_of_completed_games"], 0.5)        # partial coverage must stay visible
        for k, v in d.items():
            self.assertNotEqual(v["verification_class"], "VERIFIED_COLLECTION", k)


class Ledger(unittest.TestCase):
    def test_ledger_states_match_engine(self):
        ctx, _, tasks, _ = ve.run(write=False)
        led = json.loads((OUT / "repair_ledger.json").read_text())["entries"]
        ids = {t["id"] for t in tasks}
        for k, e in led.items():
            self.assertIn(e["state"], {"OPEN", "EVIDENCE_ADDED", "BLOCKED", "REPAIRED_VERIFIED"}, k)
            self.assertTrue(e["found"] and e["remaining"] and e["next"], k)
            if e["state"] == "REPAIRED_VERIFIED":
                self.assertEqual(ctx["inputs"][k]["status"], "VERIFIED", k)
            if e["state"] == "EVIDENCE_ADDED":
                self.assertNotEqual(ctx["inputs"][k]["status"], "VERIFIED", k)
        self.assertEqual(len([t for t in tasks if t["disposition"]]), len([k for k in led if k in ids]))


class FeatureAblation(unittest.TestCase):
    def data(self, n=140):
        import random
        rng = random.Random(7)
        games, tg = [], []
        for i in range(n):
            h, a = f"T{i % 10}", f"T{(i * 3 + 1) % 10}"
            day = f"2026-{9 + i // 70:02d}-{1 + (i // 5) % 28:02d}T{12 + i % 5:02d}:00Z"
            gid = f"g{i}"
            games.append({"event_id": gid, "start_time_utc": day, "home_team_id": h, "away_team_id": a, "home": h, "away": a, "home_periods": [rng.choice([0, 3, 7]), 0, 0, 0], "away_periods": [rng.choice([0, 3, 7]), 0, 0, 0]})
            for t in (h, a):
                tg.append({"game_id": gid, "team_id": t, "kickoff_utc": day, "box": {"plays": 60 + rng.random() * 10}, "pbp": {"scrim_plays": 60, "drives": 11, "success_plays": 27, "explosive_pass": 3, "explosive_rush": 1, "pass_plays": 30, "rush_plays": 30}})
        return games, tg

    def test_noise_features_do_not_validate_and_future_changes_nothing(self):
        from alpha_engine import cfb_q1_features_ablation as fa
        games, tg = self.data()
        rows = fa.build_rows(tg, games)
        preds = fa.predict_variants(rows)
        self.assertTrue(preds)
        res = fa.ablate(preds)
        for v, e in res["variants"].items():
            self.assertNotEqual(e.get("verdict"), "VALIDATED_PREDICTIVE", v)
        games2 = [dict(g) for g in games]; games2[-1]["home_periods"] = [99, 0, 0, 0]
        p2 = fa.predict_variants(fa.build_rows(tg, games2))
        for a, b in zip(preds[:-1], p2[:-1]):
            self.assertEqual(a["V11_all_pace_efficiency"], b["V11_all_pace_efficiency"])
        self.assertEqual(preds[-1]["V11_all_pace_efficiency"], p2[-1]["V11_all_pace_efficiency"])

    def test_ridge_recovers_signal(self):
        from alpha_engine import cfb_q1_features_ablation as fa
        X = [[i / 10.0] for i in range(100)]
        y = [3 * x[0] + 1 for x in X]
        beta, mu, xbar = fa.ridge_fit(X, y, lam=0.01)
        self.assertAlmostEqual(beta[0], 3, delta=0.1)

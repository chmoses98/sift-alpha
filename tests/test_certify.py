"""Unit tests for alpha_engine.certify (comparison, reconciliation, recovery manifest, leakage comparison)."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.certify import compare as C
from alpha_engine.certify import leakage as L
from alpha_engine.certify import reconcile as R
from alpha_engine.certify import recovery as V


def _ds(n=4, shift=0.0):
    return pd.DataFrame({"game_id": range(n), "season": [2020] * n, "date": pd.to_datetime(["2020-01-01"] * n),
                         "x": np.arange(n, dtype=float) + shift, "split": ["train"] * n})


class TestCompare(unittest.TestCase):
    def test_identical(self):
        r = C.compare(_ds(), _ds())
        self.assertTrue(r["identical_within_tolerance"])
        self.assertEqual(r["cells_mismatched"], 0)

    def test_value_and_nan_mismatch(self):
        b = _ds(); b.loc[1, "x"] = 99.0; b.loc[2, "x"] = np.nan
        r = C.compare(_ds(), b)
        self.assertFalse(r["identical_within_tolerance"])
        self.assertEqual(r["columns_with_mismatch"]["x"]["mismatch"], 2)
        self.assertEqual(r["columns_with_mismatch"]["x"]["nan_pattern_mismatch"], 1)

    def test_tolerance(self):
        self.assertTrue(C.compare(_ds(), _ds(shift=1e-9))["identical_within_tolerance"])

    def test_row_sets(self):
        r = C.compare(_ds(4), _ds(3))
        self.assertEqual((r["only_a"], r["only_b"]), (1, 0))
        self.assertFalse(r["identical_within_tolerance"])


class TestReconcile(unittest.TestCase):
    def test_classes_are_exclusive(self):
        ledger = pd.DataFrame({
            "season": ["2019", "2020", "2020", "2020", "2020", "2020"],
            "date": ["2019-12-01", "2020-01-01", "2020-01-02", "2020-01-03", "2020-03-01", "2020-01-04"],
            "game_id": ["a", "b", "c", "d", "e", "f"], "state": ["FINAL"] * 5 + ["SCHEDULED"], "overall": ["C"] * 6,
            "team_box": ["C", "C", "M", "C", "C", "C"]})
        d = pd.DataFrame({"game_id": ["b", "z"], "season": [2020, 2020], "date": pd.to_datetime(["2020-01-01", "2020-01-05"])})
        r = R.reconcile("CBB", ledger, d, "team_box")
        self.assertEqual(r["classes"], {"IN_DATASET": 1, "OUTSIDE_SEASON_RANGE": 1, "SOURCE_NOT_COMPLETE": 1, "BUILDER_EXCLUDED": 1,
                                        "AFTER_BUILD_VINTAGE": 1, "DATASET_ONLY": 1})
        self.assertEqual(r["ledger_final_games"], 5)

    def test_nhl_game_type(self):
        ledger = pd.DataFrame({"season": ["2020"], "date": ["2020-05-01"], "game_id": ["2020030111"], "state": ["FINAL"],
                               "overall": ["C"], "shot_xg": ["C"]})
        d = pd.DataFrame({"game_id": [2020020001], "season": [2020], "date": pd.to_datetime(["2020-01-01"])})
        self.assertEqual(R.reconcile("NHL", ledger, d, "shot_xg")["classes"].get("OUT_OF_SCOPE_GAME_TYPE"), 1)


class TestRecovery(unittest.TestCase):
    def test_pin_and_verify(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t); (d / "a").mkdir(); (d / "a" / "f1.parquet").write_bytes(b"one"); (d / "a" / "f2.parquet").write_bytes(b"two")
            files = V.pin_dir(d, "*/*.parquet")
            m = {"sources": {"s": {"files": files}}}
            self.assertTrue(V.verify(m, "s", d)["recoverable_byte_exact"])
            (d / "a" / "f2.parquet").write_bytes(b"changed")
            r = V.verify(m, "s", d)
            self.assertFalse(r["recoverable_byte_exact"])
            self.assertEqual(r["changed"][0], 1)

    def test_committed_manifest_shape(self):
        p = Path(__file__).resolve().parents[1] / "research/certification/recovery_manifest.json"
        m = json.loads(p.read_text())
        self.assertEqual(m["status"], "RESEARCH_ONLY")
        for s in m["sources"].values():
            self.assertIn(s["class"], {"GIT_PINNED", "UPSTREAM_MUTABLE", "LOST_EPHEMERAL"})
            for meta in s.get("files", {}).values():
                self.assertEqual(len(meta["sha256"]), 64)


class TestLeakageCompare(unittest.TestCase):
    def test_detects_change(self):
        a = _ds(); b = _ds(); b.loc[0, "x"] = 5.0
        self.assertTrue(L._compare(a, a.copy(), ["x"])["identical"])
        r = L._compare(a, b, ["x"])
        self.assertFalse(r["identical"]); self.assertEqual(r["columns_differing"], ["x"])


if __name__ == "__main__":
    unittest.main()


class TestRegistry(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1] / "research/certification"

    def test_versions_append_only_shape(self):
        from alpha_engine.certify import registry as G
        v = json.loads((self.ROOT / "dataset_versions.json").read_text())
        keys = [(e["sport"], e["canonical_sha256"]) for e in v["versions"]]
        self.assertEqual(len(keys), len(set(keys)))
        for e in v["versions"]:
            self.assertEqual(len(e["canonical_sha256"]), 64)
            self.assertIn("superseded_by", e)
            self.assertFalse(e["tiers"]["model_active"])
        before = json.dumps(v["versions"][0], sort_keys=True)
        G.register(v, dict(v["versions"][0], rows=-1))          # same (sport, hash): must not mutate or duplicate
        self.assertEqual(json.dumps(v["versions"][0], sort_keys=True), before)
        self.assertEqual(len(v["versions"]), len(keys))

    def test_game_index_references_registered_versions(self):
        v = json.loads((self.ROOT / "dataset_versions.json").read_text())
        short = {e["canonical_sha256"][:12] for e in v["versions"]}
        for f in sorted((self.ROOT / "game_index").glob("*.csv.gz")):
            g = pd.read_csv(f, dtype=str, keep_default_na=False)
            self.assertFalse(g.game_id.duplicated().any(), f.name)
            used = set(g.dataset_version) - {""}
            self.assertTrue(used <= short, f.name)
            self.assertTrue(set(g.outcome_check) <= {"A", "D", "-"})
            self.assertTrue((g[g.dataset_version != ""].recon_class.isin({"IN_DATASET", "DATASET_ONLY"})).all())

    def test_certification_summary(self):
        c = json.loads((self.ROOT / "certification.json").read_text())
        for s in ("CBB", "CFB"):
            x = c["sports"][s]
            self.assertEqual(x["verdict"], "CERTIFIED")
            self.assertEqual(x["blind_reimplementation"]["cells_mismatched"], 0)
            self.assertTrue(x["truncation_check"])
            self.assertTrue(all(d["future_scramble_identical"] and d["own_game_identical"] for d in x["leakage"].values()))

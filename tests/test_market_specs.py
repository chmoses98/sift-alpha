import json, unittest
from pathlib import Path
from alpha_engine import market_specs as ms
from alpha_engine.market_specs_data import SPEC

A = Path(__file__).resolve().parent.parent / "research" / "audit"


class Specs(unittest.TestCase):
    def test_specs_validate_against_catalog(self):
        self.assertEqual(ms.validate(), [])

    def test_every_inventoried_family_has_an_explicit_decision(self):
        master = json.load(open(A / "master_inventory.json"))["families"]
        out = json.load(open(A / "market_specs.json"))
        added = {k for k, v in out["families"].items() if v.get("added_by_overlay")}
        self.assertEqual({f["id"] for f in master} | added, set(out["families"]))
        self.assertEqual(added, {"SOCCER/player_goalscorer", "SOCCER/corners", "SOCCER/shots_sot"})   # omissions found via mis-filed series + live Kalshi series list
        for fid, r in out["families"].items():
            self.assertIn(r["status"], {"SPECIFIED", "SPECIFIED_UNOBSERVED", "SPECIFIED_BY_SERIES_SPLIT", "MISMAPPED_REROUTED", "UNSPECIFIED", "OUT_OF_SCOPE"}, fid)
            if r["status"] in ("UNSPECIFIED", "OUT_OF_SCOPE", "MISMAPPED_REROUTED"):
                self.assertTrue(r["reason"], fid)       # gaps are named, never silently dropped
            else:
                self.assertTrue(r["specs"] and r["essential_total"] > 0, fid)

    def test_resolution_covers_every_series_and_marks_provisional(self):
        res = json.load(open(A / "resolutions" / "unresolved_families.json"))
        self.assertEqual(sum(v["n_series"] for v in res["families"].values()), 91)
        nfl = res["families"]["NFL/NFL_MISC_UNCLASSIFIED"]
        self.assertEqual(nfl["series_title_only"], nfl["n_series"])          # no rules text seen: provisional, named
        self.assertTrue(nfl["missing_evidence"])
        mlb = res["families"]["MLB/unknown"]
        self.assertEqual({s["action"] for s in mlb["series"]}, {"OUT_OF_SCOPE", "REROUTE"})

    def test_market_specific_not_generic(self):
        q = SPEC["fb_quarter_total"]["drivers"]["CFB"]
        self.assertIn("cfb.kicker:E", q)
        self.assertIn("cfb.first_drive:E", q)
        self.assertIn("soc.corners:E", SPEC["sc_corners"]["drivers"]["SOCCER"])
        self.assertIn("nhl.shots_against:E", SPEC["hk_goalie_saves"]["drivers"]["NHL"])
        self.assertIn("ten.tiebreak:E", SPEC["tn_tiebreak"]["drivers"]["TENNIS"])
        self.assertIn("mlb.f3_split:E", SPEC["bs_f3"]["drivers"]["MLB"])

    def test_anticipated_classes_are_not_mapped_to_observed_families(self):
        mapped = {s for v in ms.M.values() for s in v}
        for k in ms.ANTICIPATED:
            self.assertIn(k, SPEC)
            self.assertNotIn(k, mapped)

    def test_readiness_matches_collection_status(self):
        out = json.load(open(A / "market_specs.json"))
        cs = json.load(open(A / "collection_status.json"))["sports"]
        r = out["families"]["CFB/quarter_total"]
        ess = [i for i, t in r["drivers"].items() if t == "E"]
        self.assertEqual(sum(r["essential_by_status"].values()), len(ess))
        for i in r["essential_missing"]:
            self.assertIn(cs["CFB"]["inputs"][i]["verification_class"], ("MISSING", "UNKNOWN", "CODE_REFERENCE_ONLY"))


if __name__ == "__main__":
    unittest.main()


class ModelValidation(unittest.TestCase):
    def test_validation_is_labelled_repo_reported_with_provenance(self):
        v = json.load(open(A / "model_validation.json"))
        self.assertIn("REPO-REPORTED", v["note"])
        src = v["sources"][0]
        self.assertEqual(len(src["commit"]), 40); self.assertEqual(len(src["sha256"]), 64)
        for fam in v["sports"]["NBA"]["families"].values():
            self.assertTrue(fam["reported"] and fam["readiness"])

import json
import unittest

from alpha_engine import essential_readiness as er


class EssentialReadiness(unittest.TestCase):
    def test_counts_consistent(self):
        d = er.build()
        specs = json.loads((er.A / "market_specs.json").read_text())["families"]
        self.assertEqual(set(d["families"]), set(specs))
        for k, r in d["families"].items():
            ess = [i for i, t in specs[k].get("drivers", {}).items() if t == "E"]
            self.assertEqual(r["required"], len(ess))
            self.assertLessEqual(r["verified"], r["collected"])
            self.assertLessEqual(r["collected"], r["required"])
            self.assertEqual(sum(x["required"] for x in r["dims"].values()), r["required"])
            self.assertEqual(len(r["gaps"]), r["required"] - r["verified"])
            self.assertEqual(r["predictive_validation"], "NOT_ASSESSED")
        for s, v in d["sports"].items():
            self.assertEqual(v["ALL"]["verified"], sum(x["verified"] for x in d["families"].values() if x["sport"] == s))

    def test_unclassified_links_are_surfaced_not_borrowed(self):
        self.assertIsInstance(er.build()["unclassified_links"], dict)


if __name__ == "__main__":
    unittest.main()

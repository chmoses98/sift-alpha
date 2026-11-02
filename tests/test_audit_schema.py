import copy, glob, json, unittest
from pathlib import Path
from alpha_engine.audit_schema import validate_audit, validate_inventory

ROOT = Path(__file__).resolve().parents[1] / "research" / "audit"


def load_all():
    inv = [json.load(open(p)) for p in sorted(glob.glob(str(ROOT / "*_market_inventory.json")))]
    aud = [json.load(open(p)) for p in sorted(glob.glob(str(ROOT / "audits" / "*.json")))]
    return inv, aud


class AuditArtifacts(unittest.TestCase):
    def test_committed_artifacts_validate(self):
        inv, aud = load_all()
        self.assertTrue(inv and aud)
        for i in inv:
            self.assertEqual(validate_inventory(i), [])
        for a in aud:
            self.assertEqual(validate_audit(a), [], a["market_family"])

    def test_audited_family_exists_in_inventory(self):
        inv, aud = load_all()
        fams = {(i["sport"], f["family"]): f for i in inv for f in i["families"]}
        for a in aud:
            f = fams[(a["sport"], a["market_family"])]
            self.assertEqual(f["snapshot_markets_seen"], a["coverage"]["snapshot_markets_seen"])
            self.assertEqual(sorted(s["ticker"] for s in f["series"]), sorted(a["coverage"]["series"]))

    def test_team_total_defect_is_recorded_as_repaired_not_validated(self):
        a = json.load(open(ROOT / "audits" / "nfl_team_total.json"))
        row = next(i for i in a["inputs"] if i["input"].startswith("Market-implied game total"))
        self.assertEqual(row["model_use"], "USED_DEFECT_REPAIRED")
        self.assertEqual(row["validation"], "NOT_VALIDATED")

    def test_fail_closed(self):
        _, aud = load_all()
        a = aud[0]
        bad = copy.deepcopy(a); bad["inputs"][0]["evidence"] = []
        self.assertTrue(validate_audit(bad))
        bad = copy.deepcopy(a); bad["inputs"][0]["model_use"] = "DONE"
        self.assertTrue(validate_audit(bad))
        bad = copy.deepcopy(a); bad["last_verified_utc"] = "2026-11-02T00:00:00"
        self.assertTrue(validate_audit(bad))
        bad = copy.deepcopy(a); bad["inputs"][1]["defect"] = None
        self.assertTrue(validate_audit(bad))
        bad = copy.deepcopy(a); bad["inputs"][2]["validation"] = "VALIDATED_PROSPECTIVE"; bad["inputs"][2]["evidence"] = []
        self.assertTrue(validate_audit(bad))


if __name__ == "__main__":
    unittest.main()

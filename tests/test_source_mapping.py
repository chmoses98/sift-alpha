import json
from pathlib import Path
from alpha_engine.input_research.data_foundation import source_mapping as sm

STATUSES = {"SOURCE_MAPPED_MEASURED", "SOURCE_MAPPED_PARTIAL", "NO_FREE_PATH", "NEEDS_OWNER_ACTION", "PROSPECTIVE_ONLY", "EXCLUDED_MARKET", "BLOCKED_BY_POLICY"}


def test_mappings_use_closed_vocabulary_and_never_claim_verified():
    for sp, mp in sm.load().items():
        assert mp
        for iid, v in mp.items():
            assert "." in iid, iid
            assert v["status"] in STATUSES, (iid, v["status"])


def test_ext_replay_all_pass():
    d = json.loads((sm.ROOT / "research/input_research/data_foundation/verification/replay_ext/NFL.json").read_text())
    for k, v in d["inputs"].items():
        t = v["tests"]
        assert t["determinism"]["ok"] and all(x["ok"] for x in t["truncation"]) and all(x["ok"] for x in t["perturbation"]) and t["own_game"]["ok"], k
        assert all(t[n]["ok"] for n in t if n.startswith("pit_check")), k


def test_plan_is_reproducible():
    assert json.loads(json.dumps(sm.build(), sort_keys=True)) == json.loads(sm.OUT.read_text())

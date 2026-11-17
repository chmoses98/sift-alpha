"""Phase 10 progress log: every number is recomputed from evidence, statuses are not merged, nothing is model-active."""
import json

from alpha_engine.foundation import phase10 as P
from alpha_engine.foundation.contract import OPS, ROOT


def _j(p):
    return json.loads(p.read_text())


def test_progress_file_is_regenerated_from_evidence():
    assert _j(OPS / "phase10_progress.json") == json.loads(json.dumps(P.build()))
    assert (ROOT / "docs/PHASE10_DATA_PRESERVATION.md").read_text() == P.md(P.build())


def test_training_ready_matches_catalog_and_certification():
    o = P.build(); plan = _j(OPS / "acquisition_plan.json")["totals"]
    assert o["training_ready"]["after"] == plan["training_ready_inputs"] == sum(o["training_ready"]["by_sport"].values()) + sum(
        1 for v in _j(OPS / "acquisition_inputs.json")["inputs"].values() if v["tr"]["state"] == "TRAINING_READY" and v["s"] not in P.SPORTS)
    assert o["training_ready"]["after"] - o["training_ready"]["baseline"]["training_ready_inputs"] == len(o["training_ready"]["promoted_by_certification"]) + len(o["training_ready"]["promoted_by_archived_data"]) == 13   # 7 in Phase 10/11; +5 certified and +1 data-held in Phase 12
    assert o["training_ready"]["model_active"] == 0 and all(v["hash"] for v in o["dataset_versions"])
    hashes = {v["hash"] for v in o["dataset_versions"]}      # a superseded version must point at a registered successor (Phase 12: NFL d0616511 -> 9c1893bd)
    assert all((not v["superseded_by"]) or v["superseded_by"] in hashes or any(h.startswith(v["superseded_by"][:12]) for h in hashes) for v in o["dataset_versions"])


def test_vault_and_official_evidence_are_consistent():
    o = P.build(); v = o["vault"]
    assert v["verify"]["archives_bad"] == 0 and v["verify"]["archives_ok"] == v["totals"]["archives"] and v["verify"]["deep"] is True
    assert sum(x["stored_bytes"] for x in v["by_sport"].values()) == v["totals"]["stored_bytes"] == v["verify"]["bytes_verified"]
    assert all(x["archives"] >= 1 for x in v["by_sport"].values())
    k = o["official_settlements"]
    assert {x["sport"] for x in k["sports"]} == set(P.SPORTS) and sum(x["markets"] for x in k["sports"]) == k["total_markets"]
    assert all(sum(x["classes"].values()) == x["markets"] for x in k["sports"])
    raw = (ROOT / "research/phase10/kalshi_official.json").read_text()
    assert '"ticker"' not in raw and '"rules_primary"' not in raw          # counts only: no provider rows in this public repository
    r = o["settlement_repair"]
    assert r["status"] == "DRAFT_PR_NOT_MERGED" and r["discrepancies"]["new_matches_official"] == r["discrepancies"]["contracts"] == 93

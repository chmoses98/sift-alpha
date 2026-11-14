"""Register catalog inputs that have no computable-status entry yet as NOT_COMPUTED (RESEARCH_ONLY). Idempotent.

No feature code is run: while predictive/feature work is paused, a newly registered input is NOT_COMPUTED until a builder is genuinely implemented and passes the point-in-time verification.
Usage: python -m alpha_engine.input_research.register_new_inputs
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "research/input_research/computable_inputs.json"
RD = ROOT / "research/input_research/data_readiness.json"


def register() -> list[str]:
    d = json.loads(CI.read_text()); rd = json.loads(RD.read_text())
    added = []
    for key, r in rd["inputs"].items():
        if key in d["inputs"]:
            continue
        sport, iid = key.split(":", 1)
        status = r.get("status") or r.get("readiness") or "MISSING"
        d["inputs"][key] = {"sport": sport, "id": iid, "status": "NOT_COMPUTED", "reason": f"added by the catalog-completeness phase; no feature computation attempted while feature/predictive work is paused (raw-data readiness: {status})", "blockers": []}
        added.append(key)
    if added:
        tot = collections.Counter(v["status"] for v in d["inputs"].values()); d["totals"] = dict(tot)
        bs = collections.defaultdict(collections.Counter)
        for v in d["inputs"].values():
            bs[v["sport"]][v["status"]] += 1
        d["by_sport"] = {s: dict(c) for s, c in bs.items()}
        d["n_inputs"] = len(d["inputs"]); d["n_non_market"] = d["n_inputs"] - tot.get("EXCLUDED_BENCHMARK_ONLY", 0)
        n = sum(1 for v in d["inputs"].values() if "catalog-completeness" in v.get("reason", ""))
        d["catalog_completeness_extension"] = f"{n} inputs added by the catalog-completeness phase were registered NOT_COMPUTED without running feature code (no raw data in this environment; feature work paused)."
        CI.write_text(json.dumps(d, indent=0, sort_keys=True))
    return added


if __name__ == "__main__":
    print(register())

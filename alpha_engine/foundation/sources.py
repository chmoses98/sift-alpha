"""Operation Data Foundation: source acquisition board (RESEARCH_ONLY).

Rolls the ranked dataset queue of the pipeline ledger up to the SOURCE level, so the owner can see which single source decision
unlocks the most missing PRIMARY input slots. It joins three committed facts and adds none of its own:

  * research/data_foundation_ops/pipeline_ledger.json  (queue rows, dataset -> sources, rights tier, access status, cost)
  * research/data_foundation_ops/collectors.json        (what collector, if any, was observed)
  * research/data_foundation_ops/source_probe.json      (one reachability observation per host; reachable is not permission)

A source is never shown as usable here: the rights tier is copied from the map unchanged, and ``decision_needed`` states what
the owner would have to record before any collection or builder work. Slots are counted per (dataset, source) pair, so a
dataset with two candidate sources counts toward both; the per-source numbers therefore do not add up to the 949 total.
"""
from __future__ import annotations

import json

from .contract import OPS, write_json

SCHEMA = "sift-foundation-sources/1"
P0 = ("NBA", "CBB", "NHL")


def _decision(row: dict) -> str:
    if row["paid_or_no_free_source"] and not row["archived_slots"]:
        return "PAID_OR_NO_FREE_SOURCE: a budget decision; nothing is purchased or requested by this system"
    if row["archived_slots"]:
        return ("RIGHTS_DECISION_ON_ARCHIVED_DATA: the data is already in an owner repository; the owner reads the provider terms and "
                "records whether internal research use is cleared. No collection is needed to start builder work")
    if row["prospective_slots"]:
        return "PROSPECTIVE_CAPTURE_SCHEDULE: no historical source exists; needs an owner-approved capture schedule"
    if row["reachability"] == "DENIED_BY_ENVIRONMENT":
        return "RIGHTS_DECISION_AND_NETWORK_ACCESS: owner reads the terms, then allows the host in the environment's network policy"
    return "RIGHTS_DECISION: owner reads the provider terms and records a decision before any collection"


def build() -> dict:
    ledger = json.loads((OPS / "pipeline_ledger.json").read_text())
    probe = json.loads((OPS / "source_probe.json").read_text())
    collectors = json.loads((OPS / "collectors.json").read_text())["by_source"]
    reach: dict[str, list] = {}
    for host, h in sorted(probe["hosts"].items()):
        for s in h["sources"]:
            reach.setdefault(s, []).append({"host": host, "result": h["result"]})
    rows: dict[str, dict] = {}
    for q in ledger["queue"]:
        ds = ledger["datasets"][q["dataset"]]
        for s in ds.get("sources") or ["none_recorded"]:
            r = rows.setdefault(s, {"source": s, "sports": set(), "datasets": [], "missing_primary_slots": 0, "p0_missing_primary_slots": 0,
                                    "archived_slots": 0, "prospective_slots": 0, "paid_or_no_free_source": False,
                                    "rights_tiers": set(), "costs": set(), "markets": 0})
            n = q["missing_primary_slots"]
            r["sports"].update(q["sports"]); r["datasets"].append(q["dataset"]); r["missing_primary_slots"] += n
            if q["tier"] == "P0":
                r["p0_missing_primary_slots"] += n
            if q["access_status"] == "COLLECTED_ARCHIVE":
                r["archived_slots"] += n
            if q["access_status"] == "PROSPECTIVE_CAPTURE_ONLY":
                r["prospective_slots"] += n
            if q["access_status"] in ("PAID_ONLY", "NO_FREE_SOURCE"):
                r["paid_or_no_free_source"] = True
            r["rights_tiers"].add(q["rights_tier"]); r["costs"].add(q["cost"]); r["markets"] = max(r["markets"], q["distinct_archetypes"])
    out = []
    for s, r in rows.items():
        hosts = reach.get(s, [])
        results = {h["result"] for h in hosts}
        r["reachability"] = ("NOT_PROBED" if not hosts else "REACHABLE" if "REACHABLE" in results
                             else "REFUSED_BY_PROVIDER" if "REFUSED_BY_PROVIDER" in results else "DENIED_BY_ENVIRONMENT")
        r["hosts"] = hosts
        c = collectors.get(s)
        r["collector"] = {"collector": c["collector"], "repo": c.get("repo"), "state": c["state"]} if c else {"collector": None, "repo": None, "state": "NO_COLLECTOR_RECORDED"}
        r["terms_read"] = False
        r["sports"] = sorted(r["sports"]); r["datasets"] = sorted(set(r["datasets"]))
        r["rights_tiers"] = sorted(r["rights_tiers"]); r["costs"] = sorted(r["costs"])
        r["decision_needed"] = _decision(r)
        out.append(r)
    out.sort(key=lambda r: (-r["p0_missing_primary_slots"], -r["missing_primary_slots"], r["source"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    p0q = [q for q in ledger["queue"] if q["tier"] == "P0"]
    by_group: dict[str, int] = {}
    for q in p0q:
        k = q["action_group"] + " / " + q["access_status"]
        by_group[k] = by_group.get(k, 0) + q["missing_primary_slots"]
    return {
        "schema": SCHEMA, "status": "RESEARCH_ONLY",
        "notice": ("Sources ranked by the missing PRIMARY input slots behind them. Reachable is not permission, and a located source is not "
                   "acquired data. No provider terms were read in this pass, so no rights tier changed and no new external data was collected."),
        "probe_observed_utc": probe["observed_utc"], "terms_reading": probe["terms_reading"],
        "new_external_records_acquired": 0,
        "p0_slots_by_blocker": dict(sorted(by_group.items(), key=lambda kv: -kv[1])),
        "counting_note": "A dataset with several candidate sources counts toward each, so source rows do not sum to the map's 949 slots.",
        "sources": out,
    }


def main() -> None:
    doc = build()
    write_json(OPS / "source_acquisition.json", doc)
    print(f"sources {len(doc['sources'])}; top: " + ", ".join(f"{r['source']}={r['p0_missing_primary_slots']}" for r in doc["sources"][:6]))


if __name__ == "__main__":
    main()

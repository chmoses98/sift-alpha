"""Operation Data Foundation: source acquisition board (RESEARCH_ONLY).

Rolls the ranked dataset queue of the pipeline ledger up to the SOURCE level, so the owner can see which single source decision
unlocks the most missing PRIMARY input slots. It joins three committed facts and adds none of its own:

  * research/data_foundation_ops/pipeline_ledger.json  (queue rows, dataset -> sources, rights tier, access status, cost)
  * research/data_foundation_ops/collectors.json        (what collector, if any, was observed)
  * research/data_foundation_ops/source_probe.json      (one reachability observation per host; reachable is not permission)

A source is never shown as usable here: the rights tier is copied from the map unchanged, and ``decision_needed`` states what
is needed next. Slots are DISTINCT (market, input) pairs taken from the map queue; a slot behind two sources counts toward
both rows, so rows do not add up to the distinct totals in ``p0_distinct``. Terms evidence comes from provider_terms.json.
"""
from __future__ import annotations

import json

from .contract import OPS, ROOT, write_json

SCHEMA = "sift-foundation-sources/2"
MAP = ROOT / "research/input_research/market_input_map/map.json"
P0 = ("NBA", "CBB", "NHL")


def _decision(row: dict) -> str:
    if row["paid_or_no_free_source"] and not row["archived_slots"]:
        return "PAID_OR_NO_FREE_SOURCE: a budget decision; nothing is purchased or requested by this system"
    if row["archived_slots"]:
        return ("BUILD_FROM_ARCHIVE: the data is already in an owner repository and its tier (internal research only) already permits builder "
                "work, so the next step is engineering: write and blind-verify builders. A recorded owner rights decision is needed only "
                "before anything beyond internal research (redistribution, commercial use) or before NEW collection from the provider")
    if row["prospective_slots"]:
        return "PROSPECTIVE_CAPTURE_SCHEDULE: no historical source exists; needs an owner-approved capture schedule"
    if row["reachability"] == "DENIED_BY_ENVIRONMENT":
        return "RIGHTS_DECISION_AND_NETWORK_ACCESS: owner reads the terms, then allows the host in the environment's network policy"
    return "RIGHTS_DECISION: owner reads the provider terms and records a decision before any collection"


def _slots(m: dict) -> dict:
    """dataset -> set of distinct missing PRIMARY slots (archetype, input) recorded behind it in the map queue."""
    return {q["dataset"]: {(x[0], x[1]) for x in q["slots"]} for q in m["queue"]}


def build() -> dict:
    ledger = json.loads((OPS / "pipeline_ledger.json").read_text())
    probe = json.loads((OPS / "source_probe.json").read_text())
    collectors = json.loads((OPS / "collectors.json").read_text())["by_source"]
    terms = json.loads((OPS / "provider_terms.json").read_text())
    slots = _slots(json.loads(MAP.read_text()))
    prov_of = {s: p for p in terms["providers"] for s in p["sources"]}
    is_p0 = lambda slot: slot[0].split(":")[0] in P0
    reach: dict[str, list] = {}
    for host, h in sorted(probe["hosts"].items()):
        for s in h["sources"]:
            reach.setdefault(s, []).append({"host": host, "result": h["result"]})
    rows: dict[str, dict] = {}
    for q in ledger["queue"]:
        ds = ledger["datasets"][q["dataset"]]
        for s in ds.get("sources") or ["none_recorded"]:
            r = rows.setdefault(s, {"source": s, "datasets": [], "_all": set(), "_arch": set(), "_pros": set(), "paid_or_no_free_source": False,
                                    "rights_tiers": set(), "costs": set()})
            sl = slots[q["dataset"]]
            r["datasets"].append(q["dataset"]); r["_all"] |= sl
            if q["access_status"] == "COLLECTED_ARCHIVE":
                r["_arch"] |= sl
            if q["access_status"] == "PROSPECTIVE_CAPTURE_ONLY":
                r["_pros"] |= sl
            if q["access_status"] in ("PAID_ONLY", "NO_FREE_SOURCE"):
                r["paid_or_no_free_source"] = True
            r["rights_tiers"].add(q["rights_tier"]); r["costs"].add(q["cost"])
    out = []
    for s, r in rows.items():
        al, ar, pr = r.pop("_all"), r.pop("_arch"), r.pop("_pros")
        r["sports"] = sorted({x[0].split(":")[0] for x in al})
        r["markets"] = len({x[0] for x in al})
        r["missing_primary_slots"] = len(al); r["p0_missing_primary_slots"] = sum(map(is_p0, al))
        r["archived_slots"] = len(ar); r["p0_archived_slots"] = sum(map(is_p0, ar)); r["prospective_slots"] = len(pr)
        hosts = reach.get(s, [])
        results = {h["result"] for h in hosts}
        r["reachability"] = ("NOT_PROBED" if not hosts else "REACHABLE" if "REACHABLE" in results
                             else "REFUSED_BY_PROVIDER" if "REFUSED_BY_PROVIDER" in results else "DENIED_BY_ENVIRONMENT")
        r["hosts"] = hosts
        c = collectors.get(s)
        r["collector"] = {"collector": c["collector"], "repo": c.get("repo"), "state": c["state"]} if c else {"collector": None, "repo": None, "state": "NO_COLLECTOR_RECORDED"}
        p = prov_of.get(s)
        r["terms_status"] = p["terms_status"] if p else "NOT_ATTEMPTED"
        r["terms_read"] = r["terms_status"] == "READ_DIRECT"      # only the governing document itself, fetched; a repo licence or a snippet is not
        r["terms"] = ({"provider": p["name"], "assessment": p["assessment"], "owner_decision_needed": p.get("owner_decision_needed"),
                       "lead_note": p.get("lead_note"), "documents": [d["url"] for d in p["documents"] if d.get("reached")]} if p else None)
        r["datasets"] = sorted(set(r["datasets"]))
        r["rights_tiers"] = sorted(r["rights_tiers"]); r["costs"] = sorted(r["costs"])
        r["decision_needed"] = _decision(r)
        out.append(r)
    out.sort(key=lambda r: (-r["p0_missing_primary_slots"], -r["missing_primary_slots"], r["source"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    # Distinct P0 slots. A slot can sit behind several datasets, so per-dataset sums (the earlier "492") count it more than once.
    need: dict[tuple, set] = {}
    for q in ledger["queue"]:
        for sl in slots[q["dataset"]]:
            if is_p0(sl):
                need.setdefault(sl, set()).add(q["action_group"] + " / " + q["access_status"])
    arch = "COLLECTED_ARCHIVE"
    by_sport = lambda pred: {sp: sum(1 for k, v in need.items() if k[0].startswith(sp + ":") and pred(v)) for sp in P0}
    any_arch = lambda v: any(g.endswith(arch) for g in v)
    only_arch = lambda v: all(g.endswith(arch) for g in v)
    by_group: dict[str, int] = {}
    for v in need.values():
        for g in v:
            by_group[g] = by_group.get(g, 0) + 1
    p0_distinct = {
        "missing_primary_slots": len(need), "by_sport": by_sport(lambda v: True),
        "with_an_archived_dataset": sum(map(any_arch, need.values())), "with_an_archived_dataset_by_sport": by_sport(any_arch),
        "archived_datasets_only": sum(map(only_arch, need.values())), "archived_datasets_only_by_sport": by_sport(only_arch),
        "per_dataset_sum_previously_reported": sum(q["missing_primary_slots"] for q in ledger["queue"] if q["tier"] == "P0" and q["access_status"] == arch),
        "note": ("Counted once per (market, input) slot whose market is NBA, CBB or NHL. The per-dataset sum reported earlier counted a slot once "
                 "for every dataset it lists and included other sports' slots of shared datasets; it is kept only for traceability."),
    }
    return {
        "schema": SCHEMA, "status": "RESEARCH_ONLY",
        "notice": ("Sources ranked by the distinct missing PRIMARY input slots behind them. Reachable is not permission, and a located source is "
                   "not acquired data. Terms evidence is an agent reading (research/data_foundation_ops/provider_terms.json), not legal advice "
                   "and not an owner decision: no rights tier changed and no new external data was collected."),
        "probe_observed_utc": probe["observed_utc"], "terms_reading": terms["notice"], "terms_fetched_utc": terms["fetched_utc"],
        "new_external_records_acquired": 0,
        "p0_distinct": p0_distinct,
        "p0_slots_by_blocker": dict(sorted(by_group.items(), key=lambda kv: -kv[1])),
        "counting_note": "A slot behind several datasets or sources counts toward each, so rows do not sum to the distinct totals above.",
        "public_repository_exposure": terms.get("public_repository_exposure"),
        "free_alternatives": terms["free_alternatives"], "free_alternatives_note": terms["free_alternatives_note"],
        "sources": out,
    }


def main() -> None:
    doc = build()
    write_json(OPS / "source_acquisition.json", doc)
    print(f"sources {len(doc['sources'])}; top: " + ", ".join(f"{r['source']}={r['p0_missing_primary_slots']}" for r in doc["sources"][:6]))


if __name__ == "__main__":
    main()

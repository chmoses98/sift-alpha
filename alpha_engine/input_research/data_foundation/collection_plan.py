"""Prioritised free-dataset collection plan (RESEARCH_ONLY): what can be had historically, what must start prospective capture immediately, what waits for a host decision.

Ranked by breadth: distinct ARCHETYPES touched first (a dataset that feeds many market archetypes across sports matters most), then inputs that depend on it. Computed from the committed audit rows
and registry; nothing is a performance claim and nothing here collects data.
"""
from __future__ import annotations

import json

from . import evidence as EV

DF = EV.DF
REACHABLE_SOURCES = {"nflverse", "espn_json", "mlb_statsapi", "nhl_api", "football_data_uk", "kalshi_api", "statsbomb_open", "chadwick", "nba_official", "openfootball", "espn_cbb", "sackmann"}


def build() -> dict:
    rows = json.loads((DF / "input_audit.json").read_text())["rows"]; reg = json.loads((DF / "datasets.json").read_text())["datasets"]
    dep = {}
    for r in rows:
        if r["bucket"] == "EXCLUDED":
            continue
        for x in r["requirements"]:
            d = x["satisfied_by"]
            if d:
                e = dep.setdefault(d, {"inputs": set(), "archetypes": set(), "sports": set(), "not_yet_computable": set()})
                e["inputs"].add(r["key"]); e["sports"].add(r["sport"]); e["archetypes"].update(f"{r['sport']}:{a}" for a in r["archetypes"])
                if r["bucket"] != "COMPUTABLE":
                    e["not_yet_computable"].add(r["key"])
    items = []
    for d, e in dep.items():
        v = reg[d]; st = v["access_status"]
        if st == "COLLECTED_ARCHIVE":
            continue
        feasible_now = bool(set(v["sources"]) & REACHABLE_SOURCES)
        if st in ("PAID_ONLY", "NO_FREE_SOURCE", "SAMPLE_ONLY"):
            cls = "D_BLOCKED_OR_SAMPLE_ONLY"
        elif st == "PROSPECTIVE_CAPTURE_ONLY" or v["pit"] == "LIVE_SNAPSHOT":
            cls = "B_PROSPECTIVE_CAPTURE_START_NOW" if feasible_now else "C_PROSPECTIVE_NEEDS_PERMITTED_HOST"
        elif st in ("FREE_REACHABLE", "REFERENCE_DOCUMENT") or (st == "FREE_PATH_UNCONFIRMED" and feasible_now):
            cls = "A_HISTORICAL_BACKFILL_NOW"
        else:
            cls = "C_NEEDS_HOST_DECISION"
        items.append({"dataset": d, "title": v["title"][:90], "class": cls, "access_status": st, "pit": v["pit"], "history": [v["history"]["first"], v["history"]["last"]], "tos_risk": v["tos_risk"], "cost": v["cost"], "sources": v["sources"],
                      "archetypes_touched": len(e["archetypes"]), "inputs_depending": len(e["inputs"]), "not_yet_computable_inputs": len(e["not_yet_computable"]), "sports": sorted(e["sports"])})
    items.sort(key=lambda x: (x["class"], -x["archetypes_touched"], -x["inputs_depending"]))
    return {"schema_version": "collection-plan-1.0", "status": "RESEARCH_ONLY", "classes": {"A_HISTORICAL_BACKFILL_NOW": "free, history exists, host already reachable: pull and build (no vintage problem)", "B_PROSPECTIVE_CAPTURE_START_NOW": "no usable history: start recording from a host that is already reachable today; every day of delay is history that is lost",
            "C_PROSPECTIVE_NEEDS_PERMITTED_HOST": "vintage data whose only free feed is on a host not currently reachable or restricted", "C_NEEDS_HOST_DECISION": "free and historical but the host is blocked from the runner (see NETWORK_ACCESS_PROPOSAL.md)", "D_BLOCKED_OR_SAMPLE_ONLY": "paid, none found, or only a free sample"}, "items": items}


def render(p: dict) -> list[str]:
    L = ["## Prioritised free datasets: historical backfill vs immediate prospective capture", "", "Ranked within each class by archetypes touched (breadth across market archetypes and sports), then inputs depending. Collected archives are omitted. No dataset here has been collected by this phase beyond the replay caches.", ""]
    for cls, desc in p["classes"].items():
        its = [x for x in p["items"] if x["class"] == cls]
        if not its:
            continue
        L += [f"### {cls}: {desc}", "", "| Dataset | Archetypes touched | Inputs depending (not yet computable) | Sports | Access status | PIT class | History | ToS risk | Cost |", "|---|---|---|---|---|---|---|---|---|"]
        for x in its[:14]:
            L.append(f"| `{x['dataset']}` {x['title'][:48]} | {x['archetypes_touched']} | {x['inputs_depending']} ({x['not_yet_computable_inputs']}) | {', '.join(x['sports'])} | {x['access_status']} | {x['pit']} | {x['history'][0] or '?'}–{x['history'][1] or '?'} | {x['tos_risk']} | {x['cost']} |")
        L.append("")
    return L

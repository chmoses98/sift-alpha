"""Market-first coverage: sport -> market family -> required inputs -> coverage class -> source -> gap -> next action (RESEARCH_ONLY).

    python -m alpha_engine.foundation.market_coverage [--freeze-baseline GIT_REF]

A read-only join of artifacts that already exist (market-input map, acquisition plan and inputs, dataset versions, vault ledger).
It adds no research and changes no status; it only names, for every predictive input of the six core sports, exactly ONE coverage class:

  CERTIFIED       training-ready: every core readiness check holds at the stated prediction cutoff
  UNVERIFIED      feature code exists and the raw data is archived, but the input is not independently verified FULL (or its history / PIT check is partial)
  NOT_BUILT       every raw data need is archived; no feature implementation yet
  NO_PREGAME_HISTORY  the pregame snapshot the input needs was never published with a timestamp (forward capture only): cannot be honestly reconstructed
  RIGHTS_BLOCKED  a data need is not archived and no source with a rights reading permits collecting it
  PAID_OR_NO_SOURCE   a data need has only paid sources or no known source
  DATA_MISSING    a data need is not archived (free source exists or is unprobed)

"Raw data archived" is a property of a DATASET (vault ledger / repo ledgers), shown per data need; it is never by itself a certified input.
Writes research/data_foundation_ops/market_coverage.json (+ phase12_baseline.json once, from a git ref, as the frozen "before").
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter

from .contract import OPS, ROOT, write_json

CORE = ["MLB", "CFB", "CBB", "NFL", "NBA", "NHL"]
CLASSES = ["CERTIFIED", "UNVERIFIED", "NOT_BUILT", "NO_PREGAME_HISTORY", "RIGHTS_BLOCKED", "PAID_OR_NO_SOURCE", "DATA_MISSING"]
CLASS_LABEL = {"CERTIFIED": "Certified (training-ready)", "UNVERIFIED": "Built, not independently verified", "NOT_BUILT": "Data archived, feature not built",
               "NO_PREGAME_HISTORY": "No historical pregame snapshot", "RIGHTS_BLOCKED": "Blocked by provider rights", "PAID_OR_NO_SOURCE": "Paid or no known source",
               "DATA_MISSING": "Raw data not archived"}
NEXT = {"CERTIFIED": "Use in preregistered discovery studies; no data work needed.",
        "UNVERIFIED": "Blind re-implementation + leakage suite on a registered dataset version.",
        "NOT_BUILT": "Write the feature spec and builder from the archived data.",
        "NO_PREGAME_HISTORY": "Forward capture only (inactive collector proposal); history starts at the first capture.",
        "RIGHTS_BLOCKED": "Owner rights decision for the source.", "PAID_OR_NO_SOURCE": "Owner purchase decision or drop the input.",
        "DATA_MISSING": "Probe and archive the free source into the vault."}
NO_HIST_PIT = {"PIT_UNAVAILABLE_HISTORICALLY", "NOT_PREGAME_KNOWABLE", "PIT_LEAKY_FINAL_ONLY"}


def classify(inp: dict, ds: dict, rights_blocked: set) -> tuple[str, list]:
    """One class per input + the unmet data needs [(need, [candidate datasets])]."""
    st = inp["tr"]["state"]; c = inp["tr"]["c"]
    unmet = [(n[0], n[2]) for n in inp["n"] if not any(ds.get(d, {}).get("held") for d in n[2])]
    if st == "TRAINING_READY":
        return "CERTIFIED", []
    if inp["pit"] in NO_HIST_PIT or any(d and all(ds.get(x, {}).get("a") == "PROSPECTIVE_CAPTURE_ONLY" for x in d) for _, d in unmet):
        return "NO_PREGAME_HISTORY", unmet
    if not unmet and inp["n"]:
        return ("UNVERIFIED" if c["built"] in ("OK", "PARTIAL") else "NOT_BUILT"), []
    cands = [x for _, d in unmet for x in d]
    if cands and all(ds.get(x, {}).get("a") in ("PAID_ONLY", "NO_FREE_SOURCE") for x in cands):
        return "PAID_OR_NO_SOURCE", unmet
    if cands and any(x in rights_blocked for x in cands) and all(x in rights_blocked or ds.get(x, {}).get("a") in ("PAID_ONLY", "NO_FREE_SOURCE") for x in cands):
        return "RIGHTS_BLOCKED", unmet
    return "DATA_MISSING", unmet


def build(plan: dict, acq: dict, m: dict) -> dict:
    ds = acq["datasets"]; I = acq["inputs"]
    rights_blocked = {x["dataset"] for x in plan["shortlist"] if any(str(b).startswith("RIGHTS") for b in x.get("blockers") or [])}
    inputs = {}
    for k, v in I.items():
        if v["s"] not in CORE:
            continue
        cls, unmet = classify(v, ds, rights_blocked)
        srcs = sorted({d for n in v["n"] for d in n[2]})
        inputs[k] = {"l": v["l"], "cls": cls, "st": v["tr"]["state"], "pit": v["pit"], "chk": v["tr"]["c"], "src": [[d, bool(ds.get(d, {}).get("held"))] for d in srcs],
                     "gap": "; ".join(f"{n}: {', '.join(d) or 'no dataset recorded'}" for n, d in unmet) or v["tr"]["blocker"],
                     "cert": (v["tr"].get("cert") or {}).get("dataset")}
    sports = {}
    arch = [a for a in m["archetypes"] if a["sport"] in CORE]
    by_arch: dict = {}
    for e in m["edges"]:
        if e[3] == "PREDICTIVE" and e[1] in inputs:
            by_arch.setdefault(e[0], []).append((e[1], e[2]))
    for s in CORE:
        mk = []
        for a in arch:
            if a["sport"] != s:
                continue
            es = by_arch.get(a["k"], [])
            prim = [i for i, r in es if r == "primary"]
            cc = Counter(inputs[i]["cls"] for i, _ in es); pc = Counter(inputs[i]["cls"] for i in prim)
            worst = next((c for c in ("DATA_MISSING", "NOT_BUILT", "UNVERIFIED", "NO_PREGAME_HISTORY", "RIGHTS_BLOCKED", "PAID_OR_NO_SOURCE") if pc.get(c)), None)
            top = Counter(d for i in prim for d, held in inputs[i]["src"] if not held and inputs[i]["cls"] in ("DATA_MISSING", "RIGHTS_BLOCKED", "NO_PREGAME_HISTORY")).most_common(1)
            nxt = "All primary inputs certified." if prim and pc.get("CERTIFIED") == len(prim) else (NEXT[worst] if worst else "No primary predictive input mapped.")
            if top and worst in ("DATA_MISSING", "RIGHTS_BLOCKED", "NO_PREGAME_HISTORY"):
                nxt += f" Largest single unlock: {top[0][0]} ({top[0][1]} primary inputs)."
            mk.append({"k": a["k"], "label": a["label"], "series": sorted({x for v in (a.get("series") or {}).values() for x in v})[:12],
                       "n": len(es), "n_primary": len(prim), "cls": {c: cc[c] for c in CLASSES if cc.get(c)}, "primary_cls": {c: pc[c] for c in CLASSES if pc.get(c)},
                       "certified_primary_share": round(pc.get("CERTIFIED", 0) / len(prim), 3) if prim else None, "next": nxt,
                       "inputs": sorted([[i, r] for i, r in es], key=lambda x: (x[1] != "primary", CLASSES.index(inputs[x[0]]["cls"]), x[0]))})
        mk.sort(key=lambda x: (-(x["primary_cls"].get("CERTIFIED", 0)), -x["n_primary"], x["k"]))
        mine = [v for k, v in inputs.items() if k.startswith(s + ":")]
        p = plan["sports"][s]
        sports[s] = {"inputs": len(mine), "cls": {c: sum(1 for v in mine if v["cls"] == c) for c in CLASSES}, "markets": mk,
                     "missing_primary_inputs": p["missing_primary_inputs"], "missing_primary_slots": p["missing_primary_slots"], "data_complete_missing_inputs": p["complete_with_archives"]}
    tot = {"inputs": len(inputs), "cls": {c: sum(1 for v in inputs.values() if v["cls"] == c) for c in CLASSES},
           "missing_primary_inputs": sum(sports[s]["missing_primary_inputs"] for s in CORE), "missing_primary_slots": sum(sports[s]["missing_primary_slots"] for s in CORE),
           "data_complete_missing_inputs": sum(sports[s]["data_complete_missing_inputs"] for s in CORE)}
    return {"sports": sports, "inputs": inputs, "totals": tot}


def _load(ref: str | None):
    def rd(p):
        if ref:
            return json.loads(subprocess.run(["git", "show", f"{ref}:{p}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        return json.loads((ROOT / p).read_text())
    return rd("research/data_foundation_ops/acquisition_plan.json"), rd("research/data_foundation_ops/acquisition_inputs.json"), rd("research/input_research/market_input_map/map.json")


def summary(b: dict) -> dict:
    return {"totals": b["totals"], "sports": {s: {k: v for k, v in x.items() if k != "markets"} for s, x in b["sports"].items()},
            "markets": {m["k"]: m["primary_cls"] for x in b["sports"].values() for m in x["markets"]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--freeze-baseline", help="git ref of the 'before' state; written once to phase12_baseline.json")
    a = ap.parse_args(argv)
    bp = OPS / "phase12_baseline.json"
    if a.freeze_baseline:
        sha = subprocess.run(["git", "rev-parse", a.freeze_baseline], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        write_json(bp, {"schema": "phase12-baseline-1.0", "status": "RESEARCH_ONLY", "git_ref": sha, "note": "Coverage classes computed by market_coverage.build over the artifacts at this commit (end of Phase 11).",
                        **summary(build(*_load(a.freeze_baseline)))})
    now = build(*_load(None))
    base = json.loads(bp.read_text()) if bp.exists() else None
    vl = ROOT / "research/input_research/data_collection/vault_ledger.json"
    vault = json.loads(vl.read_text()) if vl.exists() else {"datasets": {}, "vault_archives": {}}
    from ..input_research.data_foundation import datasets as DS
    linked = {k for keys in DS.VAULT_EVIDENCE.values() for k in keys}
    out = {"schema": "market-coverage-1.0", "status": "RESEARCH_ONLY",
           "notice": "Read-only join of committed artifacts; agent-run, not human verified. A class describes data and verification state only: no claim about predictive value or betting edge.",
           "classes": CLASSES, "class_label": CLASS_LABEL, "next_action": NEXT, "sports_order": CORE,
           "before": {k: base[k] for k in ("git_ref", "totals", "sports", "markets")} if base else None, "now": summary(now)["totals"], **now,
           "vault": {"archives": len(vault.get("vault_archives", {})), "measured_entries": len(vault["datasets"]),
                     "measured_not_linked_to_a_dataset": sorted(k for k in vault["datasets"] if k not in linked),
                     "entries": {k: {x: v.get(x) for x in ("games", "rows", "date_min", "date_max", "scope_note")} for k, v in vault["datasets"].items()}}}
    write_json(OPS / "market_coverage.json", out)
    print(json.dumps({"now": out["now"], "before": (base or {}).get("totals")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

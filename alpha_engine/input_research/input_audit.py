"""Audit of the candidate-input catalog: definitions, measurement, required raw data, provenance and market-free eligibility (RESEARCH_ONLY).

Two layers:
 1. `mechanical()` runs on EVERY input (no judgement): market-derivation markers, missing raw-data definition, thin measurement, unsourced inputs, near-duplicate definitions inside a sport.
 2. Reviewer files research/input_research/completeness/input_audit/<SPORT>*.json judge the inputs added by the completeness review (substantive definition, provenance, market-free class, duplicates)
    and may supply corrected text; `apply()` writes accepted corrections into the catalog and the review records (kept identical so the gate's idempotency check holds).
A reviewer verdict is a Claude agent's judgement, never human expert verification.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from . import catalog as cat
from . import completeness as comp

ROOT = Path(__file__).resolve().parents[2]
AD = comp.CD / "input_audit"
SPORTS = comp.SPORTS
MARKET_CLASS = ("yes", "hybrid", "no")          # yes = fully market-free; hybrid = has a market-derived component but a market-free rebuild is defined; no = benchmark only
MKT = re.compile(r"\b(market[- ]implied|closing line|close line|de-?vig|implied (team )?total|implied probability|kalshi (price|quote|mid)|betting line|sportsbook|moneyline odds|point spread line|market price|over/under line|book(maker)? (line|odds)|ladder price)\b", re.I)


def rd(p):
    return json.loads(Path(p).read_text())


def new_input_ids(sport: str) -> set[str]:
    out = set()
    for rec in comp.load_reviews(sport).values():
        out.update((rec.get("new_inputs") or {}))
    return out


def mechanical() -> dict:
    res = {"schema_version": "input-audit-mechanical-1.0", "by_sport": {}, "inputs": {}}
    for s in SPORTS:
        c = cat.load(s); new = new_input_ids(s); cnt = collections.Counter()
        sh = {i: comp._shingles(f"{r['label']} {r['measurement']}", 4) for i, r in c["inputs"].items()}
        for iid, r in c["inputs"].items():
            f = []
            if MKT.search(" ".join([r["label"], r["mechanism"], r["measurement"]])) and not iid.startswith("m."):
                f.append("MARKET_MARKER_IN_DEFINITION")
            if iid.startswith("m.") or (r.get("registry_ids") and any(x.startswith("m.") for x in r["registry_ids"])):
                f.append("MARKET_REGISTRY_ID")
            if len(r["measurement"]) < 120:
                f.append("THIN_MEASUREMENT")
            if r["free_sources"] in (["NONE_FOUND"], ["none_found"]):
                f.append("NO_FREE_SOURCE")
            if iid in new and not r.get("raw_data"):
                f.append("MISSING_RAW_DATA")
            if r["pregame_knowable"] == "no":
                f.append("NOT_PREGAME_KNOWABLE")
            res["inputs"][iid] = {"sport": s, "new": iid in new, "flags": f}
            for x in f:
                cnt[x] += 1
        ids = list(c["inputs"])
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if len(sh[a]) < 8 or len(sh[b]) < 8:
                    continue
                j = len(sh[a] & sh[b]) / len(sh[a] | sh[b])
                if j >= 0.55:
                    res["inputs"][a]["flags"].append(f"NEAR_DUPLICATE_OF:{b}:{j:.2f}"); res["inputs"][b]["flags"].append(f"NEAR_DUPLICATE_OF:{a}:{j:.2f}"); cnt["NEAR_DUPLICATE"] += 1
        res["by_sport"][s] = {"inputs": len(ids), "new": len(new), **dict(cnt)}
    return res


def load_audit(sport: str) -> dict:
    out: dict = {}
    for f in sorted(AD.glob(f"{sport}*.json")) if AD.exists() else []:
        out.update(rd(f).get("inputs") or {})
    return out


def validate(sport: str, audit: dict) -> list[str]:
    e = []
    c = cat.load(sport); new = new_input_ids(sport)
    for iid in new:
        if iid not in audit:
            e.append(f"{iid}: not audited")
    for iid, a in audit.items():
        if iid not in c["inputs"]:
            e.append(f"{iid}: not in catalog"); continue
        if a.get("market_free") not in MARKET_CLASS:
            e.append(f"{iid}: market_free must be one of {MARKET_CLASS}")
        if a.get("market_free") in ("hybrid", "no") and not comp._txt(a.get("market_note"), 40):
            e.append(f"{iid}: hybrid/no needs a market_note naming the market-derived component and any market-free rebuild")
        if a.get("verdict") not in ("OK", "FIXED", "WEAK", "DUPLICATE", "REMOVE_CANDIDATE"):
            e.append(f"{iid}: verdict must be OK|FIXED|WEAK|DUPLICATE|REMOVE_CANDIDATE")
        if a.get("verdict") == "DUPLICATE" and a.get("duplicate_of") not in c["inputs"]:
            e.append(f"{iid}: DUPLICATE needs duplicate_of an existing input id")
        if a.get("verdict") == "FIXED" and not comp._txt(a.get("measurement_fix"), 120):
            e.append(f"{iid}: FIXED needs measurement_fix (>=120 chars)")
        if not isinstance(a.get("raw_data"), list) or not a.get("raw_data"):
            e.append(f"{iid}: raw_data list required")
        pv = a.get("provenance") or {}
        if not pv.get("sources") or any(x.get("access") not in comp.ACCESS for x in pv["sources"]) or pv.get("verified") not in (True, False):
            e.append(f"{iid}: provenance needs sources [{{name,access}}] and verified true|false")
        if not comp._txt(a.get("assessment"), 50):
            e.append(f"{iid}: assessment must be a specific >=50 char judgement")
    return e


def apply() -> dict:
    """Write accepted corrections (measurement_fix, raw_data, market_free, provenance) into the catalog and, for new inputs, the review records."""
    stats = {}
    for s in SPORTS:
        audit = load_audit(s); c = cat.load(s); n = 0
        for iid, a in audit.items():
            r = c["inputs"].get(iid)
            if not r:
                continue
            if a.get("verdict") == "FIXED" and a.get("measurement_fix"):
                r["measurement"] = a["measurement_fix"]; n += 1
            r["raw_data"] = a["raw_data"]; r["market_free"] = a["market_free"]; r["provenance"] = a["provenance"]
            if a.get("market_note"):
                r["market_note"] = a["market_note"]
            if a.get("verdict") in ("DUPLICATE", "WEAK", "REMOVE_CANDIDATE"):
                r["audit_flag"] = {"verdict": a["verdict"], "duplicate_of": a.get("duplicate_of")}
        (cat.CATALOG_DIR / f"{s}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
        for f in sorted((comp.CD / "reviews").glob(f"{s}*.json")):
            d = rd(f); ch = False
            for rec in d.values():
                for iid, ni in (rec.get("new_inputs") or {}).items():
                    a = audit.get(iid)
                    if a and a.get("verdict") == "FIXED" and a.get("measurement_fix") and ni.get("measurement") != a["measurement_fix"]:
                        ni["measurement"] = a["measurement_fix"]; ch = True
                    if a and ni.get("raw_data") != a["raw_data"]:
                        ni["raw_data"] = a["raw_data"]; ch = True
            if ch:
                f.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
        stats[s] = {"audited": len(audit), "measurement_fixed": n}
    return stats


PATCH_FIELDS = ("label", "mechanism", "rationale", "measurement", "free_sources", "raw_data", "pregame_knowable", "registry_ids", "category")


def apply_patches() -> dict:
    """Catalog-definition corrections found while closing catalog blockers (input_patches/<SPORT>*.json = {input_id: {field: value}}). Applied to the catalog and mirrored into the review record that added the input."""
    stats = {}
    for s in SPORTS:
        d = comp.CD / "input_patches"; patches: dict = {}
        for f in sorted(d.glob(f"{s}*.json")) if d.exists() else []:
            patches.update(rd(f).get("patches") or {})
        if not patches:
            continue
        c = cat.load(s); n = 0
        for iid, fields in patches.items():
            if iid not in c["inputs"]:
                raise ValueError(f"{s}: patch for unknown input {iid}")
            for k, v in fields.items():
                if k not in PATCH_FIELDS:
                    raise ValueError(f"{s}:{iid}: field {k} not patchable")
                if k in ("mechanism", "rationale", "measurement") and len(str(v)) < 60:
                    raise ValueError(f"{s}:{iid}: {k} too thin")
                if c["inputs"][iid].get(k) != v:
                    c["inputs"][iid][k] = v; n += 1
        (cat.CATALOG_DIR / f"{s}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
        for f in sorted((comp.CD / "reviews").glob(f"{s}*.json")):
            dd = rd(f); ch = False
            for rec in dd.values():
                for iid, ni in (rec.get("new_inputs") or {}).items():
                    for k, v in (patches.get(iid) or {}).items():
                        if k in ni and ni[k] != v:
                            ni[k] = v; ch = True
            if ch:
                f.write_text(json.dumps(dd, indent=1, ensure_ascii=False) + "\n")
        stats[s] = {"patched_fields": n, "inputs": len(patches)}
    return stats


def apply_archetype_patches() -> dict:
    """Archetype-level catalog corrections (archetype_patches/<SPORT>*.json): relabel, retarget, detach inputs that do not belong, re-role attached inputs, attach existing inputs."""
    stats = {}
    for s in SPORTS:
        pt = comp.archetype_patches(s)
        if not pt:
            continue
        c = cat.load(s); n = collections.Counter()
        for k, v in pt.items():
            if k not in comp.arch_keys(c):
                raise ValueError(f"{s}: archetype patch for unknown archetype {k}")
            a = comp.arch_entry(c, k); have = {i["id"] for i in a["inputs"]}
            for fld in ("label", "target", "contract_types", "mechanism"):
                if fld in v and a.get(fld) != v[fld]:
                    if fld in ("mechanism",) and len(str(v[fld])) < 120:
                        raise ValueError(f"{s}:{k}: mechanism too thin")
                    a[fld] = v[fld]; n[fld] += 1
            for iid in v["detach"]:
                if iid in have:
                    a["inputs"] = [i for i in a["inputs"] if i["id"] != iid]; have.discard(iid); n["detached"] += 1
            if len(a["inputs"]) + len(v["attach"]) < 8:
                raise ValueError(f"{s}:{k}: an archetype needs >=8 inputs after detaching")
            for iid, role in v["roles"].items():
                if role not in ("primary", "secondary", "context"):
                    raise ValueError(f"{s}:{k}:{iid}: bad role")
                for i in a["inputs"]:
                    if i["id"] == iid and i["role"] != role:
                        i["role"] = role; n["roles"] += 1
            for drop in v.get("drop_interactions") or []:   # interactions that rest on an input the archetype no longer carries (matched by sorted input set)
                before = len(a["interactions"]); a["interactions"] = [x for x in a["interactions"] if sorted(x["inputs"]) != sorted(drop)]; n["interactions_dropped"] += before - len(a["interactions"])
            for iid in v.get("drop_nonlinearities") or []:
                before = len(a.get("nonlinearities") or []); a["nonlinearities"] = [x for x in a.get("nonlinearities") or [] if x.get("input_id") != iid]; n["nonlinearities_dropped"] += before - len(a["nonlinearities"])
            for x in v["attach"]:
                if x["id"] not in c["inputs"] or len(str(x.get("why", ""))) < 30 or x.get("role") not in ("primary", "secondary", "context"):
                    raise ValueError(f"{s}:{k}: bad attach {x}")
                if x["id"] not in have:
                    a["inputs"].append({"id": x["id"], "why": x["why"], "role": x["role"]}); have.add(x["id"]); n["attached"] += 1
        used = ({i["id"] for b in c["blueprints"].values() for i in b["inputs"]} | {i["id"] for x in list(c["archetypes"].values()) + list((c.get("unregistered_archetypes") or {}).values()) for i in x["inputs"]})
        for iid, r in c["inputs"].items():
            if iid not in used and not r.get("retired"):
                r["retired"] = {"reason": "detached from every archetype by an audited archetype patch (duplicate, irrelevant or superseded); kept for traceability"}; n["retired"] += 1
            elif iid in used and r.get("retired"):
                del r["retired"]
        (cat.CATALOG_DIR / f"{s}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
        stats[s] = dict(n)
    return stats


def summary() -> dict:
    mech = mechanical(); out = {"mechanical": mech["by_sport"], "audited": {}, "market_free": collections.Counter(), "verdicts": collections.Counter()}
    for s in SPORTS:
        a = load_audit(s); out["audited"][s] = len(a)
        for v in a.values():
            out["market_free"][v["market_free"]] += 1; out["verdicts"][v["verdict"]] += 1
    out["market_free"] = dict(out["market_free"]); out["verdicts"] = dict(out["verdicts"])
    return out


def main():
    import sys
    if "--mechanical" in sys.argv:
        AD.mkdir(parents=True, exist_ok=True)
        m = mechanical(); (AD / "mechanical.json.txt").write_text(json.dumps(m, indent=0, sort_keys=True)); print(json.dumps(m["by_sport"], indent=1)); return
    for s in SPORTS:
        a = load_audit(s)
        if a:
            errs = validate(s, a); print(s, "OK" if not errs else f"{len(errs)} problems", *errs[:6], sep="\n  " if errs else "")


if __name__ == "__main__":
    main()

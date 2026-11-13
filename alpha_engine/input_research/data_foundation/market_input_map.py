"""Market & Input Map (RESEARCH_ONLY): a navigable join of the APPROVED catalog and the latest data-foundation artifacts.

    python -m alpha_engine.input_research.data_foundation.market_input_map [--out DIR]

Read-only over existing artifacts. It does not collect, probe, build, verify, score or re-rank anything new; every status, rank,
tier and history value is copied from an existing artifact and every derived field says how it was derived.

Inputs read (never written):
  catalog/*.json                                  170 archetypes and their (input, role) edges            (baseline-locked)
  data_foundation/verified_coverage.json          verified_bucket / verified_status per distinct input    (1,649 rows)
  data_foundation/coverage_matrix.csv             evidence_summary per distinct input
  data_foundation/input_audit.json                requirements (need, trigger, satisfied_by, candidates), provenance, history
  data_foundation/datasets.json, sources.json, probes.json       raw datasets, sources and the probed URL per source
  data_foundation/rights_registry.json (via rights.py)            fail-closed rights tiers
  data_foundation/collection_plan.json, prospective_capture_plan.json, phase14_market_first_acquisition.json
  data_foundation/verification/replay*/*.json (via rights.py)     builder columns + raw sources for built inputs
  market_completeness/market_completeness.json    cross-check only: slot classification is imported from market_completeness.py
  market_universe/series_assignment.json          live Kalshi series -> archetype

Counting units (never conflated):
  distinct input   = one SPORT:input_id row of the verified-coverage matrix (1,649)
  slot / edge      = one (archetype, input) listing in the catalog; a shared input is one distinct input but many slots
  predictive slot  = an edge in the market_completeness predictive denominator (3,670)
  missing PRIMARY  = a PRIMARY-role predictive slot whose category is not FULL/PARTIAL/PROXY (949)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import market_completeness as MC
from . import rights as RT

ROOT = MC.ROOT
IR = ROOT / "research/input_research"
DF = MC.DF
OUT = IR / "market_input_map"
SCHEMA = "market-input-map-1.0"

# The eight verified buckets of verified_coverage.json, preserved verbatim (EXCLUDED = benchmark-only, not a predictive status).
BUCKETS = ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "REQUIRES_COLLECTION", "BLOCKED", "FAILED", "UNVERIFIED", "EXCLUDED")

# Display classes. PREDICTIVE is exactly market_completeness's predictive denominator; the other three partition everything it excludes.
CLASSES = {
    "PREDICTIVE": "independent sports input; counted in the 3,670 predictive slots",
    "MARKET_BENCHMARK": "derived from market prices/lines (verified EXCLUDED_BENCHMARK_ONLY, or the m.strike_hit_rates calibration benchmark); never a predictive slot",
    "RULES_SETTLEMENT_METADATA": "contract rules text, rules-parsed contract flags, settlement source/truth and stat-correction metadata; never a predictive slot",
    "OPERATIONAL": "exchange operations / execution data (fees, order book, trade tape, volume/OI, market lifecycle); never a predictive slot",
}
RULES_SETTLEMENT_IDS = set(MC.SEMANTIC_IDS) | set(MC.RULES_PARSE_ONLY_IDS) | {"m.settlement_truth", "m.stat_correction_risk", "m.stat_source_mismatch"}
OPERATIONAL_IDS = {"m.lifecycle", "m.fees", "m.orderbook_depth", "m.trade_tape", "m.volume_oi"}
CALIBRATION_IDS = set(MC.CALIBRATION_IDS)
COST_ORDER = {"free": 0, "free (key needed)": 1, "paid": 2}
OUTSTANDING_EXEMPT = {"COLLECTED_ARCHIVE"}      # a requirement whose dataset is already archived is not an outstanding acquisition


def edge_class(iid: str, category: str) -> tuple[str, str]:
    """(display class, market_completeness group). The group is what market_completeness itself did with the edge."""
    if iid in MC.SEMANTIC_IDS: grp = "semantics"
    elif iid in MC.SETTLEMENT_OPS_IDS: grp = "settlement_ops"
    elif iid in CALIBRATION_IDS: grp = "calibration"
    elif iid in MC.RULES_PARSE_ONLY_IDS: grp = "rules_parse_only"
    elif category == "EXCLUDED_MARKET": grp = "excluded_market"
    else: return "PREDICTIVE", "predictive"
    if iid in RULES_SETTLEMENT_IDS: return "RULES_SETTLEMENT_METADATA", grp
    if iid in OPERATIONAL_IDS: return "OPERATIONAL", grp
    return "MARKET_BENCHMARK", grp


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _j(p: Path):
    return json.loads(p.read_text())


def load() -> dict:
    vc = {r["key"]: r for r in _j(DF / "verified_coverage.json")["rows"]}
    with open(DF / "coverage_matrix.csv", newline="") as f:
        cm = {f"{r['sport']}:{r['input_id']}": r for r in csv.DictReader(f)}
    audit = {r["key"]: r for r in _j(DF / "input_audit.json")["rows"]}
    cats = {sp: _j(MC.CAT / f"{sp}.json") for sp in MC.SPORTS}
    reps = {}
    for sub in ("replay", "replay_ext"):        # same precedence as rights.raw_sources_by_key: extension replays override
        for p in sorted((DF / "verification" / sub).glob("*.json")):
            for iid, x in _j(p)["inputs"].items():
                reps[f"{x['sport']}:{iid}"] = {"columns": list(x.get("columns") or []), "raw": list(x.get("raw_claimed") or []), "file": str(p.relative_to(ROOT))}
    return {"vc": vc, "cm": cm, "audit": audit, "cats": cats, "reps": reps,
            "datasets": _j(DF / "datasets.json")["datasets"], "sources": _j(DF / "sources.json")["sources"],
            "probes": {p["id"]: p for p in _j(DF / "probes.json")["probes"]}, "reg": RT.registry(),
            "cplan": {i["dataset"]: i for i in _j(DF / "collection_plan.json")["items"]},
            "pplan": {f["feed_dataset"]: f for f in _j(DF / "prospective_capture_plan.json")["feeds"]},
            "p14": _j(DF / "phase14_market_first_acquisition.json"),
            "mc": _j(IR / "market_completeness/market_completeness.json"),
            "series": _j(IR / "market_universe/series_assignment.json")}


# ---------------------------------------------------------------- rights (fail closed, copied from rights_registry.json)
def source_rights(sid: str, src: dict, reg: dict) -> dict:
    label = f"{sid} {src.get('name', '')}".lower()
    matched = [s for s in reg["sources"] if any(t in label for t in s["tokens"])]
    sup = {x for s in matched for x in s.get("supersedes", [])}
    matched = [s for s in matched if s["id"] not in sup]
    tier = RT.tier_of_source(label)
    research, commercial = RT.is_cleared(tier), RT.is_commercial_cleared(tier)
    collection_allowed = bool(matched) and all(s.get("collection_allowed") is True for s in matched)
    if not matched: use, basis = "NOT_CLEARED_NO_REGISTRY_ENTRY", "no rights_registry entry matches this source: UNRESOLVED (fail closed)"
    elif research and collection_allowed: use, basis = "RESEARCH_USE_PERMITTED", "registry: " + ", ".join(s["id"] for s in matched)
    elif research: use, basis = "LICENCE_CLEARED_COLLECTION_NOT_ALLOWED", "registry: " + ", ".join(s["id"] for s in matched) + " (collection_allowed false)"
    elif tier == "WRAPPER_LICENCE_UPSTREAM_CAVEAT": use, basis = "WRAPPER_LICENCE_UPSTREAM_CAVEAT_NOT_CLEARED", "registry: " + ", ".join(s["id"] for s in matched)
    else: use, basis = "NOT_CLEARED_UNRESOLVED", "registry: " + ", ".join(s["id"] for s in matched)
    return {"tier": tier, "research_cleared": research, "commercial_cleared": commercial, "collection_allowed": collection_allowed, "use_status": use, "basis": basis}


def weakest(tiers: list[str]) -> str:
    order = RT.registry()["tier_order"]
    return order[min((order.index(t) for t in tiers), default=0)]


# ---------------------------------------------------------------- build
def build(D: dict) -> dict:
    vc, cm, audit, cats, reps = D["vc"], D["cm"], D["audit"], D["cats"], D["reps"]
    datasets, sources, probes, reg = D["datasets"], D["sources"], D["probes"], D["reg"]

    # sources
    S = {}
    for sid in sorted(sources):
        s = sources[sid]; pr = probes.get(s.get("probe")) if s.get("probe") else None
        S[sid] = {"name": s["name"], "kind": s["kind"], "cost": s["cost"], "tos_risk": s["tos_risk"],
                  "proposed_link": pr["url"] if pr else None, "probe": ({"id": pr["id"], "result": pr["result"], "http": pr.get("http"), "probed_utc": pr.get("probed_utc")} if pr else None),
                  "rights": source_rights(sid, s, reg)}
    # source groups: datasets drawing on the identical source set (one host decision can serve several tables; impact is still per dataset)
    grp = defaultdict(list)
    for did, d in datasets.items(): grp["+".join(sorted(d["sources"])) or "(none)"].append(did)
    # datasets
    DS = {}
    for did in sorted(datasets):
        d = datasets[did]
        srs = [S[s]["rights"] for s in d["sources"] if s in S]
        tier = weakest([r["tier"] for r in srs]) if srs else weakest([])
        unknown_src = [s for s in d["sources"] if s not in S]
        research = RT.is_cleared(tier) and bool(srs) and not unknown_src
        coll = bool(srs) and all(r["collection_allowed"] for r in srs) and not unknown_src
        use = ("RESEARCH_USE_PERMITTED" if research and coll else "LICENCE_CLEARED_COLLECTION_NOT_ALLOWED" if research else
               "WRAPPER_LICENCE_UPSTREAM_CAVEAT_NOT_CLEARED" if tier == "WRAPPER_LICENCE_UPSTREAM_CAVEAT" else "NOT_CLEARED_UNRESOLVED")
        cp = D["cplan"].get(did); pp = D["pplan"].get(did); key = "+".join(sorted(d["sources"])) or "(none)"
        DS[did] = {"title": d["title"], "sports": d["sports"], "sources": d["sources"], "unknown_sources": unknown_src,
                   "access_status": d["access_status"], "access_rank": d["access_rank"], "pit": d["pit"], "pit_rank": d["pit_rank"],
                   "cost": d["cost"], "tos_risk": d["tos_risk"], "history": d["history"], "evidence_grade": d["evidence_grade"],
                   "freshness": d.get("freshness"), "missingness": d.get("missingness"), "rows_collected": d.get("rows_collected"),
                   "proposed_links": sorted({S[s]["proposed_link"] for s in d["sources"] if s in S and S[s]["proposed_link"]}),
                   "rights": {"tier": tier, "research_cleared": research, "commercial_cleared": research and RT.is_commercial_cleared(tier), "collection_allowed": coll, "use_status": use,
                              "basis": "weakest tier over the dataset's sources (fail closed); a source with no registry entry is UNRESOLVED"},
                   "collection_plan_class": cp["class"] if cp else None, "prospective_feed": ({"feed": pp["feed"], "planned": pp.get("planned"), "owner_prerequisite": pp.get("owner_prerequisite")} if pp else None),
                   "source_group": key, "source_group_siblings": sorted(x for x in grp[key] if x != did)}

    # archetypes + edges
    p14 = {f"{x['sport']}:{x['input']}": x for x in D["p14"]["inputs"]}
    mc_rows = {f"{r['sport']}:{r['archetype']}": r for r in D["mc"]["rows"]}
    A, E = [], []
    for a in MC.archetypes():
        ak = f"{a['sport']}:{a['name']}"; m = mc_rows[ak]
        for iid, role in a["inputs"]:
            k = f"{a['sport']}:{iid}"
            if k not in vc:
                E.append({"a": ak, "i": k, "role": role, "cls": "UNMAPPED", "grp": "unmapped", "cat": "UNMAPPED", "bucket": "UNMAPPED", "vstatus": "UNMAPPED"}); continue
            cat = MC.category(vc[k]["verified_status"], audit[k]["full_definition_status"])
            cls, g = edge_class(iid, cat)
            E.append({"a": ak, "i": k, "role": role, "cls": cls, "grp": g, "cat": cat, "bucket": vc[k]["verified_bucket"], "vstatus": vc[k]["verified_status"]})
        A.append({"k": ak, "sport": a["sport"], "name": a["name"], "kind": a["kind"], "label": a["label"], "rank": m["rank"],
                  "critical_score": m["critical_score"], "completeness_score": m["completeness_score"], "n_required": m["n_required"], "n_primary": m["n_primary"],
                  "primary_missing_critical": m["primary_missing_critical"], "series": {}})

    # live series -> archetype (copied from series_assignment; anything not resolving to one of the 170 is reported, not guessed)
    akeys = {x["k"]: x for x in A}; series_unmapped = []
    for r in D["series"]["rows"]:
        if r["scope"] != "IN_SCOPE": continue
        k = f"{r['sport']}:{r['final'].removeprefix('unreg:')}"
        if k in akeys:
            akeys[k]["series"].setdefault(r["basis"], []).append(r["ticker"])
        else:
            series_unmapped.append({"ticker": r["ticker"], "sport": r["sport"], "final": r["final"], "basis": r["basis"]})
    for x in A:
        x["series"] = {b: sorted(v) for b, v in sorted(x["series"].items())}

    # distinct inputs
    by_input = defaultdict(list)
    for e in E: by_input[e["i"]].append(e)
    I = {}
    for k in sorted(vc):
        sp, iid = k.split(":", 1); r = vc[k]; au = audit[k]; c = cm.get(k, {}); cat_in = cats[sp]["inputs"].get(iid, {})
        reqs = [{"need": q["need"], "trigger": q["trigger"], "pit": q["pit"], "pit_sensitive": q["pit_sensitive"], "dataset": q["satisfied_by"],
                 "candidates": q["candidates"], "access_status": q["access_status"]} for q in au["requirements"]]
        built = reps.get(k)
        if built and built["raw"]:
            tier = RT.input_tier(k); rb = "builder raw sources (verification replay): " + "; ".join(built["raw"])
        else:
            ds_t = [DS[q["dataset"]]["rights"]["tier"] for q in reqs if q["dataset"] in DS]
            tier = weakest(ds_t); rb = ("weakest tier over the proposed datasets (nothing built)" if ds_t else "no dataset mapping: UNRESOLVED (fail closed)")
        cats_e = Counter(e["cat"] for e in by_input.get(k, []))
        cls = sorted({e["cls"] for e in by_input.get(k, [])}) or [edge_class(iid, MC.category(r["verified_status"], au["full_definition_status"]))[0]]
        free_ds = sorted({q["dataset"] for q in reqs if q["dataset"] in DS and DS[q["dataset"]]["cost"] != "paid" and DS[q["dataset"]]["access_status"] in ("COLLECTED_ARCHIVE", "FREE_REACHABLE", "FREE_UNPROBED", "FREE_PATH_UNCONFIRMED", "FREE_BLOCKED_FROM_RUNNER", "REFERENCE_DOCUMENT")})
        ph = p14.get(k)
        I[k] = {"sport": sp, "id": iid, "label": au["label"], "category": au["category"], "classes": cls,
                "bucket": r["verified_bucket"], "vstatus": r["verified_status"], "draft_status": r.get("draft_status"),
                "audit_status": au["full_definition_status"], "completeness_category": (sorted(cats_e)[0] if len(cats_e) == 1 else (sorted(cats_e) if cats_e else None)),
                "pit_verdict": r.get("pit_verdict"), "pregame_knowable": au.get("pregame_knowable"),
                "history": au["history"], "cost": au["cost"], "tos_risk": au["tos_risk"], "confidence": au["confidence"], "evidence_grade": au["evidence_grade"],
                "provenance_sources": [{"name": p.get("name"), "access": p.get("access"), "canonical": p.get("canonical")} for p in au["provenance_sources"]],
                "provenance_verified": au.get("provenance_verified"), "missingness": au.get("missingness") or [], "blockers": au.get("blockers") or [],
                "evidence_summary": c.get("evidence_summary") or None,
                "catalog_free_sources": cat_in.get("free_sources") or [], "measurement": cat_in.get("measurement"),
                "requirements": reqs, "built": ({"columns": built["columns"], "raw_sources": built["raw"], "replay_file": built["file"]} if built else None),
                "rights": {"tier": tier, "research_cleared": RT.is_cleared(tier), "commercial_cleared": RT.is_commercial_cleared(tier), "basis": rb},
                "free_source_datasets": free_ds,
                "prospective_need": au["full_definition_status"] == "COLLECT_PROSPECTIVE" or r["verified_status"] == "PIT_QUARANTINED" or any(q["access_status"] == "PROSPECTIVE_CAPTURE_ONLY" for q in reqs),
                "phase14": ({"status": ph["status"], "evidence": ph.get("evidence"), "evidence_files": ph.get("evidence_files", []), "point_in_time": ph.get("point_in_time"), "rights_tier": ph.get("rights_tier")} if ph else None),
                "n_markets": len(by_input.get(k, [])), "n_primary_markets": sum(e["role"] == "primary" for e in by_input.get(k, []))}

    # dataset <-> input edges (transparent: one row per requirement x dataset, edge_type SATISFIED_BY or CANDIDATE_ALTERNATIVE)
    DE = []; unresolved_ds = []
    for k in sorted(I):
        for q in I[k]["requirements"]:
            seen = set()
            for did, et in [(q["dataset"], "SATISFIED_BY")] + [(c, "CANDIDATE_ALTERNATIVE") for c in q["candidates"] if c != q["dataset"]]:
                if not did or (did, et) in seen: continue
                seen.add((did, et))
                if did not in DS: unresolved_ds.append({"input": k, "dataset": did}); continue
                DE.append({"d": did, "i": k, "type": et, "need": q["need"], "trigger": q["trigger"], "pit": q["pit"], "req_access": q["access_status"]})

    # acquisition queue: the 949 missing PRIMARY predictive slots, grouped by the dataset that satisfies each requirement
    missing = [e for e in E if e["cls"] == "PREDICTIVE" and e["role"] == "primary" and e["cat"] not in MC.COVERED]
    by_ds = defaultdict(lambda: {"slots": set(), "alt": set(), "sole": set()}); no_ds = []
    for e in missing:
        sat = sorted({q["dataset"] for q in I[e["i"]]["requirements"] if q["dataset"] in DS})
        alts = sorted({c for q in I[e["i"]]["requirements"] for c in q["candidates"] if c in DS} - set(sat))
        if not sat: no_ds.append({"archetype": e["a"], "input": e["i"], "category": e["cat"], "reason": "no requirement resolves to a dataset in datasets.json"}); continue
        outstanding = [d for d in sat if DS[d]["access_status"] not in OUTSTANDING_EXEMPT]
        for d in sat:
            by_ds[d]["slots"].add((e["a"], e["i"]))
            if outstanding == [d]: by_ds[d]["sole"].add((e["a"], e["i"]))
        for d in alts: by_ds[d]["alt"].add((e["a"], e["i"]))
    Q = []
    tier_rank = {t: i for i, t in enumerate(reg["tier_order"])}
    for did, v in by_ds.items():
        if not v["slots"]: continue        # alternative-only datasets are shown on the dataset view, not queued
        d = DS[did]; slots = sorted(v["slots"])
        Q.append({"dataset": did, "title": d["title"], "sports": d["sports"],
                  "missing_primary_slots": len(slots), "distinct_inputs": len({s[1] for s in slots}), "distinct_archetypes": len({s[0] for s in slots}),
                  "slots_where_only_outstanding_dataset": (None if d["access_status"] in OUTSTANDING_EXEMPT else len(v["sole"])), "alternative_candidate_slots": len(v["alt"] - v["slots"]),
                  "missing_by_category": dict(sorted(Counter(next(e["cat"] for e in missing if (e["a"], e["i"]) == s) for s in slots).items())),
                  "access_status": d["access_status"], "access_rank": d["access_rank"], "rights_tier": d["rights"]["tier"], "rights_use_status": d["rights"]["use_status"],
                  "commercial_cleared": d["rights"]["commercial_cleared"], "pit": d["pit"], "pit_rank": d["pit_rank"], "cost": d["cost"], "tos_risk": d["tos_risk"],
                  "history": d["history"], "collection_plan_class": d["collection_plan_class"], "source_group": d["source_group"], "source_group_siblings": d["source_group_siblings"],
                  "slots": [list(s) for s in slots], "next_actions": next_actions(did, d, len(slots), len({s[1] for s in slots}))})
    Q.sort(key=lambda q: (q["access_rank"], -tier_rank[q["rights_tier"]], q["pit_rank"], COST_ORDER.get(q["cost"], 9), -q["missing_primary_slots"], q["dataset"]))
    for n, q in enumerate(Q, 1): q["rank"] = n

    recon = reconcile(A, E, I, DS, DE, Q, missing, no_ds, unresolved_ds, series_unmapped, D)
    return {"archetypes": A, "edges": E, "inputs": I, "datasets": DS, "sources": S, "dataset_edges": DE, "queue": Q,
            "queue_unresolved": no_ds, "series_unmapped": series_unmapped, "reconciliation": recon}


def next_actions(did: str, d: dict, n_slots: int, n_inputs: int) -> list[str]:
    """Explicit, ordered next steps derived only from the dataset's recorded access status, rights and plan class. Proposals only: nothing here is executed."""
    out = []; r = d["rights"]
    if r["use_status"] != "RESEARCH_USE_PERMITTED":
        out.append(f"RIGHTS: owner decision needed — {r['tier']} ({r['use_status']}); sources {', '.join(d['sources']) or 'none'}; read the provider terms before any use (the map does not treat this source as usable)")
    a = d["access_status"]
    if a == "COLLECTED_ARCHIVE": out.append("ACCESS: data already archived in a repository; no collection needed")
    elif a == "FREE_REACHABLE": out.append("ACCESS: host reachable and free; backfill only after an owner-approved collection decision (collection_plan " + str(d["collection_plan_class"]) + ")")
    elif a in ("FREE_UNPROBED", "FREE_PATH_UNCONFIRMED"): out.append("ACCESS: free path documented but not probed/confirmed; propose a bounded probe for owner approval (no probe run here)")
    elif a == "FREE_BLOCKED_FROM_RUNNER": out.append("ACCESS: host blocked by the network policy; owner network decision (docs/NETWORK_ACCESS_PROPOSAL.md) — proposal only, no policy change made")
    elif a == "PROSPECTIVE_CAPTURE_ONLY":
        pf = d["prospective_feed"]
        out.append("ACCESS: no backfillable history; needs prospective capture" + (f" via the planned feed '{pf['feed']}' ({pf['owner_prerequisite']})" if pf else " (no planned feed recorded)") + "; nothing scheduled here")
    elif a == "REFERENCE_DOCUMENT": out.append("ACCESS: reference document; manual transcription with a recorded licence check")
    elif a in ("PAID_ONLY", "SAMPLE_ONLY", "NO_FREE_SOURCE"): out.append(f"ACCESS: {a}; owner cost/permission decision; no paid service added")
    else: out.append(f"ACCESS: {a} (no rule; review manually)")
    out.append(f"BUILD: write + blind-verify builders for {n_inputs} input(s) behind {n_slots} missing PRIMARY slot(s); verification status stays as recorded until then")
    return out


def reconcile(A, E, I, DS, DE, Q, missing, no_ds, unresolved_ds, series_unmapped, D) -> dict:
    pred = [e for e in E if e["cls"] == "PREDICTIVE"]
    mc = D["mc"]["rows"]
    per_arch_ok = all(sum(1 for e in pred if e["a"] == f"{r['sport']}:{r['archetype']}") == r["n_required"] for r in mc)
    per_arch_missing_ok = all(sum(1 for e in missing if e["a"] == f"{r['sport']}:{r['archetype']}") == r["primary_missing_critical"] for r in mc)
    queued = {tuple(s) for q in Q for s in q["slots"]}
    referenced = {e["i"] for e in E}
    return {
        "archetypes": len(A), "archetypes_by_kind": dict(sorted(Counter(a["kind"] for a in A).items())),
        "catalog_edges_all_classes": len(E), "edges_by_class": dict(sorted(Counter(e["cls"] for e in E).items())),
        "edges_by_class_and_completeness_group": dict(sorted(Counter(f"{e['cls']}|{e['grp']}" for e in E).items())),
        "predictive_slots": len(pred), "predictive_primary_slots": sum(e["role"] == "primary" for e in pred),
        "predictive_slots_by_category": dict(sorted(Counter(e["cat"] for e in pred).items())),
        "missing_primary_predictive_slots": len(missing), "missing_primary_by_category": dict(sorted(Counter(e["cat"] for e in missing).items())),
        "market_completeness_cross_check": {"n_required_sum": sum(r["n_required"] for r in mc), "primary_missing_critical_sum": sum(r["primary_missing_critical"] for r in mc),
                                            "n_primary_sum": sum(r["n_primary"] for r in mc), "per_archetype_predictive_match": per_arch_ok, "per_archetype_missing_primary_match": per_arch_missing_ok},
        "distinct_inputs": len(I), "distinct_inputs_by_bucket": dict(sorted(Counter(i["bucket"] for i in I.values()).items())),
        "distinct_inputs_by_sport": dict(sorted(Counter(i["sport"] for i in I.values()).items())),
        "distinct_inputs_referenced_by_an_archetype": len(referenced), "distinct_inputs_with_no_archetype_edge": sorted(set(I) - referenced),
        "distinct_input_ids_across_sports": len({i["id"] for i in I.values()}),
        "unmapped_catalog_edges": [e for e in E if e["cls"] == "UNMAPPED"],
        "datasets": len(DS), "sources": len(D["sources"]), "dataset_input_edges": len(DE), "dataset_input_edges_by_type": dict(sorted(Counter(e["type"] for e in DE).items())),
        "datasets_with_no_input_edge": sorted(set(DS) - {e["d"] for e in DE}),
        "unresolved_dataset_references": unresolved_ds,
        "queue_datasets": len(Q), "queue_slot_dataset_pairs": sum(q["missing_primary_slots"] for q in Q),
        "queue_distinct_slots_covered": len(queued), "queue_slots_without_dataset": no_ds,
        "queue_covers_every_missing_primary_slot": queued | {(x["archetype"], x["input"]) for x in no_ds} == {(e["a"], e["i"]) for e in missing},
        "series_in_scope": sum(1 for r in D["series"]["rows"] if r["scope"] == "IN_SCOPE"), "series_in_scope_unmapped_to_archetype": len(series_unmapped),
        "archetypes_with_no_in_scope_series": sorted(a["k"] for a in A if not a["series"]),
        "note": "distinct inputs (1,649 SPORT:input rows), predictive slots (archetype x input edges in the predictive denominator) and missing PRIMARY slots are different units; queue_slot_dataset_pairs counts a slot once per dataset it needs and is NOT a slot total",
    }


# ---------------------------------------------------------------- outputs
def _csv(rows: list[list], cols: list[str]) -> str:
    b = io.StringIO(); w = csv.writer(b, lineterminator="\n"); w.writerow(cols)
    for r in rows: w.writerow(["" if v is None else ("|".join(map(str, v)) if isinstance(v, (list, tuple)) else v) for v in r])
    return b.getvalue()


def render(M: dict, D: dict) -> dict[str, str]:
    I, DS = M["inputs"], M["datasets"]; alab = {a["k"]: a for a in M["archetypes"]}
    files = {}
    files["market_input_edges.csv"] = _csv([[e["a"].split(":")[0], e["a"].split(":", 1)[1], alab[e["a"]]["kind"], e["i"], I[e["i"]]["label"] if e["i"] in I else None, e["role"], e["cls"], e["grp"],
                                              e["bucket"], e["vstatus"], e["cat"], int(e["cls"] == "PREDICTIVE"), int(e["cls"] == "PREDICTIVE" and e["role"] == "primary" and e["cat"] not in MC.COVERED)] for e in M["edges"]],
                                            ["sport", "archetype", "archetype_kind", "input_key", "input_label", "role", "class", "completeness_group", "verified_bucket", "verified_status", "completeness_category", "is_predictive_slot", "is_missing_primary_slot"])
    files["distinct_inputs.csv"] = _csv([[k, i["sport"], i["id"], i["label"], "|".join(i["classes"]), i["bucket"], i["vstatus"], i["audit_status"], i["pit_verdict"], i["history"].get("first") or "UNKNOWN", i["history"].get("last") or "UNKNOWN",
                                          i["cost"], i["tos_risk"], i["evidence_grade"], "UNKNOWN" if i["provenance_verified"] is None else i["provenance_verified"], i["rights"]["tier"], i["rights"]["commercial_cleared"],
                                          i["free_source_datasets"], i["prospective_need"], i["n_markets"], i["n_primary_markets"], sorted({e["a"] for e in M["edges"] if e["i"] == k})] for k, i in I.items()],
                                        ["input_key", "sport", "input_id", "label", "classes", "verified_bucket", "verified_status", "audit_status", "pit_verdict", "history_first", "history_last", "cost", "tos_risk", "evidence_grade", "provenance_verified", "rights_tier", "commercial_cleared", "free_source_datasets", "prospective_need", "n_markets", "n_primary_markets", "markets"])
    files["dataset_input_edges.csv"] = _csv([[e["d"], DS[e["d"]]["title"], e["i"], I[e["i"]]["label"], e["type"], e["need"], e["trigger"], e["pit"], e["req_access"], DS[e["d"]]["access_status"], DS[e["d"]]["rights"]["tier"], DS[e["d"]]["rights"]["use_status"],
                                              DS[e["d"]]["sources"], DS[e["d"]]["proposed_links"], I[e["i"]]["n_markets"]] for e in M["dataset_edges"]],
                                            ["dataset_id", "dataset_title", "input_key", "input_label", "edge_type", "need", "trigger", "pit", "requirement_access_status", "dataset_access_status", "dataset_rights_tier", "dataset_use_status", "source_ids", "proposed_raw_links", "input_n_markets"])
    files["acquisition_queue.csv"] = _csv([[q["rank"], q["dataset"], q["title"], q["sports"], q["missing_primary_slots"], q["distinct_inputs"], q["distinct_archetypes"], q["slots_where_only_outstanding_dataset"], q["alternative_candidate_slots"],
                                            q["access_status"], q["access_rank"], q["rights_tier"], q["rights_use_status"], q["commercial_cleared"], q["pit"], q["pit_rank"], q["cost"], q["tos_risk"], q["collection_plan_class"], q["source_group"], " || ".join(q["next_actions"])] for q in M["queue"]],
                                          ["rank", "dataset_id", "title", "sports", "missing_primary_slots", "distinct_inputs", "distinct_archetypes", "slots_where_only_outstanding_dataset_ESTIMATE", "alternative_candidate_slots", "access_status", "access_rank", "rights_tier", "rights_use_status", "commercial_cleared", "pit", "pit_rank", "cost", "tos_risk", "collection_plan_class", "source_group", "next_actions"])
    meta = {"schema": SCHEMA, "status": "RESEARCH_ONLY",
            "notice": "Read-only join of the approved catalog and the latest data-foundation artifacts. No new research, collection, scoring or ranking; agent-built, not independently or human verified. A source is never shown as usable unless its rights tier is research-cleared AND the registry allows collection.",
            "classes": CLASSES, "buckets": list(BUCKETS),
            "completeness_categories": list(MC.PRED_KEYS),
            "queue_order": "access_rank asc (datasets.json), rights tier strongest first (rights_registry tier_order), pit_rank asc (datasets.json), cost (free < free key < paid), missing PRIMARY slots desc, dataset id — no composite score",
            "estimate_labels": {"slots_where_only_outstanding_dataset": "ESTIMATE: slots whose every other satisfying dataset is already COLLECTED_ARCHIVE; data-side only, a builder and blind verification are still required",
                                "source_group": "datasets sharing an identical source set; listed for transparency, impact is never summed across them"},
            "inputs_sha256": {str(p.relative_to(ROOT)): _sha(p) for p in sorted([DF / "verified_coverage.json", DF / "coverage_matrix.csv", DF / "input_audit.json", DF / "datasets.json", DF / "sources.json", DF / "probes.json", DF / "rights_registry.json",
                                                                              DF / "collection_plan.json", DF / "prospective_capture_plan.json", DF / "phase14_market_first_acquisition.json", IR / "market_completeness/market_completeness.json",
                                                                              IR / "market_universe/series_assignment.json", IR / "baseline_lock.json", *sorted(MC.CAT.glob("*.json"))])}}
    # UI index (light, loaded once) + per-sport input detail (loaded when an input is opened). Arrays are positional; the column names ship with them.
    LIGHT = ("sport", "id", "label", "category", "classes", "bucket", "vstatus", "audit_status", "completeness_category", "pit_verdict", "cost", "tos_risk", "evidence_grade", "free_source_datasets", "prospective_need", "n_markets", "n_primary_markets")
    ui = {**meta,
          "archetypes": M["archetypes"], "datasets": DS, "sources": M["sources"], "queue": M["queue"], "queue_unresolved": M["queue_unresolved"], "series_unmapped": M["series_unmapped"], "reconciliation": M["reconciliation"],
          "inputs": {k: {**{f: i[f] for f in LIGHT}, "rights": {x: i["rights"][x] for x in ("tier", "research_cleared", "commercial_cleared")}, "provenance_verified": i["provenance_verified"], "built": bool(i["built"]), "phase14_status": (i["phase14"] or {}).get("status")} for k, i in I.items()},
          "edge_cols": ["archetype", "input", "role", "class", "completeness_group", "completeness_category"],
          "edges": [[e["a"], e["i"], e["role"], e["cls"], e["grp"], e["cat"]] for e in M["edges"]],
          "dataset_edge_cols": ["dataset", "input", "edge_type", "need", "trigger", "pit", "requirement_access_status"],
          "dataset_edges": [[e["d"], e["i"], e["type"], e["need"], e["trigger"], e["pit"], e["req_access"]] for e in M["dataset_edges"]]}
    files["map.json"] = json.dumps(ui, separators=(",", ":"), sort_keys=True) + "\n"
    for sp in MC.SPORTS:
        det = {k: {f: v for f, v in i.items() if f not in LIGHT or f in ("history",)} for k, i in I.items() if i["sport"] == sp}
        files[f"input_details_{sp}.json"] = json.dumps(det, separators=(",", ":"), sort_keys=True) + "\n"
    files["reconciliation.json"] = json.dumps({**{k: meta[k] for k in ("schema", "status", "notice", "inputs_sha256")}, **M["reconciliation"]}, indent=1, sort_keys=True) + "\n"
    return files


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    out = Path(a[a.index("--out") + 1]) if "--out" in a else OUT
    D = load(); M = build(D); files = render(M, D)
    out.mkdir(parents=True, exist_ok=True)
    for name, txt in files.items(): (out / name).write_text(txt)
    r = M["reconciliation"]
    print(f"{r['archetypes']} archetypes | {r['catalog_edges_all_classes']} catalog edges {r['edges_by_class']} | {r['predictive_slots']} predictive slots | {r['missing_primary_predictive_slots']} missing PRIMARY | "
          f"{r['distinct_inputs']} distinct inputs ({len(r['distinct_inputs_with_no_archetype_edge'])} with no archetype edge) | {r['datasets']} datasets, {r['dataset_input_edges']} dataset-input edges | "
          f"queue {r['queue_datasets']} datasets covering {r['queue_distinct_slots_covered']} slots, {len(r['queue_slots_without_dataset'])} without dataset | cover-all={r['queue_covers_every_missing_primary_slot']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

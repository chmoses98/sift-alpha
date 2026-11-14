"""Pipeline ledger: one explicit lifecycle stage per input, derived only from committed evidence (RESEARCH_ONLY).

    python -m alpha_engine.foundation.ledger            # regenerates research/data_foundation_ops/{pipeline_ledger,summary}.json

Joins the Market & Input Map (170 archetypes, 1,649 inputs, 165 datasets) with
  * the published model-use audit (research/audit/input_research/sport_*.json),
  * the hand-recorded collector registry (research/data_foundation_ops/collectors.json),
  * every challenger evaluation under research/data_foundation_ops/<SPORT>/<challenger>/evaluation.json.

Nothing is collected, scored or re-ranked here. Stages are never merged into a percentage:

  research chain (in order)  IDENTIFIED > SOURCE_LOCATED > COLLECTED > VERIFIED > FEATURE_BUILT > CHALLENGER_INTEGRATED
                             > EVALUATED > VALIDATED_IMPROVEMENT
  production track (separate) PRODUCTION_APPROVED, PRODUCTION_ACTIVE

An input's ``at`` is the LAST stage of the research chain reached without a gap; ``stop`` says what stopped it at the
next stage (MISSING / BLOCKED / FAILED / REJECTED / PARTIAL / UNKNOWN) and why. The production track is reported
independently because an incumbent model can use an input that Alpha has never verified.
"""
from __future__ import annotations

import glob
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .contract import OPS, OUTCOMES, ROOT, STAGES, reference_kind, validate_evaluation, write_json

MAP = ROOT / "research/input_research/market_input_map/map.json"
AUDIT = ROOT / "research/audit/input_research"
UNIVERSE = ROOT / "research/input_research/market_universe/universe_summary.json"
SPORTS = ["NBA", "CBB", "NHL", "NFL", "CFB", "MLB", "TENNIS", "SOCCER"]
TIER = {"NBA": "P0", "CBB": "P0", "NHL": "P0", "NFL": "P1", "CFB": "P1", "MLB": "P2", "TENNIS": "P2", "SOCCER": "P2"}
CHAIN = STAGES[:8]
NO_SOURCE = {"NO_FREE_SOURCE", "PAID_ONLY", "SAMPLE_ONLY"}
GROUP_ORDER = ["ARCHIVED_BUILD_NEXT", "FREE_COLLECTION_POSSIBLE", "RIGHTS_APPROVAL_NEEDED", "PROSPECTIVE_CAPTURE_REQUIRED", "BLOCKED_OR_PAID"]
NOTICE = ("RESEARCH ONLY. Stages are derived from committed evidence files; a stage is shown as reached only when that evidence exists. "
          "A challenger evaluation is a research result on archived data, not proof of an executable or profitable edge. Agent-built, not human verified.")


def _model_use() -> dict:
    out = {}
    for s in SPORTS:
        p = AUDIT / f"sport_{s}.json"
        if not p.exists():
            continue
        for iid, rec in json.loads(p.read_text()).get("inputs", {}).items():
            out[f"{s}:{iid}"] = (rec.get("availability") or {}).get("model_use") or "UNKNOWN"
    return out


def _prod(use: str):
    u = (use or "UNKNOWN").upper()
    if u.startswith("USED_PARTIAL"):
        return "PARTIAL", "published audit records partial use by the current model"
    if u.startswith("USED"):
        return "OK", "published audit records use by the current model"
    if u.startswith("NOT_USED") or u.startswith("NOT_COLLECTED"):
        return "MISSING", "published audit: not used by the current model"
    return "UNKNOWN", "no recorded model-use evidence"


def load_evaluations() -> list:
    docs = []
    for f in sorted(glob.glob(str(OPS / "*" / "*" / "evaluation.json"))):
        d = json.loads(Path(f).read_text())
        errs = validate_evaluation(d)
        if errs:
            raise ValueError(f"{f}: contract violations: {errs[:5]}")
        d["_path"] = str(Path(f).relative_to(ROOT))
        docs.append(d)
    return docs


def _chain(inp: dict, dsets: list, datasets: dict, claims: list, feats: list):
    """Return (outcomes[8], evidence[8]) for the research chain."""
    oc = ["OK"] + ["MISSING"] * 7
    ev = ["listed in the approved input catalog", "", "", "", "no model-ready feature has been built", "no research challenger uses this input",
          "no chronological evaluation has been run", "no validated improvement"]
    b, vs, cc = inp.get("bucket"), inp.get("vstatus"), inp.get("completeness_category")
    acc = [datasets[d]["access_status"] for d in dsets if d in datasets]
    # SOURCE_LOCATED
    if not dsets:
        oc[1], ev[1] = ("OK", "market-derived or internal input; no external dataset required") if b == "EXCLUDED" else ("MISSING", "no dataset recorded for this input")
    elif all(a in NO_SOURCE for a in acc):
        oc[1], ev[1] = "BLOCKED", "only paid / sample-only / no-free-source datasets recorded: " + ", ".join(sorted(set(acc)))
    else:
        oc[1], ev[1] = "OK", "candidate dataset(s): " + ", ".join(dsets[:4]) + (" …" if len(dsets) > 4 else "")
    # COLLECTED
    if b in ("FULL", "DATA_IN_HAND"):
        oc[2], ev[2] = "OK", f"verified bucket {b}: data in an owner archive"
    elif b in ("PARTIAL", "PROXY"):
        oc[2], ev[2] = "PARTIAL", f"verified bucket {b}: archived data covers part of the requirement"
    elif b == "EXCLUDED":
        oc[2], ev[2] = "OK", "market-derived benchmark; excluded from predictive collection"
    elif b == "FAILED":
        oc[2], ev[2] = "FAILED", f"verification status {vs}"
    elif b == "BLOCKED":
        oc[2], ev[2] = "BLOCKED", f"verification status {vs}"
    elif b == "UNVERIFIED":
        oc[2], ev[2] = "UNKNOWN", f"verification status {vs}: data seen but not confirmed"
    elif cc == "PROSPECTIVE" or (acc and all(a == "PROSPECTIVE_CAPTURE_ONLY" for a in acc)):
        oc[2], ev[2] = "BLOCKED", "no historical source; needs prospective capture (an owner-approved schedule)"
    elif cc == "NO_FREE_SOURCE":
        oc[2], ev[2] = "BLOCKED", "no free source found"
    else:
        oc[2], ev[2] = "MISSING", "not collected" + (f" (dataset access: {', '.join(sorted(set(acc)))})" if acc else "")
    # VERIFIED
    if vs == "VERIFIED_FULL":
        oc[3], ev[3] = "OK", "replayed and blind-verified (VERIFIED_FULL)"
    elif vs in ("VERIFIED_PARTIAL", "VERIFIED_PROXY"):
        oc[3], ev[3] = "PARTIAL", vs
    elif vs == "DOWNGRADED_BY_VERIFIER":
        oc[3], ev[3] = "FAILED", "downgraded by the independent verifier"
    elif vs == "PIT_QUARANTINED":
        oc[3], ev[3] = "REJECTED", "quarantined: not point-in-time safe"
    elif b == "EXCLUDED":
        oc[3], ev[3] = "UNKNOWN", "benchmark-only input; not part of predictive verification"
    else:
        oc[3], ev[3] = "MISSING", "no verification record"
    # FEATURE_BUILT
    if inp.get("built"):
        oc[4], ev[4] = "OK", "builder replayed in the data-foundation verification"
    if feats:
        oc[4], ev[4] = "OK", "feature(s) built for challenger: " + ", ".join(sorted({f for f, _ in feats}))
    # challenger stages from evaluation claims
    order = {s: i for i, s in enumerate(CHAIN)}
    rank = {"OK": 5, "PARTIAL": 4, "REJECTED": 3, "FAILED": 2, "BLOCKED": 1}
    # Several challengers can claim the same input. The strongest recorded evidence wins regardless of file order
    # (a later, weaker claim used to overwrite an earlier one); ties keep the later challenger id.
    for c in sorted(claims, key=lambda c: (order.get(c["stage"], -1), rank.get(c["outcome"], 0), c["challenger"])):
        i = order.get(c["stage"])
        if i is None or i < 5:
            continue
        for j in range(5, i):
            if oc[j] != "OK":
                oc[j], ev[j] = "OK", f"{c['challenger']}"
        if c["stage"] == "VALIDATED_IMPROVEMENT" and (c.get("overall") != "VALIDATED_IMPROVEMENT" or oc[3] != "OK"):
            # A component metric (e.g. participation Brier) can be validated while the challenger as a whole is not, or while
            # the input itself is only partially verified. That is an evaluated input, never a validated improvement.
            oc[6], ev[6] = "OK", f"{c['challenger']}: {c.get('evidence', '')}"
            why = ("the challenger's overall verdict is " + str(c.get("overall")).replace("_", " ").lower() if c.get("overall") != "VALIDATED_IMPROVEMENT"
                   else "the input is not fully verified")
            oc[7], ev[7] = "MISSING", f"{c['challenger']}: a component metric improved, but {why}; not a validated improvement"
            continue
        oc[i], ev[i] = c["outcome"], f"{c['challenger']}: {c.get('evidence', '')}"
        if c["stage"] == "EVALUATED" and c["outcome"] in ("OK", "PARTIAL"):
            oc[7], ev[7] = "MISSING", f"{c['challenger']}: evaluated, not validated"
        if c["stage"] == "EVALUATED" and c["outcome"] == "REJECTED":
            oc[6], ev[6] = "OK", f"{c['challenger']}: {c.get('evidence', '')}"
            oc[7], ev[7] = "REJECTED", f"{c['challenger']}: ablation showed no validated value"
    return oc, ev


def _at(oc: list):
    """Last stage reached without a gap (OK or PARTIAL counts as reached), and the stop record."""
    at = 0
    for i in range(1, 8):
        if oc[i] in ("OK", "PARTIAL"):
            at = i
        else:
            break
    return at


def _next_action(at: int, oc: list, ev: list, inp: dict, has_eval: bool) -> str:
    if at == 7:
        return "Prepare for production review (owner approval required; no automatic promotion)."
    nxt, why = CHAIN[at + 1], oc[at + 1]
    if nxt == "SOURCE_LOCATED":
        return "Find a source: " + (ev[1] or "none recorded") + "."
    if nxt == "COLLECTED":
        if why == "BLOCKED":
            return "Owner decision: " + ev[2] + "."
        return "Collect from the located dataset once its rights tier permits (see dataset rights)."
    if nxt == "VERIFIED":
        return {"FAILED": "Repair: the verifier downgraded this input; fix the builder or source.", "REJECTED": "Do not use: point-in-time quarantine. Needs a PIT-safe source."}.get(why, "Write and blind-verify a builder against archived data.")
    if nxt == "FEATURE_BUILT":
        return "Build a model-ready feature from the verified data."
    if nxt == "CHALLENGER_INTEGRATED":
        return "Integrate the built feature into an isolated challenger for a market that lists it."
    if nxt == "EVALUATED":
        return "Run the chronological evaluation against the frozen incumbent."
    if why == "REJECTED":
        return "Rejected by ablation on current data; revisit only with new data or a different formulation."
    return "Evaluated but not validated: extend the sample / replicate on an independent cohort before any promotion."


def build() -> tuple:
    m = json.loads(MAP.read_text())
    use = _model_use()
    collectors = json.loads((OPS / "collectors.json").read_text())
    evals = load_evaluations()
    universe = json.loads(UNIVERSE.read_text())["by_sport"]

    ds_of = defaultdict(list)
    for d, i, et, *_ in m["dataset_edges"]:
        if et == "SATISFIED_BY" and d not in ds_of[i]:
            ds_of[i].append(d)
    claims, feats, ch_arch = defaultdict(list), defaultdict(list), defaultdict(list)
    challengers = {}
    for e in evals:
        cid = f"{e['sport']}:{e['challenger_id']}"
        for c in e["input_stage_claims"]:
            claims[c["input"]].append({**c, "challenger": e["challenger_id"], "overall": e["verdict"]["overall"]})
        for f in e["features"]:
            for i in f["catalog_inputs"]:
                feats[i].append((f["feature_id"], e["challenger_id"]))
        arch = sorted({a for r in e["results"] for a in r["archetypes"]})
        for a in arch:
            ch_arch[a].append(cid)
        headline = _shown_rows(e["results"])
        challengers[cid] = {
            "sport": e["sport"], "id": e["challenger_id"], "incumbent": e["incumbent_id"], "path": e["_path"], "verdict": e["verdict"],
            "archetypes": arch, "source_commits": e["source_commits"], "limitations": e["limitations"],
            "data": [{k: d.get(k) for k in ("dataset_id", "repo", "path", "rows", "first", "last", "kind", "rights_tier")} for d in e["data"]],
            "features": [{"feature_id": f["feature_id"], "catalog_inputs": f["catalog_inputs"], "description": f["description"], "pit_rule": f["pit_rule"],
                          "checks_passed": sum(1 for c in f["checks"] if c["passed"] and c["basis"] == "COMPUTED"), "checks_total": len(f["checks"]),
                          "checks_attested": [c["name"] for c in f["checks"] if c["basis"] == "ATTESTED"],
                          "checks_failed": [c["name"] + ": " + str(c["detail"]) for c in f["checks"] if not c["passed"]]} for f in e["features"]],
            "results": [{k: r.get(k) for k in ("market_family", "archetypes", "metric", "reference", "cohort", "n_rows", "n_clusters", "challenger", "reference_value", "diff", "ci95", "p_holm", "replicated", "verdict", "tested")} | {"reference_kind": reference_kind(r["reference"])} for r in headline],
            "data_through": max((_day(d.get("last")) for d in e["data"]), default=""),
            "results_total_rows": len(e["results"]), "verdict_counts": dict(Counter(r["verdict"] for r in headline)),
            "ablations": e.get("ablations", []),
            # the full design block stays in the evaluation file (``path``); the ledger is loaded on phones and must stay small
            "design_keys": sorted(e.get("design", {}))}
    # Input-information probes (not challengers): their claims enter the chain, the probe is not counted as a challenger.
    probes = []
    for f in sorted(glob.glob(str(OPS / "*" / "*_probe.json"))):
        pr = json.loads(Path(f).read_text()); probes.append(str(Path(f).relative_to(ROOT)))
        for c in pr.get("input_stage_claims", []):
            if c.get("stage") in STAGES and c.get("outcome") in OUTCOMES:
                claims[c["input"]].append({**c, "challenger": pr["probe_id"], "overall": "INCONCLUSIVE"})
    unknown_claims = sorted(set(claims) - set(m["inputs"]))
    unknown_arch = sorted(set(ch_arch) - {a["k"] for a in m["archetypes"]})

    inputs = {}
    for k, inp in m["inputs"].items():
        oc, ev = _chain(inp, ds_of.get(k, []), m["datasets"], claims.get(k, []), feats.get(k, []))
        at = _at(oc)
        pa, pe = _prod(use.get(k))
        stop = None if at == 7 else {"stage": CHAIN[at + 1], "outcome": oc[at + 1], "why": ev[at + 1]}
        inputs[k] = {"sport": inp["sport"], "id": inp["id"], "label": inp["label"], "category": inp.get("category"), "classes": inp["classes"],
                     "predictive": "PREDICTIVE" in inp["classes"], "chain": oc, "evidence": ev, "at": at, "stop": stop,
                     "production_active": pa, "production_evidence": pe, "production_approved": "UNKNOWN",
                     "datasets": ds_of.get(k, []), "pit": inp.get("pit_verdict"), "rights_tier": inp["rights"]["tier"],
                     "challengers": sorted({c["challenger"] for c in claims.get(k, [])}),
                     "n_markets": inp.get("n_markets", 0), "n_primary_markets": inp.get("n_primary_markets", 0),
                     "next_action": _next_action(at, oc, ev, inp, bool(claims.get(k)))}

    datasets = {}
    for d, x in m["datasets"].items():
        col = [collectors["by_source"][s] | {"source": s} for s in x["sources"] if s in collectors["by_source"]]
        datasets[d] = {"title": x["title"], "sports": x["sports"], "access_status": x["access_status"], "history": x["history"], "freshness": x.get("freshness"),
                       "pit": x["pit"], "cost": x["cost"], "rights_tier": x["rights"]["tier"], "rights_use_status": x["rights"]["use_status"], "sources": x["sources"],
                       "rows_collected": x.get("rows_collected"), "collectors": col or [{"state": "NO_COLLECTOR_RECORDED", "collector": None, "source": ", ".join(x["sources"])}],
                       "last_successful_collection": x["history"]["last"] if x["access_status"] == "COLLECTED_ARCHIVE" else None,
                       "last_collection_basis": x["history"]["basis"] if x["access_status"] == "COLLECTED_ARCHIVE" else "NOT_COLLECTED"}

    fam_map = json.loads((OPS / "incumbent_family_map.json").read_text())["map"]
    cov = {(r["sport"], r["family"]): r["statuses"] for r in json.loads((ROOT / "reports/outcome_intel/coverage_ledger.json").read_text())["ledger"]}
    missing_fams = sorted(f"{k}->{f}" for k, fs in fam_map.items() for f in fs if (k.split(":")[0], f) not in cov)
    if missing_fams or set(fam_map) - {a["k"] for a in m["archetypes"]}:
        raise ValueError(f"incumbent_family_map.json names unknown families/archetypes: {missing_fams}")

    def incumbent(k: str) -> dict:
        sp = k.split(":")[0]
        if k not in fam_map:
            return {"status": "NOT_MAPPED" if TIER[sp] != "P0" else "NO_INCUMBENT_EVALUATION_RECORDED", "cells": {}, "families": []}
        tot = Counter()
        for f in fam_map[k]:
            tot.update(cov[(sp, f)])
        return {"status": "RECORDED", "cells": dict(sorted(tot.items())), "families": fam_map[k]}

    edges = defaultdict(list)
    for a, i, role, cls, *_ in m["edges"]:
        edges[a].append((i, role, cls))
    markets = {}
    for a in m["archetypes"]:
        k = a["k"]; pred = [(i, r) for i, r, c in edges[k] if c == "PREDICTIVE"]
        prim = [i for i, r in pred if r == "primary"]
        cnt = lambda ids: [sum(1 for i in ids if inputs[i]["at"] == s) for s in range(8)]
        markets[k] = {"sport": a["sport"], "name": a["name"], "label": a["label"], "kind": a["kind"], "series": sorted({s for v in a["series"].values() for s in v}),
                      "n_inputs_all_classes": len(edges[k]), "n_predictive": len(pred), "n_primary": len(prim),
                      "at_counts": cnt([i for i, _ in pred]), "at_counts_primary": cnt(prim),
                      "production_active": dict(Counter(inputs[i]["production_active"] for i, _ in pred)),
                      "stopped": dict(Counter(inputs[i]["stop"]["outcome"] for i in prim if inputs[i]["stop"])),
                      "challengers": sorted(ch_arch.get(k, [])), "incumbent_evaluation": incumbent(k),
                      "inputs": [[i, r, c] for i, r, c in edges[k]]}
        markets[k]["next_action"] = _market_next(markets[k], prim, inputs)

    # ranked engineering queue: recorded factors only, lexicographic (no composite score)
    tested = {i for i, c in claims.items() if any(x["stage"] in ("EVALUATED", "VALIDATED_IMPROVEMENT") for x in c)}
    queue = []
    for q in m["queue"]:
        sp = m["datasets"][q["dataset"]]["sports"]; tier = min((TIER.get(s, "P2") for s in sp), default="P2")
        slot_inputs = sorted({s[1] for s in q["slots"]})
        queue.append({"dataset": q["dataset"], "title": m["datasets"][q["dataset"]]["title"], "sports": sp, "tier": tier, "action_group": q["action_group"],
                      "access_status": q["access_status"], "rights_tier": q["rights_tier"], "missing_primary_slots": q["missing_primary_slots"],
                      "distinct_archetypes": q["distinct_archetypes"], "distinct_inputs": q["distinct_inputs"], "cost": q["cost"], "pit": q["pit"],
                      "basis": "EVIDENCE_BACKED" if any(i in tested for i in slot_inputs) else "HYPOTHESIS",
                      "next_actions": q["next_actions"], "map_rank": q["rank"]})
    queue.sort(key=lambda r: (r["tier"], GROUP_ORDER.index(r["action_group"]), 0 if r["access_status"] == "COLLECTED_ARCHIVE" else 1, -r["missing_primary_slots"], -r["distinct_archetypes"], r["dataset"]))
    for n, r in enumerate(queue, 1):
        r["rank"] = n

    sports = {}
    for s in SPORTS:
        ins = [v for v in inputs.values() if v["sport"] == s]; pred = [v for v in ins if v["predictive"]]
        ms = [v for v in markets.values() if v["sport"] == s]
        chs = [c for c in challengers.values() if c["sport"] == s]
        sports[s] = {"tier": TIER[s], "archetypes": len(ms), "archetypes_registered": sum(1 for v in ms if v["kind"] == "registered"),
                     "kalshi_series_in_scope": universe.get(s, {}).get("in_scope"),
                     "inputs_all": len(ins), "inputs_predictive": len(pred),
                     "at_counts": [sum(1 for v in pred if v["at"] == i) for i in range(8)],
                     "reached_counts": [sum(1 for v in pred if v["at"] >= i) for i in range(8)],
                     "stop_outcomes": dict(Counter(v["stop"]["outcome"] for v in pred if v["stop"])),
                     "production_active": dict(Counter(v["production_active"] for v in pred)),
                     "challengers": [f"{c['sport']}:{c['id']}" for c in chs],
                     "challenger_verdicts": {c["id"]: c["verdict"]["overall"] for c in chs},
                     "markets_with_challenger": sum(1 for v in ms if v["challengers"]),
                     "validated_improvements": sum(1 for v in pred if v["at"] == 7),
                     "missing_primary_slots": sum(1 for a, i, role, cls, grp, cat in m["edges"] if a.startswith(s + ":") and cls == "PREDICTIVE" and role == "primary" and cat not in ("FULL", "PARTIAL", "PROXY")),
                     "top_queue": [q["dataset"] for q in queue if s in q["sports"]][:5]}

    totals = {"archetypes": len(markets), "inputs": len(inputs), "inputs_predictive": sum(1 for v in inputs.values() if v["predictive"]), "datasets": len(datasets),
              "challengers": len(challengers), "at_counts_all_inputs": [sum(1 for v in inputs.values() if v["at"] == i) for i in range(8)],
              "queue_datasets": len(queue), "missing_primary_slots": sum(v["missing_primary_slots"] for v in sports.values())}
    recon = {"map_archetypes": m["reconciliation"]["archetypes"], "map_inputs": m["reconciliation"]["distinct_inputs"], "map_datasets": m["reconciliation"]["datasets"],
             "map_missing_primary": m["reconciliation"]["missing_primary_predictive_slots"], "map_queue_datasets": m["reconciliation"]["queue_datasets"],
             "claims_for_unknown_inputs": unknown_claims, "results_for_unknown_archetypes": unknown_arch,
             "ok": (len(markets) == m["reconciliation"]["archetypes"] and len(inputs) == m["reconciliation"]["distinct_inputs"] and len(datasets) == m["reconciliation"]["datasets"]
                    and totals["missing_primary_slots"] == m["reconciliation"]["missing_primary_predictive_slots"] and sum(totals["at_counts_all_inputs"]) == len(inputs)
                    and not unknown_claims and not unknown_arch)}
    mw = json.loads((OPS / "market_watch.json").read_text()) if (OPS / "market_watch.json").exists() else None
    for sp in SPORTS:
        sports[sp]["new_series_unresolved"] = (mw or {}).get("new_in_scope_by_sport", {}).get(sp, 0) if mw else None
    head = {"schema": "sift-foundation-ledger/1", "status": "RESEARCH_ONLY", "notice": NOTICE, "stages": STAGES, "chain": CHAIN, "sports_order": SPORTS,
            "map_inputs_sha256": m["inputs_sha256"], "evaluations": [e["_path"] for e in evals], "totals": totals, "reconciliation": recon}
    ledger = {**head, "probes": probes, "inputs": inputs, "markets": markets, "datasets": datasets, "challengers": challengers, "queue": queue, "sports": sports}
    scoreboard = {s: _scoreboard([c for c in challengers.values() if c["sport"] == s]) for s in SPORTS}
    ledger["scoreboard"] = scoreboard
    summary = {**head, "sports": sports, "market_watch": mw, "scoreboard": scoreboard,
               "challengers": {k: {x: v[x] for x in ("sport", "id", "incumbent", "verdict", "archetypes", "verdict_counts", "results", "limitations", "path", "data_through")} for k, v in challengers.items()},
               "queue_top": {t: [q for q in queue if q["tier"] == t][:8] for t in ("P0", "P1", "P2")},
               "built_inputs": _built_inputs(inputs, claims, feats)}
    return ledger, summary


PHASE15 = {"NBA_nba_team3": "alpha_engine/features/nba_ext3.py", "NBA_nba_player3": "alpha_engine/features/nba_player_ext3.py",
           "NHL_nhl2": "alpha_engine/features/nhl_ext2.py", "NHL_nhl_ev2": "alpha_engine/features/nhl_ev_ext2.py", "NHL_nhl_player2": "alpha_engine/features/nhl_player_ext3.py"}


def _built_inputs(inputs: dict, claims: dict, feats: dict) -> list:
    """The Phase 15 archive-built inputs with EVERY recorded use, not only the strongest claim: built, used by a challenger or
    probe, evaluated, validated. Evidence paths point at the replay, the blind match, the builder and the claiming evaluations."""
    ver = ROOT / "research" / "input_research" / "data_foundation" / "verification"
    out = []
    for fam, builder in PHASE15.items():
        ind = json.loads((ver / "independent" / f"{fam}.json").read_text())
        sport = fam.split("_")[0]
        for iid, rec in ind["inputs"].items():
            k = f"{sport}:{iid}"; inp = inputs.get(k, {}); cols = rec.get("columns", {})
            # an earlier challenger may claim the same catalog input with its OWN implementation; only a feature whose id names the
            # Phase 15 builder (or a probe of the builder columns) counts as use of the archive-built feature
            p15 = {ch for f, ch in feats.get(k, []) if "phase15" in f}
            uses = [{"by": c["challenger"], "kind": "probe" if str(c["challenger"]).startswith("probe:") else "challenger", "stage": c["stage"], "outcome": c["outcome"],
                     "uses_phase15_builder": str(c["challenger"]).startswith("probe:") or c["challenger"] in p15,
                     "evidence": str(c.get("evidence", ""))[:400]} for c in claims.get(k, [])]
            out.append({"key": k, "sport": sport, "id": iid, "label": inp.get("label", iid), "at": inp.get("at"), "chain": inp.get("chain"),
                        "blind_match": all(v.get("verdict") == "MATCH" for v in cols.values()) and bool(cols), "n_columns": len(cols),
                        "builder": builder if (ROOT / builder).exists() else builder.replace("nhl_player_ext3", "nhl_player_ext2"),
                        "replay": f"research/input_research/data_foundation/verification/replay_ext/{fam}.json",
                        "blind": f"research/input_research/data_foundation/verification/independent/{fam}.json",
                        "uses": uses, "used_in_challenger": any(u["kind"] == "challenger" and u["uses_phase15_builder"] for u in uses),
                        "evaluated": any(u["uses_phase15_builder"] and u["stage"] in ("EVALUATED", "VALIDATED_IMPROVEMENT") for u in uses),
                        "selected_by_challenger": any(u["kind"] == "challenger" and u["uses_phase15_builder"] and u["outcome"] in ("OK", "PARTIAL") for u in uses),
                        "validated": inp.get("chain", [None] * 8)[7] == "OK" if inp else False})
    return out


def _day(x) -> str:
    """ISO day of a dataset's last record, or '' when the field is not a date (e.g. a season label)."""
    t = str(x or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", t):
        return t[:10]
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}" if re.match(r"^\d{8}T", t) else ""


def _scoreboard(chs: list) -> dict:
    """Per sport: is research improving the projection, against what, and where is it weakest. Computed from tested result
    rows only (descriptive rows are excluded); nothing here is typed by hand and nothing is a profitability statement."""
    rows = []
    for c in sorted(chs, key=lambda c: c["id"]):
        tested = [r for r in c["results"] if r.get("tested")]
        tally = {k: dict(Counter(r["verdict"] for r in tested if r["reference_kind"] == k)) for k in ("CURRENT_MODEL", "MARKET", "PRIOR_CHALLENGER", "BASELINE")}
        mk = [r for r in c["results"] if r["reference_kind"] == "MARKET"]       # tested or descriptive: the gap is shown either way, labelled
        gap = sorted(({"market_family": r["market_family"], "metric": r["metric"], "diff": r["diff"], "ci95": r["ci95"], "n_clusters": r["n_clusters"],
                       "cohort": r.get("cohort"), "tested": bool(r.get("tested")),
                       "state": "WORSE_THAN_MARKET" if r["ci95"] and r["ci95"][0] is not None and r["ci95"][0] > 0
                                else "BETTER_THAN_MARKET" if r["ci95"] and r["ci95"][1] is not None and r["ci95"][1] < 0 else "NO_DETECTABLE_DIFFERENCE"} for r in mk),
                     key=lambda g: -(g["diff"] or 0))
        rows.append({"id": c["id"], "overall": c["verdict"]["overall"], "retain_incumbent": c["verdict"].get("retain_incumbent", True),
                     "data_through": c["data_through"], "tally": {k: v for k, v in tally.items() if v},
                     "validated_vs_current_model": tally["CURRENT_MODEL"].get("VALIDATED_IMPROVEMENT", 0),
                     "validated_vs_market": tally["MARKET"].get("VALIDATED_IMPROVEMENT", 0),
                     "market_gap": gap, "why": c["verdict"].get("reason", "")})
    worse = Counter(g["market_family"] for r in rows for g in r["market_gap"] if g["state"] == "WORSE_THAN_MARKET")
    better = Counter(g["market_family"] for r in rows for g in r["market_gap"] if g["state"] == "BETTER_THAN_MARKET")
    status = ("NO_CHALLENGER" if not rows else "VALIDATED_VS_MARKET" if any(r["validated_vs_market"] for r in rows)
              else "VALIDATED_VS_CURRENT_MODEL_ONLY" if any(r["validated_vs_current_model"] for r in rows) else "NO_VALIDATED_GAIN")
    return {"status": status, "challengers": rows, "families_worse_than_market": sorted(worse), "families_better_than_market": sorted(better),
            "data_through": max((r["data_through"] for r in rows), default="")}


def _shown_rows(results: list) -> list:
    """Rows shown on the dashboard: the evaluation's own headline rows (pooled test cohorts), plus, for every other
    (family, metric, reference) that has no headline row, its widest cohort (a pooled cohort if one exists, else the
    largest). This keeps market comparisons visible when the market reference exists for one season only."""
    pooled = lambda r: "pooled" in str(r.get("cohort", "pooled"))
    key = lambda r: (r["market_family"], r["metric"], r["reference"])
    head = [r for r in results if r.get("headline") or (not any("headline" in x for x in results) and pooled(r))]
    seen = {key(r) for r in head}
    rest = {}
    for r in results:
        k = key(r)
        if k in seen:
            continue
        best = rest.get(k)
        if best is None or (pooled(r), r["n_rows"]) > (pooled(best), best["n_rows"]):
            rest[k] = r
    # Rows outside the evaluation's Holm family carry a placeholder p-value and verdict in the source file. They are shown
    # for context only: no adjusted p-value, and an explicit DESCRIPTIVE label instead of a tested verdict.
    extra = [{**rest[k], "p_holm": None, "verdict": "DESCRIPTIVE", "tested": False} for k in sorted(rest)]
    return [{**r, "tested": True} for r in head] + extra


def _market_next(mk: dict, prim: list, inputs: dict) -> str:
    if not prim:
        return "No PRIMARY predictive input is listed; review the archetype's blueprint."
    stops = Counter((inputs[i]["stop"]["stage"], inputs[i]["stop"]["outcome"]) for i in prim if inputs[i]["stop"])
    if not stops:
        return "Every PRIMARY input has a validated improvement; prepare for production review."
    (stage, outcome), n = sorted(stops.items(), key=lambda kv: (-kv[1], CHAIN.index(kv[0][0])))[0]
    verb = {"SOURCE_LOCATED": "find a source for", "COLLECTED": "collect (or get an owner decision for)", "VERIFIED": "verify / repair builders for", "FEATURE_BUILT": "build features for",
            "CHALLENGER_INTEGRATED": "integrate into a challenger", "EVALUATED": "evaluate", "VALIDATED_IMPROVEMENT": "replicate the evaluation for"}[stage]
    tail = "" if mk["challengers"] else " No challenger is attached to this market yet."
    return f"Largest stop: {n} of {len(prim)} PRIMARY inputs at {stage} ({outcome}) — {verb} them first.{tail}"


def main() -> None:
    ledger, summary = build()
    write_json(OPS / "pipeline_ledger.json", ledger)
    write_json(OPS / "summary.json", summary)
    t = ledger["totals"]
    print(f"{t['archetypes']} archetypes | {t['inputs']} inputs | {t['datasets']} datasets | {t['challengers']} challengers | at-stage counts {dict(zip(CHAIN, t['at_counts_all_inputs']))} | reconciles={ledger['reconciliation']['ok']}")


if __name__ == "__main__":
    main()

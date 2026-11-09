"""Data-foundation audit of every catalog input (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.audit            # build all artifacts under research/input_research/data_foundation/
    python -m alpha_engine.input_research.data_foundation.audit --packets DIR   # also write compact per-sport review packets for reviewers (outside the repo)

For every one of the catalog's inputs (1,649 at the approved baseline) the audit records: exact raw-data requirements (needs -> datasets), the real sources named by the catalog's own
provenance, measured access status of each required dataset, history coverage, freshness, cost, ToS risk, known missingness and the point-in-time verdict, then resolves one STATUS and one
headline BUCKET. Reviewer corrections (`review/<SPORT>.json`) are validated and merged; nothing a reviewer says can override the registry's measured facts, only which datasets an input needs.

STATUS -> BUCKET
  COMPUTED_FULL | COMPUTED_PARTIAL | COMPUTED_PROXY   (earlier milestone computed it on real data with a point-in-time perturbation test; agent-verified, independent verification pending)  -> COMPUTABLE
  DATA_IN_HAND                  every needed dataset is a profiled archive and the point-in-time verdict is safe/coarse; no builder written yet                                          -> COMPUTABLE
  COLLECT_FREE_MEASURED         a free source for every need was fetched from the runner (pull + build)                                                                                     -> REQUIRES_COLLECTION
  COLLECT_FREE_UNVERIFIED       free source documented but not verifiable from the runner (blocked host, unprobed, reference document to encode)                                            -> REQUIRES_COLLECTION
  COLLECT_PROSPECTIVE           history cannot be backfilled (vintages, live-only feeds, manual coding): record from now on, or accept FINAL-ONLY leakage                                  -> REQUIRES_COLLECTION
  BLOCKED_SAMPLE_ONLY / BLOCKED_PAID_ONLY / BLOCKED_NO_FREE_SOURCE                                                                                                                    -> BLOCKED
  EXCLUDED_BENCHMARK_ONLY       market-derived; never a market-free input                                                                                                                   -> EXCLUDED
"""
from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

from .. import catalog as cat
from .. import market_dependency as MD
from . import datasets as DS
from . import evidence as EV
from . import rules as RL
from . import sources as SRC

ROOT = EV.ROOT
IN = EV.IN
DF = EV.DF
REVIEW = DF / "review"
SPORTS = RL.SPORTS
PROV_RANK = {"free": 1, "free_scrape": 1, "free_limited": 1, "derived": None, "own_capture": 5, "paid": 6, "unavailable_public": 7}
STATUS_OF_RANK = {0: "DATA_IN_HAND", 1: "COLLECT_FREE_MEASURED", 2: "COLLECT_FREE_UNVERIFIED", 3: "COLLECT_FREE_UNVERIFIED", 4: "BLOCKED_SAMPLE_ONLY", 5: "COLLECT_PROSPECTIVE", 6: "BLOCKED_PAID_ONLY", 7: "BLOCKED_NO_FREE_SOURCE"}
BUCKET = {"COMPUTED_FULL": "COMPUTABLE", "COMPUTED_PARTIAL": "COMPUTABLE", "COMPUTED_PROXY": "COMPUTABLE", "DATA_IN_HAND": "COMPUTABLE", "COLLECT_FREE_MEASURED": "REQUIRES_COLLECTION", "COLLECT_FREE_UNVERIFIED": "REQUIRES_COLLECTION",
          "COLLECT_PROSPECTIVE": "REQUIRES_COLLECTION", "BLOCKED_SAMPLE_ONLY": "BLOCKED", "BLOCKED_PAID_ONLY": "BLOCKED", "BLOCKED_NO_FREE_SOURCE": "BLOCKED", "EXCLUDED_BENCHMARK_ONLY": "EXCLUDED"}
STATUSES = tuple(BUCKET)
STATUS_ORDER = ("COMPUTED_FULL", "COMPUTED_PARTIAL", "COMPUTED_PROXY", "DATA_IN_HAND", "COLLECT_FREE_MEASURED", "COLLECT_FREE_UNVERIFIED", "COLLECT_PROSPECTIVE", "BLOCKED_SAMPLE_ONLY", "BLOCKED_PAID_ONLY", "BLOCKED_NO_FREE_SOURCE")
PIT_VERDICTS = ("PIT_SAFE", "PIT_COARSE", "PIT_LEAKY_FINAL_ONLY", "PIT_UNAVAILABLE_HISTORICALLY", "NOT_PREGAME_KNOWABLE", "NOT_APPLICABLE")
COMPUTED = {"COMPUTED_FULL": "COMPUTED_FULL", "COMPUTED_LIMITED_FULL": "COMPUTED_FULL", "COMPUTED_PARTIAL": "COMPUTED_PARTIAL", "COMPUTED_LIMITED_PARTIAL": "COMPUTED_PARTIAL", "COMPUTED_PROXY": "COMPUTED_PROXY", "COMPUTED_LIMITED_PROXY": "COMPUTED_PROXY"}


def rd(p):
    return json.loads(Path(p).read_text())


def _year(x):
    return None if not x else str(x)[:4]


def load_inputs() -> list[dict]:
    comp = rd(IN / "computable_inputs.json")["inputs"]
    coll = rd(ROOT / "research/audit/collection_status.json")["sports"]
    rows = []
    for s in SPORTS:
        c = cat.load(s)
        used = collections.defaultdict(list)
        for sec in ("archetypes", "unregistered_archetypes"):
            for a, rec in (c.get(sec) or {}).items():
                for i in rec["inputs"]:
                    used[i["id"]].append(("unreg:" + a) if sec == "unregistered_archetypes" else a)
        for iid, r in c["inputs"].items():
            rows.append({"sport": s, "id": iid, "rec": r, "archetypes": sorted(set(used.get(iid, []))), "computed": comp.get(f"{s}:{iid}"), "collection": (coll.get(s, {}).get("inputs") or {}).get(iid)})
    return rows


def load_review() -> dict:
    out = {}
    for s in SPORTS:
        f = REVIEW / f"{s}.json"
        if f.exists():
            out[s] = rd(f)
    return out


PREFIX = {"NFL": "nfl", "CFB": "cfb", "NBA": "nba", "CBB": "cbb", "NHL": "nhl", "MLB": "mlb", "SOCCER": "soc", "TENNIS": "ten"}


def register_proposed(sport: str, rv: dict) -> list[str]:
    """Reviewer-proposed datasets (a need the registry has no dataset for). Registered as DOCUMENTED, flagged `proposed_by`; measured facts are never taken from a proposal."""
    e = []
    for d in rv.get("new_datasets") or []:
        i = d.get("id", "")
        if not i or i in DS.DATASETS or not (i.startswith(PREFIX[sport] + ".") or i.startswith(("xx.", "env."))):
            e.append(f"{sport}: bad or duplicate new dataset id {i!r}"); continue
        if d.get("kind") not in DS.KINDS or d.get("pit") not in DS.PIT or any(x not in SRC.SOURCES for x in d.get("sources") or []) or not d.get("sources") or len(str(d.get("title", ""))) < 10:
            e.append(f"{sport}: invalid new dataset {i}"); continue
        DS.D(i, [sport] if not i.startswith(("xx.", "env.")) else d.get("sports") or [sport], d["title"], d["sources"], first=d.get("first"), last=d.get("last"), basis="DOCUMENTED", pit=d["pit"], fresh=d.get("freshness", ""), miss=d.get("missingness", ""), kind=d["kind"],
             notes=f"proposed_by: {rv.get('reviewer')} (DOCUMENTED, not measured)")
    return e


def validate_review(sport: str, rv: dict, ids: set[str], reg: dict, strict: bool = True) -> list[str]:
    e = []
    if not isinstance(rv.get("overrides"), dict) or not isinstance(rv.get("verdicts"), dict):
        return [f"{sport}: review file needs 'verdicts' and 'overrides' objects"]
    vd = rv["verdicts"]
    if strict:
        if set(vd) != ids:
            e.append(f"{sport}: verdicts must cover exactly every input id (missing {len(ids - set(vd))}, unknown {len(set(vd) - ids)}): {sorted(ids - set(vd))[:5]}")
        for i, v in vd.items():
            if v not in ("OK", "FIX"):
                e.append(f"{sport}:{i}: verdict must be OK or FIX")
        for i in [i for i, v in vd.items() if v == "FIX"]:
            if i not in rv["overrides"]:
                e.append(f"{sport}:{i}: FIX needs an override")
        for i in rv["overrides"]:
            if vd.get(i) != "FIX":
                e.append(f"{sport}:{i}: override without a FIX verdict")
    for iid, o in rv["overrides"].items():
        if iid not in ids:
            e.append(f"{sport}:{iid}: unknown input"); continue
        if len(str(o.get("rationale", ""))) < 40:
            e.append(f"{sport}:{iid}: rationale >= 40 chars required")
        for n in o.get("needs") or []:
            if n.get("need") not in {x[0] for x in RL.NEED_RX} | {"RESULTS"}:
                e.append(f"{sport}:{iid}: unknown need {n.get('need')}")
            for d in n.get("datasets") or []:
                if d not in reg:
                    e.append(f"{sport}:{iid}: unknown dataset {d}")
        if o.get("status") and o["status"] not in STATUSES:
            e.append(f"{sport}:{iid}: unknown status {o['status']}")
        if o.get("pit") and o["pit"] not in PIT_VERDICTS:
            e.append(f"{sport}:{iid}: unknown pit {o['pit']}")
        for u in o.get("depends_on") or []:
            if u not in ids and ":" not in u:
                e.append(f"{sport}:{iid}: depends_on {u} is not a catalog input id of this sport (use SPORT:id for another sport)")
    return e


def assess(sport: str, rec: dict, reg: dict, review: dict | None, extra: dict) -> dict:
    iid = extra["id"]; r = rec
    raw = r.get("raw_data") or []
    hits, basis = RL.needs_for(sport, r["label"], raw, r.get("measurement", ""), r.get("mechanism", ""))
    needs = [{"need": n, "trigger": t, "candidates": RL.need_map(sport, n)} for n, t in hits]
    if not needs:
        needs = [{"need": "RESULTS", "trigger": "(no trigger matched: default to results/schedule)", "candidates": RL.need_map(sport, "RESULTS")}]; basis = "default"
    conf = "HIGH" if basis == "raw_data+label" and len(hits) >= 1 else ("MEDIUM" if basis == "label+measurement" and hits else "LOW")
    if review and review.get("needs"):
        needs = [{"need": n["need"], "trigger": "reviewer", "candidates": [d for d in n.get("datasets") or []]} for n in review["needs"] if n.get("datasets")] or needs
        conf = review.get("confidence") or "HIGH"; basis = "reviewer"
    resolved = []
    for n in needs:
        cands = [d for d in n["candidates"] if d in reg and (sport in reg[d]["sports"])]
        if not cands:
            cands = [d for d in n["candidates"] if d in reg]
        best = min(cands, key=lambda d: (reg[d]["access_rank"], reg[d]["pit_rank"]), default=None)
        resolved.append({**n, "datasets_considered": cands, "satisfied_by": best, "access_status": reg[best]["access_status"] if best else None, "pit": reg[best]["pit"] if best else None, "pit_sensitive": n["need"] in RL.PIT_SENSITIVE})
    drank = max((reg[x["satisfied_by"]]["access_rank"] for x in resolved if x["satisfied_by"]), default=1)
    # catalog provenance: best source access class (alternatives), conservative floor for own-capture / paid / unavailable
    prov = (r.get("provenance") or {}).get("sources") or []
    pr = [PROV_RANK[x["access"]] for x in prov if PROV_RANK.get(x["access"]) is not None]
    prov_best = min(pr) if pr else None
    floor = prov_best if (prov_best is not None and prov_best >= 5) else 0
    rank = max(drank, floor)
    status = STATUS_OF_RANK[rank]
    flags = []
    if floor > drank:
        flags.append(f"catalog provenance caps availability: best listed source is {['', 'free', '', '', '', 'own_capture', 'paid', 'unavailable_public'][floor]} while the dataset map says {STATUS_OF_RANK[drank]}")
    sens = [x for x in resolved if x["pit_sensitive"]]
    nonsens_final = [x for x in resolved if not x["pit_sensitive"] and x["pit"] == "FINAL_ONLY"]
    pk = r.get("pregame_knowable")
    if pk == "no":
        pitv = "NOT_PREGAME_KNOWABLE"
    else:
        worst = max([PIT_RANK(x["pit"]) for x in sens if x["pit"]] + [0])
        pitv = "PIT_UNAVAILABLE_HISTORICALLY" if worst >= 3 else ("PIT_LEAKY_FINAL_ONLY" if worst == 2 else ("PIT_COARSE" if worst == 1 else "PIT_SAFE"))
        if nonsens_final and pitv == "PIT_SAFE":
            pitv = "PIT_COARSE"; flags.append("a non-sensitive need rests on FINAL_ONLY data (as-played / retrieval-time values): check for look-ahead")
    # earlier milestone computation
    cp = extra.get("computed"); prior = None
    if cp and cp.get("status") in COMPUTED:
        cov = [c["coverage"] for c in (cp.get("coverage") or {}).values() if c.get("present")]
        firsts = [c["first"] for c in (cp.get("coverage") or {}).values() if c.get("first")]; lasts = [c["last"] for c in (cp.get("coverage") or {}).values() if c.get("last")]
        prior = {"status": cp["status"], "level": cp.get("level"), "pit_class": cp.get("pit"), "leak_test_ok": (cp.get("leak_test") or {}).get("ok"), "coverage_min": round(min(cov), 4) if cov else None,
                 "first": min(firsts) if firsts else None, "last": max(lasts) if lasts else None, "missing_components": cp.get("missing") or [], "table": cp.get("table")}
    full_def_status = status
    bench = MD.kind(iid) == "benchmark_only"
    if bench:
        status = "EXCLUDED_BENCHMARK_ONLY"; pitv = "NOT_APPLICABLE"
    elif prior:
        status = COMPUTED[cp["status"]]
        if pitv in ("PIT_LEAKY_FINAL_ONLY", "PIT_UNAVAILABLE_HISTORICALLY") and prior["leak_test_ok"]:
            flags.append("computed under a perturbation leak test but the registry says a needed vintage is final-only: the test cannot detect stale-vintage leakage")
    else:
        if pitv in ("PIT_LEAKY_FINAL_ONLY", "PIT_UNAVAILABLE_HISTORICALLY") and status in ("DATA_IN_HAND", "COLLECT_FREE_MEASURED", "COLLECT_FREE_UNVERIFIED"):
            status = "COLLECT_PROSPECTIVE"; flags.append("point-in-time: only final/as-played or live-snapshot values exist historically; genuine pregame history needs vintage capture")
    # review override of the final status (rationale validated; measured registry facts are never edited)
    if review and review.get("status") and not bench:   # a market-derived benchmark input stays excluded whatever a reviewer says
        flags.append(f"status set by reviewer from {status} to {review['status']}"); status = review["status"]
    if review and review.get("pit"):
        pitv = review["pit"]
    sat = [reg[x["satisfied_by"]] for x in resolved if x["satisfied_by"]]
    firsts = [_year(s["history"]["first"]) for s in sat]; lasts = [_year(s["history"]["last"]) for s in sat]
    hist = {"first": (max(f for f in firsts if f) if all(firsts) else None), "last": (min(l for l in lasts if l) if all(lasts) else None), "complete": bool(firsts) and all(firsts), "basis": ("MEASURED" if sat and all(s["history"]["basis"] == "MEASURED" for s in sat) else "DOCUMENTED_OR_UNKNOWN")}
    if prior and prior["first"]:
        hist = {"first": _year(prior["first"]), "last": _year(prior["last"]), "complete": True, "basis": "MEASURED (computed table)"}
    if hist["first"] and hist["last"] and hist["complete"] and not prior:
        try:
            if int(hist["last"]) - int(hist["first"]) + 1 < 3:
                flags.append(f"short history ({hist['first']}-{hist['last']}): fewer than 3 seasons")
        except ValueError:
            pass
    miss = []
    for s in sat:
        if s["missingness"] and s["missingness"] not in miss:
            miss.append(s["missingness"])
    if prior and prior["coverage_min"] is not None:
        miss.insert(0, f"computed coverage (min over columns) {prior['coverage_min']:.1%}")
    cost = "paid" if any(s["cost"] == "paid" for s in sat) or status == "BLOCKED_PAID_ONLY" else ("free (key needed)" if any(s["cost"] == "free (key needed)" for s in sat) else "free")
    full_cost = cost
    if prior:
        cost = "free"   # it WAS computed, from collected/free data; what the full definition would additionally need is recorded in full_definition_cost / full_definition_status
        if prior["status"] in ("COMPUTED_FULL", "COMPUTED_LIMITED_FULL") and STATUS_ORDER.index(full_def_status) >= STATUS_ORDER.index("COLLECT_PROSPECTIVE"):
            flags.append(f"CONFLICT: computed at FULL definition by the earlier milestone, but the need map says the full definition is {full_def_status}: the draft need map is too pessimistic for this input")
    tos = max([s["tos_risk"] for s in sat] or ["low"], key=lambda x: ("low", "medium", "high").index(x))
    if status.startswith("COLLECT") or status == "DATA_IN_HAND":
        if tos == "high":
            flags.append("source terms restrict automated/bulk access (ToS risk high): obtain a permitted route before any collection")
    srcs = []
    for p in prov:
        ids = SRC.resolve(p["name"])
        srcs.append({"name": p["name"][:140], "access": p["access"], "canonical": ids})
    if not prov:
        for fs in (r.get("free_sources") or [])[:4]:
            srcs.append({"name": fs[:140], "access": "(free_sources text, no provenance)", "canonical": SRC.resolve(fs)})
    blockers = []
    if status.startswith("BLOCKED") or status == "COLLECT_PROSPECTIVE":
        blockers = [{"need": x["need"], "dataset": x["satisfied_by"], "access_status": x["access_status"], "pit": x["pit"]} for x in resolved if x["satisfied_by"] and (reg[x["satisfied_by"]]["access_rank"] >= 4 or (x["pit_sensitive"] and PIT_RANK(x["pit"]) >= 2))]
    ev_grade = "MEASURED" if all(reg[x["satisfied_by"]]["evidence_grade"] == "MEASURED" for x in resolved if x["satisfied_by"]) else "PARTLY_DOCUMENTED"
    if prior:
        ev_grade = "MEASURED (computed)"
    cc = extra.get("collection")
    out = {"key": f"{sport}:{iid}", "sport": sport, "id": iid, "label": r["label"], "category": r["category"], "pregame_knowable": pk, "market_free": r.get("market_free"), "retired": bool(r.get("retired")), "audit_flag": r.get("audit_flag"),
           "archetypes": extra["archetypes"], "catalog_raw_data": raw, "requirements": resolved, "requirement_basis": basis, "provenance_sources": srcs, "provenance_verified": (r.get("provenance") or {}).get("verified"),
           "status": status, "bucket": BUCKET[status], "full_definition_status": full_def_status, "pit_verdict": pitv, "history": hist, "freshness": sorted({s["freshness"] for s in sat if s["freshness"]}), "cost": cost, "full_definition_cost": full_cost, "tos_risk": tos,
           "missingness": miss[:4], "blockers": blockers, "confidence": conf, "evidence_grade": ev_grade, "flags": flags, "computed_prior": prior, "prior_collection_class": (cc or {}).get("collection"), "prior_verification_class": (cc or {}).get("verification_class"),
           "reviewed": bool(review)}
    if review:
        out["review"] = {"rationale": review.get("rationale"), "notes": review.get("notes"), "needs_new_dataset": review.get("needs_new_dataset")}
    return out


def PIT_RANK(p):
    return EV.PIT_RANK.get(p, 0)


def build(write: bool = True) -> dict:
    rv_all = load_review(); rows = []; ids_by_sport = collections.defaultdict(set); errors = []
    inputs = load_inputs()
    for x in inputs:
        ids_by_sport[x["sport"]].add(x["id"])
    snapshot = dict(DS.DATASETS)
    try:
        for s_, rv in rv_all.items():
            errors += register_proposed(s_, rv)
        reg = EV.resolve_all()
        for s_, rv in rv_all.items():
            errors += validate_review(s_, rv, ids_by_sport[s_], reg)
        if errors:
            raise ValueError("review files invalid:\n  " + "\n  ".join(errors[:40]))
        for x in inputs:
            ov = ((rv_all.get(x["sport"]) or {}).get("overrides") or {}).get(x["id"])
            row = assess(x["sport"], x["rec"], reg, ov, x)
            row["reviewed"] = x["sport"] in rv_all and ((rv_all[x["sport"]].get("verdicts") or {}).get(x["id"]) in ("OK", "FIX"))
            row["review_verdict"] = (rv_all.get(x["sport"]) or {}).get("verdicts", {}).get(x["id"])
            row["depends_on"] = list((ov or {}).get("depends_on") or [])
            rows.append(row)
    finally:
        DS.DATASETS.clear(); DS.DATASETS.update(snapshot)
    propagate_dependencies(rows)
    summ = summarize(rows, reg, rv_all)
    if write:
        DF.mkdir(parents=True, exist_ok=True)
        pub = {k: v for k, v in reg.items()}
        (DF / "datasets.json").write_text(json.dumps({"schema_version": "data-foundation-datasets-1.0", "status": "RESEARCH_ONLY", "datasets": pub}, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
        (DF / "sources.json").write_text(json.dumps({"schema_version": "data-foundation-sources-1.0", "status": "RESEARCH_ONLY", "sources": {k: SRC.public(k) for k in SRC.SOURCES}}, indent=0, sort_keys=True) + "\n")
        (DF / "input_audit.json").write_text(json.dumps({"schema_version": "data-foundation-input-audit-1.0", "status": "RESEARCH_ONLY", "independently_verified": False, "n_inputs": len(rows), "rows": rows}, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
        (DF / "summary.json").write_text(json.dumps(summ, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
        with open(DF / "coverage_matrix.csv", "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["sport", "input_id", "bucket", "status", "pit_verdict", "history_first", "history_last", "cost", "tos_risk", "confidence", "needs", "satisfied_by", "limiting_dataset", "pregame_knowable", "reviewed"])
            for r in rows:
                lim = sorted((x for x in r["requirements"] if x["satisfied_by"]), key=lambda x: -reg[x["satisfied_by"]]["access_rank"])
                w.writerow([r["sport"], r["id"], r["bucket"], r["status"], r["pit_verdict"], r["history"]["first"], r["history"]["last"], r["cost"], r["tos_risk"], r["confidence"], "|".join(x["need"] for x in r["requirements"]),
                            "|".join(sorted({x["satisfied_by"] for x in r["requirements"] if x["satisfied_by"]})), lim[0]["satisfied_by"] if lim else "", r["pregame_knowable"], int(r["reviewed"])])
    return {"rows": rows, "summary": summ, "registry": reg}


def propagate_dependencies(rows: list[dict]) -> None:
    """A derived input is only as available as the inputs it is built from: status = worst of its own and its upstream inputs (conservative; cycles ignored)."""
    byk = {r["key"]: r for r in rows}
    memo: dict[str, str] = {}

    def worst(k: str, stack: tuple = ()) -> str:
        if k in memo:
            return memo[k]
        r = byk[k]; st = r["status"]
        if r["status"] == "EXCLUDED_BENCHMARK_ONLY":
            return st
        for u in r.get("depends_on") or []:
            uk = u if ":" in u else f"{r['sport']}:{u}"
            if uk not in byk or uk in stack:
                continue
            us = worst(uk, stack + (k,))
            if us == "EXCLUDED_BENCHMARK_ONLY":
                if "depends on a benchmark-only (market-derived) input" not in r["flags"]:
                    r["flags"].append("depends on a benchmark-only (market-derived) input")
                continue
            avail = STATUS_ORDER.index("DATA_IN_HAND")   # computed / in-hand upstream inputs are all "available": they never downgrade a computed input
            if STATUS_ORDER.index(us) > max(STATUS_ORDER.index(st), avail):
                st = us
        memo[k] = st
        return st
    for r in rows:
        new = worst(r["key"])
        if new != r["status"]:
            r["flags"].append(f"status {r['status']} -> {new}: limited by an upstream input it is derived from")
            r["status"] = new; r["bucket"] = BUCKET[new]


def summarize(rows: list[dict], reg: dict, rv_all: dict) -> dict:
    by_sport = {s: collections.Counter() for s in SPORTS}; bucket_sport = {s: collections.Counter() for s in SPORTS}; pit_sport = {s: collections.Counter() for s in SPORTS}
    for r in rows:
        by_sport[r["sport"]][r["status"]] += 1; bucket_sport[r["sport"]][r["bucket"]] += 1; pit_sport[r["sport"]][r["pit_verdict"]] += 1
    # collection priorities: for inputs that need collection or are blocked, the limiting dataset
    limit = collections.defaultdict(lambda: {"inputs": 0, "archetype_links": 0, "sports": set()})
    for r in rows:
        if r["bucket"] in ("REQUIRES_COLLECTION", "BLOCKED"):
            lim = sorted((x for x in r["requirements"] if x["satisfied_by"]), key=lambda x: -reg[x["satisfied_by"]]["access_rank"])
            if lim:
                d = lim[0]["satisfied_by"]; limit[d]["inputs"] += 1; limit[d]["archetype_links"] += len(r["archetypes"]); limit[d]["sports"].add(r["sport"])
    prio = sorted(({"dataset": d, "title": reg[d]["title"], "access_status": reg[d]["access_status"], "pit": reg[d]["pit"], "cost": reg[d]["cost"], "tos_risk": reg[d]["tos_risk"], "inputs_limited_by_it": v["inputs"], "archetype_links": v["archetype_links"],
                    "sports": sorted(v["sports"])} for d, v in limit.items()), key=lambda x: (-x["inputs_limited_by_it"], x["dataset"]))
    return {"schema_version": "data-foundation-summary-1.0", "status": "RESEARCH_ONLY", "independently_verified": False,
            "verification_note": "Built by a Claude agent from measured probes, repo ledgers and the catalog's own provenance, then reviewed per sport by Claude reviewers. NOT independently verified and NOT human expert verified: predictive experimentation stays paused until that verification exists.",
            "n_inputs": len(rows), "by_status": dict(collections.Counter(r["status"] for r in rows)), "by_bucket": dict(collections.Counter(r["bucket"] for r in rows)), "by_sport_status": {s: dict(v) for s, v in by_sport.items()},
            "by_sport_bucket": {s: dict(v) for s, v in bucket_sport.items()}, "by_sport_pit": {s: dict(v) for s, v in pit_sport.items()}, "confidence": dict(collections.Counter(r["confidence"] for r in rows)),
            "evidence_grade": dict(collections.Counter(r["evidence_grade"] for r in rows)), "reviewed_inputs": sum(1 for r in rows if r["reviewed"]), "review_files": sorted(rv_all),
            "datasets": {"total": len(reg), "by_access_status": dict(collections.Counter(v["access_status"] for v in reg.values())), "evidence_grade": dict(collections.Counter(v["evidence_grade"] for v in reg.values()))},
            "collection_priorities": prio[:40], "needs_review_flags": sum(1 for r in rows if r["flags"]), "tos_high_collectable": sum(1 for r in rows if r["bucket"] in ("REQUIRES_COLLECTION", "COMPUTABLE") and r["tos_risk"] == "high"),
            "cost": dict(collections.Counter(r["cost"] for r in rows)), "paid_services_added": 0, "all_inputs_reviewed": all(r["reviewed"] for r in rows), "reviewer_verdicts": dict(collections.Counter(r.get("review_verdict") or "NOT_REVIEWED" for r in rows)),
            "proposed_datasets": sorted(d for d, v in reg.items() if "proposed_by" in (v.get("notes") or ""))}


def write_packets(dirp: Path) -> None:
    b = build(write=False); dirp.mkdir(parents=True, exist_ok=True)
    reg = b["registry"]
    for s in SPORTS:
        rows = []
        for r in b["rows"]:
            if r["sport"] != s:
                continue
            rows.append({"id": r["id"], "label": r["label"][:160], "pk": r["pregame_knowable"], "raw_data": r["catalog_raw_data"][:6], "prov": [f"{x['name'][:70]} [{x['access']}]" for x in r["provenance_sources"][:4]],
                         "needs": [{"need": x["need"], "trig": x["trigger"][:30], "ds": x["satisfied_by"], "st": x["access_status"], "pit": x["pit"]} for x in r["requirements"]], "status": r["status"], "pitv": r["pit_verdict"], "conf": r["confidence"],
                         "prior": (r["computed_prior"] or {}).get("status"), "flags": [f[:120] for f in r["flags"]]})
        (dirp / f"{s}.jsonl").write_text("\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in rows) + "\n")
    (dirp / "datasets.json").write_text(json.dumps({d: {"title": v["title"][:120], "sports": v["sports"], "status": v["access_status"], "pit": v["pit"], "hist": [v["history"]["first"], v["history"]["last"]], "cost": v["cost"], "miss": v["missingness"][:140]} for d, v in reg.items()}, separators=(",", ":"), ensure_ascii=False))


def main(argv=None) -> int:
    a = (argv if argv is not None else sys.argv)[1:]
    if "--packets" in a:
        write_packets(Path(a[a.index("--packets") + 1])); return 0
    b = build(write=True)
    s = b["summary"]
    print(json.dumps({k: s[k] for k in ("n_inputs", "by_bucket", "by_status", "confidence", "reviewed_inputs")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

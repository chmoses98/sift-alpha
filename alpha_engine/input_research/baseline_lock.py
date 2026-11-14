"""Content lock for the approved catalog baseline (RESEARCH_ONLY).

    python -m alpha_engine.input_research.baseline_lock                    # verify; exit 1 and list every mismatch
    python -m alpha_engine.input_research.baseline_lock --bump '<reason>'  # re-pin after a DELIBERATE, reviewed change (appends to history; never edits it)

What is pinned (research/input_research/baseline_lock.json):
  * per sport: sha256 of the canonical catalog JSON, plus counts of inputs, archetypes, interactions, non-linearities
  * every declared gap (the `unresolved` entries of the review records, 1,030 at approval): a sha256 of its full record and of its classification, so a gap cannot be deleted,
    reworded into a softer claim or reclassified without the change showing up here by id
  * the approved commit and the list of repairs applied on top of it (the approved commit is the *blueprint*; it is not human expert verification)
The lock is a tripwire for SILENT change, not a claim that the content is right. A bump needs a reason and is recorded; the test suite fails until the lock matches.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

from . import catalog as cat
from . import completeness as comp
from . import gap_audit

LOCK = comp.IN / "baseline_lock.json"
APPROVED_COMMIT = "50dc65e32e0a2c57a700905ceb986d6198ecf219"


def _sha(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def snapshot() -> dict:
    sports, gaps = {}, {}
    for s in comp.SPORTS:
        c = cat.load(s)
        arches = [comp.arch_entry(c, k) for k in comp.arch_keys(c)]
        sports[s] = {"catalog_sha256": _sha(c), "inputs": len(c["inputs"]), "registered_archetypes": len(c["archetypes"]), "unregistered_archetypes": len(c.get("unregistered_archetypes") or {}),
                     "archetype_interactions": sum(len(a["interactions"]) for a in arches), "blueprint_interactions": sum(len(b["interactions"]) for b in c["blueprints"].values()),
                     "nonlinearities": sum(len(a.get("nonlinearities") or []) for a in arches)}
        cls = gap_audit.load(s)
        for key, g in gap_audit.collect(s).items():
            gaps[f"{s}:{key}"] = {"record_sha256": _sha(g)[:16], "class": (cls.get(key) or {}).get("class"), "classification_sha256": _sha(cls.get(key))[:16]}
    by_class: dict = {}
    for g in gaps.values():
        by_class[g["class"]] = by_class.get(g["class"], 0) + 1
    return {"sports": sports, "totals": {"inputs": sum(v["inputs"] for v in sports.values()), "archetypes": sum(v["registered_archetypes"] + v["unregistered_archetypes"] for v in sports.values()),
                                          "declared_gaps": len(gaps), "gaps_by_class": dict(sorted(by_class.items()))}, "gaps": gaps}


def load() -> dict:
    return json.loads(LOCK.read_text())


def verify(lock: dict | None = None, snap: dict | None = None) -> list[str]:
    lock = lock or load(); snap = snap or snapshot(); cur = lock["current"]; out = []
    if snap["totals"] != cur["totals"]:
        out.append(f"totals changed: pinned {cur['totals']} now {snap['totals']}")
    for s in comp.SPORTS:
        a, b = cur["sports"].get(s), snap["sports"][s]
        if a != b:
            diff = {k: (a or {}).get(k) if k == "catalog_sha256" else (a or {}).get(k) for k in b if (a or {}).get(k) != b[k]}
            out.append(f"{s}: catalog drifted from the approved baseline ({', '.join(sorted(diff))})")
    pg, ng = cur["gaps"], snap["gaps"]
    for k in sorted(pg.keys() - ng.keys()):
        out.append(f"declared gap REMOVED: {k}")
    for k in sorted(ng.keys() - pg.keys()):
        out.append(f"declared gap ADDED without a lock bump: {k}")
    for k in sorted(pg.keys() & ng.keys()):
        if pg[k]["record_sha256"] != ng[k]["record_sha256"]:
            out.append(f"declared gap REWORDED: {k}")
        if pg[k]["classification_sha256"] != ng[k]["classification_sha256"]:
            out.append(f"declared gap RECLASSIFIED: {k} ({pg[k]['class']} -> {ng[k]['class']})")
    return out


def bump(reason: str) -> dict:
    if len(reason.strip()) < 30:
        raise SystemExit("a lock bump needs a reason of at least 30 characters")
    lock = load() if LOCK.exists() else {"schema_version": "baseline-lock-1.0", "approved_commit": APPROVED_COMMIT, "history": []}
    snap = snapshot()
    problems = verify(lock, snap) if "current" in lock else []
    lock.setdefault("history", []).append({"date": datetime.date.today().isoformat(), "reason": reason, "changes_acknowledged": problems[:200], "totals": snap["totals"]})
    lock["current"] = snap
    LOCK.write_text(json.dumps(lock, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return lock


def main(argv=None) -> int:
    a = (argv if argv is not None else sys.argv)[1:]
    if "--bump" in a:
        i = a.index("--bump"); bump(a[i + 1] if len(a) > i + 1 else "")
        print("lock re-pinned"); return 0
    errs = verify()
    print("baseline lock: OK" if not errs else "baseline lock: MISMATCH\n  " + "\n  ".join(errs))
    return 0 if not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())

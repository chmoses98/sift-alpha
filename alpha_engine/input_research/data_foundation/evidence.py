"""Resolve dataset access status from MEASURED evidence (RESEARCH_ONLY).

Evidence sources, all committed in the repo:
  probes.json                                         HTTP range-GET probes from the research runner (2026-11-09)
  research/input_research/data_collection/*_ledger.json   profiled collections (rows, date range, field completeness)
  research/input_research/source_verification.json    earlier (2026-11-07) per-endpoint year probes for nflverse, football-data, MLB, NHL, ESPN

Access status (ordered best to worst; `rank` is used to compare):
  COLLECTED_ARCHIVE            rows exist in a profiled ledger (collected into repo archives / sibling repos)
  FREE_REACHABLE               a probe (or earlier verification) fetched it from the runner: pullable now
  FREE_PATH_UNCONFIRMED        probe got 404 at the guessed path; ACL/path may be the cause, existence unverified
  FREE_BLOCKED_FROM_RUNNER     documented free, but the egress proxy denied the host: unverified from here, NOT proof of absence
  FREE_UNPROBED                documented free, not probed
  REFERENCE_DOCUMENT           static rules / regulation documents (read once, encode by hand)
  SAMPLE_ONLY                  free but only selected competitions/seasons
  PROSPECTIVE_CAPTURE_ONLY     no public history; recorded from the capture start date
  PAID_ONLY                    commercial only (not added without the owner's permission)
  NO_FREE_SOURCE               catalog audit found none
"""
from __future__ import annotations

import json
from pathlib import Path

from . import datasets as DS
from . import sources as SRC

ROOT = Path(__file__).resolve().parents[3]
IN = ROOT / "research/input_research"
DF = IN / "data_foundation"
RANK = {"COLLECTED_ARCHIVE": 0, "FREE_REACHABLE": 1, "REFERENCE_DOCUMENT": 2, "FREE_PATH_UNCONFIRMED": 3, "FREE_BLOCKED_FROM_RUNNER": 3, "FREE_UNPROBED": 3, "SAMPLE_ONLY": 4,
        "PROSPECTIVE_CAPTURE_ONLY": 5, "PAID_ONLY": 6, "NO_FREE_SOURCE": 7}
PIT_RANK = {"STATIC": 0, "EVENT_TIME": 0, "PIT_NATIVE": 0, "WEEKLY_SNAPSHOT": 1, "FINAL_ONLY": 2, "LIVE_SNAPSHOT": 3, "NONE": 3}


def rd(p):
    return json.loads(Path(p).read_text())


def probes() -> dict:
    return {p["id"]: p for p in rd(DF / "probes.json")["probes"]}


def ledgers() -> dict:
    out = {}
    for f in sorted((IN / "data_collection").glob("*_ledger.json")):
        out[f.name] = rd(f)
    return out


def _ledger_entry(L: dict, spec):
    if not spec:
        return None
    fname, key = spec
    d = L.get(fname)
    if d is None:
        return None
    if key is None:
        return d
    return (d.get("datasets") or {}).get(key)


def resolve_all() -> dict:
    P, L, SV = probes(), ledgers(), rd(IN / "source_verification.json")
    out = {}
    for did, d in DS.DATASETS.items():
        ev = d["evidence"]; measured = []; status = None
        led = [e for k in ("ledger", "ledger2") if (e := _ledger_entry(L, ev.get(k)))]
        pr = [P[ev[k]] for k in ("probe", "probe2") if ev.get(k) in P]
        missing_probe = [ev[k] for k in ("probe", "probe2") if ev.get(k) and ev[k] not in P]
        prior = None
        if ev.get("prior"):
            a, b = ev["prior"]
            prior = (SV.get(a) or {}).get(b)
        rows = sum(int(e.get("rows") or e.get("games") or e.get("player_game_rows") or 0) for e in led)
        dmin = [e.get("date_min") for e in led if e.get("date_min")]; dmax = [e.get("date_max") for e in led if e.get("date_max")]
        for e in led:
            measured.append(f"ledger rows={e.get('rows') or e.get('games') or e.get('player_game_rows')} {e.get('date_min', '')}..{e.get('date_max', '')}".strip())
        for p in pr:
            measured.append(f"probe {p['id']}: {p['result']} (HTTP {p['http']})")
        if prior:
            measured.append("earlier verification 2026-11-07: " + (json.dumps(prior)[:160] if not isinstance(prior, str) else prior))
        k = d["kind"]
        if led and k not in ("paid", "none"):
            status = "COLLECTED_ARCHIVE"
        elif k == "paid":
            status = "PAID_ONLY"
        elif k == "none":
            status = "NO_FREE_SOURCE"
        elif k == "own_capture":
            status = "PROSPECTIVE_CAPTURE_ONLY"
        elif k == "sample_only":
            status = "SAMPLE_ONLY"
        elif k == "reference" and not pr:
            status = "REFERENCE_DOCUMENT"
        elif any(p["result"] == "REACHABLE" for p in pr) or (prior and not isinstance(prior, str)):
            status = "FREE_REACHABLE"
        elif any(p["result"] == "NOT_FOUND_AT_PATH" for p in pr):
            status = "FREE_PATH_UNCONFIRMED"
        elif pr and all(p["result"] in ("POLICY_DENIED", "UNRESOLVED") for p in pr):
            status = "FREE_BLOCKED_FROM_RUNNER"
        elif k == "reference":
            status = "REFERENCE_DOCUMENT"
        else:
            status = "FREE_UNPROBED"
        hist = dict(d["history"])
        if led and dmin and dmax and hist["basis"] != "MEASURED":
            hist.update(first=min(dmin), last=max(dmax), basis="MEASURED")
        srcs = [SRC.public(s) for s in d["sources"] if s in SRC.SOURCES]
        out[did] = {**{k2: d[k2] for k2 in ("id", "sports", "title", "pit", "freshness", "missingness", "kind", "notes")}, "history": hist, "sources": d["sources"], "source_kinds": sorted({s["kind"] for s in srcs}),
                    "tos_risk": max((s["tos_risk"] for s in srcs), key=lambda x: ("low", "medium", "high").index(x), default="low"), "cost": "paid" if status == "PAID_ONLY" else ("free (key needed)" if any(s["kind"] == "free_key" for s in srcs) and status != "COLLECTED_ARCHIVE" else "free"),
                    "access_status": status, "access_rank": RANK[status], "pit_rank": PIT_RANK[d["pit"]], "evidence_measured": measured, "rows_collected": rows or None, "unknown_probe_ids": missing_probe,
                    "evidence_grade": "MEASURED" if (led or any(p["result"] == "REACHABLE" for p in pr) or prior) else ("DOCUMENTED_NOT_VERIFIED" if status not in ("NO_FREE_SOURCE",) else "CATALOG_AUDIT")}
    return out

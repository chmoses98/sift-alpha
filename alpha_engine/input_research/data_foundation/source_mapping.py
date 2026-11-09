"""Aggregate the blind per-sport source MAPPINGS into a free-source acquisition plan (RESEARCH_ONLY).

A mapping is a CLAIM (source, columns, event time, history, computation) made by a Claude agent: SOURCE_MAPPED_* is never "implemented" and never "verified".
Checks here: ids exist in the committed catalogs, every mapped source id is a known dataset/source token, status vocabulary is closed, and a greedy set cover ranks
sources by unique incremental inputs per sport, split by access class (no new permission / terms pending / owner action) with vintage-dependent inputs held for prospective capture.
    python -m alpha_engine.input_research.data_foundation.source_mapping [--write]
"""
from __future__ import annotations
import collections, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MD = ROOT / "research/input_research/data_foundation/verification/source_mapping"
OUT = ROOT / "research/input_research/data_foundation/free_source_plan.json"
TERMS_PENDING = ("sportsdataverse", "football_data", "footballdata", "sdv", "football-data")
OWNER_ACTION = ("open_meteo", "openmeteo", "cfbd", "cbbd", "moneypuck", "retrosheet", "wikidata", "wikipedia")


def access_class(sources: list[str], m: dict) -> str:
    s = " ".join(sources).lower()
    if any(k in s for k in OWNER_ACTION): return "NEEDS_OWNER_ACTION"
    if m.get("terms_pending") or any(k in s for k in TERMS_PENDING): return "TERMS_PENDING"
    return "NO_NEW_PERMISSION"


def load() -> dict:
    return {f.stem.split("_")[1]: json.loads(f.read_text())["mappings"] for f in sorted(MD.glob("MAP_*.json"))}


def build() -> dict:
    maps = load(); out = {"schema": "free-source-plan-1.0", "note": "claims by Claude agents, not verified implementations", "sports": {}}
    for sp, mp in maps.items():
        st = collections.Counter(v["status"] for v in mp.values())
        cls = collections.defaultdict(list); vint = []
        for iid, v in mp.items():
            if not v.get("sources"): continue
            if "VINTAGE" in v.get("status", "") or v.get("pit") in ("VINTAGE_DEPENDENT", "NEEDS_VINTAGE"): vint.append(iid); continue
            if v["status"].startswith("SOURCE_MAPPED"): cls[access_class(v["sources"], v)].append(iid)
        # greedy set cover over sources within NO_NEW_PERMISSION
        rem = {i: set(mp[i]["sources"]) for i in cls["NO_NEW_PERMISSION"]}; order = []
        while rem:
            cnt = collections.Counter(s for ss in rem.values() for s in ss)
            if not cnt: break
            s, n = cnt.most_common(1)[0]; got = [i for i, ss in rem.items() if s in ss]
            order.append({"source": s, "unique_incremental_inputs": len(got)}); [rem.pop(i) for i in got]
        out["sports"][sp] = {"n_mapped": len(mp), "by_status": dict(st), "by_access_class": {k: len(v) for k, v in cls.items()}, "vintage_dependent_prospective": len(vint), "greedy_source_order_no_new_permission": order[:12]}
    return out


def main() -> int:
    r = build()
    if "--write" in sys.argv: OUT.write_text(json.dumps(r, indent=1, sort_keys=True) + "\n")
    print(json.dumps(r, indent=1)[:6000]); return 0


if __name__ == "__main__":
    raise SystemExit(main())

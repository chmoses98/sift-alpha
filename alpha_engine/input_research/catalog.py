"""Catalog schema + validator for research/input_research/catalog/<SPORT>.json.

A catalog is a hypothesis list, never evidence. Collection status / model use are NOT stored here (linker.py derives them from the
verification engine); only the scientific reasoning is: why the input should matter, through what mechanism, how it interacts, what free
source could provide it, and whether it is knowable before the market closes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "research/input_research/catalog"
REGISTRY = ROOT / "research/audit/input_registry.json"
SPORTS = ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS")
PIT = ("yes", "partial", "no")            # knowable before the market's decision time
CATEGORIES = ("team_strength", "pace_volume", "matchup", "player_role", "availability", "environment", "game_state", "schedule_context",
              "market_structure", "distribution", "officiating", "motivation", "variance_luck", "other")
MIN_RATIONALE = 60


def load(sport: str) -> dict:
    return json.loads((CATALOG_DIR / f"{sport}.json").read_text())


def registry_blueprints(sport: str) -> dict[str, list[str]]:
    reg = json.loads(REGISTRY.read_text())["sports"][sport]
    out: dict[str, list[str]] = {}
    for fam, rec in reg["families"].items():
        for b in rec["blueprints"]:
            out.setdefault(b, []).append(fam)
    return out


def registry_input_ids(sport: str) -> set[str]:
    reg = json.loads(REGISTRY.read_text())
    return set(reg["sports"][sport]["inputs"]) | set(reg["common_inputs"])


def validate(doc: dict, sport: str, *, require_blueprint_coverage: bool = True) -> list[str]:
    """Return a list of problems (empty == valid)."""
    errs: list[str] = []
    if doc.get("sport") != sport:
        errs.append(f"sport field must be {sport!r}")
    inputs = doc.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        return errs + ["inputs must be a non-empty object keyed by input id"]
    known = registry_input_ids(sport)
    for iid, r in inputs.items():
        p = f"input {iid}"
        if not iid.islower() or "." not in iid:
            errs.append(f"{p}: id must be lowercase 'prefix.name'")
        for k in ("label", "category", "mechanism", "rationale", "pregame_knowable", "free_sources", "measurement", "registry_ids"):
            if k not in r:
                errs.append(f"{p}: missing {k}")
        if r.get("category") not in CATEGORIES:
            errs.append(f"{p}: category {r.get('category')!r} not in {CATEGORIES}")
        if r.get("pregame_knowable") not in PIT:
            errs.append(f"{p}: pregame_knowable must be one of {PIT}")
        if len(str(r.get("rationale", ""))) < MIN_RATIONALE or len(str(r.get("mechanism", ""))) < 25:
            errs.append(f"{p}: rationale/mechanism too thin")
        if not isinstance(r.get("free_sources"), list) or not r.get("free_sources"):
            errs.append(f"{p}: free_sources must list at least one source (or ['NONE_FOUND'])")
        rid = r.get("registry_ids")
        if not isinstance(rid, list):
            errs.append(f"{p}: registry_ids must be a list")
        else:
            for x in rid:
                if x not in known:
                    errs.append(f"{p}: registry id {x!r} not in committed registry for {sport}")
    bps = doc.get("blueprints")
    if not isinstance(bps, dict) or not bps:
        return errs + ["blueprints must be a non-empty object"]
    for b, rec in bps.items():
        p = f"blueprint {b}"
        for k in ("mechanism", "target", "inputs", "interactions"):
            if k not in rec:
                errs.append(f"{p}: missing {k}")
        if len(str(rec.get("mechanism", ""))) < 80:
            errs.append(f"{p}: mechanism summary too thin")
        ins = rec.get("inputs") or []
        if len(ins) < 6:
            errs.append(f"{p}: needs >=6 candidate inputs (has {len(ins)})")
        for it in ins:
            if it.get("id") not in inputs:
                errs.append(f"{p}: input {it.get('id')!r} not defined in inputs")
            if len(str(it.get("why", ""))) < 30:
                errs.append(f"{p}: input {it.get('id')!r} needs a market-specific 'why'")
        for ix in rec.get("interactions") or []:
            if len(ix.get("inputs", [])) < 2 or any(i not in inputs for i in ix["inputs"]):
                errs.append(f"{p}: interaction {ix} references undefined inputs")
            if len(str(ix.get("hypothesis", ""))) < 30:
                errs.append(f"{p}: interaction needs a hypothesis")
        if len(rec.get("interactions") or []) < 2:
            errs.append(f"{p}: needs >=2 interactions")
    used = ({i.get("id") for rec in bps.values() for i in rec.get("inputs", [])} | {i.get("id") for rec in (doc.get("archetypes") or {}).values() for i in rec.get("inputs", [])}
            | {i.get("id") for rec in (doc.get("unregistered_archetypes") or {}).values() for i in rec.get("inputs", [])})
    for iid in inputs:
        if iid not in used and not inputs[iid].get("retired"):   # `retired` = detached from every archetype by an audited correction (kept for traceability, never deleted)
            errs.append(f"input {iid}: defined but not attached to any blueprint or archetype input list (it would be invisible on the dashboard)")
    fam_by_bp = registry_blueprints(sport)
    all_fams = {f for fs in fam_by_bp.values() for f in fs}
    for a, rec in (doc.get("archetypes") or {}).items():
        p = f"archetype {a}"
        if rec.get("blueprint") not in bps:
            errs.append(f"{p}: blueprint {rec.get('blueprint')!r} not defined")
        fams = rec.get("families")
        if not isinstance(fams, list) or not fams:
            errs.append(f"{p}: families must list registry family keys (e.g. 'NFL/GAME_EVENT')")
        else:
            for f in fams:
                if f not in all_fams:
                    errs.append(f"{p}: family {f!r} not in registry")
        for k in ("label", "target", "mechanism", "inputs", "interactions"):
            if k not in rec:
                errs.append(f"{p}: missing {k}")
        if len(str(rec.get("mechanism", ""))) < 120:
            errs.append(f"{p}: mechanism must be a substantive paragraph (>=120 chars)")
        if len(rec.get("inputs") or []) < 8:
            errs.append(f"{p}: needs >=8 inputs")
        for it in rec.get("inputs") or []:
            if it.get("id") not in inputs:
                errs.append(f"{p}: input {it.get('id')!r} not defined in inputs")
            if len(str(it.get("why", ""))) < 30:
                errs.append(f"{p}: input {it.get('id')!r} needs a market-specific 'why'")
        for ix in rec.get("interactions") or []:
            if len(ix.get("inputs", [])) < 2 or any(i not in inputs for i in ix["inputs"]):
                errs.append(f"{p}: interaction references undefined inputs")
        if len(rec.get("interactions") or []) < 3:
            errs.append(f"{p}: needs >=3 interactions")
    for a, rec in (doc.get("unregistered_archetypes") or {}).items():
        p = f"unregistered archetype {a}"
        if rec.get("blueprint") not in bps:
            errs.append(f"{p}: blueprint {rec.get('blueprint')!r} not defined")
        if not rec.get("contract_types"):
            errs.append(f"{p}: contract_types must list the listed Kalshi contract titles it covers")
        if a in (doc.get("archetypes") or {}):
            errs.append(f"{p}: name collides with a registered archetype")
        for k in ("label", "target", "mechanism", "inputs", "interactions"):
            if k not in rec:
                errs.append(f"{p}: missing {k}")
        if len(str(rec.get("mechanism", ""))) < 120:
            errs.append(f"{p}: mechanism must be a substantive paragraph (>=120 chars)")
        if len(rec.get("inputs") or []) < 8:
            errs.append(f"{p}: needs >=8 inputs")
        for it in rec.get("inputs") or []:
            if it.get("id") not in inputs:
                errs.append(f"{p}: input {it.get('id')!r} not defined in inputs")
            if len(str(it.get("why", ""))) < 30:
                errs.append(f"{p}: input {it.get('id')!r} needs a market-specific 'why'")
        if len(rec.get("interactions") or []) < 3:
            errs.append(f"{p}: needs >=3 interactions")
    if require_blueprint_coverage:
        reg = registry_blueprints(sport)
        miss = sorted(set(reg) - set(bps))
        if miss:
            errs.append(f"blueprints missing vs registry: {miss}")
        extra = sorted(set(bps) - set(reg))
        if extra:
            errs.append(f"blueprints not in registry: {extra}")
    return errs


def validate_all(require_all_sports: bool = True) -> dict[str, list[str]]:
    out = {}
    for s in SPORTS:
        f = CATALOG_DIR / f"{s}.json"
        if not f.exists():
            if require_all_sports:
                out[s] = ["catalog file missing"]
            continue
        out[s] = validate(json.loads(f.read_text()), s)
    return {k: v for k, v in out.items() if v}


if __name__ == "__main__":  # python -m alpha_engine.input_research.catalog [SPORT ...]
    import sys
    sports = sys.argv[1:] or list(SPORTS)
    bad = False
    for s in sports:
        errs = validate(load(s), s) if (CATALOG_DIR / f"{s}.json").exists() else ["catalog file missing"]
        print(s, "OK" if not errs else f"{len(errs)} problems")
        for e in errs[:40]:
            print("  -", e)
        bad |= bool(errs)
    sys.exit(1 if bad else 0)

"""Explicit record of where the APPROVED catalog baseline differs from what the source layers regenerate (RESEARCH_ONLY).

Why this exists. The approved baseline (commit 50dc65e) was assembled by several agent rounds, some of which edited the catalog JSON directly (repaired definitions, re-attached
inputs with new text, interactions added by hand) without updating the review records / patch files that `completeness.integrate`, `input_audit.apply*` regenerate it from.
Re-running that pipeline therefore silently reverted those edits. Rather than rewrite approved content, the deviations are recorded here, one entry per differing field:

  completeness/baseline_overlay/<SPORT>.json = {
     "inputs":     {input_id:  {"replaces_sha256": <sha of what the sources generate | null if absent>, "value": <approved record>}},
     "archetypes": {arch_key:  {field: {"replaces_sha256": ..., "value": <approved field value>}}},    # arch_key as in completeness.arch_keys
     "blueprints": {name:      {field: {...}}} }

`apply()` runs LAST in the regeneration pipeline. For every entry it requires the freshly generated value to hash to `replaces_sha256` (the source layers still say what they said when
the overlay was derived) or to already equal the approved value. Anything else raises: a source layer changed underneath the approved baseline, and a human must decide whether to
bump the baseline lock (baseline_lock.py) or fix the source. Nothing is ever overwritten silently.

The overlay is debt, not a feature: every entry is a place where the review records and the approved catalog disagree. It is derived by `regenerate --derive-overlay` and should only
shrink (by folding entries back into the source layers), never grow, once the lock is in place.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import catalog as cat
from . import completeness as comp

OD = comp.CD / "baseline_overlay"
ABSENT = "__ABSENT__"


def sha(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _containers(c: dict) -> dict:
    """name -> dict-like holders keyed the way the overlay addresses them."""
    out = {"inputs": c["inputs"], "blueprints": c["blueprints"]}
    arch = {}
    for k in comp.arch_keys(c):
        arch[k] = comp.arch_entry(c, k)
    out["archetypes"] = arch
    return out


def derive_sport(generated: dict, approved: dict) -> dict:
    """Overlay that turns the regenerated catalog `generated` back into the `approved` one. Field-level for archetypes/blueprints, record-level for inputs."""
    g, a = _containers(generated), _containers(approved)
    res: dict = {"inputs": {}, "archetypes": {}, "blueprints": {}, "top_level": {}}
    for iid in sorted(set(g["inputs"]) | set(a["inputs"])):
        gv, av = g["inputs"].get(iid), a["inputs"].get(iid)
        if gv != av:
            res["inputs"][iid] = {"replaces_sha256": sha(gv) if iid in g["inputs"] else ABSENT, "value": av if iid in a["inputs"] else ABSENT}
    for section in ("archetypes", "blueprints"):
        for key in sorted(set(g[section]) | set(a[section])):
            gd, ad = g[section].get(key), a[section].get(key)
            if gd is None or ad is None:
                raise ValueError(f"{section} {key} exists on only one side; the overlay cannot add or remove whole {section}")
            ent = {}
            for f in sorted(set(gd) | set(ad)):
                if gd.get(f, ABSENT) != ad.get(f, ABSENT):
                    ent[f] = {"replaces_sha256": sha(gd[f]) if f in gd else ABSENT, "value": ad[f] if f in ad else ABSENT}
            if ent:
                res[section][key] = ent
    for k in sorted((set(generated) | set(approved)) - {"inputs", "blueprints", "archetypes", "unregistered_archetypes"}):
        if generated.get(k, ABSENT) != approved.get(k, ABSENT):
            res["top_level"][k] = {"replaces_sha256": sha(generated[k]) if k in generated else ABSENT, "value": approved[k] if k in approved else ABSENT}
    return res


def _guarded_set(holder: dict, field: str, ent: dict, where: str) -> int:
    cur = holder.get(field, ABSENT)
    want = ent["value"]
    if cur == want:
        return 0
    cur_sha = sha(cur) if field in holder else ABSENT
    if cur_sha != ent["replaces_sha256"]:
        raise ValueError(f"baseline overlay is stale at {where}.{field}: the source layers now generate something different from what the overlay was derived against "
                         f"(generated sha {str(cur_sha)[:12]}, overlay expects {str(ent['replaces_sha256'])[:12]}). A source layer changed under the approved baseline: "
                         "fix the source, or bump the baseline lock deliberately (python -m alpha_engine.input_research.baseline_lock --bump '<reason>').")
    if want == ABSENT:
        holder.pop(field, None)
    else:
        holder[field] = json.loads(json.dumps(want))
    return 1


def apply_sport(sport: str, c: dict, ov: dict) -> int:
    n = 0
    for iid, ent in (ov.get("inputs") or {}).items():
        cur = c["inputs"].get(iid, ABSENT)
        if cur == ent["value"]:
            continue
        cs = sha(cur) if iid in c["inputs"] else ABSENT
        if cs != ent["replaces_sha256"]:
            raise ValueError(f"baseline overlay is stale for {sport} input {iid} (generated sha {str(cs)[:12]}, overlay expects {str(ent['replaces_sha256'])[:12]}); see baseline_overlay.py")
        if ent["value"] == ABSENT:
            c["inputs"].pop(iid, None)
        else:
            c["inputs"][iid] = json.loads(json.dumps(ent["value"]))
        n += 1
    cont = _containers(c)
    for section in ("archetypes", "blueprints"):
        for key, fields in (ov.get(section) or {}).items():
            if key not in cont[section]:
                raise ValueError(f"baseline overlay names unknown {section[:-1]} {sport}:{key}")
            for f, ent in fields.items():
                n += _guarded_set(cont[section][key], f, ent, f"{sport}:{section}:{key}")
    for k, ent in (ov.get("top_level") or {}).items():
        n += _guarded_set(c, k, ent, f"{sport}:top")
    return n


def load(sport: str) -> dict:
    f = OD / f"{sport}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def apply() -> dict:
    stats = {}
    for s in comp.SPORTS:
        ov = load(s)
        if not ov:
            continue
        c = cat.load(s)
        n = apply_sport(s, c, ov)
        (cat.CATALOG_DIR / f"{s}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
        stats[s] = {"fields_restored_to_baseline": n}
    return stats


def summary() -> dict:
    out = {}
    for s in comp.SPORTS:
        ov = load(s)
        out[s] = {"inputs": len(ov.get("inputs") or {}), "archetype_fields": sum(len(v) for v in (ov.get("archetypes") or {}).values()), "archetypes": len(ov.get("archetypes") or {}),
                  "blueprint_fields": sum(len(v) for v in (ov.get("blueprints") or {}).values()), "top_level": len(ov.get("top_level") or {})}
    return out

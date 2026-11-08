"""Classification of every declared gap (`unresolved` entry of every archetype review) for the catalog-completeness gate (RESEARCH_ONLY).

The point is to separate what STOPS the catalog from being a complete statement of what each market needs (a missing mechanism, input or definition) from what is merely
unknown or inaccessible outside the catalog (a contract text Kalshi has not published, a data source that cannot be verified from here, data that has to be collected prospectively).

Classes
  CATALOG_BLOCKER           an input, mechanism, interaction, contract reading or definition the catalog still lacks or has wrong; fixable by more research/authoring; blocks completeness
  UNVERIFIABLE_CONTRACT     the contract's settlement wording is unavailable or ambiguous in the sampled Kalshi text (no listed market, truncated rules, silent on overtime...); resolvable only by Kalshi publishing/clarifying
  DATA_SOURCE_LIMITATION    the input is fully defined but its raw source is inaccessible, unverified, discontinued, paid or coverage-limited from here
  FUTURE_DATA_COLLECTION    the input is fully defined and a source exists, but the history needs prospective own-capture (vintages, lineups, in-play snapshots) before it can be computed

Files: research/input_research/completeness/gap_classification/<SPORT>*.json  {"classifier": ..., "gaps": {"<archetype>#<gap id>": {"class","blocks_catalog","rationale","catalog_action"?}}}
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from . import completeness as comp

GD = comp.CD / "gap_classification"
CLASSES = ("CATALOG_BLOCKER", "UNVERIFIABLE_CONTRACT", "DATA_SOURCE_LIMITATION", "FUTURE_DATA_COLLECTION")


def collect(sport: str) -> dict[str, dict]:
    out = {}
    for k, rec in comp.load_reviews(sport).items():
        for u in rec.get("unresolved") or []:
            out[f"{k}#{u.get('id')}"] = {"archetype": k, "id": u.get("id"), "type": u.get("type"), "category": u.get("category"), "description": u.get("description"), "what_would_resolve": u.get("what_would_resolve")}
    return out


def load(sport: str) -> dict:
    out = {}
    for f in sorted(GD.glob(f"{sport}*.json")) if GD.exists() else []:
        out.update(json.loads(f.read_text()).get("gaps") or {})
    return out


def validate(sport: str, cls: dict) -> list[str]:
    e = []
    gaps = collect(sport)
    for g in gaps:
        if g not in cls:
            e.append(f"{g}: not classified")
    for g, c in cls.items():
        if g not in gaps:
            e.append(f"{g}: not a declared gap"); continue
        if c.get("class") not in CLASSES:
            e.append(f"{g}: class must be one of {CLASSES}")
        if c.get("blocks_catalog") is not (c.get("class") == "CATALOG_BLOCKER"):
            e.append(f"{g}: blocks_catalog must be true exactly for CATALOG_BLOCKER")
        if not comp._txt(c.get("rationale"), 60):
            e.append(f"{g}: rationale must be a specific >=60 char judgement")
        if c.get("class") == "CATALOG_BLOCKER" and not comp._txt(c.get("catalog_action"), 40):
            e.append(f"{g}: CATALOG_BLOCKER needs a catalog_action (>=40 chars) saying what research/authoring closes it")
    return e


def summary() -> dict:
    tot = collections.Counter(); by = {}; blockers = []; n = 0
    for s in comp.SPORTS:
        cls = load(s); gaps = collect(s); c = collections.Counter(v["class"] for v in cls.values()); by[s] = {"declared": len(gaps), "classified": len(cls), **dict(c)}
        tot.update(c); n += len(gaps)
        blockers += [{"sport": s, "gap": g, "action": v.get("catalog_action"), "rationale": v["rationale"]} for g, v in cls.items() if v["class"] == "CATALOG_BLOCKER"]
    return {"declared": n, "classified": sum(tot.values()), "by_class": dict(tot), "by_sport": by, "catalog_blockers": blockers}


def main():
    for s in comp.SPORTS:
        cls = load(s)
        if cls:
            errs = validate(s, cls); print(s, "OK" if not errs else f"{len(errs)} problems", *errs[:6], sep="\n  " if errs else "")
    print(json.dumps({k: v for k, v in summary().items() if k != "catalog_blockers"}, indent=1))


if __name__ == "__main__":
    main()

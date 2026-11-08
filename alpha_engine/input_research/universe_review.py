"""Market-universe reconciliation for the catalog-completeness gate (RESEARCH_ONLY).

The PR #62 series ledger is PRESERVED. This module adds an authoritative overlay: for every series flagged by the archetype reviews as possibly misfiled, a reviewer reads the
actual Kalshi contract rules (research/input_research/market_universe/contract_rules_sample.json) and either confirms the ledger archetype, re-files the series into another
existing archetype, assigns it to a NEW archetype (an unregistered contract type of one of the eight supported sports) or classifies it explicitly OUT_OF_SCOPE with a reason.
Every claim is checkable: quotes must be verbatim substrings of the sampled rules; series without rules text can only be classified on TITLE_ONLY / NO_LISTING basis and keep
that uncertainty.

Files (research/input_research/completeness/universe/): packs/<SPORT>.json (reviewer input), <SPORT>.json (reviewer output),
and research/input_research/market_universe/series_assignment.json (authoritative final assignment of ALL ledger series; derived).
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from . import catalog as cat
from . import completeness as comp

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "research/input_research"
UD = IN / "completeness/universe"
LEDGER = IN / "market_universe/series_ledger.json"
RULES = IN / "market_universe/contract_rules_sample.json"
ASSIGN = IN / "market_universe/series_assignment.json"
SPORTS = list(cat.SPORTS)
BASES = ("RULES_TEXT", "TITLE_ONLY", "NO_LISTING")
OOS = "OUT_OF_SCOPE"
CONFIDENCE = ("high", "medium", "low")


def rd(p):
    return json.loads(Path(p).read_text())


def flagged() -> dict[tuple[str, str], list[dict]]:
    out = collections.defaultdict(list)
    f = comp.CD / "series_remap_proposals.json"
    for x in rd(f)["rows"]:
        out[(x["sport"], x["ticker"])].append(x)
    return out


def build_packs() -> dict:
    UD.mkdir(parents=True, exist_ok=True); (UD / "packs").mkdir(exist_ok=True)
    led = {r["ticker"]: r for r in rd(LEDGER)["rows"]}
    rules = rd(RULES)
    fl = flagged(); n = {}
    for s in SPORTS:
        c = cat.load(s)
        archs = {k: {"label": comp.arch_entry(c, k)["label"], "target": comp.arch_entry(c, k)["target"], "contract_types": comp.arch_entry(c, k).get("contract_types")} for k in comp.arch_keys(c)}
        series = {}
        for (sp, t), props in fl.items():
            if sp != s:
                continue
            r = led.get(t, {})
            series[t] = {"title": r.get("title"), "ledger_archetype": r.get("archetype"), "ledger_status": r.get("status"), "ledger_type": r.get("type"), "ledger_evidence": r.get("evidence"),
                         "rules": rules.get(t), "proposals": [{"filed_under": p["filed_under"], "belongs_in": p["belongs_in"], "issue": p["issue"]} for p in props]}
        pack = {"sport": s, "existing_archetypes": archs, "blueprints": list(c["blueprints"]), "series": series}
        (UD / "packs" / f"{s}.json").write_text(json.dumps(pack, indent=1, sort_keys=True)); n[s] = len(series)
    return n


def load_universe(sport: str) -> dict:
    out = {"series": {}, "new_archetypes": {}, "out_of_scope_categories": {}}
    for f in sorted(UD.glob(f"{sport}_*.json")) + sorted(UD.glob(f"{sport}.json")):
        d = rd(f)
        out["series"].update(d.get("series") or {}); out["new_archetypes"].update(d.get("new_archetypes") or {}); out["out_of_scope_categories"].update(d.get("out_of_scope_categories") or {})
    return out


def validate(sport: str, doc: dict, pack: dict | None = None) -> list[str]:
    e: list[str] = []
    pack = pack or rd(UD / "packs" / f"{sport}.json")
    rules = rd(RULES)
    existing = set(pack["existing_archetypes"])
    new = {"unreg:" + k for k in doc["new_archetypes"]}
    for t in pack["series"]:
        if t not in doc["series"]:
            e.append(f"series {t} not classified")
    for t, r in doc["series"].items():
        if t not in pack["series"]:
            e.append(f"{t}: not in the pack"); continue
        final, basis = r.get("final", ""), r.get("basis")
        if not (final in existing or final in new or final.startswith(OOS + ":")):
            e.append(f"{t}: final {final!r} is neither an existing archetype, a declared new archetype nor OUT_OF_SCOPE:<category>")
        if final.startswith(OOS + ":") and final.split(":", 1)[1] not in doc["out_of_scope_categories"]:
            e.append(f"{t}: out-of-scope category not described in out_of_scope_categories")
        if basis not in BASES:
            e.append(f"{t}: basis must be one of {BASES}")
        have = bool((rules.get(t) or {}).get("rules_primary"))
        if basis == "RULES_TEXT":
            if not have:
                e.append(f"{t}: claims RULES_TEXT but no rules text exists")
            samp = rules.get(t) or {}
            blob = " ".join(" ".join(str(samp.get(k) or "") for k in ("rules_primary", "rules_secondary", "title")).split())
            q = " ".join(str(r.get("quote", "")).split())
            if len(q) < 20 or q not in blob:
                e.append(f"{t}: quote is not a verbatim substring (>=20 chars) of the sampled rules")
        elif basis == "TITLE_ONLY" and have:
            e.append(f"{t}: rules text exists; basis must be RULES_TEXT")
        elif basis == "NO_LISTING" and have:
            e.append(f"{t}: rules text exists; basis cannot be NO_LISTING")
        if not comp._txt(r.get("reason"), 50):
            e.append(f"{t}: reason must be a specific >=50 char judgement")
        if r.get("confidence") not in CONFIDENCE:
            e.append(f"{t}: confidence must be one of {CONFIDENCE}")
        if basis != "RULES_TEXT" and r.get("confidence") == "high":
            e.append(f"{t}: high confidence is not allowed without rules text")
    for name, a in doc["new_archetypes"].items():
        p = f"new archetype {name}"
        if not name.islower() or " " in name:
            e.append(f"{p}: name must be snake_case")
        if a.get("blueprint") not in pack["blueprints"]:
            e.append(f"{p}: blueprint must be one of {pack['blueprints']}")
        for k in ("label", "target", "why_distinct"):
            if not comp._txt(a.get(k), 20):
                e.append(f"{p}: {k} too thin")
        if not a.get("contract_types"):
            e.append(f"{p}: contract_types must list the contract titles it covers")
        members = [t for t, r in doc["series"].items() if r.get("final") == "unreg:" + name]
        if not members:
            e.append(f"{p}: no series assigned (declare it only if a series needs it)")
        if name in {k.replace("unreg:", "") for k in existing}:
            e.append(f"{p}: collides with an existing archetype")
    for k, v in doc["out_of_scope_categories"].items():
        if not comp._txt(v, 30):
            e.append(f"out_of_scope category {k}: needs a description")
    return e


def apply() -> dict:
    """Authoritative assignment of every ledger series (derived; the ledger itself is unchanged)."""
    led = rd(LEDGER)["rows"]; rules = rd(RULES)
    uni = {s: load_universe(s) for s in SPORTS}
    fin = {}
    for s, d in uni.items():
        for t, r in d["series"].items():
            fin[t] = {**r, "new": d["new_archetypes"]}
    rows, cnt = [], collections.defaultdict(collections.Counter)
    for r in led:
        t = r["ticker"]; o = fin.get(t)
        if r["sport"].startswith("OTHER_SPORT") or r["sport"] not in SPORTS:
            row = {"ticker": t, "sport": r["sport"], "title": r["title"], "ledger_archetype": r["archetype"], "final": OOS + ":unsupported_sport", "scope": "OUT_OF_SCOPE", "basis": r["evidence"], "origin": "ledger"}
        elif o:
            f = o["final"]
            row = {"ticker": t, "sport": r["sport"], "title": r["title"], "ledger_archetype": r["archetype"], "final": f, "scope": "OUT_OF_SCOPE" if f.startswith(OOS) else "IN_SCOPE", "basis": o["basis"], "confidence": o["confidence"],
                   "origin": "reviewed" if f != r["archetype"] else "reviewed_confirmed"}
        else:
            ledger_arch = r["archetype"]
            row = {"ticker": t, "sport": r["sport"], "title": r["title"], "ledger_archetype": ledger_arch, "final": ledger_arch, "scope": "IN_SCOPE" if r["status"].startswith(("COVERED", "CLASSIFIED")) else ("NO_LISTED_MARKETS" if r["status"] == "NO_LISTED_MARKETS" else "EXCLUDED"),
                   "basis": "RULES_TEXT" if (rules.get(t) or {}).get("rules_primary") else ("NO_LISTING" if r["status"] == "NO_LISTED_MARKETS" else "TITLE_ONLY"), "origin": "ledger"}
        rows.append(row); cnt[row["sport"]][(row["scope"], row["basis"])] += 1
    out = {"schema_version": "series-assignment-1.0", "status": "RESEARCH_ONLY", "note": "Overlay on the preserved PR #62 ledger; derived by universe_review.apply().", "total": len(rows), "rows": rows,
           "by_sport": {s: {f"{a}|{b}": n for (a, b), n in c.items()} for s, c in cnt.items()}}
    ASSIGN.write_text(json.dumps(out, indent=0, sort_keys=True))
    return out


def main():
    import sys
    if "--packs" in sys.argv:
        print(build_packs()); return
    bad = {}
    for s in SPORTS:
        if any(UD.glob(f"{s}*.json")):
            errs = validate(s, load_universe(s))
            bad[s] = errs
            print(s, "OK" if not errs else f"{len(errs)} problems", *errs[:8], sep="\n  " if errs else "")


if __name__ == "__main__":
    main()

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
import re
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


def stale_flagged(sport: str) -> list[str]:
    """Flagged series whose recorded basis is out of date: rules text now exists (e.g. recovered from Kalshi's historical-markets endpoint) but the decision says TITLE_ONLY/NO_LISTING."""
    rules = rd(RULES); d = load_universe(sport); out = []
    for t, r in d["series"].items():
        if r.get("basis") != "RULES_TEXT" and (rules.get(t) or {}).get("rules_primary"):
            out.append(t)
    return out


def build_hist_packs() -> dict:
    rules = rd(RULES); led = {r["ticker"]: r for r in rd(LEDGER)["rows"]}; n = {}
    for sp in SPORTS:
        c = cat.load(sp); u = load_universe(sp); ts = stale_flagged(sp)
        # series the ledger could not classify ("no listed market") but whose archived contract text is now readable
        asg = rd(ASSIGN)["rows"] if ASSIGN.exists() else []
        unc = [r["ticker"] for r in asg if r["sport"] == sp and r["scope"] == "NO_LISTED_MARKETS" and (rules.get(r["ticker"]) or {}).get("rules_primary") and r["ticker"] not in u["series"]]
        ts = ts + unc
        if not ts:
            continue
        archs = {k: {"label": comp.arch_entry(c, k)["label"], "target": comp.arch_entry(c, k)["target"]} for k in comp.arch_keys(c)}
        archs.update({"unreg:" + k: {"label": v["label"], "target": v["target"]} for k, v in u["new_archetypes"].items()})
        series = {t: {"title": led.get(t, {}).get("title"), "ledger_archetype": led.get(t, {}).get("archetype"), "rules": rules[t], "prior_decision": ({k: u["series"][t].get(k) for k in ("final", "basis", "reason", "confidence")} if t in u["series"] else None)} for t in ts}
        pk = {"sport": sp, "existing_archetypes": archs, "blueprints": list(c["blueprints"]), "series": series}
        (UD / "packs" / f"{sp}_hist.json").write_text(json.dumps(pk, indent=1, sort_keys=True)); n[sp] = len(ts)
    return n


def load_universe(sport: str) -> dict:
    out = {"series": {}, "new_archetypes": {}, "out_of_scope_categories": {}}
    for f in sorted(x for x in UD.glob(f"{sport}_*.json") if "_rest" not in x.name and "_hist" not in x.name or x.name.endswith("_hist.json")) + sorted(UD.glob(f"{sport}.json")):
        d = rd(f)
        out["series"].update(d.get("series") or {}); out["new_archetypes"].update(d.get("new_archetypes") or {}); out["out_of_scope_categories"].update(d.get("out_of_scope_categories") or {})
    return out


def load_all(sport: str) -> dict:
    d = load_universe(sport); r = expand_rest(sport)
    d["series"].update(r["series"]); d["new_archetypes"].update(r["new_archetypes"]); d["out_of_scope_categories"].update(r["out_of_scope_categories"])
    return d


def validate(sport: str, doc: dict, pack: dict | None = None) -> list[str]:
    e: list[str] = []
    if pack is None:
        pack = rd(UD / "packs" / f"{sport}.json")
        hp = UD / "packs" / f"{sport}_hist.json"
        if hp.exists():
            pack["series"] = {**pack["series"], **rd(hp)["series"]}
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


def _norm(t: str) -> str:
    t = re.sub(r"\b[A-Z][\w'.&-]*\b", "X", t); t = re.sub(r"\d+(\.\d+)?", "N", t)
    return re.sub(r"\s+", " ", t).lower()[:400]


def build_rest_packs(soccer_parts: int = 3, tag: str = "rest", skip: set | None = None) -> dict:
    """Series NOT flagged by the archetype reviews whose actual contract rules are now available: clustered into templates (identical text after removing names/numbers) so a reviewer
    classifies each distinct contract template once. Confirmed templates keep their ledger archetype; deviations are re-filed."""
    rules = rd(RULES); a = rd(ASSIGN) if ASSIGN.exists() else apply()
    led = {r["ticker"]: r for r in rd(LEDGER)["rows"]}
    n = {}
    for sp in SPORTS:
        c = cat.load(sp)
        archs = {k: {"label": comp.arch_entry(c, k)["label"], "target": comp.arch_entry(c, k)["target"]} for k in comp.arch_keys(c)}
        u = load_universe(sp)
        archs.update({"unreg:" + k: {"label": v["label"], "target": v["target"]} for k, v in u["new_archetypes"].items()})
        cl = collections.defaultdict(list)
        for x in a["rows"]:
            if x["sport"] == sp and x["scope"] == "IN_SCOPE" and x["origin"] == "ledger" and x["basis"] == "RULES_TEXT" and x["ticker"] not in (skip or set()):
                cl[(x["final"], _norm(rules[x["ticker"]].get("rules_primary") or ""))].append(x)
        temps = []
        for (fin, _), mem in sorted(cl.items(), key=lambda kv: (str(kv[0][0]), kv[1][0]["ticker"])):
            t0 = rules[mem[0]["ticker"]]
            temps.append({"ledger_archetype": fin, "rules_primary": t0.get("rules_primary"), "rules_secondary": (t0.get("rules_secondary") or "")[:300], "sample_ticker": mem[0]["ticker"],
                          "members": [{"ticker": m["ticker"], "title": m["title"], "ledger_type": led[m["ticker"]].get("type")} for m in mem]})
        parts = soccer_parts if sp == "SOCCER" else 1
        size = -(-len(temps) // parts) if temps else 1
        for k in range(parts):
            chunk = temps[k * size:(k + 1) * size]
            if not chunk:
                continue
            tid = {f"{tag[0]}{tag[-1]}{k}_{i:03d}": t for i, t in enumerate(chunk)}
            (UD / "packs" / f"{sp}_{tag}_{k}.json").write_text(json.dumps({"sport": sp, "existing_archetypes": archs, "blueprints": list(c["blueprints"]), "templates": tid}, indent=1, sort_keys=True))
        n[sp] = len(temps)
    return n


def expand_rest(sport: str) -> dict:
    """Expand template-level decisions (<SPORT>_rest_<k>.json outputs) into per-series entries."""
    out = {"series": {}, "new_archetypes": {}, "out_of_scope_categories": {}}
    for f in sorted(UD.glob(f"{sport}_rest*_*.json")):
        pf = UD / "packs" / f.name
        if not pf.exists():
            continue
        pack, d = rd(pf), rd(f)
        out["new_archetypes"].update(d.get("new_archetypes") or {}); out["out_of_scope_categories"].update(d.get("out_of_scope_categories") or {})
        for tid, dec in (d.get("templates") or {}).items():
            t = pack["templates"].get(tid)
            if not t:
                continue
            for m in t["members"]:
                ov = (dec.get("member_overrides") or {}).get(m["ticker"])
                fin = (ov or {}).get("final") or (dec["final"] if dec.get("decision") == "REFILE" else t["ledger_archetype"])
                out["series"][m["ticker"]] = {"final": fin, "basis": "RULES_TEXT", "quote": dec.get("quote"), "reason": (ov or {}).get("reason") or dec.get("reason"), "confidence": dec.get("confidence"), "template": tid, "rest": True}
    return out


def validate_rest(sport: str) -> list[str]:
    e = []; rules = rd(RULES)
    for pf in sorted((UD / "packs").glob(f"{sport}_rest*_*.json")):
        of = UD / pf.name
        if not of.exists():
            continue
        pack, d = rd(pf), rd(of)
        existing = set(pack["existing_archetypes"]); new = {"unreg:" + k for k in d.get("new_archetypes", {})}
        for tid, t in pack["templates"].items():
            dec = (d.get("templates") or {}).get(tid)
            if not dec:
                e.append(f"{pf.name}:{tid} not decided"); continue
            if dec.get("decision") not in ("CONFIRM", "REFILE"):
                e.append(f"{tid}: decision must be CONFIRM|REFILE")
            if dec.get("decision") == "REFILE":
                f = dec.get("final", "")
                if not (f in existing or f in new or f.startswith(OOS + ":")):
                    e.append(f"{tid}: final {f!r} invalid")
                if f.startswith(OOS + ":") and f.split(":", 1)[1] not in d.get("out_of_scope_categories", {}):
                    e.append(f"{tid}: out-of-scope category undeclared")
            samp = rules[t["sample_ticker"]]
            blob = " ".join(" ".join(str(samp.get(k) or "") for k in ("rules_primary", "rules_secondary", "title")).split())
            q = " ".join(str(dec.get("quote", "")).split())
            if len(q) < 20 or q not in blob:
                e.append(f"{tid}: quote is not a verbatim >=20 char substring of the template's sampled rules")
            if not comp._txt(dec.get("reason"), 50) or dec.get("confidence") not in CONFIDENCE:
                e.append(f"{tid}: reason >=50 chars and confidence required")
            for tk, ov in (dec.get("member_overrides") or {}).items():
                if tk not in {m["ticker"] for m in t["members"]}:
                    e.append(f"{tid}: override for non-member {tk}")
                f = (ov or {}).get("final", "")
                if not (f in existing or f in new or f.startswith(OOS + ":")) or not comp._txt((ov or {}).get("reason"), 40):
                    e.append(f"{tid}: bad override for {tk}")
        for k, a in (d.get("new_archetypes") or {}).items():
            if a.get("blueprint") not in pack["blueprints"] or not a.get("contract_types"):
                e.append(f"new archetype {k}: blueprint/contract_types invalid")
    return e


def apply() -> dict:
    """Authoritative assignment of every ledger series (derived; the ledger itself is unchanged)."""
    led = rd(LEDGER)["rows"]; rules = rd(RULES)
    uni = {s: load_all(s) for s in SPORTS}
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
                   "origin": "reviewed" if f != r["archetype"] else "reviewed_confirmed", "by_template": bool(o.get("rest"))}
        else:
            ledger_arch = r["archetype"]
            row = {"ticker": t, "sport": r["sport"], "title": r["title"], "ledger_archetype": ledger_arch, "final": ledger_arch, "scope": "IN_SCOPE" if r["status"].startswith(("COVERED", "CLASSIFIED")) else ("NO_LISTED_MARKETS" if r["status"] == "NO_LISTED_MARKETS" else "EXCLUDED"),
                   "basis": "RULES_TEXT" if (rules.get(t) or {}).get("rules_primary") else ("NO_LISTING" if (r["status"] == "NO_LISTED_MARKETS" or (rules.get(t) or {}).get("status") == "NO_MARKETS_LISTED") else "TITLE_ONLY"), "origin": "ledger"}
        rows.append(row); cnt[row["sport"]][(row["scope"], row["basis"])] += 1
    out = {"schema_version": "series-assignment-1.0", "status": "RESEARCH_ONLY", "note": "Overlay on the preserved PR #62 ledger; derived by universe_review.apply().", "total": len(rows), "rows": rows,
           "by_sport": {s: {f"{a}|{b}": n for (a, b), n in c.items()} for s, c in cnt.items()}}
    ASSIGN.write_text(json.dumps(out, indent=0, sort_keys=True))
    return out


def main():
    import sys
    if "--packs" in sys.argv:
        print(build_packs()); return
    if "--rest-packs" in sys.argv:
        print(build_rest_packs()); return
    if "--hist-packs" in sys.argv:
        print(build_hist_packs()); return
    if "--rest2-packs" in sys.argv:
        done = set()
        for sp in SPORTS:
            done |= set(expand_rest(sp)["series"]) | set(load_universe(sp)["series"])
        print(build_rest_packs(tag="rest2", skip=done)); return
    bad = {}
    for s in SPORTS:
        if any(UD.glob(f"{s}*.json")):
            errs = validate(s, load_universe(s)) + validate_rest(s)
            bad[s] = errs
            print(s, "OK" if not errs else f"{len(errs)} problems", *errs[:8], sep="\n  " if errs else "")


if __name__ == "__main__":
    main()

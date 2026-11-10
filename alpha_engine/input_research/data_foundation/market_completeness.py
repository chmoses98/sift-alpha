"""Market-archetype data completeness (RESEARCH_ONLY): for every one of the 170 catalog market archetypes (118 registered + 52 unregistered) measure how complete its independent input set is.

    python -m alpha_engine.input_research.data_foundation.market_completeness [--baseline-ref 74aab4e]

Per archetype: the catalog lists its inputs with a role (primary / secondary / context). Market-derived benchmark inputs (EXCLUDED_BENCHMARK_ONLY) are not independent inputs and are not required. Every other input falls in exactly ONE category,
taken from the verified-coverage matrix (never from a draft claim):
  FULL / PARTIAL / PROXY      replayed + blind-verified builders (PARTIAL: part of the definition; PROXY: different quantity, same mechanism)
  DATA_IN_HAND                real columns confirmed point-in-time buildable by two blind verifiers; no builder yet
  FREE_ACCESSIBLE             a permitted free source exists (audit: COLLECT_FREE_MEASURED / COLLECT_FREE_UNVERIFIED) but nothing is built/verified yet
  PROSPECTIVE                 needs capture from now on (no backfillable history: audit COLLECT_PROSPECTIVE, or point-in-time quarantined)
  NO_FREE_SOURCE              audit/recheck says no permitted free source (paid-only, none found, sample-only, policy-blocked, blind-confirmed blocked)
  CONTESTED                   blind rounds disagree on whether any permitted source exists (counted as unresolved, not as blocked)
Completeness score = (1*FULL + 0.5*PARTIAL + 0.25*PROXY)/required inputs; critical score is the same over PRIMARY-role inputs only. Ranking is by critical score then overall score (data completeness, NOT profitability).
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DF = ROOT / "research/input_research/data_foundation"
CAT = ROOT / "research/input_research/catalog"
OUT = ROOT / "research/input_research/market_completeness"
SPORTS = ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS")
W = {"FULL": 1.0, "PARTIAL": 0.5, "PROXY": 0.25}
COVERED = ("FULL", "PARTIAL", "PROXY")


def category(vs: str, audit_status: str | None) -> str:
    if vs == "EXCLUDED_BENCHMARK_ONLY": return "EXCLUDED_MARKET"
    if vs == "VERIFIED_FULL": return "FULL"
    if vs == "VERIFIED_PARTIAL": return "PARTIAL"
    if vs == "VERIFIED_PROXY": return "PROXY"
    if vs == "DATA_IN_HAND_CONFIRMED": return "DATA_IN_HAND"
    if vs in ("BLOCKED_CONFIRMED", "BLOCKED_BY_POLICY"): return "NO_FREE_SOURCE"
    if vs == "BLOCKED_CONTESTED": return "CONTESTED"
    if vs == "PIT_QUARANTINED": return "PROSPECTIVE"
    a = audit_status or ""
    if a in ("COLLECT_FREE_MEASURED", "COLLECT_FREE_UNVERIFIED", "DATA_IN_HAND"): return "FREE_ACCESSIBLE"
    if a == "COLLECT_PROSPECTIVE": return "PROSPECTIVE"
    if a.startswith("BLOCKED"): return "NO_FREE_SOURCE"
    return "FREE_ACCESSIBLE"


def load_status(ref: str | None) -> dict:
    if ref:
        txt = subprocess.run(["git", "show", f"{ref}:research/input_research/data_foundation/verified_coverage.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        vc = json.loads(txt)
    else:
        vc = json.loads((DF / "verified_coverage.json").read_text())
    return {r["key"]: r["verified_status"] for r in vc["rows"]}


def archetypes() -> list[dict]:
    out = []
    for sp in SPORTS:
        j = json.loads((CAT / f"{sp}.json").read_text())
        reg = j["archetypes"].items()
        unreg = j.get("unregistered_archetypes", [])
        unreg = unreg.items() if isinstance(unreg, dict) else unreg
        for kind, items in (("registered", reg), ("unregistered", unreg)):
            for name, a in items:
                out.append({"sport": sp, "name": name, "kind": kind, "label": a.get("label", ""), "inputs": [(i["id"], i["role"]) for i in a["inputs"]]})
    return out


def measure(status: dict, audit: dict) -> list[dict]:
    rows = []
    for a in archetypes():
        cats = []
        for iid, role in a["inputs"]:
            k = f"{a['sport']}:{iid}"
            if k not in status:
                cats.append((iid, role, "UNMAPPED")); continue
            cats.append((iid, role, category(status[k], (audit.get(k) or {}).get("full_definition_status"))))
        req = [c for c in cats if c[2] not in ("EXCLUDED_MARKET",)]
        prim = [c for c in req if c[1] == "primary"]
        cnt = Counter(c[2] for c in req); pcnt = Counter(c[2] for c in prim)
        score = lambda cs: (sum(W.get(c[2], 0.0) for c in cs) / len(cs)) if cs else None
        missing = [c[0] for c in prim if c[2] not in COVERED]
        rows.append({"sport": a["sport"], "archetype": a["name"], "kind": a["kind"], "label": a["label"], "n_inputs_listed": len(cats), "n_excluded_market_inputs": len(cats) - len(req), "n_required": len(req), "n_primary": len(prim),
                     "FULL": cnt["FULL"], "PARTIAL": cnt["PARTIAL"], "PROXY": cnt["PROXY"], "DATA_IN_HAND": cnt["DATA_IN_HAND"], "FREE_ACCESSIBLE": cnt["FREE_ACCESSIBLE"], "PROSPECTIVE": cnt["PROSPECTIVE"],
                     "NO_FREE_SOURCE": cnt["NO_FREE_SOURCE"], "CONTESTED": cnt["CONTESTED"], "UNMAPPED": cnt["UNMAPPED"],
                     "primary_FULL": pcnt["FULL"], "primary_PARTIAL": pcnt["PARTIAL"], "primary_PROXY": pcnt["PROXY"], "primary_missing_critical": len(missing), "missing_critical_ids": missing,
                     "missing_critical_free_opportunity": [c[0] for c in prim if c[2] in ("DATA_IN_HAND", "FREE_ACCESSIBLE")], "missing_critical_prospective": [c[0] for c in prim if c[2] == "PROSPECTIVE"],
                     "missing_critical_no_free_source": [c[0] for c in prim if c[2] in ("NO_FREE_SOURCE", "CONTESTED", "UNMAPPED")],
                     "completeness_score": score(req), "critical_score": score(prim), "input_categories": {c[0]: c[2] for c in cats}})
    return rows


def rank(rows: list[dict]) -> list[dict]:
    key = lambda r: (-(r["critical_score"] if r["critical_score"] is not None else -1), -(r["completeness_score"] if r["completeness_score"] is not None else -1), r["sport"], r["archetype"])
    rs = sorted(rows, key=key)
    for i, r in enumerate(rs, 1): r["rank"] = i
    return rs


def render_doc(now: list[dict], ref: str | None) -> str:
    sec = lambda t: f"\n## {t}\n\n"
    by = defaultdict(Counter); n_arch = Counter(r["sport"] for r in now); cs = defaultdict(list)
    for r in now:
        for k in ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "n_required", "n_primary", "primary_FULL", "primary_PARTIAL", "primary_PROXY", "primary_missing_critical"): by[r["sport"]][k] += r[k]
        if r["critical_score"] is not None: cs[r["sport"]].append(r["critical_score"])
    o = ["# Market-archetype data completeness (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.market_completeness` from `research/input_research/data_foundation/verified_coverage.json` (agent verification, NOT human) and the catalog; artifacts under `research/input_research/market_completeness/`. "
         "**This ranks DATA COMPLETENESS only. It says nothing about edge, profitability or model quality; modelling experiments remain PAUSED.**", "",
         "Universe: 170 archetypes = 118 registered + 52 unregistered across 8 sports. Each lists catalog inputs with a role (primary / secondary / context). Market-derived benchmark inputs are excluded: they are not independent inputs. "
         "Input slots are counted per archetype, so one input shared by several archetypes is counted in each (slots, not distinct inputs).", "",
         "Per input (exactly one category): **FULL / PARTIAL / PROXY** = replayed + blind-verified builder; **DATA_IN_HAND** = real columns confirmed buildable, no builder yet; **FREE_ACCESSIBLE** = a permitted free source exists, nothing built or verified; "
         "**PROSPECTIVE** = needs capture from now on (no backfillable history, or point-in-time quarantined); **NO_FREE_SOURCE** = paid-only / none / sample-only / policy-blocked / blind-confirmed blocked; **CONTESTED** = blind rounds disagree on whether any permitted source exists. "
         "Score = (1.0 FULL + 0.5 PARTIAL + 0.25 PROXY) / required inputs; critical score is the same over PRIMARY-role inputs. Ranking: critical score, then overall score."]
    o.append(sec("Roll-up by sport (input slots)"))
    o += ["| Sport | archetypes | required slots | FULL | PARTIAL | PROXY | DATA_IN_HAND | FREE_ACCESSIBLE | PROSPECTIVE | NO_FREE_SOURCE | CONTESTED | primary slots | primary covered (F/P/X) | primary missing critical | mean critical score |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sp in SPORTS:
        c = by[sp]; o.append(f"| {sp} | {n_arch[sp]} | {c['n_required']} | {c['FULL']} | {c['PARTIAL']} | {c['PROXY']} | {c['DATA_IN_HAND']} | {c['FREE_ACCESSIBLE']} | {c['PROSPECTIVE']} | {c['NO_FREE_SOURCE']} | {c['CONTESTED']} | {c['n_primary']} | {c['primary_FULL']}/{c['primary_PARTIAL']}/{c['primary_PROXY']} | {c['primary_missing_critical']} | {sum(cs[sp]) / max(1, len(cs[sp])):.3f} |")
    t = Counter()
    for r in now:
        for k in ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "n_required", "primary_missing_critical"): t[k] += r[k]
    o.append(f"| **all** | 170 | {t['n_required']} | {t['FULL']} | {t['PARTIAL']} | {t['PROXY']} | {t['DATA_IN_HAND']} | {t['FREE_ACCESSIBLE']} | {t['PROSPECTIVE']} | {t['NO_FREE_SOURCE']} | {t['CONTESTED']} | | | {t['primary_missing_critical']} | |")
    if ref:
        gained = [r for r in now if r.get("baseline") and (r["FULL"] + r["PARTIAL"] + r["PROXY"]) > (r["baseline"]["FULL"] + r["baseline"]["PARTIAL"] + r["baseline"]["PROXY"])]
        o.append(sec(f"Change versus baseline `{ref}`"))
        P = lambda r, b=False: sum((r["baseline"] if b else r).get(k, 0) for k in ("primary_FULL", "primary_PARTIAL", "primary_PROXY"))
        both = [r for r in now if r.get("baseline")]
        o.append(f"Counts of improved archetypes depend on the measure (all four are reported; none is a profitability claim): built-and-verified input slots up **{len(gained)}**; PRIMARY built slots up **{sum(P(r) > P(r, True) for r in both)}**; critical (primary) score up **{sum(r['critical_score'] > r['baseline']['critical_score'] for r in both)}**; primary slots still missing down **{sum(r['primary_missing_critical'] < r['baseline']['primary_missing_critical'] for r in both)}**. Unique PRIMARY slots unlocked (sum over archetypes): **{sum(P(r) - P(r, True) for r in both)}**.\n")
        o.append(f"{len(gained)} of 170 archetypes gained built-and-verified input slots; the largest gains:\n")
        o += ["| Archetype | slots built before | now | critical score before | now |", "|---|---|---|---|---|"]
        for r in sorted(gained, key=lambda r: -((r['FULL'] + r['PARTIAL'] + r['PROXY']) - (r['baseline']['FULL'] + r['baseline']['PARTIAL'] + r['baseline']['PROXY'])))[:20]:
            b = r["baseline"]; o.append(f"| {r['sport']}/{r['archetype']} | {b['FULL'] + b['PARTIAL'] + b['PROXY']} | {r['FULL'] + r['PARTIAL'] + r['PROXY']} | {b['critical_score'] if b['critical_score'] is None else round(b['critical_score'], 3)} | {round(r['critical_score'], 3) if r['critical_score'] is not None else None} |")
    o.append(sec("All 170 archetypes ranked by data completeness"))
    o += ["| # | Sport | Archetype | req | F | P | X | in hand | free | prospective | no free src | contested | primary missing | critical | overall |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f3 = lambda v: "" if v is None else f"{v:.3f}"
    for r in now:
        o.append(f"| {r['rank']} | {r['sport']} | {r['archetype']} | {r['n_required']} | {r['FULL']} | {r['PARTIAL']} | {r['PROXY']} | {r['DATA_IN_HAND']} | {r['FREE_ACCESSIBLE']} | {r['PROSPECTIVE']} | {r['NO_FREE_SOURCE']} | {r['CONTESTED']} | {r['primary_missing_critical']} | {f3(r['critical_score'])} | {f3(r['completeness_score'])} |")
    o.append(sec("Missing critical inputs, by what could fix them"))
    o.append("Per archetype, the PRIMARY-role inputs not yet built, split into: (a) accessible now (data in hand or a permitted free source), (b) prospective capture only, (c) no viable free source. Full lists: `market_completeness.json` (`missing_critical_*`).\n")
    o += ["| Sport | Archetype | (a) accessible free | (b) prospective | (c) no free source |", "|---|---|---|---|---|"]
    for r in now[:0]:
        pass
    for r in sorted(now, key=lambda r: (-r["primary_missing_critical"], r["sport"], r["archetype"]))[:25]:
        o.append(f"| {r['sport']} | {r['archetype']} | {len(r['missing_critical_free_opportunity'])} | {len(r['missing_critical_prospective'])} | {len(r['missing_critical_no_free_source'])} |")
    o.append("\n(25 archetypes with the most missing critical slots shown; the other 145 are in the JSON/CSV.)")
    return "\n".join(o) + "\n"


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    ref = a[a.index("--baseline-ref") + 1] if "--baseline-ref" in a else None
    audit = {r["key"]: r for r in json.loads((DF / "input_audit.json").read_text())["rows"]}
    now = rank(measure(load_status(None), audit)); base = {(r["sport"], r["archetype"]): r for r in measure(load_status(ref), audit)} if ref else {}
    for r in now:
        b = base.get((r["sport"], r["archetype"]))
        if b: r["baseline"] = {k: b[k] for k in ("FULL", "PARTIAL", "PROXY", "completeness_score", "critical_score", "primary_missing_critical", "primary_FULL", "primary_PARTIAL", "primary_PROXY")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "market_completeness.json").write_text(json.dumps({"schema": "market-completeness-1.0", "status": "RESEARCH_ONLY", "n_archetypes": len(now), "baseline_ref": ref, "weights": W,
                                                           "note": "data completeness only; no profitability, edge or model-quality claim; agent verification, not human", "rows": now}, indent=1, default=str) + "\n")
    cols = ["rank", "sport", "archetype", "kind", "n_required", "n_primary", "FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "UNMAPPED", "primary_missing_critical", "critical_score", "completeness_score"]
    with open(OUT / "market_completeness.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in now: w.writerow([r[c] if not isinstance(r[c], float) else round(r[c], 4) for c in cols])
    (ROOT / "docs/MARKET_COMPLETENESS.md").write_text(render_doc(now, ref))
    by = defaultdict(lambda: Counter())
    for r in now:
        for k in ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "UNMAPPED", "n_required"): by[r["sport"]][k] += r[k]
    print(len(now), "archetypes;", sum(r["primary_missing_critical"] for r in now), "missing critical slots")
    for sp, c in by.items(): print(sp, dict(c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

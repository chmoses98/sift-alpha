"""Exact per-series accounting of the live Kalshi sports listing (RESEARCH_ONLY): every series gets exactly ONE status; totals must reconcile to the snapshot with no record missing or
double counted (asserted, and tested). Status vocabulary:
  OUT_OF_SCOPE_SPORT          not one of the eight sports (golf, motorsport, esports, other leagues, ...)
  EXCLUDED_TEST               Kalshi test/placeholder series (titles like 'test', 'delete'); no contract to model
  COVERED_REGISTERED          classified; a registered-family archetype models it
  COVERED_UNREGISTERED        classified; modelled only by an archetype for contracts the registry lacks (catalog_unregistered)
  EXCLUDED_COMBO              multivariate combo of other contracts (modelled through its legs, not a distinct mechanism)
  EXCLUDED_NONSPORT           corporate/political/facility event with no sporting mechanism (reason recorded)
  NO_LISTED_MARKETS           series exists but lists no market, so no contract rules can be read (explicit gap, never guessed)
  CLASSIFIED_NO_ARCHETYPE     contract type understood from rules text; no archetype yet (explicit gap)
  UNCLASSIFIED                rules text unavailable or not understood (explicit gap)
Contract rules text (contract_rules_sample.json) overrides title keywords where they disagree.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from . import market_universe as MU, universe_reconcile as UR

ROOT = Path(__file__).resolve().parents[2]
MUD = ROOT / "research/input_research/market_universe"
OUT = MUD / "series_ledger.json"
SCOPE = ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS")


def build(use_overrides: bool = True) -> dict:
    rows = json.loads((MUD / "live_series_snapshot.json").read_text())
    tickers = [r["ticker"] for r in rows]
    assert len(tickers) == len(set(tickers)), "duplicate series tickers in the snapshot"
    known = MU.known_series()
    overrides = json.loads((MUD / "classification_overrides.json").read_text()) if (use_overrides and (MUD / "classification_overrides.json").exists()) else {}
    led = []
    for r in rows:
        sp = MU.sport_of(r)
        rec = {"ticker": r["ticker"], "sport": sp, "title": r["title"], "registered_series": r["ticker"] in known}
        if sp not in SCOPE:
            rec.update(status="OUT_OF_SCOPE_SPORT", type=None, archetype=None)
        else:
            c = UR.classify(r)
            arch = UR.covering_archetype(sp, c)
            o = overrides.get(r["ticker"])
            if o:
                c = {"type": o["type"], "period": o.get("period", "full")}
                arch = o.get("archetype", arch)
                rec["override_reason"] = o["reason"]
            rec.update(type=c["type"], period=c["period"], archetype=arch)
            if arch == "EXCLUDED_JUNK" or c["type"] == "test_junk":
                rec["status"] = "EXCLUDED_TEST"
            elif arch == "OUT_OF_SCOPE_BASKETBALL":
                rec.update(status="OUT_OF_SCOPE_SPORT", sport="OTHER_SPORT:Basketball (non-NBA/CBB league)")
            elif arch in ("EXCLUDED_COMBO", "EXCLUDED_NONSPORT", "NO_LISTED_MARKETS"):
                rec["status"] = arch
            elif isinstance(arch, str) and arch.startswith("unreg:"):
                rec["status"] = "COVERED_UNREGISTERED"
            elif arch in (None, "UNAUTHORED", "NOT_AUTHORED"):
                rec["status"] = "UNCLASSIFIED" if c["type"] == "unclassified" else "CLASSIFIED_NO_ARCHETYPE"
            else:
                rec["status"] = "COVERED_REGISTERED"
        led.append(rec)
    # evidence grade per series: RULES_TEXT (a sampled market's contract rules were read), NO_LISTING (nothing to read), TITLE_ONLY (classified from title/ticker, rules not sampled)
    rules = json.loads((MUD / "contract_rules_sample.json").read_text()) if (MUD / "contract_rules_sample.json").exists() else {}
    for rec in led:
        q = rules.get(rec["ticker"])
        rec["evidence"] = "NO_LISTING" if (q and q.get("status") == "NO_MARKETS_LISTED") else ("RULES_TEXT" if q and q.get("rules_primary") else "TITLE_ONLY")
    cnt = collections.Counter((x["sport"] if x["status"] == "OUT_OF_SCOPE_SPORT" else "IN_SCOPE", x["status"]) for x in led)
    by_sport = {s: collections.Counter(x["status"] for x in led if x["sport"] == s) for s in SCOPE}
    total = len(led)
    in_scope = sum(1 for x in led if x["sport"] in SCOPE)
    by_sport = {s: collections.Counter(x["status"] for x in led if x["sport"] == s) for s in SCOPE}
    assert sum(sum(c.values()) for c in by_sport.values()) == in_scope
    assert in_scope + sum(1 for x in led if x["status"] == "OUT_OF_SCOPE_SPORT") == total
    return {"schema_version": "series-ledger-1.0", "status": "RESEARCH_ONLY", "total_series": total, "in_scope": in_scope, "out_of_scope": total - in_scope,
            "by_sport": {s: {"total": sum(c.values()), **dict(c)} for s, c in by_sport.items()}, "evidence_totals": dict(collections.Counter(x["evidence"] for x in led if x["sport"] in SCOPE)), "rows": led}


def main():
    L = build()
    OUT.write_text(json.dumps(L, indent=0, sort_keys=True))
    print(L["total_series"], "total;", L["in_scope"], "in scope;", L["out_of_scope"], "out of scope")
    for s, v in L["by_sport"].items():
        print(s, v)


if __name__ == "__main__":
    main()

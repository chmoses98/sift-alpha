"""Rank the highest-value unanswered research questions from the data (no hand-typed priorities).

score = market_weight x evidence_gap x feasibility
  market_weight  log(1 + live markets in the archetype's families)       (where a finding would be usable)
  evidence_gap   L0 inventory-only 1.0 > L1 baseline-only 0.7 > L2 vs close 0.45 > L3 0.2
  feasibility    share of the archetype's primary inputs that are pregame-knowable and have a free source
Questions about already-tested archetypes are generated from their own results (what the test could NOT answer).
"""
from __future__ import annotations

import math

LEVEL_GAP = {"L0_INVENTORY_ONLY": 1.0, "L1_TESTED_VS_BASELINE": 0.7, "L2_TESTED_VS_MARKET": 0.45, "L3_TESTED_VS_KALSHI": 0.2, "L4_PROSPECTIVELY_CONFIRMED": 0.0}


def _feasible(arch: dict, cat_inputs: dict) -> float:
    prim = [i for i in arch["inputs"] if i.get("role") in ("primary", None)] or arch["inputs"]
    ok = 0
    for i in prim:
        c = cat_inputs[i["id"]]
        if c["pregame_knowable"] in ("yes", "partial") and c["free_sources"] != ["NONE_FOUND"]:
            ok += 1
    return ok / max(1, len(prim))


def build(sport_docs: dict, catalogs: dict) -> dict:
    items = []
    for s, d in sport_docs.items():
        for a, rec in d["archetypes"].items():
            fams = rec["families"]
            markets = sum((d["families"].get(f, {}).get("markets_now") or 0) for f in fams)
            feas = _feasible({"inputs": [{"id": i["id"], "role": i["role"]} for i in rec["inputs"]]}, catalogs[s]["inputs"])
            n_untested = sum(1 for i in rec["inputs"] if not i["tested"])
            n_missing = sum(1 for i in rec["inputs"] if d["inputs"][i["id"]]["availability"]["overall"] in ("NOT_IN_REGISTRY", "NO_FREE_SOURCE_FOUND", "NO_REFERENCE_FOUND", "SOURCE_AVAILABLE_NOT_COLLECTED"))
            score = math.log1p(markets) * LEVEL_GAP[rec["level"]] * (0.3 + 0.7 * feas)
            if rec["level"] == "L0_INVENTORY_ONLY":
                q = (f"Which of the {len(rec['inputs'])} candidate inputs for {rec['label']} carry out-of-sample predictive information, and do any beat a closing market? "
                     f"{n_untested} untested, {n_missing} not yet collected or sourced.")
                first = "Backfill the cheapest free historical closing lines + outcomes, build point-in-time features for the primary inputs, and run the walk-forward study already used for NFL."
            elif rec["level"] == "L1_TESTED_VS_BASELINE":
                q = (f"{rec['label']}: inputs show predictive value over a no-market baseline; does any of it survive a contemporaneous market price? "
                     f"{n_untested} of {len(rec['inputs'])} candidate inputs remain untested.")
                first = "Obtain historical prop/market lines (capture Kalshi quotes prospectively) and re-run with the market as benchmark."
            else:
                q = (f"{rec['label']}: tested against a closing line with no demonstrated gain. Does an inefficiency exist earlier in the price path, in unmodelled inputs, or only in Kalshi prices?"
                     f" {n_untested} of {len(rec['inputs'])} candidate inputs untested.")
                first = "Test open-to-close line movement and Kalshi quotes vs the sportsbook close; add the untested primary inputs (coverage scheme, time-to-throw, route-level data where free)."
            items.append({"id": f"{s}:{a}", "sport": s, "archetype": a, "label": rec["label"], "level": rec["level"], "live_markets": markets, "feasibility": round(feas, 3),
                          "untested_inputs": n_untested, "uncollected_inputs": n_missing, "score": round(score, 4), "question": q, "first_step": first, "cost": "$0 (free sources only)",
                          "status": "RESEARCHED_IN_PART" if rec["paths"] else "OPEN"})
    items.sort(key=lambda x: -x["score"])
    for i, it in enumerate(items):
        it["rank"] = i + 1
    return {"method": __doc__.split("\n\n")[0], "items": items[:60], "n_archetypes": len(items)}

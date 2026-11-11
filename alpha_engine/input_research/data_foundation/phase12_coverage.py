"""Phase 12 coverage inventory (RESEARCH_ONLY): which PRIMARY missing slots a direct CFBD/CBBD path or MoneyPuck's listed downloads could satisfy, quota estimates, and the next-20 ranking.

    python -m alpha_engine.input_research.data_foundation.phase12_coverage [--write]

Pure derivation from committed artifacts (verified_coverage, input_audit, catalog, rights_registry). No network, no key. "Serviceable" means a source path EXISTS on paper;
nothing is covered until data is acquired under authorization, a builder is written and replayed, and a blind re-implementation matches. Coverage claims stay with market_completeness.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import market_completeness as MC
from . import rights as RT
from ...collect import college_direct as CD

ROOT = Path(__file__).resolve().parents[3]
DF = ROOT / "research/input_research/data_foundation"
OUT = DF / "phase12_coverage.json"
QUOTA_SCENARIOS = {"unverified_tier_1000": 1000, "unverified_tier_5000": 5000, "unverified_tier_25000": 25000}   # monthly-cap scenarios, NOT measured; the owner's real cap is unknown
SHARE = 0.4          # share of the shared monthly cap the planned backfill is allowed to use per month
# MoneyPuck: files evidenced as in production use by the owner's nhl-edge-finder (src/nhl_edge/data/moneypuck.py at de1c36a); the page itself was NOT read.
MONEYPUCK_EVIDENCED = {
    "playerData/seasonSummary/{year}/regular/teams.csv": {"grain": "team season by situation (all/5on5/5on4/4on5/other)", "serves": ["TEAM_BOX (season aggregates)"]},
    "playerData/seasonSummary/{year}/regular/goalies.csv": {"grain": "goalie season by situation, xGoals vs goals", "serves": ["PLAYER_BOX (goalie season)"]},
    "playerData/careers/gameByGame/all_teams.csv": {"grain": "every team-game since 2008 by situation", "serves": ["TEAM_BOX (game level)", "EVENT aggregates (xG for/against by situation)"]},
}
# files the agent remembers on the MoneyPuck data page; NOT evidenced, may be unlisted or renamed: not usable until the owner confirms the page listing
MONEYPUCK_REMEMBERED_UNVERIFIED = ["shots_{year}.zip (shot-level xG events)", "skaters.csv / lines.csv / pairings (season by situation)", "allPlayersLookup.csv", "playerData/careers/gameByGame/{player}.csv"]
NHL_NEED_TO_MP = {"TEAM_BOX": "MONEYPUCK_EVIDENCED", "PLAYER_BOX": "MONEYPUCK_EVIDENCED (goalie season only) / REMEMBERED_UNVERIFIED (skaters)", "EVENT": "REMEMBERED_UNVERIFIED (shot file)"}
CLASS_W = {"DATA_IN_HAND": 1.0, "FREE_ACCESSIBLE": 0.7, "PROSPECTIVE": 0.1, "NO_FREE_SOURCE": 0.0, "CONTESTED": 0.05}


def best_source_tier(a: dict) -> str:
    order = RT.registry()["tier_order"]; names = [n for p in a.get("provenance_sources", []) for n in p.get("canonical", [])]
    return max((RT.tier_of_source(n) for n in names), key=order.index, default=order[0]) if names else order[0]


def build() -> dict:
    st = MC.load_status(None); aud = {r["key"]: r for r in json.loads((DF / "input_audit.json").read_text())["rows"]}
    rows = MC.measure(st, aud); slots: Counter = Counter(); cat = {}
    for r in rows:
        for i in r["missing_critical_ids"]: slots[(r["sport"], i)] += 1; cat[(r["sport"], i)] = r["input_categories"][i]
    per_sport = Counter(); [per_sport.update({s: n}) for (s, _), n in slots.items()]
    inv = []
    for (sp, iid), n in slots.items():
        a = aud[f"{sp}:{iid}"]; rec = {"key": f"{sp}:{iid}", "sport": sp, "id": iid, "label": a["label"], "primary_missing_slots": n, "category": cat[(sp, iid)], "full_def_status": a.get("full_definition_status"),
                                        "needs": sorted({q["need"] for q in a.get("requirements", [])}), "best_source_tier": best_source_tier(a), "sources": sorted({n for p in a.get("provenance_sources", []) for n in p.get("canonical", [])})}
        if sp in ("CFB", "CBB"): rec["direct_api"] = CD.serviceability(sp.lower(), a.get("requirements", []))
        if sp == "NHL": rec["moneypuck"] = {q["need"]: NHL_NEED_TO_MP.get(q["need"], "NOT_MONEYPUCK") for q in a.get("requirements", [])}
        inv.append(rec)
    inv.sort(key=lambda r: (-r["primary_missing_slots"], r["key"]))
    college = {}
    for sp in ("CFB", "CBB"):
        mine = [r for r in inv if r["sport"] == sp]; by = defaultdict(lambda: {"inputs": 0, "slots": 0})
        for r in mine: c = r["direct_api"]["class"]; by[c]["inputs"] += 1; by[c]["slots"] += r["primary_missing_slots"]
        seas = list(range(2014, 2026)); dom = sp.lower(); ep = set(e for r in mine if r["direct_api"]["class"] != "NOT_SERVICEABLE" for e in r["direct_api"]["endpoints"])
        est = CD.estimate(dom, seas, sorted(ep)); calls = est["static_calls"]; pg = sum(est["per_game_calls_estimate"].values())
        months = {k: {"static_backfill_calls": calls, "per_game_calls": pg, "months_at_%d%%_share" % (SHARE * 100): round((calls + pg) / (v * SHARE), 2)} for k, v in QUOTA_SCENARIOS.items()}
        college[sp] = {"missing_primary_slots": per_sport[sp], "direct_api_serviceability": {k: dict(v) for k, v in by.items()}, "endpoints_needed": sorted(ep), "estimate_2014_2025": est, "months_to_complete_by_cap_scenario": months}
    cov = {k: sum(v["primary_missing_slots"] for v in inv if v["sport"] in ("CFB", "CBB") and v["direct_api"]["class"] == k) for k in ("FULLY_SERVICEABLE", "PARTLY_SERVICEABLE", "NOT_SERVICEABLE")}
    nhl = [r for r in inv if r["sport"] == "NHL"]
    nhl_sum = {"missing_primary_slots": per_sport["NHL"], "distinct_inputs": len(nhl),
               "slots_with_any_evidenced_moneypuck_need": sum(r["primary_missing_slots"] for r in nhl if any(v.startswith("MONEYPUCK_EVIDENCED") for v in r["moneypuck"].values())),
               "slots_with_only_unverified_listing_needs": sum(r["primary_missing_slots"] for r in nhl if not any(v.startswith("MONEYPUCK_EVIDENCED") for v in r["moneypuck"].values()) and any(v.startswith("REMEMBERED") for v in r["moneypuck"].values())),
               "evidenced_listed_downloads": MONEYPUCK_EVIDENCED, "remembered_unverified": MONEYPUCK_REMEMBERED_UNVERIFIED,
               "isolation": "MoneyPuck-derived outputs carry tier CLEARED_NONCOMMERCIAL_RESEARCH (owner-reported); they are never counted commercial-cleared; unlisted resources and the NHL API stay UNRESOLVED"}
    rank = sorted(inv, key=lambda r: -(r["primary_missing_slots"] * CLASS_W.get(r["category"], 0.3)))
    top = [{"rank": i + 1, "key": r["key"], "label": r["label"][:70], "primary_missing_slots": r["primary_missing_slots"], "category": r["category"], "best_source_tier": r["best_source_tier"], "sources": r["sources"],
            "feasibility": ("direct CFBD/CBBD API (needs owner authorization)" if "direct_api" in r and r["direct_api"]["class"] != "NOT_SERVICEABLE" else "MoneyPuck listed download (evidenced files only)" if r.get("moneypuck") and any(v.startswith("MONEYPUCK_EVIDENCED") for v in r["moneypuck"].values())
                            else "prospective capture only" if r["category"] == "PROSPECTIVE" else "free source exists; rights/builder open")} for i, r in enumerate(rank[:20])]
    return {"schema": "phase12-coverage-1.0", "status": "RESEARCH_ONLY", "primary_missing_slots": sum(per_sport.values()), "primary_missing_by_sport": dict(per_sport),
            "college_direct_api": {"missing_slots_by_class": cov, "by_sport": college, "quota_note": "caps are scenarios, not measurements; real shared monthly cap and per-call limits unknown until an authorised probe", "share_of_cap_used_for_backfill": SHARE},
            "nhl_moneypuck": nhl_sum, "top20_next": top, "inventory": inv}


def main(argv=None) -> int:
    d = build(); txt = json.dumps(d, indent=1, sort_keys=True) + "\n"
    if "--check" in (argv or sys.argv[1:]): return 0 if OUT.exists() and OUT.read_text() == txt else 1
    if "--write" in (argv or sys.argv[1:]): OUT.write_text(txt)
    print(json.dumps({k: d[k] for k in ("primary_missing_slots", "primary_missing_by_sport")}), json.dumps(d["college_direct_api"]["missing_slots_by_class"]), json.dumps(d["nhl_moneypuck"]["slots_with_any_evidenced_moneypuck_need"])); return 0


if __name__ == "__main__":
    sys.exit(main())

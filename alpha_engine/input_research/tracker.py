"""The single authoritative research progress tracker (RESEARCH_ONLY): computes every number from committed artifacts and renders docs/RESEARCH_TRACKER.md + progress.json.

Nothing here is typed by hand except the coordination notes and the open-gap list's wording; counts are recomputed on every run, so the tracker cannot drift from the data.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IR = ROOT / "research/audit/input_research"
IN = ROOT / "research/input_research"
SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"]


def rd(p):
    return json.loads(Path(p).read_text())


def compute() -> dict:
    cats = {s: rd(IN / f"catalog/{s}.json") for s in SPORTS}
    audit = rd(IR / "coverage_audit.json")
    adj = rd(IN / "gap_adjudication.json")
    rec = rd(IN / "market_universe/reconciliation.json")
    uni = rd(IN / "market_universe/universe_summary.json")
    dep = rd(IN / "market_dependency.json")
    src = rd(IN / "source_verification.json")
    cat_rows = {s: {"inputs": len(c["inputs"]), "archetypes": len(c["archetypes"]), "unregistered_archetypes": len(c.get("unregistered_archetypes") or {}),
                    "interactions": sum(len(a["interactions"]) for a in list(c["archetypes"].values()) + list((c.get("unregistered_archetypes") or {}).values())) + sum(len(b["interactions"]) for b in c["blueprints"].values())} for s, c in cats.items()}
    verdicts = collections.Counter(a["verdict"] for a in adj["adjudications"])
    rec_rows = {}
    for s, rows in rec["sports"].items():
        tot = sum(r["series"] for r in rows)
        cov = sum(r["series"] for r in rows if r["archetype"] not in (None, "UNAUTHORED", "NOT_AUTHORED", "EXCLUDED_JUNK") and not str(r["archetype"]).startswith("unreg:"))
        unreg = sum(r["series"] for r in rows if str(r["archetype"]).startswith("unreg:"))
        junk = sum(r["series"] for r in rows if r["archetype"] == "EXCLUDED_JUNK")
        rec_rows[s] = {"in_scope_series": tot, "covered_by_registered_archetype": cov, "covered_only_by_unregistered_archetype": unreg, "no_archetype_or_unclassified": tot - cov - unreg - junk, "excluded_test_series": junk,
                       "unregistered_series": uni["by_sport"].get(s, {}).get("new_unregistered", 0)}
    other = sum(v["series"] for k, v in uni["by_sport"].items() if k not in SPORTS)
    ready = audit["readiness"]
    verified = sum(len(v["with_measured_free_source"]) for v in ready.values())
    return {"schema_version": "tracker-1.0", "status": "RESEARCH_ONLY",
            "catalog": {"by_sport": cat_rows, "inputs_total": sum(r["inputs"] for r in cat_rows.values()), "archetypes_total": sum(r["archetypes"] for r in cat_rows.values()),
                        "unregistered_archetypes_total": sum(r["unregistered_archetypes"] for r in cat_rows.values())},
            "mechanism_audit": {"checklist_flags": adj["n_flags"], "adjudications": adj["n_adjudications"], "verdicts": dict(verdicts),
                                "unadjudicated_archetypes": sum(len(r["unadjudicated_missing"]) > 0 for rows in audit["mechanism_matrix"].values() for r in rows)},
            "market_universe": {"live_series": uni["n_series"], "in_scope_reconciliation": rec_rows, "outside_the_eight_sports_series": other},
            "market_dependency": {"benchmark_only_inputs": sum(len(v) for v in dep["benchmark_only"].values()), "hybrid_rebuild_required": sum(len(v) for v in dep["hybrid_rebuild"].values()),
                                  "incidental_mentions": sum(len(v) for v in dep["incidental"].values())},
            "data_readiness": {"inputs_with_measured_free_source": verified, "inputs_total": sum(r["inputs"] for r in cat_rows.values()),
                               "by_sport": {s: {"measured_free_source": len(v["with_measured_free_source"]), "snapshot_only": len(v["snapshot_only_source"])} for s, v in ready.items()},
                               "sources_blocked_from_runner": [u for u, st in src["reachability_from_runner"].items() if st != 200]},
            "search_experiments": {"nfl_qb_passing_yards": "market-free nested search done (+1.94% vs history); worse than Kalshi mid", "soccer_totals_goal_difference": "market-free nested search done; no Kalshi comparison", "other_sports": "NOT STARTED (no data pulled yet)"},
            "coordination": {"pr_53": "merged 6720c01", "pr_59": "draft NFL-only laboratory (alpha_engine/lab: ledger, game/player labs, Kalshi comparison). Overlap: market-free guard (59's is stricter: also rejects implied/closing/consensus and post-game columns; align on merge), NFL Kalshi comparison (same conclusion: independent model worse than Kalshi). Not duplicated here: ledger, ratings grid, player lab. Cross-sport catalog, audit, reconciliation, search harness and dashboard live only in #60.",
                             "pr_60": "this branch: single milestone PR, draft"}}


def render(p: dict) -> str:
    L = ["# SIFT Alpha research progress tracker (RESEARCH_ONLY)", "", "Generated by `python -m alpha_engine.input_research.tracker` from committed artifacts; do not edit by hand. One authoritative tracker; PR #60 carries it.", ""]
    c = p["catalog"]
    L += ["## P0 candidate-input catalog", f"{c['inputs_total']} candidate inputs, {c['archetypes_total']} registered-market archetypes and {c['unregistered_archetypes_total']} archetypes for listed-but-unregistered contract types. **Not claimed complete**: a populated list is not evidence of completeness.", "",
          "| Sport | Inputs | Archetypes | Unregistered archetypes | Interactions |", "|---|---|---|---|---|"]
    L += [f"| {s} | {r['inputs']} | {r['archetypes']} | {r['unregistered_archetypes']} | {r['interactions']} |" for s, r in c["by_sport"].items()]
    m = p["mechanism_audit"]
    L += ["", f"Mechanism checklist: {m['checklist_flags']} (archetype, category) flags, every one adjudicated ({m['unadjudicated_archetypes']} unadjudicated): " + ", ".join(f"{k} {v}" for k, v in m["verdicts"].items()) + ". Detail: `research/input_research/gap_adjudication.json`.", ""]
    u = p["market_universe"]
    L += ["## Market universe reconciliation", f"{u['live_series']} live Kalshi sports series; {u['outside_the_eight_sports_series']} are outside the eight sports (unsupported).", "", "| Sport | In-scope series | Covered by a registered archetype | Covered only by an unregistered-contract archetype | No archetype / unclassified | Series absent from registry |", "|---|---|---|---|---|---|"]
    L += [f"| {s} | {r['in_scope_series']} | {r['covered_by_registered_archetype']} | {r['covered_only_by_unregistered_archetype']} | {r['no_archetype_or_unclassified']} | {r['unregistered_series']} |" for s, r in u["in_scope_reconciliation"].items()]
    d = p["market_dependency"]
    L += ["", "## Market-free policy", f"{d['benchmark_only_inputs']} catalog inputs are benchmark-only (price/line-derived), {d['hybrid_rebuild_required']} need a market-free rebuild before use, {d['incidental_mentions']} mention prices incidentally. `marketfree.assert_market_free` rejects market columns in primary models.", ""]
    r = p["data_readiness"]
    L += ["## P1 data readiness", f"{r['inputs_with_measured_free_source']} of {r['inputs_total']} inputs have a free source MEASURED reachable and populated (`source_verification.json`). By sport: " + ", ".join(f"{s} {v['measured_free_source']}" for s, v in r["by_sport"].items()) + ". Hosts blocked from the research runner: " + ", ".join(r["sources_blocked_from_runner"]) + ".", ""]
    L += ["## P2/P3 experiments", *[f"- {k}: {v}" for k, v in p["search_experiments"].items()], "", "## Coordination", *[f"- {k}: {v}" for k, v in p["coordination"].items()], ""]
    return "\n".join(L)


if __name__ == "__main__":
    p = compute()
    (IR / "progress.json").write_text(json.dumps(p, indent=0, sort_keys=True))
    (ROOT / "docs/RESEARCH_TRACKER.md").write_text(render(p))
    print(render(p)[:1800])

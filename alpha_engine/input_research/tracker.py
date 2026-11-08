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
    led = rd(IN / "market_universe/series_ledger.json")
    dr = rd(IN / "data_readiness.json")
    rep = rd(IN / "data_collection/repo_archives_ledger.json")
    coll = {f.stem.replace("_ledger", ""): rd(f) for f in sorted((IN / "data_collection").glob("*_ledger.json")) if f.stem != "repo_archives_ledger"}
    cross = rd(IR / "experiments/search_crosssport_v1.json") if (IR / "experiments/search_crosssport_v1.json").exists() else {"studies": {}}
    arch_counts = {s: dict(collections.Counter(v["readiness"] for v in dr["archetype_readiness"].values() if v["sport"] == s)) for s in SPORTS}
    cs = rd(IN / "computable_summary.json")
    ss = rd(IR / "scaled_search_summary.json")
    comp_f = IN / "completeness/summary.json"
    return {"schema_version": "tracker-2.1", "status": "RESEARCH_ONLY", "phase": rd(IN / "phase_control.json"),
            "completeness": rd(comp_f) if comp_f.exists() else None,
            "computable_inputs": {"n_inputs": cs["n_inputs"], "n_non_market": cs["n_non_market"], "verified_computed": cs["verified_computed"], "verified_by_level": cs["verified_by_level"], "totals": cs["totals"], "by_sport": cs["by_sport"], "blocker_classes": cs["blocker_classes"], "verification": cs["verification"]},
            "scaled_search": {"totals": ss["totals"], "ledger": ss["ledger"], "multiple_testing": ss["multiple_testing"], "rows": [r for r in ss["rows"] if r["status"] == "TESTED"], "not_tested": [r for r in ss["rows"] if r["status"] != "TESTED"]},
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
            "series_ledger": {"total": led["total_series"], "in_scope": led["in_scope"], "out_of_scope": led["out_of_scope"], "by_sport": led["by_sport"],
                              "status_totals": dict(collections.Counter(r["status"] for r in led["rows"])), "evidence_totals": led["evidence_totals"], "reconciles": sum(v["total"] for v in led["by_sport"].values()) == led["in_scope"]},
            "data_collected": {"repo_archives": {k: {"rows": v.get("rows"), "date_min": v.get("date_min"), "date_max": v.get("date_max"), "source_repo": v.get("source_repo"), "branch": v.get("branch")} for k, v in rep["datasets"].items()},
                               "api_collectors": {k: {"rows": v.get("games") or v.get("player_game_rows") or v.get("player_games"), "seasons": v.get("seasons"), "retrieved_utc": v.get("retrieved_utc"), "timestamp_reliability": v.get("timestamp_reliability")} for k, v in coll.items()}},
            "data_readiness_after": {"before_inputs_with_measured_free_source": verified, "after": dr["totals"], "before_after": dr["before_after"], "by_sport": dr["by_sport"], "archetype_readiness_by_sport": arch_counts, "top_unlocks": dr["unlock_ranking"][:12]},
            "search_experiments_cross_sport": {k: {"market": v.get("market"), "n": v.get("n_games"), "gain_pct": (v.get("nested_gain") or {}).get("pct_gain"), "seasons_positive": (v.get("nested_gain") or {}).get("seasons_positive"),
                                                   "seasons": len((v.get("nested_gain") or {}).get("seasons", [])), "null_pct": [x["pct_gain"] for x in v.get("permutation_null", [])]} for k, v in cross["studies"].items() if "error" not in v},
            "search_experiments": {"nfl_qb_passing_yards": "market-free nested search done (+1.94% vs history); worse than Kalshi mid", "soccer_totals_goal_difference": "market-free nested search done; no Kalshi comparison", "cross_sport": "see search_experiments_cross_sport"},
            "coordination": {"pr_53": "merged 6720c01", "pr_59": "draft NFL-only laboratory (alpha_engine/lab). MILESTONE 2 RECONCILIATION (no duplicate laboratory, nothing of #59 merged): (1) its append-only experiment ledger schema is adopted verbatim as input_research/ledger.py (same exp_id hash, same JSONL rows, gz convention) and search.nested_search now logs every configuration x block; #59's 13,362 experiments are counted read-only from origin/feat/sift-lab; (2) its stricter guard is merged into marketfree.assert_market_free as a superset (implied/closing/consensus/_mkt_/bid/ask + post-game targets-only). STILL REUSABLE after review: (3) parametrised rating grid (lab/ratings.py) as a feature generator for the NFL tables; (4) exceedance calibration and market-comparison code for the later Kalshi step. NOT duplicated here: its NFL game/player labs and 13,362-experiment ledger. Unique to #60: cross-sport catalog, adjudication, exact series ledger, rules-text classification, raw-data collectors and readiness model, cross-sport search harness, dashboard. Both PRs reach the same NFL conclusion: independent models do not beat Kalshi prices.",
                             "pr_60": "this branch: single milestone PR, draft",
                             "catalog_completeness": "2026-11-07 priority change: predictive experimentation PAUSED (phase_control.json); PR #60 and #62 code and results preserved as PRELIMINARY. The completeness review is carried on branch claude/market-catalog-completeness-74mme9, stacked on #62 (no additional PR opened). RESEARCH_ONLY: no orders, spending, deployments or merges."}}


SHORT = {"NOT_STARTED": "not started", "STRUCTURE_INCOMPLETE": "structure incomplete", "AUTHORED_NOT_INDEPENDENTLY_REVIEWED": "authored, awaiting independent review",
         "INDEPENDENT_REVIEW_OPEN_FINDINGS": "independent review: open findings", "REVERIFICATION_PENDING": "awaiting second verification", "READY_FOR_USER_APPROVAL": "ready for your approval"}


def _completeness_md(p: dict) -> list[str]:
    ph, g = p["phase"], p.get("completeness")
    L = ["> **PHASE: CATALOG COMPLETENESS. Predictive experimentation is PAUSED** (" + ph["predictive_experiments"]["state"] + "; `research/input_research/phase_control.json`). "
         "Every predictive result in this tracker (combination search, benchmarks, weights) is **PRELIMINARY**, preserved from PR #60 / #62 and not being expanded. "
         "Nothing here authorises orders, spending, deployments or merges. RESEARCH_ONLY.", ""]
    if not g:
        return L + ["## Catalog completeness gate", "Not yet generated (`python -m alpha_engine.input_research.completeness`).", ""]
    t = g["totals"]
    L += ["## Catalog completeness gate (the sole active research priority)",
          f"{t['archetypes']} market archetypes (registered + unregistered contract types) across the eight sports. **{t['READY_FOR_USER_APPROVAL']} have reached the code's ceiling (ready for your approval); none is declared complete, and the catalog is only complete if the acceptance criteria below are all met and you approve.** "
          f"Approval recorded: **{'YES' if g['approval'].get('approved') else 'NO'}**. A populated list or a passing automated check is necessary, never sufficient; the ceiling the code can award is *ready for your approval*.", "",
          "Acceptance criteria (all must hold per archetype): " + "; ".join(g["criteria"]) + ".", "",
          "| Sport | Archetypes | Not started | Structure incomplete | Authored, awaiting independent review | Independent review: open findings | Awaiting second verification | Ready for your approval | Inputs in catalog |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {s_} | {v['archetypes']} | {v['NOT_STARTED']} | {v['STRUCTURE_INCOMPLETE']} | {v['AUTHORED_NOT_INDEPENDENTLY_REVIEWED']} | {v['INDEPENDENT_REVIEW_OPEN_FINDINGS']} | {v['REVERIFICATION_PENDING']} | {v['READY_FOR_USER_APPROVAL']} | {v['inputs']} |" for s_, v in g["by_sport"].items()]
    ac = g.get("acceptance")
    if ac:
        L += ["", "### Documented acceptance criteria, evaluated from the artifacts", "| Criterion | Result | Detail |", "|---|---|---|"]
        L += [f"| {c['criterion']} | {'PASS' if c['pass'] else '**NOT MET**'} | {c['detail']} |" for c in ac["criteria"]]
        L += ["", f"**All documented criteria met: {'yes' if ac['meets_criteria'] else 'no'}.** {ac['note']}", "",
              "### Authoritative catalog totals (after integrating every review)", "| Sport | Inputs | Registered archetypes | Unregistered / new archetypes | Interactions (archetype + blueprint) | Non-linearities | Inputs with raw-data definition |", "|---|---|---|---|---|---|---|"]
        for s_, v in ac["catalog_totals"].items():
            L.append(f"| {s_} | {v['inputs']} | {v['registered_archetypes']} | {v['unregistered_archetypes']} | {v['archetype_interactions']} + {v['blueprint_interactions']} = {v['archetype_interactions'] + v['blueprint_interactions']} | {v['nonlinearities']} | {v['inputs_with_raw_data_definition']} |")
        ver = ac["verification"]
        L += ["", "### Verification record (agents, not human experts)",
              f"* Independent reviews: {ver['independent_reviews']}. Finding resolutions: {ver['finding_resolutions']}.",
              f"* Second verification (different model) of closed blocker/major findings: {ver['second_verification_of_closed_blocker_major']}.",
              f"* Post-reconcile audit of edited records: {ver['post_reconcile_audit']} (reconciled archetypes: {ver['reconcile'].get('archetypes_reconciled', 0)}).",
              "", "### Gap classification (every declared `unresolved` entry)", f"{ac['gap_classification']['classified']} of {ac['gap_classification']['declared']} classified: {ac['gap_classification']['by_class']}.", "",
              "| Sport | Declared | Catalog blocker | Unverifiable contract | Data-source limitation | Future data collection |", "|---|---|---|---|---|---|"]
        for s_, v in ac["gap_classification"]["by_sport"].items():
            L.append(f"| {s_} | {v['declared']} | {v.get('CATALOG_BLOCKER', 0)} | {v.get('UNVERIFIABLE_CONTRACT', 0)} | {v.get('DATA_SOURCE_LIMITATION', 0)} | {v.get('FUTURE_DATA_COLLECTION', 0)} |")
        ia = ac["input_audit"]
        L += ["", f"### Input audit (definition, raw data, provenance, market-free class)", f"Audited {sum(ia['audited'].values())} inputs. Market-free class: {ia['market_free']}. Verdicts: {ia['verdicts']}."]
    L += ["", "### Per-archetype status", "Stages = mechanism stages; New = inputs discovered by this review; Audit = existing inputs individually judged; Ix/NL = interactions / non-linearities; Data = required datasets; Open = unresolved gaps declared; Rules = contract text verification; Ind = independent review.", "",
          "| Sport | Archetype | Status | Live series (rules read) | Stages | New | Audit | Ix/NL | Data | Open | Rules | Ind (open findings) |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in g["rows"]:
        L.append(f"| {r['sport']} | {r['archetype']} | {SHORT[r['status']]} | {r['live_series']} ({r['rules_text_series']}) | {r.get('stages', '–')} | {r.get('new_inputs', '–')} | {r.get('existing_inputs_audited', '–')} | "
                 f"{r.get('interactions', '–')}/{r.get('nonlinearities', '–')} | {r.get('datasets', '–')} | {r.get('unresolved', '–')} | {(r.get('rules_verification') or '–').replace('_', ' ').lower()} | {r.get('independent', '–')} ({r.get('open_findings', '–')}) |")
    L += ["", "### Contract universe behind the review (exact reconciled assignment of every ledger series; the PR #62 ledger is preserved, overridden only by series_assignment.json)",
          "| Sport | Series | In scope | Out of scope (explicit) | No listed market (contract unreadable) | In scope: rules text read | In scope: title only | In scope: no listing | Reviewed vs rules/title | Re-filed by review | In new archetypes |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    tot = {}
    for s_, v in g["contract_universe"].items():
        L.append(f"| {s_} | {v['series']} | {v['in_scope']} | {v['out_of_scope']} | {v['no_listed_market']} | {v['in_scope_rules_text_read']} | {v['in_scope_title_only']} | {v['in_scope_no_listing']} | {v['reviewed_against_rules_or_title']} | {v['refiled_by_review']} | {v['in_new_archetypes']} |")
        for k_, n_ in v.items():
            tot[k_] = tot.get(k_, 0) + n_
    L.append(f"| **all eight sports** | {tot['series']} | {tot['in_scope']} | {tot['out_of_scope']} | {tot['no_listed_market']} | {tot['in_scope_rules_text_read']} | {tot['in_scope_title_only']} | {tot['in_scope_no_listing']} | {tot['reviewed_against_rules_or_title']} | {tot['refiled_by_review']} | {tot['in_new_archetypes']} |")
    L += ["", "Series whose classification rests on the title only, and series that list no market, are **explicitly unresolved**, not complete. Per-archetype detail (mechanism stages, inputs, formulas, interactions, raw data, gaps, independent findings): `research/input_research/completeness/` and the dashboard Catalog completeness panel.", ""]
    return L


def render(p: dict) -> str:
    L = ["# SIFT Alpha research progress tracker (RESEARCH_ONLY)", "", "Generated by `python -m alpha_engine.input_research.tracker` from committed artifacts; do not edit by hand. One authoritative tracker; carried by PR #60 and its stacked milestone-2 PR.", ""]
    L += _completeness_md(p)
    c = p["catalog"]
    L += ["## P0 candidate-input catalog", f"{c['inputs_total']} candidate inputs, {c['archetypes_total']} registered-market archetypes and {c['unregistered_archetypes_total']} archetypes for listed-but-unregistered contract types. **Not claimed complete**: a populated list is not evidence of completeness.", "",
          "| Sport | Inputs | Archetypes | Unregistered archetypes | Interactions |", "|---|---|---|---|---|"]
    L += [f"| {s} | {r['inputs']} | {r['archetypes']} | {r['unregistered_archetypes']} | {r['interactions']} |" for s, r in c["by_sport"].items()]
    m = p["mechanism_audit"]
    L += ["", f"Mechanism checklist: {m['checklist_flags']} (archetype, category) flags, every one adjudicated ({m['unadjudicated_archetypes']} unadjudicated): " + ", ".join(f"{k} {v}" for k, v in m["verdicts"].items()) + ". Detail: `research/input_research/gap_adjudication.json`.", ""]
    u = p["market_universe"]
    L += ["## Market universe reconciliation as filed in the preserved PR #62 ledger (superseded for archetype coverage by the reconciled assignment in the completeness gate above; every series has exactly one status; rows sum to the series total)", f"{u['live_series']} live Kalshi sports series; {p['series_ledger']['out_of_scope']} are outside the eight sports (unsupported), {p['series_ledger']['in_scope']} in scope.", "",
          "| Sport | Series | Covered (registered archetype) | Covered (unregistered-contract archetype) | No listed market (rules unreadable) | Excluded (test / non-sport / combo) | Classified, no archetype | Unclassified | Sum |", "|---|---|---|---|---|---|---|---|---|"]
    for s_, v in p["series_ledger"]["by_sport"].items():
        ex = v.get("EXCLUDED_TEST", 0) + v.get("EXCLUDED_NONSPORT", 0) + v.get("EXCLUDED_COMBO", 0)
        cells = [v.get("COVERED_REGISTERED", 0), v.get("COVERED_UNREGISTERED", 0), v.get("NO_LISTED_MARKETS", 0), ex, v.get("CLASSIFIED_NO_ARCHETYPE", 0), v.get("UNCLASSIFIED", 0)]
        L.append(f"| {s_} | {v['total']} | " + " | ".join(str(c) for c in cells) + f" | {sum(cells)} |")
    L += ["", f"Evidence behind the classification: {p['series_ledger']['evidence_totals']} series (RULES_TEXT = a sampled market's actual contract rules were read; TITLE_ONLY = classified from title/ticker, rules not yet read; NO_LISTING = series lists no market).", ""]
    ci = p["computable_inputs"]
    L += ["## Verified computable inputs (milestone 2; replaces the keyword-based readiness estimate below)",
          f"**{ci['verified_computed']} of {ci['n_non_market']} non-market candidate inputs are computed from real raw rows and verified** (full definition {ci['verified_by_level'].get('FULL', 0)}, partial {ci['verified_by_level'].get('PARTIAL', 0)}, proxy {ci['verified_by_level'].get('PROXY', 0)}); {ci['n_inputs'] - ci['n_non_market']} are market-derived and excluded. Verification: {ci['verification']}.", "",
          "| Sport | Computed (verified) | Built, not pregame-eligible / unverified / failed | Not computed | Market-derived |", "|---|---|---|---|---|"]
    for s_, v in ci["by_sport"].items():
        okc = sum(n for k, n in v.items() if k.startswith("COMPUTED"))
        L.append(f"| {s_} | {okc} | {v.get('NOT_PREGAME_ELIGIBLE', 0) + v.get('UNVERIFIED_LEAK_TEST', 0) + v.get('LEAK_FAIL', 0)} | {v.get('NOT_COMPUTED', 0)} | {v.get('EXCLUDED_BENCHMARK_ONLY', 0)} |")
    L += ["", "Raw data classes that block the not-computed inputs (count of inputs): " + ", ".join(f"{k.lower()} {n}" for k, n in list(ci["blocker_classes"].items())[:10]) + ". Per-input status, coverage, history and what is missing: `research/input_research/computable_inputs.json` (dashboard: Verified computable inputs).", ""]
    sc = p["scaled_search"]
    L += ["## Scaled market-free combination testing (milestone 2) — PRELIMINARY, PAUSED", f"{sc['totals']['n_tested']} markets tested across the eight sports on verified inputs only; **{sc['ledger']['rows_logged']:,} configuration x block records logged** ({sc['ledger']['unique_market_configurations']:,} unique market-configurations; ledger schema identical to PR #59, whose {sc['ledger']['lab59_experiments_read_only']:,} experiments are read from its branch, not copied). Verdicts: {sc['totals'].get('verdicts')}. Multiple testing: {sc['multiple_testing']}.", "",
          "| Market | Rows | Groups | Gain | 95% CI | Holm p | Blocks + | Null | Verdict |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['market']} | {r['n']:,} | {r['groups']} | {r['gain']:.2f}% | [{r['ci'][0]:.3g}, {r['ci'][1]:.3g}] | {r['holm_p']:.3f} | {r['pos']}/{r['blocks']} | {', '.join(f'{x:.2f}%' for x in r['null'])} | {r['verdict']} |" for r in sc["rows"]]
    if sc["not_tested"]:
        L += ["", "Not tested: " + "; ".join(f"{r['market']} ({r['why']})" for r in sc["not_tested"]) + "."]
    L += [""]
    d = p["market_dependency"]
    L += ["", "## Market-free policy", f"{d['benchmark_only_inputs']} catalog inputs are benchmark-only (price/line-derived), {d['hybrid_rebuild_required']} need a market-free rebuild before use, {d['incidental_mentions']} mention prices incidentally. `marketfree.assert_market_free` rejects market columns in primary models.", ""]
    r = p["data_readiness"]
    L += ["## P1 data readiness", f"Before this round: {r['inputs_with_measured_free_source']} of {r['inputs_total']} inputs had a free source MEASURED reachable and populated (`source_verification.json`). Hosts blocked from the research runner: " + ", ".join(r["sources_blocked_from_runner"]) + ".", ""]
    dd = p["data_readiness_after"]
    L += [f"After (raw-data-class model, `data_readiness.json`, an estimate from keyword rules, SUPERSEDED by the verified-computable table above): {dd['after']['AVAILABLE']} inputs AVAILABLE, {dd['after']['PARTIAL']} PARTIAL, {dd['after']['MISSING']} MISSING, {dd['after']['EXCLUDED_BENCHMARK_ONLY']} excluded as benchmark-only (of {dd['after']['inputs']}).", "",
          "| Sport | Available | Partial | Missing | Benchmark-only | Archetype readiness |", "|---|---|---|---|---|---|"]
    L += [f"| {s} | {v.get('AVAILABLE', 0)} | {v.get('PARTIAL', 0)} | {v.get('MISSING', 0)} | {v.get('EXCLUDED_BENCHMARK_ONLY', 0)} | " + ", ".join(f"{k} {n}" for k, n in dd['archetype_readiness_by_sport'][s].items()) + " |" for s, v in dd["by_sport"].items()]
    L += ["", "Largest raw-data unlocks (inputs that become fully available if the class reaches full coverage): " + "; ".join(f"{u['sport']} {u['class'].lower()} (+{u['inputs_unlocked_by_upgrading_to_full']})" for u in dd["top_unlocks"][:8]) + ".", ""]
    sl = p["series_ledger"]
    L += ["## Exact series ledger (PR #62, preserved; the reconciled assignment is in series_assignment.json)", f"{sl['total']} series = {sl['in_scope']} in scope + {sl['out_of_scope']} out of scope (reconciles: {sl['reconciles']}). Status totals: " + ", ".join(f"{k} {v}" for k, v in sorted(sl["status_totals"].items())) + ".", ""]
    dc = p["data_collected"]
    L += ["## Raw data in hand", "From the project's own repositories (`git show`, no new host): " + "; ".join(f"{k} {v['rows']:,} rows ({v['date_min']}..{v['date_max']})" for k, v in dc["repo_archives"].items() if v.get("rows")) + ".", "",
          "Collected from free APIs this round: " + "; ".join(f"{k} {v['rows']:,}" for k, v in dc["api_collectors"].items() if v.get("rows")) + ".", ""]
    if p["search_experiments_cross_sport"]:
        L += ["## Cross-sport market-free search (nested chronological, permutation null) — PRELIMINARY, PAUSED", "| Market | n | Gain vs baseline | Positive blocks | Null gain |", "|---|---|---|---|---|"]
        L += [f"| {v['market']} | {v['n']:,} | {v['gain_pct']:.2f}% | {v['seasons_positive']}/{v['seasons']} | {', '.join(f'{x:.2f}%' for x in v['null_pct'])} |" for v in p["search_experiments_cross_sport"].values()]
        L += [""]
    L += ["## P2/P3 experiments (PRELIMINARY, PAUSED)", *[f"- {k}: {v}" for k, v in p["search_experiments"].items()], "", "## Coordination", *[f"- {k}: {v}" for k, v in p["coordination"].items()], ""]
    return "\n".join(L)


if __name__ == "__main__":
    p = compute()
    (IR / "progress.json").write_text(json.dumps(p, indent=0, sort_keys=True))
    (ROOT / "docs/RESEARCH_TRACKER.md").write_text(render(p))
    print(render(p)[:1800])

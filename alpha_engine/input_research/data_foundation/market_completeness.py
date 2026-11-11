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

from . import rights as RT

ROOT = Path(__file__).resolve().parents[3]
DF = ROOT / "research/input_research/data_foundation"
CAT = ROOT / "research/input_research/catalog"
OUT = ROOT / "research/input_research/market_completeness"
SPORTS = ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS")
W = {"FULL": 1.0, "PARTIAL": 0.5, "PROXY": 0.25}
COVERED = ("FULL", "PARTIAL", "PROXY")
SEM_EVIDENCE = DF / "semantics_capture_evidence.json"
SEMANTIC_IDS = ("m.rules_text",)   # market semantics metadata (Kalshi rules/settlement text), excluded from the PREDICTIVE denominator and tracked as its own dimension
# Phase 10 (owner decision 1): settlement / operational metadata and market-calibration benchmarks are NOT independent market-free sports predictors. Derived classification only: the catalog entries stay (baseline lock untouched).
SETTLEMENT_OPS_IDS = ("m.settlement_truth", "m.lifecycle", "m.stat_correction_risk", "m.stat_source_mismatch")
CALIBRATION_IDS = ("m.strike_hit_rates",)
# Phase 11: inputs whose WHOLE catalog measurement is a parse of Kalshi rules text into contract flags (no sports measurement) are contract metadata. Inputs that MIX a rules-text part with an independent sports measurement are split component-wise and stay in the predictive denominator.
RULES_PARSE_ONLY_IDS = ("soc.competition_scope_and_win_definition",)
COMPONENT_SPLIT = {
    "ten.retirement_settlement_rules": {"metadata_component": "rules_primary text parsed into settle_on_retirement / void_if_not_completed / min sets-games / count_partial_games flags", "predictive_component": "P(match completes) and P(retire by state) from the player retirement hazard (Sackmann RET/W-O history; overlaps ten.retirement_margin_state, ten.walkover_slot_hazard)", "denominator": "PREDICTIVE (retained)"},
    "ten.ace_settlement_source": {"metadata_component": "named source of record parsed from rules text", "predictive_component": "historical disagreement rate between ace/double-fault counting sources (needs a second statistics feed: not free-accessible)", "denominator": "PREDICTIVE (retained)"},
    "ten.short_format_rules": {"metadata_component": "event format coding (sets to win, games per set, tiebreak score, ad/no-ad) from the rulebook", "predictive_component": "no-ad hold formula, first-to-four set DP, best-of-five roll-up and the short-format variance inflation from past Next Gen Finals sets", "denominator": "PREDICTIVE (retained)"},
    "soc.competition_scope_and_win_definition": {"metadata_component": "all of it: competitions_all / league_only, friendlies_count, shootout_win_counts, men_only, calendar window parsed from rules text", "predictive_component": "none", "denominator": "METADATA (removed from the predictive denominator)"},
}
NON_PREDICTIVE_IDS = SEMANTIC_IDS + SETTLEMENT_OPS_IDS + CALIBRATION_IDS + RULES_PARSE_ONLY_IDS
PRED_KEYS = ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "UNMAPPED")


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


def sem_capture_state() -> dict:
    ev = json.loads(SEM_EVIDENCE.read_text())["sports"] if SEM_EVIDENCE.exists() else {}
    return {sp: ev.get(sp, {}).get("state", "NOT_CAPTURED") for sp in SPORTS}


def measure(status: dict, audit: dict) -> list[dict]:
    rows = []; sem_cap = sem_capture_state()
    for a in archetypes():
        cats = []
        for iid, role in a["inputs"]:
            k = f"{a['sport']}:{iid}"
            if k not in status:
                cats.append((iid, role, "UNMAPPED")); continue
            cats.append((iid, role, category(status[k], (audit.get(k) or {}).get("full_definition_status"))))
        sem = [c for c in cats if c[0] in SEMANTIC_IDS and c[2] != "EXCLUDED_MARKET"]
        sops = [c for c in cats if c[0] in SETTLEMENT_OPS_IDS and c[2] != "EXCLUDED_MARKET"]
        rpo = [c for c in cats if c[0] in RULES_PARSE_ONLY_IDS and c[2] != "EXCLUDED_MARKET"]     # Phase 11: pure rules-text contract flags
        calib = [c for c in cats if c[0] in CALIBRATION_IDS]          # includes the sports where the matrix already excluded it as benchmark-only
        req = [c for c in cats if c[2] not in ("EXCLUDED_MARKET",) and c[0] not in NON_PREDICTIVE_IDS]
        prim = [c for c in req if c[1] == "primary"]
        cnt = Counter(c[2] for c in req); pcnt = Counter(c[2] for c in prim)
        score = lambda cs: (sum(W.get(c[2], 0.0) for c in cs) / len(cs)) if cs else None
        tier = lambda c: RT.input_tier(f"{a['sport']}:{c[0]}") if c[2] in COVERED else None
        cleared = [c for c in req if c[2] in COVERED and RT.is_cleared(tier(c))]; cleared_p = [c for c in prim if c[2] in COVERED and RT.is_cleared(tier(c))]
        comm = [c for c in req if c[2] in COVERED and RT.is_commercial_cleared(tier(c))]; comm_p = [c for c in prim if c[2] in COVERED and RT.is_commercial_cleared(tier(c))]
        wrapper = [c for c in req if c[2] in COVERED and tier(c) == "WRAPPER_LICENCE_UPSTREAM_CAVEAT"]
        unres = [c for c in req if c[2] in COVERED and tier(c) == "UNRESOLVED_INTERNAL_ONLY"]
        rscore = lambda cs, base: (sum(W[c[2]] for c in cs) / len(base)) if base else None
        missing = [c[0] for c in prim if c[2] not in COVERED]
        sem_state = [sem_cap[a["sport"]] for c in sem]
        rows.append({"sport": a["sport"], "archetype": a["name"], "kind": a["kind"], "label": a["label"], "n_inputs_listed": len(cats), "n_excluded_market_inputs": sum(c[2] == "EXCLUDED_MARKET" and c[0] not in NON_PREDICTIVE_IDS for c in cats), "n_required": len(req), "n_primary": len(prim), "rules_parse_only_required": len(rpo), "rules_parse_only_primary": sum(c[1] == "primary" for c in rpo),
                     "FULL": cnt["FULL"], "PARTIAL": cnt["PARTIAL"], "PROXY": cnt["PROXY"], "DATA_IN_HAND": cnt["DATA_IN_HAND"], "FREE_ACCESSIBLE": cnt["FREE_ACCESSIBLE"], "PROSPECTIVE": cnt["PROSPECTIVE"],
                     "NO_FREE_SOURCE": cnt["NO_FREE_SOURCE"], "CONTESTED": cnt["CONTESTED"], "UNMAPPED": cnt["UNMAPPED"],
                     "primary_FULL": pcnt["FULL"], "primary_PARTIAL": pcnt["PARTIAL"], "primary_PROXY": pcnt["PROXY"], "primary_missing_critical": len(missing), "missing_critical_ids": missing,
                     "primary_PROSPECTIVE": pcnt["PROSPECTIVE"],
                     "missing_critical_free_opportunity": [c[0] for c in prim if c[2] in ("DATA_IN_HAND", "FREE_ACCESSIBLE")], "missing_critical_prospective": [c[0] for c in prim if c[2] == "PROSPECTIVE"],
                     "missing_critical_no_free_source": [c[0] for c in prim if c[2] in ("NO_FREE_SOURCE", "CONTESTED", "UNMAPPED")],
                     "completeness_score": score(req), "critical_score": score(prim), "input_categories": {c[0]: c[2] for c in cats},
                     # --- Phase 9 dimensions
                     "predictive_required": len(req), "predictive_primary": len(prim),
                     "semantics_required": len(sem), "semantics_primary": sum(c[1] == "primary" for c in sem), "semantics_built": 0, "semantics_state": sem_state, "semantics_captured_unverified": sum(x == "CAPTURED_UNVERIFIED" for x in sem_state), "semantics_partial_capture": sum(x == "PARTIAL_CAPTURE_UNVERIFIED" for x in sem_state),
                     "semantics_completeness": (0.0 if sem else None),
                     "settlement_ops_required": len(sops), "settlement_ops_primary": sum(c[1] == "primary" for c in sops), "settlement_ops_ids": sorted(c[0] for c in sops),
                     "calibration_required": len(calib), "calibration_primary": sum(c[1] == "primary" for c in calib), "calibration_ids": sorted(c[0] for c in calib),
                     "built_rights_cleared": len(cleared), "built_wrapper_licence_only": len(wrapper), "built_rights_unresolved": len(unres),
                     "primary_built_rights_cleared": len(cleared_p), "built_commercial_cleared": len(comm), "primary_built_commercial_cleared": len(comm_p),
                     "rights_cleared_score": rscore(cleared, req), "rights_cleared_critical_score": rscore(cleared_p, prim),
                     "prospective_gap_slots": cnt["PROSPECTIVE"], "prospective_gap_primary": pcnt["PROSPECTIVE"],
                     "independently_complete": bool(req) and cnt["FULL"] == len(req) and len(cleared) == len(req) and not sem})
    return rows


def rank(rows: list[dict]) -> list[dict]:
    key = lambda r: (-(r["critical_score"] if r["critical_score"] is not None else -1), -(r["completeness_score"] if r["completeness_score"] is not None else -1), r["sport"], r["archetype"])
    rs = sorted(rows, key=key)
    for i, r in enumerate(rs, 1): r["rank"] = i
    return rs


def render_doc(now: list[dict], ref: str | None) -> str:
    sec = lambda t: f"\n## {t}\n\n"
    by = defaultdict(Counter); n_arch = Counter(r["sport"] for r in now); cs = defaultdict(list); rcs = defaultdict(list)
    SUM = ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "UNMAPPED", "n_required", "n_primary", "primary_FULL", "primary_PARTIAL", "primary_PROXY", "primary_missing_critical", "primary_PROSPECTIVE",
           "semantics_required", "semantics_primary", "semantics_built", "semantics_captured_unverified", "semantics_partial_capture", "settlement_ops_required", "settlement_ops_primary", "calibration_required", "calibration_primary", "built_rights_cleared", "built_wrapper_licence_only", "built_rights_unresolved", "primary_built_rights_cleared", "built_commercial_cleared", "primary_built_commercial_cleared", "prospective_gap_slots", "prospective_gap_primary")
    for r in now:
        for k in SUM: by[r["sport"]][k] += r[k]
        by[r["sport"]]["sem_archetypes"] += r["semantics_required"] > 0
        if r["critical_score"] is not None: cs[r["sport"]].append(r["critical_score"])
        if r["rights_cleared_critical_score"] is not None: rcs[r["sport"]].append(r["rights_cleared_critical_score"])
    T = Counter()
    for r in now:
        for k in SUM: T[k] += r[k]
        T["sem_archetypes"] += r["semantics_required"] > 0
    mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
    o = ["# Market-archetype data completeness (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.market_completeness` from `research/input_research/data_foundation/verified_coverage.json` (agent verification, NOT human), the catalog and `rights_registry.json`; artifacts under `research/input_research/market_completeness/`. "
         "**This ranks DATA COMPLETENESS only. It says nothing about edge, profitability or model quality; modelling experiments remain PAUSED.**", "",
         "Universe: 170 archetypes = 118 registered + 52 unregistered across 8 sports. Each lists catalog inputs with a role (primary / secondary / context). Market-derived benchmark inputs are excluded: they are not independent inputs. "
         "Input slots are counted per archetype, so one input shared by several archetypes is counted in each (slots, not distinct inputs).", "",
         "**Five separate dimensions (Phase 9, extended Phase 10).** (1) *Predictive input completeness*: the score below, computed WITHOUT any market-metadata slot (Kalshi rules text, settlement/operational metadata, calibration benchmarks; see section 2b). (2) *Market semantics completeness*: whether the timestamped, contract-specific rules and settlement text each archetype's contracts need is captured (the `m.rules_text` slots: 144 slots, of which 134 are PRIMARY-role). "
         "Rules text is market semantics metadata, mandatory for settling a contract correctly but not an independent predictive sports input, so it is removed from the predictive denominator and never counted as predictive coverage. The catalog still lists it in every archetype and the baseline lock is unchanged. "
         "(3) *Rights-cleared availability*, reported separately for non-commercial research clearance and for commercial-use clearance: built-and-verified predictive slots whose sources carry an explicit data licence (`CLEARED_*` tiers); wrapper-only licences (nflverse CC BY over NFL upstream terms, `WRAPPER_ONLY`) and unresolved upstream terms count for neither. (4) *Prospective-capture gaps*: predictive slots that need vintages captured from now on.", "",
         "Per predictive input (exactly one category): **FULL / PARTIAL / PROXY** = replayed + blind-verified builder; **DATA_IN_HAND** = real columns confirmed buildable, no builder yet; **FREE_ACCESSIBLE** = a permitted free source exists, nothing built or verified; "
         "**PROSPECTIVE** = needs capture from now on (no backfillable history, or point-in-time quarantined); **NO_FREE_SOURCE** = paid-only / none / sample-only / policy-blocked / blind-confirmed blocked; **CONTESTED** = blind rounds disagree on whether any permitted source exists. "
         "Score = (1.0 FULL + 0.5 PARTIAL + 0.25 PROXY) / required predictive inputs; critical score is the same over PRIMARY-role inputs. Ranking: critical score, then overall score."]
    o.append(sec("1. Predictive input completeness (rules text excluded), roll-up by sport (input slots)"))
    o += ["| Sport | archetypes | predictive slots | FULL | PARTIAL | PROXY | DATA_IN_HAND | FREE_ACCESSIBLE | PROSPECTIVE | NO_FREE_SOURCE | CONTESTED | primary slots | primary covered (F/P/X) | primary missing critical | mean critical score |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sp in SPORTS:
        c = by[sp]; o.append(f"| {sp} | {n_arch[sp]} | {c['n_required']} | {c['FULL']} | {c['PARTIAL']} | {c['PROXY']} | {c['DATA_IN_HAND']} | {c['FREE_ACCESSIBLE']} | {c['PROSPECTIVE']} | {c['NO_FREE_SOURCE']} | {c['CONTESTED']} | {c['n_primary']} | {c['primary_FULL']}/{c['primary_PARTIAL']}/{c['primary_PROXY']} | {c['primary_missing_critical']} | {mean(cs[sp]):.3f} |")
    o.append(f"| **all** | 170 | {T['n_required']} | {T['FULL']} | {T['PARTIAL']} | {T['PROXY']} | {T['DATA_IN_HAND']} | {T['FREE_ACCESSIBLE']} | {T['PROSPECTIVE']} | {T['NO_FREE_SOURCE']} | {T['CONTESTED']} | {T['n_primary']} | {T['primary_FULL']}/{T['primary_PARTIAL']}/{T['primary_PROXY']} | {T['primary_missing_critical']} | |")
    o.append(sec("2. Market semantics completeness (Kalshi rules text, `m.rules_text`)"))
    o.append("Requirement: per contract, the rules text with its capture timestamp and version (overtime inclusion, push/tie treatment, void/DNP, postponement window, settlement source, expiration), preserved so a model's output definition can be matched to the exact clause. "
             "The public Kalshi market object carries `rules_primary`, `rules_secondary`, `early_close_condition`, `created_time`, `updated_time` and `settlement_timer_seconds`, but only its CURRENT text: no version history is exposed, so a timestamped history exists only from the first capture onward (see `docs/PHASE9_RIGHTS_SEMANTICS_PROSPECTIVE.md`). "
             "Measured in the owner's archives (`semantics_capture_evidence.json`): NBA and NHL hold timestamped full snapshots plus deltas of the market objects since 2026-09-18 / 2026-09-29, and the NFL prospective-capture branch holds per-contract rules text for 5 series since 2026-11-07 (see the table). "
             "Those captures are NOT audited for contract-family coverage and no clause extraction has been blind-verified, so **verified** semantics completeness is 0 for every archetype; the capture presence is reported separately and is not counted as completeness.\n")
    o += ["| Sport | capture state | archetypes needing rules text | semantics slots | of which PRIMARY | timestamped capture exists (unverified) | verified | verified completeness |", "|---|---|---|---|---|---|---|---|"]
    st_ = sem_capture_state()
    for sp in SPORTS:
        c = by[sp]; o.append(f"| {sp} | {st_[sp]} | {c['sem_archetypes']} | {c['semantics_required']} | {c['semantics_primary']} | {c['semantics_captured_unverified'] + c['semantics_partial_capture']} | {c['semantics_built']} | 0.000 |")
    o.append(f"| **all** | | {T['sem_archetypes']} | {T['semantics_required']} | {T['semantics_primary']} | {T['semantics_captured_unverified'] + T['semantics_partial_capture']} | {T['semantics_built']} | 0.000 |")
    o.append(sec("2b. Settlement / operational metadata and market-calibration benchmarks (not predictors)"))
    o.append("Owner decision (Phase 10): `m.settlement_truth`, `m.lifecycle`, `m.stat_correction_risk` and `m.stat_source_mismatch` are settlement/operational metadata (what settled, when a contract opened/closed, whether a stat later changed or disagrees across feeds); `m.strike_hit_rates` is a market-calibration / benchmark input (historical hit rates of Kalshi strikes, i.e. market-pricing information). "
             "None is an independent market-free sports predictor, so none counts in the predictive denominator and none is ever scored as predictive coverage. The catalog entries are kept (baseline lock unchanged); this is a derived classification only, and historical point-in-time cutoffs are not touched.\n")
    o += ["| Sport | settlement/ops slots | of which PRIMARY | calibration slots | of which PRIMARY |", "|---|---|---|---|---|"]
    for sp in SPORTS:
        c = by[sp]; o.append(f"| {sp} | {c['settlement_ops_required']} | {c['settlement_ops_primary']} | {c['calibration_required']} | {c['calibration_primary']} |")
    o.append(f"| **all** | {T['settlement_ops_required']} | {T['settlement_ops_primary']} | {T['calibration_required']} | {T['calibration_primary']} |")
    o.append(sec("3. Rights-cleared availability (built-and-verified predictive slots)"))
    o.append("Rights tiers come from `rights_registry.json` (weakest tier over a builder's raw sources; an unmatched source is UNRESOLVED). Research clearance (internal, non-commercial): CLEARED_OPEN_LICENCE (CC0) and CLEARED_NONCOMMERCIAL_RESEARCH (Sackmann CC BY-NC-SA 4.0). Commercial clearance: CLEARED_OPEN_LICENCE only; CC BY-NC-SA is never commercial-cleared. nflverse stays `WRAPPER_ONLY` (CC BY on the wrapper repository, upstream NFL/FTN/NGS terms not evaluated) and counts for neither; its computational evidence is retained. A repository CODE licence is not evidence about upstream data.\n")
    o += ["| Sport | built (F+P+X) | research-cleared | commercial-cleared | wrapper licence only (nflverse) | rights UNRESOLVED (internal only) | primary built | primary built rights-cleared | mean rights-cleared critical score | mean critical score |", "|---|---|---|---|---|---|---|---|---|---|"]
    for sp in SPORTS:
        c = by[sp]; b = c["FULL"] + c["PARTIAL"] + c["PROXY"]; pb = c["primary_FULL"] + c["primary_PARTIAL"] + c["primary_PROXY"]
        o.append(f"| {sp} | {b} | {c['built_rights_cleared']} | {c['built_commercial_cleared']} | {c['built_wrapper_licence_only']} | {c['built_rights_unresolved']} | {pb} | {c['primary_built_rights_cleared']} | {mean(rcs[sp]):.3f} | {mean(cs[sp]):.3f} |")
    b = T["FULL"] + T["PARTIAL"] + T["PROXY"]; pb = T["primary_FULL"] + T["primary_PARTIAL"] + T["primary_PROXY"]
    o.append(f"| **all** | {b} | {T['built_rights_cleared']} | {T['built_commercial_cleared']} | {T['built_wrapper_licence_only']} | {T['built_rights_unresolved']} | {pb} | {T['primary_built_rights_cleared']} | | |")
    o.append(sec("4. Prospective-capture gaps (predictive slots that need vintages captured from now on)"))
    o += ["| Sport | prospective slots | of which PRIMARY |", "|---|---|---|"]
    for sp in SPORTS: o.append(f"| {sp} | {by[sp]['PROSPECTIVE']} | {by[sp]['prospective_gap_primary']} |")
    o.append(f"| **all** | {T['PROSPECTIVE']} | {T['prospective_gap_primary']} |")
    ic = sum(r["independently_complete"] for r in now); anyfull = sum(1 for r in now if r["n_required"] and r["FULL"] == r["n_required"])
    o.append(sec("5. What remains for full independent input coverage"))
    o.append(f"An archetype is *independently complete* only when EVERY predictive slot is FULL, every one of those is rights-cleared, and its market semantics are captured. Today: **{ic} of 170** archetypes are independently complete; {anyfull} have every predictive slot FULL (before rights and semantics).\n")
    tot = T["n_required"]
    o += ["| What it takes | predictive slots | share of slots | primary slots |", "|---|---|---|---|"]
    rows_ = [("already FULL (definition complete, replay + blind verified)", T["FULL"], T["primary_FULL"]),
             ("PARTIAL: finish the definition (missing clauses, history, or model-side steps; each needs a new build, replay and blind verification)", T["PARTIAL"], T["primary_PARTIAL"]),
             ("PROXY: replace by a builder of the actual quantity", T["PROXY"], T["primary_PROXY"]),
             ("DATA_IN_HAND: build, replay, blind-verify", T["DATA_IN_HAND"], None),
             ("FREE_ACCESSIBLE: permitted free source exists, nothing built (collect, build, replay, blind-verify)", T["FREE_ACCESSIBLE"], None),
             ("PROSPECTIVE: capture vintages from now on, then build", T["PROSPECTIVE"], T["prospective_gap_primary"]),
             ("NO_FREE_SOURCE or CONTESTED: needs a paid/restricted source or an owner policy decision", T["NO_FREE_SOURCE"] + T["CONTESTED"], None)]
    prim_free = sum(len(r["missing_critical_free_opportunity"]) for r in now); prim_nofree = sum(len(r["missing_critical_no_free_source"]) for r in now)
    rows_[3] = (rows_[3][0], rows_[3][1], None); rows_[4] = (rows_[4][0], rows_[4][1], None); rows_[6] = (rows_[6][0], rows_[6][1], prim_nofree)
    rows_[3:5] = [(rows_[3][0] + " + " + rows_[4][0], rows_[3][1] + rows_[4][1], prim_free)]
    for lab, n, pn in rows_: o.append(f"| {lab} | {n} | {100 * n / tot:.1f}% | {'' if pn is None else pn} |")
    dist = defaultdict(set)
    for r in now:
        for iid, c in r["input_categories"].items():
            if c != "EXCLUDED_MARKET" and iid not in NON_PREDICTIVE_IDS: dist[c].add((r["sport"], iid))
    o.append("\nDistinct predictive inputs (a shared input counts once per sport; the slot counts above double-count shared inputs): " + ", ".join(f"{c} {len(dist[c])}" for c in PRED_KEYS if dist[c]) + ".")
    o.append(f"\nOf the {b} built slots, only {T['built_rights_cleared']} sit on rights-cleared sources; {T['built_wrapper_licence_only']} rest on a wrapper licence with upstream caveat and {T['built_rights_unresolved']} on unresolved upstream terms, so rights decisions gate a large share of what is already built. Separately, {T['semantics_required']} rules-text slots (134 primary) need timestamped capture.")
    if ref:
        gained = [r for r in now if r.get("baseline") and (r["FULL"] + r["PARTIAL"] + r["PROXY"]) > (r["baseline"]["FULL"] + r["baseline"]["PARTIAL"] + r["baseline"]["PROXY"])]
        o.append(sec(f"Change versus baseline `{ref}` (predictive measure; baseline recomputed with the same rules-text exclusion)"))
        both = [r for r in now if r.get("baseline")]
        full_up = sum(r["FULL"] - r["baseline"]["FULL"] for r in both)
        o.append(f"Predictive FULL slots changed by **{full_up:+d}**; archetypes gaining built-and-verified slots: **{len(gained)}**. (Phase 9 added no builder and promoted no input: the single FULL candidate reviewed was refused by the gate; the differences versus the Phase 8 document are the separation of rules text and the new rights, semantics and prospective dimensions.)\n")
        if gained:
            o += ["| Archetype | slots built before | now | critical score before | now |", "|---|---|---|---|---|"]
            for r in sorted(gained, key=lambda r: -((r['FULL'] + r['PARTIAL'] + r['PROXY']) - (r['baseline']['FULL'] + r['baseline']['PARTIAL'] + r['baseline']['PROXY'])))[:20]:
                bb = r["baseline"]; o.append(f"| {r['sport']}/{r['archetype']} | {bb['FULL'] + bb['PARTIAL'] + bb['PROXY']} | {r['FULL'] + r['PARTIAL'] + r['PROXY']} | {bb['critical_score'] if bb['critical_score'] is None else round(bb['critical_score'], 3)} | {round(r['critical_score'], 3) if r['critical_score'] is not None else None} |")
        up = [r for r in both if r["FULL"] > r["baseline"]["FULL"]]
        if up:
            o.append("\nArchetypes with more FULL predictive slots than the baseline:\n")
            o += ["| Archetype | FULL before | FULL now |", "|---|---|---|"] + [f"| {r['sport']}/{r['archetype']} | {r['baseline']['FULL']} | {r['FULL']} |" for r in up]
    o.append(sec("All 170 archetypes ranked by predictive data completeness"))
    o += ["| # | Sport | Archetype | pred req | F | P | X | in hand | free | prospective | no free src | contested | primary missing | critical | overall | rules text (slot/primary) | built rights-cleared | rights-cleared critical |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f3 = lambda v: "" if v is None else f"{v:.3f}"
    for r in now:
        sm = "" if not r["semantics_required"] else ("primary" if r["semantics_primary"] else "context")
        o.append(f"| {r['rank']} | {r['sport']} | {r['archetype']} | {r['n_required']} | {r['FULL']} | {r['PARTIAL']} | {r['PROXY']} | {r['DATA_IN_HAND']} | {r['FREE_ACCESSIBLE']} | {r['PROSPECTIVE']} | {r['NO_FREE_SOURCE']} | {r['CONTESTED']} | {r['primary_missing_critical']} | {f3(r['critical_score'])} | {f3(r['completeness_score'])} | {sm} | {r['built_rights_cleared']} | {f3(r['rights_cleared_critical_score'])} |")
    o.append(sec("Missing critical inputs, by what could fix them"))
    o.append("Per archetype, the PRIMARY-role predictive inputs not yet built, split into: (a) accessible now (data in hand or a permitted free source), (b) prospective capture only, (c) no viable free source. Full lists: `market_completeness.json` (`missing_critical_*`).\n")
    o += ["| Sport | Archetype | (a) accessible free | (b) prospective | (c) no free source |", "|---|---|---|---|---|"]
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
    (OUT / "market_completeness.json").write_text(json.dumps({"schema": "market-completeness-3.0", "status": "RESEARCH_ONLY", "n_archetypes": len(now), "baseline_ref": ref, "weights": W,
                                                           "note": "data completeness only; no profitability, edge or model-quality claim; agent verification, not human; predictive denominator excludes the m.rules_text market-semantics slots", "semantic_ids": list(SEMANTIC_IDS), "rows": now}, indent=1, default=str) + "\n")
    cols = ["rank", "sport", "archetype", "kind", "n_required", "n_primary", "FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "FREE_ACCESSIBLE", "PROSPECTIVE", "NO_FREE_SOURCE", "CONTESTED", "UNMAPPED", "primary_missing_critical", "critical_score", "completeness_score",
            "semantics_required", "semantics_primary", "semantics_completeness", "settlement_ops_required", "settlement_ops_primary", "calibration_required", "calibration_primary", "built_rights_cleared", "built_commercial_cleared", "built_wrapper_licence_only", "built_rights_unresolved", "rights_cleared_critical_score", "prospective_gap_slots", "prospective_gap_primary", "independently_complete"]
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

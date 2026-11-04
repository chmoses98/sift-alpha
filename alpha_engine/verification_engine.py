"""Universal verification engine: market family -> input -> source-to-projection chain, with strict statuses.

Reads ONLY committed audit artifacts (research/audit/*.json) and, for the one reference family, the pinned ablation file.
Nothing is hand-typed into a status and nothing is upgraded: a status is a pure function of recorded evidence, and an
unrecorded stage is UNKNOWN (never PASS). Verified collection is NOT predictive validation: VALIDATED_PREDICTIVE needs a
family-specific ablation verdict (see ABLATION_FILES) that survived multiplicity correction and a chronological check.

Chain per input:  source -> archive -> timestamp -> transform -> consumption   (input level, per sport)
                  market_mapping -> projection -> historical_eval -> outcomes   (family level)
Each stage is PASS | PARTIAL | FAIL | UNKNOWN | NA with a reason; the first non-PASS stage is the recorded failure.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "research" / "audit"
OUT = A / "verification"

STATUSES = ["VALIDATED_PREDICTIVE", "VERIFIED", "COLLECTED_UNVERIFIED", "COLLECTED_UNUSED", "STALE", "MISSING", "UNSUPPORTED", "UNKNOWN"]
STAGES = ["source", "archive", "timestamp", "transform", "consumption"]
FAMILY_STAGES = ["market_mapping", "projection", "historical_eval", "outcomes"]
COLLECTED_CLASSES = {"VERIFIED_COLLECTION", "COLLECTED_UNVERIFIED_PIT", "STALE_OR_PARTIAL"}
UNUSED_MODEL_USE = {"COLLECTED_UNUSED", "NOT_COLLECTED"}
USED = {"USED", "USED_PARTIAL"}
ABLATION_FILES = {"CFB/quarter_total": "CFB_quarter_total_ablation.json"}
# which ablation variant exercises which registry input (only inputs the variant actually consumes)
ABLATION_INPUT = {"V2_opp_defense": "cfb.q_scoring", "V1_team_offense": "cfb.q_scoring", "V4_recency": "cfb.q_scoring", "V5_team_only_total": "cfb.q_scoring"}
# repo-reported model families (model_validation.json) mapped to Kalshi native families by exact semantic name
MV_MAP = {"NBA": {"player_points": "points", "player_rebounds": "rebounds", "player_assists": "assists", "player_threes": "threes", "player_pra": "pra", "team_total": "team_points"},
          "NHL": {"player_shots": "shots", "player_goals": "goals", "player_assists": "assists", "player_points": "points", "goalie_saves": "saves", "team_total": "team_goals"}}


# Overlay links: registry inputs a reference audit shows are mechanisms for the family but market_specs does not link. They ADD
# contextual/exploratory links only (never essential, never lower an existing tier) so the committed essential denominators
# (1,762 links) are untouched; each row carries origin="overlay" so the addition is auditable and removable.
OVERLAY = {
    "CFB/quarter_total": {i: ("C", why) for i, why in {
        "cfb.sp_plus": "prior on team strength", "cfb.drives": "number of Q1 possessions/scoring chances", "cfb.redzone": "FG vs TD conversion of Q1 drives",
        "cfb.pass_rate": "clock use / scoring variance", "cfb.script": "opening script", "cfb.ol": "drive sustaining / pressure", "cfb.qb": "QB efficiency on opening drives",
        "cfb.depth_chart": "confirmed starters", "cfb.injuries": "availability", "cfb.transfer_roster": "roster churn", "cfb.venue": "neutral site / dome",
        "cfb.rest_travel": "fatigue", "m.ladder_structure": "implied distribution over 0/3/7/10/14", "m.strike_hit_rates": "ladder calibration"}.items()},
}


def rederive_ablation_verdict(ab: dict, variant: str) -> str:
    """Recompute promotion eligibility from the RECORDED numbers; the file's own verdict string is never trusted."""
    e = (ab.get("variants") or {}).get(variant) or {}
    n_comp = sum(1 for v in ab.get("variants", {}).values() if v.get("compared_to"))
    try:
        ok = (ab.get("dependence_aware") is True and ab.get("n_eval", 0) >= ab.get("min_eval", 10**9) and e.get("compared_to") == "V0_league_mean"
              and e.get("n_comparisons_family") == n_comp and e["mae_improvement_ci_bonferroni"][0] > 0 and min(e["chronological_halves_mean"]) > 0
              and e.get("team_jackknife_min_mean") is not None and e["team_jackknife_min_mean"] > 0 and e.get("n_week_clusters", 0) >= 8)
    except (KeyError, TypeError, IndexError):
        ok = False
    return "ELIGIBLE" if ok else "NOT_ELIGIBLE"


WEAK_CLASSES = {"UNKNOWN", "CODE_REFERENCE_ONLY", "NO_REFERENCE_FOUND", "MISSING"}
OVERRIDE_TARGETS = {"COLLECTED_UNVERIFIED_PIT", "STALE_OR_PARTIAL"}


COLLECTION_FOR = {"COLLECTED_UNVERIFIED_PIT": {"COLLECTED_NOT_PIT_ARCHIVED"}, "STALE_OR_PARTIAL": {"PARTIAL_OR_STALE"}}


def apply_source_verification(entry: dict, sv: dict | None) -> dict:
    """Let MEASURED evidence from an existing archive lift an input out of a weak class. Guardrails: only from UNKNOWN / CODE_REFERENCE_ONLY /
    NO_REFERENCE_FOUND / MISSING(source available), never from DERIVED or UNSUPPORTED (no reliable source), never to VERIFIED_COLLECTION or a PIT
    archive, collection label must match the class, a pinned source (repo+commit+path) and measurements are required. Returns a new entry."""
    if not sv:
        return entry
    vc = entry.get("verification_class")
    if vc not in WEAK_CLASSES or (vc == "MISSING" and entry.get("collection") == "NO_RELIABLE_SOURCE"):
        return entry
    m = sv.get("measured") or {}
    src = m.get("source") or {}
    tgt = sv.get("verification_class")
    if tgt not in OVERRIDE_TARGETS or sv.get("collection") not in COLLECTION_FOR[tgt] or not sv.get("why") or not (src.get("repo") and src.get("commit") and src.get("path")):
        return entry
    e = dict(entry)
    e.update(verification_class=tgt, collection=sv["collection"], _source_verification={"why": sv["why"], "source": src})
    e["evidence"] = list(entry.get("evidence", [])) + [f"measured:{src['repo']}@{src['commit'][:7]}:{src['path']}"]
    e["note"] = (entry.get("note", "") + " | MEASURED: " + sv["why"]).strip(" |")
    return e


def _j(p):
    return json.loads(Path(p).read_text())


def may_validate(entry: dict, ablation_ok: bool, family_match: bool = True, transform_state: str = "PASS") -> bool:
    """VALIDATED_PREDICTIVE gate. ALL must hold: the input is verified collection, the model is recorded as ACTUALLY consuming it
    (model_use == USED; unused/unknown/partial never qualifies), the evidence is for this market family, and a chronological,
    multiplicity-corrected, dependence-aware ablation supports it. A contradictory unused record always blocks promotion."""
    return bool(ablation_ok and family_match and transform_state == "PASS" and entry.get("verification_class") == "VERIFIED_COLLECTION" and entry.get("model_use") == "USED")


def input_status(entry: dict, validated: bool = False) -> str:
    """Pure function of one collection_status entry (+ whether a surviving ablation validates it)."""
    vc, col, mu = entry.get("verification_class", "UNKNOWN"), entry.get("collection", "UNKNOWN"), entry.get("model_use", "UNKNOWN")
    if vc == "STALE_OR_PARTIAL":
        return "STALE"
    if vc == "MISSING":
        return "UNSUPPORTED" if col == "NO_RELIABLE_SOURCE" else "MISSING"
    if vc in COLLECTED_CLASSES:
        if validated and may_validate(entry, True, transform_state=(entry.get("_transform_state") or "UNKNOWN")):
            return "VALIDATED_PREDICTIVE"
        if mu in UNUSED_MODEL_USE:
            return "COLLECTED_UNUSED"
        return "VERIFIED" if vc == "VERIFIED_COLLECTION" else "COLLECTED_UNVERIFIED"
    return "UNKNOWN"          # CODE_REFERENCE_ONLY, UNKNOWN, DERIVED (parents unaudited), NO_REFERENCE_FOUND


def input_stages(entry: dict, lineage: dict | None = None, static: dict | None = None, visible: dict | None = None) -> dict:
    """lineage: verified source->feature->model records for this (sport,input) from family_evidence.json (see _lineage_state)."""
    vc, col, mu = entry.get("verification_class", "UNKNOWN"), entry.get("collection", "UNKNOWN"), entry.get("model_use", "UNKNOWN")
    code = entry.get("code") or {}
    ev = entry.get("evidence") or []
    S = lambda state, why: {"state": state, "why": why}     # noqa: E731
    st = {}
    st["source"] = S("PASS", f"{len(ev)} evidence reference(s)") if ev else (S("FAIL", "no reliable source identified") if col == "NO_RELIABLE_SOURCE" else S("UNKNOWN", "no source evidence recorded"))
    if col == "PIT_ARCHIVED":
        st["archive"] = S("PASS", "point-in-time archive recorded")
    elif col in ("COLLECTED_NOT_PIT_ARCHIVED", "PARTIAL_OR_STALE"):
        st["archive"] = S("PARTIAL", "collected but not a complete point-in-time archive" if col != "PARTIAL_OR_STALE" else "partial or stale coverage")
    elif col in ("SOURCE_AVAILABLE_NOT_COLLECTED", "NO_RELIABLE_SOURCE"):
        st["archive"] = S("FAIL", "not collected by any collector")
    elif col == "DERIVED":
        st["archive"] = S("NA", "derived input: only as good as its parents (parents not audited)")
    else:
        st["archive"] = S("UNKNOWN", f"collection={col}")
    st["timestamp"] = S("PASS", "availability timestamps verified") if vc == "VERIFIED_COLLECTION" else (S("FAIL", "collected but point-in-time availability NOT verified") if vc in ("COLLECTED_UNVERIFIED_PIT", "STALE_OR_PARTIAL") else (S("FAIL", "nothing archived to timestamp") if vc == "MISSING" else S("UNKNOWN", "not assessed")))
    mf = code.get("model_files", 0)
    st["transform"] = _lineage_state(lineage, mf)
    if st["transform"]["state"] == "UNKNOWN" and static and static.get("static_consumption_candidate"):
        st["transform"] = {"state": "PARTIAL", "why": f"STATIC AST evidence only (not an executed lineage): {static['collector_files']} collector and {static['model_read_files']} model file(s) reference it in {static['repo']}@{static['commit'][:7]}"}
    st["consumption"] = (S("PARTIAL", "recorded as USED by the sport repo (repo-reported; not independently verified)") if mu == "USED" else S("PARTIAL", "model reads it partially") if mu == "USED_PARTIAL" else
                         S("PARTIAL", "research-only use") if mu == "RESEARCH_ONLY" else S("FAIL", "collected but model does not consume it") if mu == "COLLECTED_UNUSED" else
                         S("FAIL", "not collected, so not consumable") if mu == "NOT_COLLECTED" else S("UNKNOWN", "model use not established"))
    if mu in UNUSED_MODEL_USE and visible and visible.get("visible_in_output") and visible.get("evidence_kind") == "applied":
        st["consumption"] = {"state": "UNKNOWN", "why": f"CONTRADICTION: recorded {mu} but an applied input field is visible in the published projection; the record or the audit is wrong"}
    elif mu == "USED" and visible and visible.get("visible_in_output") and visible.get("evidence_kind") == "applied":
        st["consumption"] = {"state": "PASS", "why": f"recorded USED and input-derived field(s) populated/varying in the PUBLISHED projection ({', '.join(visible.get('visible_leaves') or [visible.get('field', '')])})"}
    elif st["consumption"]["state"] == "UNKNOWN" and visible and visible.get("visible_in_output"):
        st["consumption"] = {"state": "PARTIAL", "why": f"{visible.get('evidence_kind', 'unclassified')}-kind field(s) populated and varying in the PUBLISHED projection (an output or echoed value is not proof the input was used) ({', '.join(visible.get('visible_leaves') or [visible.get('field', '')])}); model not re-run, so correctness/causality unproven"}
    return st


def _lineage_state(lineage, model_files):
    """A model-file keyword hit is NOT a transformation. PASS needs a PRODUCTION lineage record naming source, feature code and
    model consumer AND an executed-run reference; a RESEARCH-scope record (e.g. an ablation script) is PARTIAL."""
    if lineage:
        need = ("source_ref", "feature_ref", "model_ref", "run_ref")
        if lineage.get("scope") == "PRODUCTION" and all(lineage.get(k) for k in need):
            return {"state": "PASS", "why": f"lineage verified: {lineage['source_ref']} -> {lineage['feature_ref']} -> {lineage['model_ref']} ({lineage['run_ref']})"}
        if lineage.get("scope") == "RESEARCH" and lineage.get("feature_ref"):
            return {"state": "PARTIAL", "why": f"research-only lineage ({lineage['feature_ref']}); not the production model"}
    if model_files:
        return {"state": "UNKNOWN", "why": f"{model_files} model file(s) mention it textually; no source-to-feature-to-model lineage record, so no transformation is claimed"}
    return {"state": "UNKNOWN", "why": "no lineage record and no model-code reference (absence is not proof of non-use)"}


def first_failure(stages: dict):
    for k in STAGES:
        if stages[k]["state"] != "PASS":
            return {"stage": k, "state": stages[k]["state"], "why": stages[k]["why"]}
    return None


def recompute_denominators(specs, master, cs, registry, readiness_file=None) -> dict:
    """Independent recount straight from raw artifacts (does not read essential_readiness.json for its numbers)."""
    fam_specs = specs["families"]
    master_ids = {f["id"] for f in master["families"]}
    spec_ids = set(fam_specs)
    inputs = {}
    for s, v in cs["sports"].items():
        for i, x in v["inputs"].items():
            inputs[(s, i)] = x
    distinct_ids = {i for (_, i) in inputs}
    reg_ids = {i for sp in registry["sports"].values() for i in sp["inputs"]} | set(registry["common_inputs"])
    cls = Counter(x["verification_class"] for x in inputs.values())
    dcls = {}
    for (s, i), x in inputs.items():           # distinct input ids: worst/first class wins deterministically (sorted by sport)
        dcls.setdefault(i, x["verification_class"])
    links = ver = 0
    fully = 0
    unclassified = 0
    per_sport = defaultdict(lambda: Counter())
    for key, f in fam_specs.items():
        ess = [i for i, t in f.get("drivers", {}).items() if t == "E"]
        v = 0
        for i in ess:
            x = inputs.get((f["sport"], i))
            if x is None:
                unclassified += 1
            v += bool(x and x["verification_class"] == "VERIFIED_COLLECTION")
        links += len(ess); ver += v
        per_sport[f["sport"]]["links"] += len(ess); per_sport[f["sport"]]["verified"] += v
        per_sport[f["sport"]]["families"] += 1
        if ess and v == len(ess):
            fully += 1; per_sport[f["sport"]]["fully_verified"] += 1
    rec = {
        "families_master_inventory": len(master_ids), "families_market_specs": len(spec_ids),
        "spec_only_not_in_master_inventory": sorted(spec_ids - master_ids), "master_not_in_specs": sorted(master_ids - spec_ids),
        "inputs_registry_distinct_ids": len(reg_ids), "inputs_sport_rows_in_collection_status": len(inputs), "inputs_distinct_ids_in_collection_status": len(distinct_ids),
        "inputs_in_registry_not_in_collection_status": sorted(reg_ids - distinct_ids), "inputs_in_collection_status_not_in_registry": sorted(distinct_ids - reg_ids),
        "class_counts_sport_rows": dict(cls), "class_counts_distinct_ids": dict(Counter(dcls.values())),
        "essential_links": links, "essential_links_verified": ver, "families_with_all_essentials_verified": fully, "unclassified_links": unclassified,
        "per_sport": {s: dict(c) for s, c in per_sport.items()},
    }
    n_rows, n_ids = len(inputs), len(distinct_ids)
    cr_rows, cr_ids = cls.get("CODE_REFERENCE_ONLY", 0), rec["class_counts_distinct_ids"].get("CODE_REFERENCE_ONLY", 0)
    rec["reconciliation_notes"] = [
        f"{len(master_ids)} = discovered families in master_inventory; {len(spec_ids)} = market_specs families = {len(master_ids)} + {len(spec_ids - master_ids)} spec-only blueprints ({', '.join(sorted(spec_ids - master_ids))}) not observed on Kalshi. None removed.",
        f"'285 inputs' is the BASELINE sport-input row count (docs/OVERNIGHT_REPORT.md). Authoritative rows are {n_rows}, holding {n_ids} DISTINCT input ids (cross-sport m.* ids repeat per sport).",
        f"'118 code-reference-only' (PR #8 text) vs recount: {cr_rows} sport-rows / {cr_ids} distinct ids in the committed artifact. The artifact is authoritative; no input was hidden or deleted to reach either number.",
        f"{ver}/{links} essential links verified and {fully} fully-verified families are recounted from raw artifacts."]
    if readiness_file is not None:
        r = readiness_file
        tot = sum(d["ALL"]["required"] for d in r["sports"].values()); vv = sum(d["ALL"]["verified"] for d in r["sports"].values())
        ff = sum(d["FAMILIES"]["fully_verified"] for d in r["sports"].values())
        rec["committed_essential_readiness"] = {"links": tot, "verified": vv, "fully_verified": ff, "agrees_with_recount": (tot, vv, ff) == (links, ver, fully)}
    return rec


def projection_evidence(fkey, f, mv, intel, audits):
    s, nat = f["sport"], f["native_family"]
    k = MV_MAP.get(s, {}).get(nat)
    if k and k in mv.get("sports", {}).get(s, {}).get("families", {}):
        e = mv["sports"][s]["families"][k]
        ready = e.get("readiness")
        return {"state": "REPO_REPORTED_" + ("READY" if ready == "READY" else "NOT_READY"), "model": e.get("model"), "reported_readiness": ready,
                "evidence": f"model_validation.json:{s}.{k}", "independently_reproduced": False}
    if fkey in intel:
        v = intel[fkey]["validation"]
        return {"state": "RESEARCH_WALK_FORWARD", "verdict": v.get("verdict"), "n_eval": v.get("n_eval"), "evidence": f"intel/{fkey.replace('/', '_')}", "independently_reproduced": True}
    lk = f"{s}/{nat.lower()}"
    if lk in audits:
        return {"state": "SPEC_ONLY", "evidence": audits[lk]["file"], "settles_on": audits[lk]["settles_on"], "independently_reproduced": False}
    return {"state": "NONE_FOUND", "evidence": None, "independently_reproduced": False}


def _rules_ok(fkey, f, inputs):
    """Family-specific rules evidence: the family itself links m.rules_text AND that input is verified collection."""
    s = f["sport"]
    linked = "m.rules_text" in f.get("drivers", {})
    rec = inputs.get(f"{s}:m.rules_text")
    return linked, bool(linked and rec and rec["verification_class"] == "VERIFIED_COLLECTION")


def market_mapping_stage(fkey, f, mi, inputs, orientation):
    """PASS needs ALL of: (identity) observed listing with archived series tickers, (rules) family-linked verified rules text plus a
    sampled contract text, (orientation) a recorded settles-on/strike-direction statement. Anything less is PARTIAL; an unobserved
    blueprint is FAIL. Missing rule linkage can never pass vacuously."""
    ident = bool(mi and mi.get("series_sample") and mi["observed"]["state"] in ("OBSERVED_NOW", "OBSERVED_PRIOR_SNAPSHOT_ONLY", "OBSERVED_SETTLED_ONLY"))
    linked, verified = _rules_ok(fkey, f, inputs)
    text = bool(mi and mi["settlement"]["status"] == "SAMPLED_CONTRACT_TEXT")
    rules = verified and text
    if not orientation and text:       # orientation derived ONLY from a sampled contract text that states the Yes condition
        orientation = bool(re.search(r"resolves? to (yes|no)\b", mi["settlement"].get("text") or "", re.I))
    parts = {"identity": ident, "rules": rules, "orientation": bool(orientation)}
    if not mi or f["status"] == "SPECIFIED_UNOBSERVED" or not ident and not linked:
        state = "FAIL" if f["status"] == "SPECIFIED_UNOBSERVED" or not mi else "PARTIAL"
    else:
        state = "PASS" if all(parts.values()) else "PARTIAL"
    missing = [k for k, v in parts.items() if not v]
    return {"state": state, "why": "identity/rules/orientation all evidenced" if not missing else f"missing evidence: {', '.join(missing)} (rules linked={linked}, verified={verified}, sampled text={text})", "parts": parts}


OUTPUT_FAMILIES = {"CBB": {"TOTAL": "projection.total", "GAME_WINNER": "projection.home_win_prob", "SPREAD": "projection.margin", "TEAM_TOTAL": "projection.home_score/away_score"},
                   "NFL": {"PLAYER_STAT": "forecasts: receiving/rushing/passing player stat distributions"}}


def attach_output(proj, fkey, f, outs):
    """Link a family to an actual PUBLISHED projection output (file + freshness) when one exists. Never sets independently_reproduced."""
    s, nat = f["sport"], f["native_family"]
    d = outs.get(s) if isinstance(outs, dict) else None
    if not isinstance(d, dict):
        return proj
    src = d.get("source", {})
    ref = f"{src.get('repo')}@{str(src.get('commit'))[:7]}:{src.get('path') or src.get('branch')}"
    if s == "NBA" and nat in MV_MAP["NBA"] and MV_MAP["NBA"][nat] in (d.get("by_family") or {}):
        return dict(proj, output_ref=ref, fresh_asof=d.get("data_asof_utc"), output_n=(d.get("by_family") or {}).get(MV_MAP["NBA"].get(nat)), published=True, independently_reproduced=False)
    if s == "NHL" and nat in MV_MAP["NHL"] and MV_MAP["NHL"][nat] in (d.get("by_family") or {}):
        return dict(proj, output_ref=ref, fresh_asof=d.get("data_asof_utc"), output_n=(d.get("by_family") or {}).get(MV_MAP["NHL"][nat]), published=True, independently_reproduced=False)
    if s in OUTPUT_FAMILIES and nat in OUTPUT_FAMILIES[s]:
        asof = (d.get("generated_range") or [None, None])[1] or d.get("generated_utc")
        base = proj if proj["state"] != "NONE_FOUND" else {"state": "PUBLISHED_OUTPUT", "independently_reproduced": False, "evidence": None}
        return dict(base, output_ref=ref, fresh_asof=asof, published=True, independently_reproduced=False, output_field=OUTPUT_FAMILIES[s][nat])
    return proj


def historical_stage(proj):
    ie = proj.get("independent_evaluation")
    if ie and ie.get("verdict") == "CHALLENGER_BETTER":
        return {"state": "PASS", "why": f"independent chronological evaluation of ARCHIVED forecasts vs ESPN final box scores: challenger beats the incumbent model (n={ie['n_paired']} paired player-games, Bonferroni CI {ie['ci_bonferroni']}, positive in both halves and leave-one-player-out); NO market-price baseline, so this is predictive accuracy, not edge"}
    if ie:
        return {"state": "PARTIAL", "why": f"independent evaluation exists but verdict {ie['verdict'].lower()}: baseline {ie['baseline']}"}
    if proj["state"] == "RESEARCH_WALK_FORWARD":
        v = proj.get("verdict")
        return {"state": "PARTIAL" if v == "SUPPORTED" else "FAIL" if v == "NOT_SUPPORTED" else "UNKNOWN", "why": f"{v} n={proj.get('n_eval')}; no market-price baseline"}
    if proj["state"].startswith("REPO_REPORTED"):
        return {"state": "PARTIAL", "why": "repo-reported, not independently reproduced"}
    return {"state": "UNKNOWN", "why": "no historical evaluation recorded"}


def outcomes_stage(fkey, f, inputs, evidence):
    """PASS needs a family-specific, evidence-linked outcome join (ticker -> settled value -> period/void handling) recorded in
    family_evidence.json['outcome_joins'] AND verified family rules. Sport-level settlement archives alone give at most PARTIAL."""
    s = f["sport"]
    rec = inputs.get(f"{s}:m.settlement_truth")
    linked = "m.settlement_truth" in f.get("drivers", {})
    rl, rv = _rules_ok(fkey, f, inputs)
    join = (evidence.get("outcome_joins") or {}).get(fkey)
    if not linked or rec is None:
        return {"state": "UNKNOWN", "why": "family does not link m.settlement_truth"}
    if join and join.get("verified") and join.get("evidence_ref") and rv and rec["verification_class"] == "VERIFIED_COLLECTION":
        return {"state": "PASS", "why": f"family-specific join verified: {join['evidence_ref']}"}
    base = {"VERIFIED_COLLECTION": "sport-level settlement archive verified", "COLLECTED_UNVERIFIED_PIT": "sport-level settlement collected, unverified"}.get(rec["verification_class"], f"settlement class {rec['verification_class']}")
    state = "PARTIAL" if rec["verification_class"] in ("VERIFIED_COLLECTION", "COLLECTED_UNVERIFIED_PIT", "STALE_OR_PARTIAL") else ("FAIL" if rec["verification_class"] == "MISSING" else "UNKNOWN")
    return {"state": state, "why": f"{base}; NO family-specific outcome join evidence (rules linked={rl}, verified={rv})"}


def projection_stage(proj, mapping_state):
    """PASS needs: independently reproduced model evidence, an actual projection output record, a PASSing market mapping and a valid
    freshness timestamp. A repo-reported readiness flag proves none of those."""
    ok = proj.get("independently_reproduced") and proj.get("output_ref") and proj.get("fresh_asof") and mapping_state == "PASS"
    if ok:
        return {"state": "PASS", "why": "reproduced, output present, fresh, mapped"}
    if proj.get("published"):
        return {"state": "PARTIAL", "why": f"published output exists ({proj['output_ref']}, as of {proj['fresh_asof']}) but it is not independently reproduced"}
    why = {"NONE_FOUND": "no projection or validation evidence found", "SPEC_ONLY": "audit/spec only; no projection output",
           "RESEARCH_WALK_FORWARD": "independently reproduced research walk-forward only; no production output record or freshness evidence",
           }.get(proj["state"], "repo-reported readiness only: not reproduced, no output/freshness evidence linked here")
    return {"state": "FAIL" if proj["state"] == "NONE_FOUND" else "PARTIAL", "why": why}


def build():
    specs, master, cs = _j(A / "market_specs.json"), _j(A / "master_inventory.json"), _j(A / "collection_status.json")
    registry, mv, ready = _j(A / "input_registry.json"), _j(A / "model_validation.json"), _j(A / "essential_readiness.json")
    intel = {}
    for p in sorted((A / "intel").glob("*.json")):
        d = _j(p)
        intel[f"{d['sport']}/{d['market_family']}"] = d
    audits = {}
    for p in sorted((A / "audits").glob("*.json")):
        d = _j(p)
        audits[f"{d['sport']}/{str(d['market_family']).lower()}"] = {"file": f"audits/{p.name}", "settles_on": d.get("settles_on")}
    ablation = {}
    for fk, fn in ABLATION_FILES.items():
        if (OUT / fn).exists():
            ablation[fk] = _j(OUT / fn)
    master_ids = {f["id"] for f in master["families"]}
    mi_by_id = {f["id"]: f for f in master["families"]}
    static = _j(OUT / "model_use_static.json")["inputs"] if (OUT / "model_use_static.json").exists() else {}
    outs = _j(OUT / "projection_outputs.json") if (OUT / "projection_outputs.json").exists() else {}
    nbaev = _j(OUT / "NBA_forecast_eval.json") if (OUT / "NBA_forecast_eval.json").exists() else {}
    nfltot = _j(OUT / "NFL_totals_incremental.json") if (OUT / "NFL_totals_incremental.json").exists() else {}
    paths = _j(OUT / "pricing_paths.json")["families"] if (OUT / "pricing_paths.json").exists() else {}
    vis = {}
    for sp, d in outs.items():
        if isinstance(d, dict):
            for iid, v in (d.get("input_visibility") or {}).items():
                vis[f"{sp}:{iid}"] = v
    evidence = _j(OUT / "family_evidence.json") if (OUT / "family_evidence.json").exists() else {}
    # ---- input level (sport x input)
    inputs = {}
    cs_raw = cs
    svs = (_j(OUT / "source_verifications.json")["inputs"] if (OUT / "source_verifications.json").exists() else {})
    cs = dict(cs); cs["sports"] = {sp: dict(v, inputs={i: apply_source_verification(x, svs.get(f"{sp}:{i}")) for i, x in v["inputs"].items()}) for sp, v in cs["sports"].items()}
    for s, v in cs["sports"].items():
        for i, x in v["inputs"].items():
            st = input_stages(x, (evidence.get("lineage") or {}).get(f"{s}:{i}"), static.get(f"{s}:{i}"), vis.get(f"{s}:{i}"))
            inputs[f"{s}:{i}"] = {"sport": s, "input": i, "label": x["label"], "status": input_status(x), "collection": x["collection"], "verification_class": x["verification_class"],
                                  "model_use": x["model_use"], "stages": st, "first_failure": first_failure(st), "derived": x["verification_class"] == "DERIVED", "note": x["note"], "evidence": x["evidence"],
                                  "static_use": ({k: static[f"{s}:{i}"][k] for k in ("repo", "commit", "collector_files", "model_read_files", "test_files", "refs")} if f"{s}:{i}" in static else None),
                                  "output_visibility": vis.get(f"{s}:{i}"), "source_verification": x.get("_source_verification")}
    # ---- family level
    fams = {}
    for key, f in specs["families"].items():
        s = f["sport"]
        validated = set()
        if key in ablation:
            for var, ent in ablation[key]["variants"].items():
                if rederive_ablation_verdict(ablation[key], var) == "ELIGIBLE" and var in ABLATION_INPUT and ablation[key].get("family") == key:
                    validated.add(ABLATION_INPUT[var])
        proj = projection_evidence(key, f, mv, intel, audits)
        proj = attach_output(proj, key, f, outs)
        ev = (nbaev.get("families") or {}).get(MV_MAP.get("NBA", {}).get(f["native_family"], "")) if s == "NBA" else None
        if ev and ev.get("paired_vs_incumbent"):
            pv = ev["paired_vs_incumbent"]
            proj = dict(proj, independent_evaluation={"ref": "verification/NBA_forecast_eval.json", "n_paired": pv["n"], "verdict": pv["verdict"], "mae_improvement_mean": pv["mae_improvement_mean"], "ci_bonferroni": pv["ci_bonferroni"], "baseline": "existing (incumbent) model; NO market-price baseline"})
        elif ev:
            proj = dict(proj, independent_evaluation={"ref": "verification/NBA_forecast_eval.json", "n_paired": 0, "verdict": "NO_BASELINE", "baseline": "none archived for this family"})
        if nfltot and key == nfltot.get("family"):
            gv = [g["verdict"] for g in nfltot["groups"].values()]
            proj = dict(proj, independent_evaluation={"ref": "verification/NFL_totals_incremental.json", "n_paired": nfltot["n_test_games"], "n_groups": len(gv),
                                                      "verdict": "INCREMENTAL_GAIN_VALIDATED" if "VALIDATED_INCREMENTAL" in gv else "NOT_DEMONSTRATED_VS_MARKET_UNDERPOWERED",
                                                      "group_verdicts": {v: gv.count(v) for v in sorted(set(gv))},
                                                      "baseline": "market line (near-close consensus, not point-in-time); NO Kalshi price baseline; game totals only"})
        orientation = proj.get("settles_on") if proj["state"] == "SPEC_ONLY" else (evidence.get("orientation") or {}).get(key)
        rows, counts = [], {"E": Counter(), "C": Counter(), "X": Counter()}
        drivers = dict(f.get("drivers", {}))
        origin = {i: "market_specs" for i in drivers}
        for i, (tier, _why) in OVERLAY.get(key, {}).items():
            if i not in drivers:
                drivers[i] = tier; origin[i] = "overlay"
        for i, tier in sorted(drivers.items()):
            rec = inputs.get(f"{s}:{i}")
            if rec is None:
                rows.append({"input": i, "tier": tier, "origin": origin[i], "status": "UNKNOWN", "first_failure": {"stage": "source", "state": "UNKNOWN", "why": "input not in collection_status for this sport (never borrowed from another sport)"}})
                counts[tier]["UNKNOWN"] += 1
                continue
            ent = cs["sports"][s]["inputs"][i]
            stt = "VALIDATED_PREDICTIVE" if i in validated and may_validate(ent, True, family_match=True, transform_state=rec["stages"]["transform"]["state"]) else rec["status"]
            pp = (paths.get(key, {}).get("inputs") or {}).get(i)
            rows.append({"input": i, "tier": tier, "origin": origin[i], "status": stt, "first_failure": rec["first_failure"], "pricing_path": pp["state"] if pp else None, "pricing_path_refs": (pp or {}).get("refs", [])[:2]})
            counts[tier][stt] += 1
        mapping = market_mapping_stage(key, f, mi_by_id.get(key), inputs, orientation)
        fam_stage = {
            "market_mapping": mapping,
            "projection": projection_stage(proj, mapping["state"]),
            "historical_eval": historical_stage(proj),
            "outcomes": outcomes_stage(key, f, inputs, evidence),
        }
        ess = [r for r in rows if r["tier"] == "E"]
        fams[key] = {"sport": s, "family": f["native_family"], "markets_now": f.get("markets_now"), "spec_status": f["status"], "in_master_inventory": key in master_ids,
                     "inputs": rows, "counts_by_tier": {t: dict(c) for t, c in counts.items()}, "stages": fam_stage, "projection": proj,
                     "essential_verified": sum(r["status"] in ("VERIFIED", "VALIDATED_PREDICTIVE") for r in ess), "essential_total": len(ess), "essential_chain_complete": sum(1 for r in ess if r["status"] in ("VERIFIED", "VALIDATED_PREDICTIVE") and r["first_failure"] is None),
                     "essential_legacy_verified": sum(inputs.get(f"{s}:{r['input']}", {}).get("verification_class") == "VERIFIED_COLLECTION" for r in ess),
                     "ablation": f"verification/{ABLATION_FILES[key]}" if key in ablation else None,
                     "pricing_path": ({k: paths[key][k] for k in ("repo", "commit", "path_globs", "n_files", "files_total_lines")} if key in paths else None)}
    return {"specs": specs, "master": master, "cs": cs, "cs_raw": cs_raw, "registry": registry, "ready": ready, "inputs": inputs, "fams": fams, "intel": intel, "ablation": ablation}


def repair_tasks(ctx) -> list[dict]:
    ledger = _j(OUT / "repair_ledger.json") if (OUT / "repair_ledger.json").exists() else {}
    """One task per (sport, input) that blocks essential links; ordered by markets affected. Reproducible, never 'resolved' here."""
    by = defaultdict(lambda: {"families": [], "markets": 0, "essential_in": []})
    for fk, f in ctx["fams"].items():
        for r in f["inputs"]:
            if r["tier"] != "E" or r["status"] in ("VERIFIED", "VALIDATED_PREDICTIVE"):
                continue
            b = by[(f["sport"], r["input"])]
            b["families"].append(fk); b["markets"] += f["markets_now"] or 0
            if r.get("pricing_path") == "NOT_FOUND_IN_PRICING_PATH":
                b.setdefault("not_in_path", []).append(fk)
    tasks = []
    for (s, i), b in by.items():
        rec = ctx["inputs"].get(f"{s}:{i}")
        if rec is None:
            continue
        ff = rec["first_failure"] or {}
        kind = {"archive": "COLLECT_OR_ARCHIVE", "timestamp": "PROVE_POINT_IN_TIME_AVAILABILITY", "source": "IDENTIFY_SOURCE", "transform": "AUDIT_FEATURE_TRANSFORM", "consumption": "WIRE_INTO_MODEL"}.get(ff.get("stage"), "REVIEW")
        if rec["status"] == "UNSUPPORTED":
            kind = "BLOCKED_NO_RELIABLE_SOURCE"
        led = (ledger.get("entries") or {}).get(f"{s}:{i}")
        tasks.append({"id": f"{s}:{i}", "disposition": ({k: led[k] for k in ("state", "found", "remaining", "next", "searched")} if led else None), "sport": s, "input": i, "status": rec["status"], "kind": kind, "defect": ff, "families_affected": sorted(b["families"]), "n_families": len(b["families"]),
                      "markets_affected": b["markets"], "not_in_pricing_path_families": sorted(b.get("not_in_path", [])), "existing_evidence": rec["evidence"], "note": rec["note"], "state": "OPEN",
                      "rules": ["do not backfill with information unavailable before the event", "observed_at must be capture time, never batch/backfill time",
                                "re-run `python -m alpha_engine.verification_engine` after any repair; status must change only via recorded evidence"]})
    return sorted(tasks, key=lambda t: (-t["markets_affected"], t["id"]))


def summarize(ctx, rec) -> dict:
    per = {}
    for s in ctx["cs"]["sports"]:
        c = Counter(v["status"] for v in ctx["inputs"].values() if v["sport"] == s)
        fam = [f for f in ctx["fams"].values() if f["sport"] == s]
        el = sum(f["essential_total"] for f in fam)
        before = Counter(input_status(x) for x in ctx["cs_raw"]["sports"][s]["inputs"].values())
        per[s] = {"inputs_by_status": dict(c), "inputs_by_status_before_measured_evidence": dict(before), "families": len(fam), "markets_now": sum(f["markets_now"] or 0 for f in fam),
                  "essential_links": el, "essential_legacy_verified": sum(f["essential_legacy_verified"] for f in fam),
                  "essential_collection_verified": sum(f["essential_verified"] for f in fam), "essential_chain_complete": sum(f["essential_chain_complete"] for f in fam),
                  "families_projection": dict(Counter(f["projection"]["state"] for f in fam)),
                  "families_all_essentials_collection_verified": sum(1 for f in fam if f["essential_total"] and f["essential_verified"] == f["essential_total"])}
    return {"schema_version": "verification-1.0", "statuses": STATUSES, "stages": STAGES, "family_stages": FAMILY_STAGES,
            "definitions": {"VERIFIED": "COLLECTION verified (point-in-time availability) and not recorded as unused. Says nothing about lineage or consumption: see essential_chain_complete", "COLLECTED_UNVERIFIED": "collected but availability timestamps not verified",
                            "COLLECTED_UNUSED": "collected but recorded as not consumed by any model", "STALE": "partial or stale coverage", "MISSING": "source exists, not collected",
                            "UNSUPPORTED": "no reliable source found", "UNKNOWN": "no evidence recorded (includes code-reference-only and derived)",
                            "VALIDATED_PREDICTIVE": "survived Bonferroni-adjusted chronological ablation vs a no-information baseline; NOT proof of an executable after-fee edge"},
            "reconciliation": rec, "sports": per, "totals": {"inputs_by_status": dict(Counter(v["status"] for v in ctx["inputs"].values())),
                                                             "validated_predictive_links": sum(1 for f in ctx["fams"].values() for r in f["inputs"] if r["status"] == "VALIDATED_PREDICTIVE")}}


def run(write=True):
    ctx = build()
    rec = recompute_denominators(ctx["specs"], ctx["master"], ctx["cs_raw"], ctx["registry"], ctx["ready"])
    tasks = repair_tasks(ctx)
    summ = summarize(ctx, rec)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(json.dumps(summ, indent=1, sort_keys=True) + "\n")
        (OUT / "inputs.json").write_text(json.dumps({"schema_version": "verification-1.0", "inputs": ctx["inputs"]}, indent=0, sort_keys=True) + "\n")
        (OUT / "families.json").write_text(json.dumps({"schema_version": "verification-1.0", "families": ctx["fams"]}, indent=0, sort_keys=True) + "\n")
        (OUT / "repair_tasks.json").write_text(json.dumps({"schema_version": "verification-1.0", "n": len(tasks), "tasks": tasks}, indent=0, sort_keys=True) + "\n")
    return ctx, rec, tasks, summ


if __name__ == "__main__":  # pragma: no cover
    ctx, rec, tasks, summ = run()
    print(json.dumps({k: rec[k] for k in rec if k not in ("per_sport",)}, indent=1)[:3500])
    print(json.dumps(summ["totals"], indent=1)); print("repair tasks", len(tasks))

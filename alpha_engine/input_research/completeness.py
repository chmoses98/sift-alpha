"""Catalog-completeness review layer and acceptance gate (RESEARCH_ONLY).

Purpose: decide, per market archetype, *what information is needed to evaluate it* before any model is optimised against an incomplete input set.
This module never concludes that a catalog is "complete". It (1) validates the structure and the internal consistency of a mechanism-level review,
(2) mechanically checks claims that can be checked (quoted contract text must be a verbatim substring of the sampled Kalshi rules; referenced tickers must be in the
series ledger; every pre-existing archetype input must have been individually audited; boilerplate text across archetypes is detected), (3) requires an independent
second review with no open BLOCKER/MAJOR finding, and (4) tops out at READY_FOR_USER_APPROVAL. A populated list or a passing check is necessary, never sufficient:
only `approval.json` (written by a human decision, never by code) can mark anything approved.

Files (all under research/input_research/completeness/):
  evidence/<SPORT>.json     derived working packs (existing catalog entry + live series + sampled contract rules) given to reviewers
  reviews/<SPORT>*.json     {archetype_key: review record}   key = archetype name, or "unreg:<name>" for unregistered contract types
  independent/<SPORT>.json  {archetype_key: {"reviewer","date","verdict","findings":[{id,severity,text,resolution}]}}
  gate.json / summary.json  derived by `python -m alpha_engine.input_research.completeness`
  approval.json             human decision record (code never writes "approved")
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from . import catalog as cat

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "research/input_research"
CD = IN / "completeness"
SPORTS = list(cat.SPORTS)
LEDGER = IN / "market_universe/series_ledger.json"
RULES = IN / "market_universe/contract_rules_sample.json"

# What can determine an outcome. Every archetype must say, for each, COVERED (with input ids), NOT_APPLICABLE (with a reason) or GAP (an explicit open hole).
TAXONOMY = {
    "talent_strength": "underlying team/player ability, opponent-adjusted, with the right memory and shrinkage",
    "opponent_matchup": "how this specific opponent/unit/surface/style interacts with the subject",
    "role_personnel": "who is on the field/court/ice/pitch, role, lineup, depth chart, usage allocation",
    "availability_news": "injury/rest/suspension/lineup status and its timing (point-in-time vintage)",
    "coaching_scheme": "coach tendencies, scheme, tactics, play-calling, rotation and substitution patterns",
    "environment": "venue, weather, altitude, surface, travel, time zone, crowd, officials' conditions",
    "game_context_script": "expected game flow: score state, blowout/garbage time, pace of play, leverage, clock, overtime/extra-time",
    "pace_volume": "number of opportunities (possessions, attempts, plate appearances, serve points) the outcome is counted over",
    "efficiency_conversion": "rate per opportunity (shooting, finishing, save, conversion, hold) including luck-vs-skill split",
    "distribution_variance": "shape of the outcome distribution: overdispersion, tails, discreteness, correlation between components",
    "situational_schedule_motivation": "rest, congestion, stakes, rivalry, clinched/eliminated status, rotation incentives, fatigue",
    "officiating_rules": "officials' tendencies and rule/format details that change the outcome process",
    "settlement_contract": "exact resolution wording: period covered, OT/ET/penalties, voids/DNP, rounding, data source of truth, strike construction",
}
CAT_STATUS = ("COVERED", "NOT_APPLICABLE", "GAP")
INTERACTION_FORMS = ("multiplicative", "threshold", "saturating", "convex", "concave", "piecewise", "conditional", "joint-distribution", "regime-switch", "diminishing-returns", "other-nonlinear")
VERDICTS = ("KEEP_PRIMARY", "KEEP_SECONDARY", "KEEP_CONTEXT", "WEAK", "IRRELEVANT", "BENCHMARK_ONLY")  # or "DUPLICATE_OF:<input id>"
RULES_VERIF = ("VERIFIED_FROM_RULES_TEXT", "PARTIALLY_VERIFIED", "NOT_VERIFIED_NO_RULES_TEXT", "NO_LIVE_SERIES")
UNRESOLVED_TYPES = ("MECHANISM_UNCERTAIN", "CONTRACT_AMBIGUOUS", "DATA_UNAVAILABLE", "INPUT_DEFINITION_UNCERTAIN", "SOURCE_UNVERIFIED", "OTHER")
ACCESS = ("free", "free_scrape", "free_limited", "paid", "own_capture", "unavailable_public", "derived")
SEVERITY = ("BLOCKER", "MAJOR", "MINOR")
NEW_INPUT_REQUIRED = ("label", "category", "mechanism", "rationale", "measurement", "pregame_knowable", "free_sources", "registry_ids", "raw_data", "why", "role")
STATUSES = ("NOT_STARTED", "STRUCTURE_INCOMPLETE", "AUTHORED_NOT_INDEPENDENTLY_REVIEWED", "INDEPENDENT_REVIEW_OPEN_FINDINGS", "READY_FOR_USER_APPROVAL")


def rd(p):
    return json.loads(Path(p).read_text())


def _txt(x, n):
    return isinstance(x, str) and len(x.strip()) >= n


def arch_keys(c: dict) -> list[str]:
    return list(c["archetypes"]) + ["unreg:" + k for k in (c.get("unregistered_archetypes") or {})]


def arch_entry(c: dict, key: str) -> dict:
    return (c.get("unregistered_archetypes") or {})[key[6:]] if key.startswith("unreg:") else c["archetypes"][key]


def ledger_by_archetype() -> dict[tuple[str, str], list[dict]]:
    out = collections.defaultdict(list)
    for r in rd(LEDGER)["rows"]:
        out[(r["sport"], r["archetype"])].append(r)
    return out


def build_evidence() -> dict[str, int]:
    """Working packs for reviewers; derived only from committed artifacts."""
    led = ledger_by_archetype()
    rules = rd(RULES) if RULES.exists() else {}
    (CD / "evidence").mkdir(parents=True, exist_ok=True)
    n = {}
    for s in SPORTS:
        c = cat.load(s)
        pack = {}
        for k in arch_keys(c):
            a = arch_entry(c, k)
            rows = led.get((s, k), [])
            pack[k] = {
                "sport": s, "key": k, "registered": not k.startswith("unreg:"), "label": a["label"], "blueprint": a["blueprint"], "families": a.get("families"), "contract_types": a.get("contract_types"),
                "target": a["target"], "existing_mechanism": a["mechanism"],
                "existing_inputs": [{"id": i["id"], "role": i.get("role"), "why": i["why"], "label": c["inputs"][i["id"]]["label"], "category": c["inputs"][i["id"]]["category"], "pregame_knowable": c["inputs"][i["id"]]["pregame_knowable"]} for i in a["inputs"]],
                "existing_interactions": a["interactions"],
                "live_series": [{"ticker": r["ticker"], "title": r["title"], "type": r.get("type"), "period": r.get("period"), "evidence": r["evidence"], "status": r["status"]} for r in rows],
                "rules_samples": {r["ticker"]: rules[r["ticker"]] for r in rows if r["ticker"] in rules and rules[r["ticker"]].get("rules_primary")},
            }
        (CD / "evidence" / f"{s}.json").write_text(json.dumps(pack, indent=1, sort_keys=True))
        n[s] = len(pack)
    return n


def load_reviews(sport: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted((CD / "reviews").glob(f"{sport}*.json")) if (CD / "reviews").exists() else []:
        out.update(rd(f))
    return out


def load_independent(sport: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted((CD / "independent").glob(f"{sport}*.json")) if (CD / "independent").exists() else []:
        out.update(rd(f))
    return out


def _shingles(text: str, n: int = 5) -> set[str]:
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def _inputs_defined(c: dict, rec: dict) -> set[str]:
    return set(c["inputs"]) | set((rec.get("new_inputs") or {}))


def validate_review(sport: str, key: str, rec: dict, c: dict, rules: dict, led_rows: list[dict]) -> list[str]:
    """Structural + mechanically checkable claims. Empty list == structure passes (which is NOT a statement of completeness)."""
    e: list[str] = []
    a = arch_entry(c, key)
    known = _inputs_defined(c, rec)
    for k in ("contract", "mechanism", "input_audit", "interactions", "nonlinearities", "required_data", "unresolved", "reviewer", "review_date"):
        if k not in rec:
            e.append(f"missing {k}")
    if e:
        return e
    # --- contract -------------------------------------------------------------------------------------------------------------------------------------------
    ct = rec["contract"]
    tick = {r["ticker"] for r in led_rows}
    if not _txt(ct.get("settlement_definition"), 120):
        e.append("contract.settlement_definition must state what settles YES (period, overtime/extra time, DNP/void, ties, source of truth) in >=120 chars")
    if ct.get("rules_verification") not in RULES_VERIF:
        e.append(f"contract.rules_verification must be one of {RULES_VERIF}")
    if not led_rows and ct.get("rules_verification") != "NO_LIVE_SERIES":
        e.append("archetype has no live series in the ledger: rules_verification must be NO_LIVE_SERIES")
    if led_rows and ct.get("rules_verification") == "NO_LIVE_SERIES":
        e.append("archetype has live series: rules_verification cannot be NO_LIVE_SERIES")
    if not isinstance(ct.get("variants_and_edge_cases"), list) or len(ct["variants_and_edge_cases"]) < 2:
        e.append("contract.variants_and_edge_cases needs >=2 concrete items (ties, OT, void, DNP, strike construction, ...)")
    ev = ct.get("rules_evidence") or []
    for x in ev:
        t = x.get("ticker")
        if t not in tick:
            e.append(f"rules_evidence ticker {t!r} is not a ledger series of this archetype"); continue
        samp = rules.get(t) or {}
        blob = " ".join([str(samp.get("rules_primary") or ""), str(samp.get("rules_secondary") or ""), str(samp.get("title") or "")])
        q = " ".join(str(x.get("quote", "")).split())
        if len(q) < 25 or q not in " ".join(blob.split()):
            e.append(f"rules_evidence quote for {t} is not a verbatim substring (>=25 chars) of the sampled rules text")
        if not _txt(x.get("establishes"), 30):
            e.append(f"rules_evidence for {t} must say what the quote establishes")
    if ct.get("rules_verification") in ("VERIFIED_FROM_RULES_TEXT", "PARTIALLY_VERIFIED"):
        have = {t for t in tick if rules.get(t, {}).get("rules_primary")}
        if not have:
            e.append("claims rules verification but no rules text exists for any series of this archetype")
        if len({x.get("ticker") for x in ev}) < min(2, len(have)):
            e.append("rules verification needs rules_evidence quotes from >=2 distinct series (or all that exist)")
    if ct.get("rules_verification") == "NOT_VERIFIED_NO_RULES_TEXT" and any(rules.get(t, {}).get("rules_primary") for t in tick):
        e.append("rules text exists for this archetype's series; it must be read (VERIFIED/PARTIALLY_VERIFIED)")
    # --- mechanism ------------------------------------------------------------------------------------------------------------------------------------------
    m = rec["mechanism"]
    if not _txt(m.get("summary"), 300):
        e.append("mechanism.summary must be a substantive >=300 char derivation of how the outcome is generated, written from first principles")
    stages = m.get("stages") or []
    if len(stages) < 3:
        e.append("mechanism.stages needs >=3 stages of the outcome-generating process")
    sids = set()
    for s in stages:
        sid = s.get("id", "?"); sids.add(sid)
        if not _txt(s.get("description"), 200):
            e.append(f"stage {sid}: description must be >=200 chars")
        if not _txt(s.get("distribution"), 40):
            e.append(f"stage {sid}: distribution (shape / variance source / discreteness) must be stated")
        if not s.get("input_ids"):
            e.append(f"stage {sid}: no input_ids (if the stage has no input, that is a GAP and must be listed in unresolved and as a new input)")
        for i in s.get("input_ids") or []:
            if i not in known:
                e.append(f"stage {sid}: unknown input {i!r}")
        bad = [x for x in s.get("categories") or [] if x not in TAXONOMY]
        if bad or not s.get("categories"):
            e.append(f"stage {sid}: categories must be drawn from the taxonomy (bad: {bad})")
    cc = m.get("category_coverage") or {}
    for t in TAXONOMY:
        r = cc.get(t)
        if not r or r.get("status") not in CAT_STATUS:
            e.append(f"category_coverage.{t} missing or status not in {CAT_STATUS}"); continue
        if r["status"] == "COVERED" and (not r.get("input_ids") or any(i not in known for i in r["input_ids"])):
            e.append(f"category_coverage.{t}: COVERED needs known input_ids")
        if r["status"] in ("NOT_APPLICABLE", "GAP") and not _txt(r.get("note"), 60):
            e.append(f"category_coverage.{t}: {r['status']} needs a >=60 char specific reason")
        if r["status"] == "GAP" and not any(u.get("category") == t for u in rec.get("unresolved") or []):
            e.append(f"category_coverage.{t}: GAP must also appear in unresolved with category={t}")
    # --- new inputs -----------------------------------------------------------------------------------------------------------------------------------------
    for iid, ni in (rec.get("new_inputs") or {}).items():
        p = f"new_input {iid}"
        if iid in c["inputs"]:
            # idempotent after merge_new_inputs: allowed only if the catalog definition is exactly the one this review wrote
            if any(c["inputs"][iid].get(x) != ni.get(x) for x in ("label", "category", "mechanism", "rationale", "measurement", "pregame_knowable", "free_sources", "registry_ids")):
                e.append(f"{p}: id already exists in the catalog with a different definition; reference it or pick a new id")
            continue
        if not iid.islower() or "." not in iid or iid.split(".")[0] not in {i.split(".")[0] for i in c["inputs"] if not i.startswith("m.")}:
            e.append(f"{p}: id must be lowercase '<sport prefix>.<name>' using the sport's existing prefix")
        for k in NEW_INPUT_REQUIRED:
            if k not in ni:
                e.append(f"{p}: missing {k}")
        if ni.get("category") not in cat.CATEGORIES:
            e.append(f"{p}: category must be one of {cat.CATEGORIES}")
        if ni.get("pregame_knowable") not in cat.PIT:
            e.append(f"{p}: pregame_knowable must be one of {cat.PIT}")
        if not _txt(ni.get("measurement"), 120):
            e.append(f"{p}: measurement must give the exact calculation (windows, adjustments, shrinkage, units) in >=120 chars")
        if not isinstance(ni.get("raw_data"), list) or not ni.get("raw_data"):
            e.append(f"{p}: raw_data must list the raw tables/fields required")
        if not _txt(ni.get("rationale"), 80) or not _txt(ni.get("mechanism"), 40):
            e.append(f"{p}: rationale/mechanism too thin")
        if ni.get("registry_ids") not in ([], None) and any(x not in cat.registry_input_ids(sport) for x in ni.get("registry_ids") or []):
            e.append(f"{p}: registry_ids contains ids not in the registry")
    # --- audit of the existing inputs -----------------------------------------------------------------------------------------------------------------------
    ia = rec["input_audit"]
    existing = [i["id"] for i in a["inputs"] if i["id"] not in (rec.get("new_inputs") or {})]   # inputs this review itself added (and merged) are not "pre-existing"
    for i in existing:
        r = ia.get(i)
        if not r:
            e.append(f"input_audit missing existing input {i}"); continue
        v = r.get("verdict", "")
        if not (v in VERDICTS or (v.startswith("DUPLICATE_OF:") and v[13:] in known and v[13:] != i)):
            e.append(f"input_audit.{i}: bad verdict {v!r}")
        if not _txt(r.get("reason"), 40):
            e.append(f"input_audit.{i}: reason must be a specific >=40 char judgement")
    for i in ia:
        if i not in existing:
            e.append(f"input_audit has {i!r}, which is not an existing input of this archetype")
    # --- interactions & nonlinearities ----------------------------------------------------------------------------------------------------------------------
    ix = rec["interactions"]
    if len(ix) < 4:
        e.append("interactions needs >=4 entries")
    for n, x in enumerate(ix):
        if len(x.get("inputs") or []) < 2 or any(i not in known for i in x.get("inputs") or []):
            e.append(f"interaction {n}: needs >=2 known input ids")
        if x.get("form") not in INTERACTION_FORMS:
            e.append(f"interaction {n}: form must be one of {INTERACTION_FORMS}")
        if not _txt(x.get("mechanism"), 80):
            e.append(f"interaction {n}: mechanism must be >=80 chars (why, in which direction, in which regime)")
        if not _txt(x.get("how_to_test"), 40):
            e.append(f"interaction {n}: how_to_test must say what feature/contrast would reveal it")
    nl = rec["nonlinearities"]
    if len(nl) < 2:
        e.append("nonlinearities needs >=2 entries (shape of response of an input, not an interaction)")
    for n, x in enumerate(nl):
        if x.get("input_id") not in known:
            e.append(f"nonlinearity {n}: unknown input")
        if not _txt(x.get("shape"), 20) or not _txt(x.get("why"), 60):
            e.append(f"nonlinearity {n}: shape and a >=60 char why required")
    # --- required data --------------------------------------------------------------------------------------------------------------------------------------
    rdta = rec["required_data"]
    if len(rdta) < 2:
        e.append("required_data needs >=2 datasets")
    fed = set()
    for n, d in enumerate(rdta):
        for k in ("dataset", "grain", "fields", "timestamp_requirement", "history_needed", "candidate_sources", "feeds_inputs"):
            if not d.get(k):
                e.append(f"required_data[{n}] missing {k}")
        for s_ in d.get("candidate_sources") or []:
            if s_.get("access") not in ACCESS or not _txt(s_.get("name"), 3):
                e.append(f"required_data[{n}] candidate source needs name and access in {ACCESS}")
        fed.update(d.get("feeds_inputs") or [])
        for i in d.get("feeds_inputs") or []:
            if i not in known:
                e.append(f"required_data[{n}] feeds unknown input {i!r}")
    stage_inputs = {i for s in stages for i in s.get("input_ids") or []}
    unfed = sorted(i for i in stage_inputs if i not in fed and not i.startswith("m."))
    if len(unfed) > max(3, 0.25 * len(stage_inputs)):
        e.append(f"required_data does not define raw data for too many staged inputs ({len(unfed)}: {unfed[:6]}...)")
    # --- unresolved -----------------------------------------------------------------------------------------------------------------------------------------
    un = rec["unresolved"]
    if not un:
        e.append("unresolved must list at least one genuine open gap (no archetype is declared complete)")
    for n, u in enumerate(un):
        if u.get("type") not in UNRESOLVED_TYPES or not _txt(u.get("description"), 60) or not _txt(u.get("what_would_resolve"), 30):
            e.append(f"unresolved[{n}]: type in {UNRESOLVED_TYPES}, description >=60 chars and what_would_resolve >=30 chars required")
    return e


def similarity_flags(sport: str, reviews: dict[str, dict], threshold: float = 0.35) -> dict[str, list[str]]:
    """Boilerplate detector: stage descriptions / interaction mechanisms copied (even lightly edited) between archetypes of one sport."""
    texts: dict[str, list[tuple[str, set]]] = {}
    for k, r in reviews.items():
        L = [(f"stage:{s.get('id')}", _shingles(s.get("description", ""))) for s in (r.get("mechanism") or {}).get("stages", [])]
        L += [(f"interaction:{n}", _shingles(x.get("mechanism", ""))) for n, x in enumerate(r.get("interactions") or [])]
        texts[k] = L
    flags: dict[str, list[str]] = collections.defaultdict(list)
    keys = list(texts)
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            for la, sa in texts[ka]:
                for lb, sb in texts[kb]:
                    if len(sa) < 8 or len(sb) < 8:
                        continue
                    j = len(sa & sb) / len(sa | sb)
                    if j >= threshold:
                        msg = f"{la} ~ {kb}/{lb} (Jaccard {j:.2f} on 5-grams)"
                        flags[ka].append(msg); flags[kb].append(f"{lb} ~ {ka}/{la} (Jaccard {j:.2f} on 5-grams)")
    return dict(flags)


def finding_closed(f: dict, rec: dict | None) -> bool:
    """A finding is closed only by (a) RESOLVED: <what changed, >=40 chars> or (b) DEFERRED_TO_UNRESOLVED:<id> where <id> is a declared entry in the record's own unresolved list."""
    r = str(f.get("resolution", "OPEN"))
    if r.startswith("RESOLVED"):
        return len(r) >= 48
    if r.startswith("DEFERRED_TO_UNRESOLVED:"):
        return r.split(":", 1)[1].strip() in {u.get("id") for u in (rec or {}).get("unresolved") or []}
    return False


def independent_state(ind: dict | None, rec: dict | None = None) -> tuple[str, list[dict]]:
    if not ind:
        return "NONE", []
    if ind.get("verdict") not in ("PASS_WITH_OPEN_GAPS", "REVISE") or len(str(ind.get("rederivation_notes", "")).strip()) < 200 or not ind.get("reviewer"):
        return "NONE", []   # a review without the reviewer's own re-derivation does not count
    openf = [x for x in ind.get("findings") or [] if x.get("severity") in ("BLOCKER", "MAJOR", "SOURCE_UNVERIFIED") and not finding_closed(x, rec)]
    return ("OPEN_FINDINGS" if openf else "CLEAR"), openf


def series_remap_proposals() -> dict:
    """Misfiled-series findings recorded in the reviews (contract.series_mapping_issues). PROPOSALS ONLY: the PR #62 series ledger is preserved and not rewritten."""
    out: dict = {"schema_version": "series-remap-proposals-1.0", "status": "PROPOSALS_PENDING_APPROVAL", "note": "Collected from reviewer/resolver findings; the committed series ledger is unchanged.", "by_sport": {}, "rows": []}
    for s in SPORTS:
        n = 0
        for k, rec in load_reviews(s).items():
            for x in (rec.get("contract") or {}).get("series_mapping_issues") or []:
                out["rows"].append({"sport": s, "filed_under": k, "ticker": x.get("ticker"), "issue": x.get("issue"), "belongs_in": x.get("belongs_in")}); n += 1
        out["by_sport"][s] = n
    seen = collections.defaultdict(set)
    for r in out["rows"]:
        seen[(r["sport"], r["ticker"])].add(r["belongs_in"])
    out["distinct_series"] = len(seen)
    out["new_archetype_needed"] = sorted({str(b) for v in seen.values() for b in v if str(b).startswith("NEW_ARCHETYPE_NEEDED")})
    return out


def merge_new_inputs(write: bool = True) -> dict[str, int]:
    """Add reviewer-discovered inputs to the catalog (idempotent; never edits or removes an existing input) and attach each to the archetype that discovered it."""
    added = {}
    for s in SPORTS:
        c = cat.load(s); reviews = load_reviews(s); n = 0
        for k, rec in reviews.items():
            if k not in arch_keys(c):
                continue
            a = arch_entry(c, k)
            for iid, ni in (rec.get("new_inputs") or {}).items():
                if iid not in c["inputs"]:
                    c["inputs"][iid] = {x: ni[x] for x in ("label", "category", "mechanism", "rationale", "measurement", "pregame_knowable", "free_sources", "registry_ids")}
                    n += 1
                if iid not in {i["id"] for i in a["inputs"]}:
                    a["inputs"].append({"id": iid, "why": ni["why"], "role": ni["role"]})
        added[s] = n
        if write and n:
            (cat.CATALOG_DIR / f"{s}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
    return added


def compute_gate() -> dict:
    led = ledger_by_archetype()
    rules = rd(RULES)
    rows, per_sport, contract_universe = [], {}, {}
    all_rows = rd(LEDGER)["rows"]
    for s in SPORTS:
        c = cat.load(s); reviews = load_reviews(s); ind = load_independent(s)
        flags = similarity_flags(s, reviews)
        cnt = collections.Counter()
        for k in arch_keys(c):
            a = arch_entry(c, k); lr = led.get((s, k), [])
            rec = reviews.get(k)
            row = {"sport": s, "archetype": k, "label": a["label"], "registered": not k.startswith("unreg:"), "live_series": len(lr), "rules_text_series": sum(1 for r in lr if rules.get(r["ticker"], {}).get("rules_primary"))}
            if not rec:
                row.update(status="NOT_STARTED", problems=["no review record"])
            else:
                errs = validate_review(s, k, rec, c, rules, lr)
                sim = flags.get(k, [])
                if sim:
                    errs = errs + [f"possible boilerplate: {x}" for x in sim[:4]]
                ist, openf = independent_state(ind.get(k), rec)
                m = rec.get("mechanism") or {}
                row.update(problems=errs[:25], n_problems=len(errs), stages=len(m.get("stages") or []), new_inputs=len(rec.get("new_inputs") or {}), existing_inputs_audited=len(rec.get("input_audit") or {}),
                           interactions=len(rec.get("interactions") or []), nonlinearities=len(rec.get("nonlinearities") or []), datasets=len(rec.get("required_data") or []),
                           unresolved=len(rec.get("unresolved") or []), gaps=sum(1 for v in (m.get("category_coverage") or {}).values() if v.get("status") == "GAP"),
                           rules_verification=(rec.get("contract") or {}).get("rules_verification"), independent=ist, open_findings=len(openf),
                           independent_findings=len((ind.get(k) or {}).get("findings") or []), independent_verdict=(ind.get(k) or {}).get("verdict"))
                row["status"] = ("STRUCTURE_INCOMPLETE" if errs else "AUTHORED_NOT_INDEPENDENTLY_REVIEWED" if ist == "NONE" else "INDEPENDENT_REVIEW_OPEN_FINDINGS" if ist == "OPEN_FINDINGS" else "READY_FOR_USER_APPROVAL")
            cnt[row["status"]] += 1; rows.append(row)
        per_sport[s] = {"archetypes": len(arch_keys(c)), **{k: cnt.get(k, 0) for k in STATUSES}, "inputs": len(c["inputs"])}
        sr = [r for r in all_rows if r["sport"] == s]
        contract_universe[s] = {"series": len(sr), **dict(collections.Counter(r["status"] for r in sr)), "evidence": dict(collections.Counter(r["evidence"] for r in sr if r["status"] != "NO_LISTED_MARKETS"))}
    approval = rd(CD / "approval.json") if (CD / "approval.json").exists() else {"approved": False, "approved_by": None, "date": None, "note": "no human approval recorded; code never writes this"}
    tot = collections.Counter(r["status"] for r in rows)
    gate = {"schema_version": "completeness-gate-1.0", "status": "RESEARCH_ONLY", "phase": "CATALOG_COMPLETENESS (predictive experimentation PAUSED)",
            "totals": {"archetypes": len(rows), **{k: tot.get(k, 0) for k in STATUSES}}, "by_sport": per_sport, "contract_universe": contract_universe, "approval": approval, "rows": rows,
            "criteria": ["structure valid (13-category mechanism coverage, staged mechanism, >=4 interactions incl. form+test, >=2 nonlinearities, required-data definitions with sources and access)",
                         "every pre-existing archetype input individually audited (keep/weak/duplicate/irrelevant/benchmark-only with a reason)",
                         "contract text: verbatim quotes from sampled Kalshi rules for >=2 series where rules exist; ledger-checked tickers; edge cases listed",
                         "no boilerplate: stage and interaction text not near-duplicated across archetypes (5-gram Jaccard < 0.35)",
                         "at least one explicit unresolved gap per archetype (no archetype may be declared complete)",
                         "independent second review recorded with no open BLOCKER/MAJOR finding",
                         "READY_FOR_USER_APPROVAL is the ceiling: the human decision lives in approval.json and is never written by code"]}
    return gate


def summarize(gate: dict) -> dict:
    """Small dashboard summary: no per-archetype problem text, just counts."""
    keep = ("sport", "archetype", "label", "registered", "live_series", "rules_text_series", "status", "stages", "new_inputs", "existing_inputs_audited", "interactions", "nonlinearities", "datasets", "unresolved", "gaps", "rules_verification", "independent", "open_findings", "independent_findings", "n_problems")
    return {**{k: gate[k] for k in ("schema_version", "status", "phase", "totals", "by_sport", "contract_universe", "approval", "criteria", "series_mapping_proposals") if k in gate}, "rows": [{k: r.get(k) for k in keep} for r in gate["rows"]]}


def main():
    import sys
    CD.mkdir(parents=True, exist_ok=True)
    if "--evidence" in sys.argv:   # evidence packs describe the PRE-review catalog; regenerate only before a review round, never after merge_new_inputs
        build_evidence()
    g = compute_gate()
    (CD / "gate.json").write_text(json.dumps(g, indent=1, sort_keys=True))
    (CD / "summary.json").write_text(json.dumps(summarize(g), indent=0, sort_keys=True))
    rp = series_remap_proposals()
    (CD / "series_remap_proposals.json").write_text(json.dumps(rp, indent=0, sort_keys=True))
    g["series_mapping_proposals"] = {"total_entries": len(rp["rows"]), "distinct_series": rp["distinct_series"], "by_sport": rp["by_sport"], "new_archetypes_needed": len(rp["new_archetype_needed"])}
    (CD / "gate.json").write_text(json.dumps(g, indent=1, sort_keys=True))
    (CD / "summary.json").write_text(json.dumps(summarize(g), indent=0, sort_keys=True))
    print(json.dumps(g["totals"], indent=1))
    for s, v in g["by_sport"].items():
        print(s, v)


if __name__ == "__main__":
    main()

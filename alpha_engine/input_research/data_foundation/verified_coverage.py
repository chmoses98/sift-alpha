"""Verified coverage: the ONE authoritative coverage matrix (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.verified_coverage

Merges the draft audit (`input_audit.json`) with committed verification evidence under `research/input_research/data_foundation/verification/`:
  replay/<SPORT>.json          feature replay on RE-COLLECTED raw data (replay_verify.py): determinism, coverage replay, truncation, perturbation (new seeds/cuts), own-game, vintage dependence
  data_in_hand/<GROUP>.json    blind verifier verdicts for inputs claimed computable without a builder, judged against real (or schema-only) column evidence
  bucket_sample/*.json         blind verifier answers on a stratified sample of the other buckets + the sealed key (scored)
  blocked_recheck/*.json       blind verifier answers for EVERY input the draft calls BLOCKED
Nothing is promoted without evidence and nothing is claimed "verified" that was not replayed or checked against real columns. Verifiers are Claude agents: this is agent verification, never
human expert verification, and the owner still decides whether it is sufficient to lift the pause on predictive work.

VERIFIED STATUS (what the matrix reports; `verified_bucket` is the headline)
  VERIFIED_FULL | VERIFIED_PARTIAL | VERIFIED_PROXY     computed AND replayed: every replay test passed, no dependence on as-played fields, coverage and provenance checked (FULL also needs the whole definition implemented)
  DATA_IN_HAND_CONFIRMED                                  blind verifier confirmed from real re-collected columns
  REPLAYED_PIT_CAVEAT                                     replayed but point-in-time integrity not clean (depends on retrieval-time/as-played fields or on schedule structure)
  REPLAY_FAILED                                           a replay test failed: not computable until fixed
  CLAIMED_NOT_REPLAYED                                    computed by the earlier milestone but the raw data could not be re-collected in this session: UNVERIFIED claim
  DATA_IN_HAND_SCHEMA_ONLY                                verifier judged the ledger schema sufficient but no raw rows were re-read: UNVERIFIED claim
  DOWNGRADED_BY_VERIFIER                                  a verifier showed the claim fails (missing columns / history / point-in-time)
  REQUIRES_COLLECTION / BLOCKED_CONFIRMED / BLOCKED_CONTESTED / EXCLUDED_BENCHMARK_ONLY
"""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

from ...features import pit_policy as PP
from . import audit as A
from . import evidence as EV

ROOT = EV.ROOT
DF = EV.DF
VD = DF / "verification"
import re
# tables whose rows were NOT re-read this session (ledger schema only): a verdict resting on them can never count as verified
UNMEASURED_TABLES = re.compile(r"pbp|play.?by.?play|stint|nhl_shots|nhl\.shots|shots_extension|moneypuck_shots", re.I)
SCHEDULE_COLS = {"games_left_pre", "games_remaining"}
VERIFIED_COMPUTABLE = ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY", "DATA_IN_HAND_CONFIRMED")
# status -> headline bucket. FULL / PARTIAL / PROXY / DATA_IN_HAND are verified; UNVERIFIED claims and FAILED claims are never mixed into them.
HEADLINE = {"VERIFIED_FULL": "FULL", "VERIFIED_PARTIAL": "PARTIAL", "VERIFIED_PROXY": "PROXY", "DATA_IN_HAND_CONFIRMED": "DATA_IN_HAND",
            "REPLAYED_PIT_CAVEAT": "CAVEAT", "CLAIMED_NOT_REPLAYED": "UNVERIFIED", "DATA_IN_HAND_SCHEMA_ONLY": "UNVERIFIED", "REPLAY_FAILED": "FAILED", "DOWNGRADED_BY_VERIFIER": "FAILED", "PIT_QUARANTINED": "FAILED",
            "REQUIRES_COLLECTION": "REQUIRES_COLLECTION", "BLOCKED_CONFIRMED": "BLOCKED", "BLOCKED_BY_POLICY": "BLOCKED", "BLOCKED_CONTESTED": "UNVERIFIED", "EXCLUDED_BENCHMARK_ONLY": "EXCLUDED"}
BUCKET_ORDER = ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "CAVEAT", "UNVERIFIED", "FAILED", "REQUIRES_COLLECTION", "BLOCKED", "EXCLUDED")
LEDGER = {"CBB": ("espn_cbb_ledger.json", None, "games", None), "CFB": ("espn_cfb_ledger.json", None, "games", None), "MLB": ("mlb_schedule_ledger.json", None, "games", "schedule"), "TENNIS": ("repo_archives_ledger.json", "tennis_atp_matches", "rows", "atp"),
          "NBA": ("repo_archives_ledger.json", "nba_espn_team_games", "rows", "team_games"), "NHL": ("repo_archives_ledger.json", "nhl_games", "rows", "games")}


def rd(p):
    return json.loads(Path(p).read_text())


def load_replays() -> dict:
    return {f.stem: rd(f) for f in sorted((VD / "replay").glob("*.json"))} if (VD / "replay").exists() else {}


def load_ext_replays() -> dict:
    """Replays of builders added AFTER the earlier milestone (replay_ext.py / replay_generic.py): the input was REQUIRES_COLLECTION in the draft audit and is promoted only by passing these.
    Several files per sport are merged (input ids are unique); a duplicate id across files is an error, never a silent overwrite."""
    d = VD / "replay_ext"; out: dict = {}
    for f in (sorted(d.glob("*.json")) if d.exists() else []):
        r = rd(f); sp = r["sport"]; cur = out.setdefault(sp, {"sport": sp, "kind": "replay_ext", "raw_rows": {}, "inputs": {}, "files": []})
        dup = set(cur["inputs"]) & set(r["inputs"])
        if dup: raise ValueError(f"duplicate extension replay ids {sorted(dup)} in {f.name}")
        cur["inputs"].update(r["inputs"]); cur["raw_rows"][f.stem] = r.get("raw_rows"); cur["files"].append(f.name)
    return out


def load_independent() -> dict:
    """Blind independent re-implementation verdicts per input and column (verification/independent/*.json). Agent verification, never human."""
    d = VD / "independent"; out: dict = {}
    for f in (sorted(d.glob("*.json")) if d.exists() else []):
        for iid, v in rd(f)["inputs"].items():
            out.setdefault(iid, {}).update(v["columns"])
    return out


def independent_gate(row: dict, cols: list[str], ind: dict) -> tuple[str | None, dict]:
    """None = passes; otherwise the status to use. Fail closed: every column of the input needs a MATCH from a blind re-implementation."""
    rec = ind.get(row["id"]); ev = {"independent": {}}
    if not rec:
        return "REQUIRES_COLLECTION", {"replayed_without_independent_verification": True}
    verd = {c: (rec.get(c) or {}).get("verdict", "MISSING") for c in cols}; ev["independent"] = verd
    if any(v == "MISMATCH" for v in verd.values()):
        return "DOWNGRADED_BY_VERIFIER", ev
    if any(v != "MATCH" for v in verd.values()):
        return "REQUIRES_COLLECTION", {**ev, "replayed_without_independent_verification": True}
    return None, ev


# PIT tests that MUST be present and ok for an extension replay (fail closed: a missing test is a failure, not a pass).
REQUIRED_PIT_CHECKS = {"*": ("pit_check_perturbation_not_vacuous",), "nfl.injuries_pit": ("pit_check_perturbation_not_vacuous", "pit_check_post_kickoff_injuries")}


def pit_check_failures(iid: str, t: dict) -> list[str]:
    need = REQUIRED_PIT_CHECKS.get(iid, REQUIRED_PIT_CHECKS["*"])
    bad = [n for n in need if n not in t]                                   # absent required check
    bad += [n for n in t if n.startswith("pit_check") and not (isinstance(t[n], dict) and t[n].get("ok") is True)]
    for k in ("determinism", "own_game"):
        if not (isinstance(t.get(k), dict) and t[k].get("ok") is True): bad.append(k)
    for k in ("truncation", "perturbation"):
        if not t.get(k) or not all(isinstance(x, dict) and x.get("ok") is True for x in t[k]): bad.append(k)   # no cuts at all also fails
    return sorted(set(bad))


def provenance_check(sp: str, rp: dict) -> dict:
    """Re-collected raw data vs the committed ledger of the earlier collection (same source, later retrieval: the replay may hold MORE rows, never materially fewer)."""
    led = LEDGER.get(sp)
    raw_rows = rp.get("raw_rows")
    n = (raw_rows.get(led[3]) if (isinstance(raw_rows, dict) and led and led[3]) else (sum(raw_rows.values()) if isinstance(raw_rows, dict) else raw_rows))
    if not led:
        return {"ok": bool(n), "basis": "no ledger for this source: re-collected rows exist and the source was probed reachable", "replay_rows": n}
    d = rd(EV.IN / "data_collection" / led[0]); d = (d.get("datasets") or {}).get(led[1]) if led[1] else d
    lr = int(d.get(led[2]) or d.get("rows") or 0)
    return {"ok": bool(n) and n >= 0.97 * lr, "basis": f"ledger {led[0]}: {lr} rows at the earlier collection", "replay_rows": n, "ledger_rows": lr}


def assess_computed(row: dict, rp: dict | None, prov: dict | None) -> tuple[str, dict]:
    """Verified status for an input the earlier milestone computed."""
    if rp is None or row["id"] not in rp["inputs"]:
        return "CLAIMED_NOT_REPLAYED", {"why": "raw data for this sport could not be re-collected in this session (or the replay has not run): the earlier computation is an unverified claim"}
    r = rp["inputs"][row["id"]]; t = r["tests"]; ev = {"replay": {}}
    det = t["determinism"]["ok"]
    pit_bad = pit_check_failures(row["id"], t) if r.get("kind", rp.get("kind")) == "replay_ext" or any(k.startswith("pit_check") for k in t) else []
    if pit_bad:
        ev["replay"] = {"pit_checks_failed_or_missing": pit_bad}
        return "REPLAY_FAILED", ev
    trunc_bad = [x for x in t.get("truncation", []) if not x["ok"]]; pert_bad = [x for x in t.get("perturbation", []) if not x["ok"]]
    own = t.get("own_game", {}); vint = {k: v for k, v in (t.get("vintage_dependence") or {}).items() if v}
    role = {k: x["bad_columns"] for k, x in (t.get("role_fields_own_date") or {}).items() if x["bad_columns"]}
    cov = t["coverage_replay"]
    ev["replay"] = {"determinism": det, "truncation_cuts": [x["cut"] for x in t.get("truncation", [])], "truncation_failed": [(x["cut"], x["bad_columns"]) for x in trunc_bad], "perturbation_cuts_seeds": [(x["cut"], x["seed"]) for x in t.get("perturbation", [])],
                    "perturbation_failed": [(x["cut"], x["bad_columns"]) for x in pert_bad], "own_game_date": own.get("date"), "own_game_failed": own.get("bad_columns"), "vintage_dependent_on": sorted(vint), "role_field_dependent_on": sorted(role),
                    "coverage_min": cov["min_coverage_new"], "coverage_drift_vs_recorded": cov["max_abs_coverage_drift"], "constant_columns": cov["constant_columns"], "first": cov["first_new"], "last": cov["last_new"], "provenance": prov}
    if not det or pert_bad or not cov["present"]:
        return "REPLAY_FAILED", ev
    forbidden = sorted({f for f in list(vint) + list(role) if PP.classify(f)})
    if forbidden:   # the owner's policy: observed weather, retrieval-time ranks, as-played lineups/officials, final starter flags can never be pregame inputs
        ev["quarantine"] = {"fields": forbidden, "classes": sorted({PP.classify(f) for f in forbidden}), "rule": [PP.CLASS_RULE[PP.classify(f)] for f in forbidden][:3]}
        return "PIT_QUARANTINED", ev
    trunc_cols = {c for x in trunc_bad for c in x["bad_columns"]}
    own_fail = bool(own.get("bad_columns"))
    if trunc_bad and not trunc_cols <= SCHEDULE_COLS:
        return "REPLAY_FAILED", ev
    caveat = []
    if trunc_bad:
        caveat.append("depends on schedule structure (rows that exist in the full season file, e.g. games left): valid only if the fixture list is known before the event")
    if vint:
        caveat.append("depends on as-played / retrieval-time raw fields " + ", ".join(sorted(vint)) + ": not a pregame vintage")
    if own_fail and not vint:
        return "REPLAY_FAILED", ev
    if (row.get("computed_prior") or {}).get("pit_class") == "final_postgame":
        caveat.append("spec is post-game only")
    if caveat:
        ev["caveats"] = caveat
        return "REPLAYED_PIT_CAVEAT", ev
    lvl = r["level_claimed"]
    limits = []
    if cov["min_coverage_new"] is not None and cov["min_coverage_new"] < 0.5:
        limits.append("min column coverage below 50%")
    if cov["max_abs_coverage_drift"] > 0.10:
        limits.append("replayed coverage differs from the recorded coverage by more than 10 points")
    if cov["constant_columns"]:
        limits.append("constant columns")
    if prov and not prov["ok"]:
        limits.append("re-collected rows do not match the earlier collection's ledger")
    if limits:
        ev["limits"] = limits
        return "VERIFIED_PARTIAL" if lvl == "FULL" else {"FULL": "VERIFIED_FULL", "PARTIAL": "VERIFIED_PARTIAL", "PROXY": "VERIFIED_PROXY"}[lvl] if False else ("VERIFIED_PARTIAL" if lvl != "PROXY" else "VERIFIED_PROXY"), ev
    if lvl == "FULL":
        if r["missing_claimed"]:
            ev["limits"] = ["definition not fully implemented: " + "; ".join(r["missing_claimed"])]
            return "VERIFIED_PARTIAL", ev
        return "VERIFIED_FULL", ev
    return ("VERIFIED_PARTIAL" if lvl == "PARTIAL" else "VERIFIED_PROXY"), ev


def load_dih() -> dict:
    out = {}
    d = VD / "data_in_hand"
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        out.update(rd(f)["answers"])
    return out


def load_dir_answers(sub: str, pat: str = "*.json") -> dict:
    out = {}
    d = VD / sub
    for f in sorted(d.glob(pat)) if d.exists() else []:
        out.update(rd(f)["answers"])
    return out


def quarantine_from_replays(replays: dict) -> dict:
    """Every replayed input whose features depend on a field the point-in-time policy forbids, whatever its bucket (benchmark-only and demoted inputs included)."""
    q = {}
    for sp, rp in replays.items():
        for iid, r in rp["inputs"].items():
            t = r["tests"]
            fields = sorted({f for f, b in (t.get("vintage_dependence") or {}).items() if b and PP.classify(f)} | {f for f, x in (t.get("role_fields_own_date") or {}).items() if x["bad_columns"] and PP.classify(f)})
            if fields:
                q[f"{sp}:{iid}"] = {"fields": fields, "classes": sorted({PP.classify(f) for f in fields})}
    return q


def combine_blocked(prior: dict | None, pol: dict | None) -> tuple[str, dict]:
    """Drafted-BLOCKED input, two blind rounds: round 1 (no policy) and round 2 under the owner's explicit access policy. Disagreement stays CONTESTED: it is never resolved in anyone's favour by assertion."""
    p1 = (prior or {}).get("bucket"); c2 = (pol or {}).get("category")
    ev = {"round1_bucket": p1, "round2_policy_category": c2, "round2_source_or_reason": (pol or {}).get("source_or_reason"), "round2_confidence": (pol or {}).get("confidence")}
    if pol is None:
        return "BLOCKED_CONTESTED", {**ev, "why": "no policy-aware recheck recorded"}
    if c2 in ("BLOCKED_BY_POLICY", "BLOCKED_NO_SOURCE"):
        if p1 == "BLOCKED":
            return "BLOCKED_CONFIRMED", ev
        if c2 == "BLOCKED_BY_POLICY":
            return "BLOCKED_BY_POLICY", {**ev, "why": "round 1 had no access policy and counted a route that the owner's policy forbids"}
        return "BLOCKED_CONTESTED", {**ev, "why": "round 2 says no source exists; round 1 found one"}
    if c2 in ("COLLECTABLE_PERMITTED", "PROSPECTIVE_ONLY", "NEEDS_OWNER_ACTION"):
        if p1 == "BLOCKED":
            return "BLOCKED_CONTESTED", {**ev, "why": "round 1 said blocked, round 2 found a permitted route"}
        return "REQUIRES_COLLECTION", {**ev, "reclassified_from_blocked": True, "needs_owner_action": c2 == "NEEDS_OWNER_ACTION", "prospective_only": c2 == "PROSPECTIVE_ONLY"}
    if c2 == "EXCLUDED_MARKET":
        return "BLOCKED_CONTESTED", {**ev, "why": "round 2 calls it market-derived: the benchmark list must decide"}
    return "BLOCKED_CONTESTED", {**ev, "why": "round 2 claims it is computable now, but no replay or column check supports that"}


def load_blocked() -> dict:
    out = {}
    d = VD / "blocked_recheck"
    for f in sorted(d.glob("answers_*.json")) if d.exists() else []:
        out.update(rd(f)["answers"])
    return out


def load_full_certifications() -> dict:
    """Owner-reviewable certification records (verification/full_certification/*.json): for each input, the catalog `measurement` clauses mapped to builder columns, the required history, timing statement and
    the SOURCE-USE RIGHTS note. Rights are tracked here and never decide the status; a missing record means no certification."""
    d = VD / "full_certification"; out: dict = {}
    for f in (sorted(d.glob("*.json")) if d.exists() else []):
        out.update(rd(f)["inputs"])
    return out


def certification_failures(row: dict, cols: list[str], rp_input: dict | None, ev: dict, cert: dict | None) -> list[str]:
    """Why an extension input may NOT be certified FULL (empty list = every requirement met). Fail closed: anything absent is a failure.
    Requirements: (1) a certification record exists and maps EVERY catalog measurement clause to implemented columns and covers exactly the replayed columns; (2) the builder declares nothing missing;
    (3) every replay/leakage/provenance/non-vacuity check passes (pit_check_failures); (4) every column has a blind MATCH; (5) coverage >= 0.5 for every column with no constant column and no recorded limits;
    (6) replayed history spans the catalog's stated history; (7) point-in-time class is pregame and the timing rule is recorded."""
    bad: list[str] = []
    if not cert:
        return ["no certification record"]
    clauses = cert.get("catalog_clauses") or []
    if not clauses or any(not c.get("columns") or not c.get("implemented") for c in clauses):
        bad.append("catalog clause not mapped to implemented columns")
    mapped = {c for cl in clauses for c in (cl.get("columns") or [])}
    if set(cols) != mapped:
        bad.append("certified columns differ from replayed columns")
    if cert.get("builder_missing"):
        bad.append("builder declares missing components")
    if not cert.get("timing_rule"):
        bad.append("timing rule not recorded")
    if not rp_input:
        return bad + ["no extension replay"]
    t = rp_input.get("tests") or {}
    bad += ["replay:" + x for x in pit_check_failures(row["id"], t)]
    if len({x.get("seed") for x in t.get("perturbation", [])}) < 3 or len(t.get("truncation", [])) < 3:
        bad.append("fewer than 3 truncation cuts / perturbation seeds")
    ind = ev.get("independent") or {}
    if not cols or any(ind.get(c) != "MATCH" for c in cols):
        bad.append("blind exact match missing for a column")
    cov = (t.get("coverage_replay") or {})
    if cov.get("min_coverage_new") is None or cov["min_coverage_new"] < 0.5 or cov.get("constant_columns") or ev.get("limits"):
        bad.append("coverage/limits not clean")
    h = row.get("history") or {}
    first = (cov.get("first_new") or "")[:4]; last = (cov.get("last_new") or "")[:4]
    try:
        if not (h.get("complete") and int(first) <= int(h["first"]) and int(last) >= int(h["last"]) - 1):
            bad.append("replayed history shorter than the catalog's required history")
    except (ValueError, TypeError, KeyError):
        bad.append("history not determinable")
    if row.get("pit_verdict") != "PIT_SAFE" or row.get("pregame_knowable") != "yes":
        bad.append("not recorded as pregame-knowable PIT_SAFE")
    return bad


def certify_extension_full(row: dict, cols: list[str], rp_input: dict | None, vs: str, ev: dict, cert: dict | None) -> tuple[str, dict]:
    """Evidence-based FULL certification for an extension-built input (replaces the former unconditional cap). A VERIFIED_FULL claim is kept only when `certification_failures` is empty;
    otherwise it is held at VERIFIED_PARTIAL with the reasons. Source-use rights are attached as separate evidence and never change the status."""
    if vs != "VERIFIED_FULL":
        return vs, ev
    ev = {**ev, "source_use_rights": (cert or {}).get("source_use_rights", "unrecorded")}
    bad = certification_failures(row, cols, rp_input, ev, cert)
    if bad:
        return "VERIFIED_PARTIAL", {**ev, "full_candidate": True, "certification_failures": bad, "limits": list(ev.get("limits", [])) + ["FULL not certified: " + "; ".join(bad)]}
    return "VERIFIED_FULL", {**ev, "full_certified": True, "certification": {k: cert[k] for k in ("catalog_clauses", "timing_rule", "required_history", "reviewed_by", "excluded_model_steps") if k in cert}}


# statuses a measured extension builder (replay gates + blind exact match) may promote from: no builder existed yet. DOWNGRADED_BY_VERIFIER is deliberately NOT promotable.
PROMOTABLE = ("REQUIRES_COLLECTION", "DATA_IN_HAND_CONFIRMED", "DATA_IN_HAND_SCHEMA_ONLY")


def build(write: bool = True) -> dict:
    rows = rd(DF / "input_audit.json")["rows"]
    replays = load_replays(); exts = load_ext_replays(); ind = load_independent(); dih = load_dih(); blk = load_blocked(); dih2 = load_dir_answers('data_in_hand_round2'); certs = load_full_certifications(); blkp = load_dir_answers('blocked_recheck_policy', 'answers_*.json')
    prov = {sp: provenance_check(sp, rp) for sp, rp in replays.items()}
    out = []
    for r in rows:
        sp = r["sport"]; ev = {}
        if r["status"] == "EXCLUDED_BENCHMARK_ONLY":
            vs = "EXCLUDED_BENCHMARK_ONLY"
        elif r["computed_prior"] and r["status"].startswith("COMPUTED"):
            vs, ev = assess_computed(r, replays.get(sp), prov.get(sp))
        elif r["status"] == "DATA_IN_HAND":
            a = dih.get(r["key"]); a2 = dih2.get(r["key"])
            if a is None and a2 is None:
                vs, ev = "CLAIMED_NOT_REPLAYED", {"why": "no verifier verdict recorded"}
            else:
                v1 = a["verdict"] if a else None; v2 = a2["verdict"] if a2 else None
                # round 1 for NBA/NHL was SCHEMA-ONLY; round 2 used REAL re-read columns. For the others both rounds saw real columns: a downgrade in either round wins, and CONFIRMED needs both.
                sch_only = v1 == "CONFIRMED_SCHEMA_ONLY" or (v1 is None)
                final = v2 if sch_only else ("DOWNGRADED" if "DOWNGRADED" in (v1, v2) else ("CONFIRMED" if v1 == "CONFIRMED" and v2 == "CONFIRMED" else "UNDETERMINED"))
                if v1 is not None and v1 != "CONFIRMED_SCHEMA_ONLY" and v2 is None:
                    final = {"CONFIRMED": "UNDETERMINED"}.get(v1, v1)   # one round only: not enough to confirm
                pick = a2 or a
                unmeasured = sp in ("NBA", "NHL") and final == "CONFIRMED" and bool(UNMEASURED_TABLES.search(json.dumps(pick.get("columns_used")) + " " + str(pick.get("reason")) + " " + str(pick.get("history"))))
                if unmeasured:
                    final = "UNDETERMINED"   # confirmed only on a table whose rows were not re-read this session
                vs = {"CONFIRMED": "DATA_IN_HAND_CONFIRMED", "DOWNGRADED": "DOWNGRADED_BY_VERIFIER", "UNDETERMINED": "DATA_IN_HAND_SCHEMA_ONLY"}[final]
                ev = {"rests_on_unmeasured_table": unmeasured, "round1_verdict": v1, "round2_verdict": v2, "columns_used": pick.get("columns_used"), "history": pick.get("history"), "pit_ok": pick.get("pit_ok"), "downgrade_to": pick.get("downgrade_to"), "reason": pick.get("reason")}
        elif r["bucket"] == "BLOCKED":
            vs, ev = combine_blocked(blk.get(r["key"]), blkp.get(r["key"]))
        else:
            vs = "REQUIRES_COLLECTION"
        if vs in PROMOTABLE and r["id"] in (exts.get(sp) or {}).get("inputs", {}):
            was = vs
            vs, ev = assess_computed(r, exts[sp], {"ok": True, "basis": "extension replay on freshly collected public release data; no earlier ledger", "replay_rows": exts[sp].get("raw_rows")})
            if vs.startswith("VERIFIED"):
                gate, gev = independent_gate(r, exts[sp]["inputs"][r["id"]]["columns"], ind)
                ev.update(gev)
                if gate: vs = gate
                else: vs, ev = certify_extension_full(r, exts[sp]['inputs'][r['id']]['columns'], exts[sp]['inputs'][r['id']], vs, ev, certs.get(r['id']))
            ev["promoted_from"] = was
        if vs == "VERIFIED_PARTIAL" and r["id"] in (exts.get(sp) or {}).get("inputs", {}):
            # an extension builder that completes the definition of an input the earlier milestone left PARTIAL: it must pass the same replay gates AND the blind exact-match gate; even then the status stays PARTIAL (extension-gate cap), with `full_candidate` evidence
            vs2, ev2 = assess_computed(r, exts[sp], {"ok": True, "basis": "extension replay on freshly collected public release data; no earlier ledger", "replay_rows": exts[sp].get("raw_rows")})
            gate, gev = independent_gate(r, exts[sp]["inputs"][r["id"]]["columns"], ind) if vs2 == "VERIFIED_FULL" else (None, {})
            if vs2 == "VERIFIED_FULL" and not gate:
                vs3, ev3 = certify_extension_full(r, exts[sp]["inputs"][r["id"]]["columns"], exts[sp]["inputs"][r["id"]], vs2, {**ev2, **gev}, certs.get(r["id"]))
                if vs3 == "VERIFIED_FULL":
                    vs, ev = vs3, {**ev3, "promoted_from": "VERIFIED_PARTIAL", "earlier_partial_missing": ev.get("limits")}
                else:
                    ev = {**ev, "full_candidate": True, "full_candidate_evidence": ev3, "earlier_partial_missing": ev.get("limits")}
        if r["computed_prior"] and not r["status"].startswith("COMPUTED") and r["status"] != "EXCLUDED_BENCHMARK_ONLY":
            ps, pe = assess_computed(r, replays.get(sp), prov.get(sp))   # the earlier milestone computed it but a reviewer/dependency later demoted it: keep what the replay found
            ev = {**ev, "earlier_computation_replay_status": ps, "earlier_computation_replay": pe}
        out.append({"key": r["key"], "sport": sp, "id": r["id"], "draft_bucket": r["bucket"], "draft_status": r["status"], "verified_status": vs, "verified_bucket": HEADLINE[vs], "pit_verdict": r["pit_verdict"], "evidence": ev})
    summ = summarize(out, prov)
    quarantine = quarantine_from_replays(replays)
    if write:
        (DF / "verified_coverage.json").write_text(json.dumps({"schema_version": "verified-coverage-1.0", "status": "RESEARCH_ONLY", "independently_verified_by_human": False, "rows": out, "summary": summ}, indent=0, sort_keys=True, ensure_ascii=False, default=str) + "\n")
        write_matrix(out, rows)
        (DF / "pit_quarantine.json").write_text(json.dumps({"schema_version": "pit-quarantine-1.0", "status": "RESEARCH_ONLY", "policy": "alpha_engine/features/pit_policy.py", "specs": {k.split(":", 1)[0] + ":" + k.split(":", 1)[1]: v for k, v in sorted(quarantine.items())}}, indent=0, sort_keys=True) + "\n")
    return {"rows": out, "summary": summ}


def write_matrix(vrows: list[dict], arows: list[dict]) -> None:
    """The ONE authoritative coverage matrix (csv): draft audit columns plus verified status/bucket."""
    byk = {r["key"]: r for r in arows}
    with open(DF / "coverage_matrix.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sport", "input_id", "verified_bucket", "verified_status", "draft_bucket", "draft_status", "pit_verdict", "history_first", "history_last", "cost", "tos_risk", "confidence", "needs", "satisfied_by", "pregame_knowable", "evidence_summary"])
        for v in vrows:
            r = byk[v["key"]]; e = v["evidence"]
            summ = e.get("reason") or "; ".join(e.get("caveats") or e.get("limits") or []) or e.get("why") or ""
            w.writerow([v["sport"], v["id"], v["verified_bucket"], v["verified_status"], v["draft_bucket"], v["draft_status"], v["pit_verdict"], r["history"]["first"], r["history"]["last"], r["cost"], r["tos_risk"], r["confidence"],
                        "|".join(x["need"] for x in r["requirements"]), "|".join(sorted({x["satisfied_by"] for x in r["requirements"] if x["satisfied_by"]})), r["pregame_knowable"], str(summ)[:200].replace("\n", " ")])


def summarize(vrows: list[dict], prov: dict) -> dict:
    by = collections.Counter(v["verified_status"] for v in vrows); hb = collections.Counter(v["verified_bucket"] for v in vrows)
    sp = {s: dict(collections.Counter(v["verified_status"] for v in vrows if v["sport"] == s)) for s in A.SPORTS}
    earlier = collections.Counter((v["evidence"].get("earlier_computation_replay_status") or v["verified_status"]) for v in vrows if v["evidence"].get("earlier_computation_replay_status") or v["verified_status"] in ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY", "REPLAYED_PIT_CAVEAT", "REPLAY_FAILED", "CLAIMED_NOT_REPLAYED", "PIT_QUARANTINED") and v["draft_status"].startswith("COMPUTED"))
    return {"earlier_milestone_computed_replay_outcomes": dict(earlier), "by_verified_status": dict(by), "by_verified_bucket": dict(hb), "by_sport_verified_status": sp, "provenance_checks": prov, "n": len(vrows),
            "verified_computable": sum(by[s] for s in VERIFIED_COMPUTABLE), "claimed_computable_at_draft": sum(1 for v in vrows if v["draft_bucket"] == "COMPUTABLE")}


def main() -> int:
    b = build(True)
    print(json.dumps({k: b["summary"][k] for k in ("n", "by_verified_status", "verified_computable", "claimed_computable_at_draft")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

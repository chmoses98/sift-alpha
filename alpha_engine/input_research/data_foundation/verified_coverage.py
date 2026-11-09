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

from . import audit as A
from . import evidence as EV

ROOT = EV.ROOT
DF = EV.DF
VD = DF / "verification"
SCHEDULE_COLS = {"games_left_pre", "games_remaining"}
VERIFIED_COMPUTABLE = ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY", "DATA_IN_HAND_CONFIRMED")
HEADLINE = {"VERIFIED_FULL": "VERIFIED_COMPUTABLE", "VERIFIED_PARTIAL": "VERIFIED_COMPUTABLE", "VERIFIED_PROXY": "VERIFIED_COMPUTABLE", "DATA_IN_HAND_CONFIRMED": "VERIFIED_COMPUTABLE",
            "REPLAYED_PIT_CAVEAT": "COMPUTABLE_WITH_CAVEAT", "CLAIMED_NOT_REPLAYED": "CLAIMED_UNVERIFIED", "DATA_IN_HAND_SCHEMA_ONLY": "CLAIMED_UNVERIFIED", "REPLAY_FAILED": "NOT_COMPUTABLE_AS_CLAIMED",
            "DOWNGRADED_BY_VERIFIER": "NOT_COMPUTABLE_AS_CLAIMED", "REQUIRES_COLLECTION": "REQUIRES_COLLECTION", "BLOCKED_CONFIRMED": "BLOCKED", "BLOCKED_CONTESTED": "BLOCKED_CONTESTED", "EXCLUDED_BENCHMARK_ONLY": "EXCLUDED"}
LEDGER = {"CBB": ("espn_cbb_ledger.json", None, "games"), "CFB": ("espn_cfb_ledger.json", None, "games"), "MLB": ("mlb_schedule_ledger.json", None, "games"), "TENNIS": ("repo_archives_ledger.json", "tennis_atp_matches", "rows")}


def rd(p):
    return json.loads(Path(p).read_text())


def load_replays() -> dict:
    return {f.stem: rd(f) for f in sorted((VD / "replay").glob("*.json"))} if (VD / "replay").exists() else {}


def provenance_check(sp: str, rp: dict) -> dict:
    """Re-collected raw data vs the committed ledger of the earlier collection (same source, later retrieval: the replay may hold MORE rows, never materially fewer)."""
    led = LEDGER.get(sp)
    raw_rows = rp.get("raw_rows"); n = sum(raw_rows.values()) if isinstance(raw_rows, dict) else raw_rows
    if sp == "TENNIS" and isinstance(raw_rows, dict):
        n = raw_rows.get("atp", 0)
    if sp == "MLB" and isinstance(raw_rows, dict):
        n = raw_rows.get("schedule", 0)
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
    trunc_bad = [x for x in t.get("truncation", []) if not x["ok"]]; pert_bad = [x for x in t.get("perturbation", []) if not x["ok"]]
    own = t.get("own_game", {}); vint = {k: v for k, v in (t.get("vintage_dependence") or {}).items() if v}
    cov = t["coverage_replay"]
    ev["replay"] = {"determinism": det, "truncation_cuts": [x["cut"] for x in t.get("truncation", [])], "truncation_failed": [(x["cut"], x["bad_columns"]) for x in trunc_bad], "perturbation_cuts_seeds": [(x["cut"], x["seed"]) for x in t.get("perturbation", [])],
                    "perturbation_failed": [(x["cut"], x["bad_columns"]) for x in pert_bad], "own_game_date": own.get("date"), "own_game_failed": own.get("bad_columns"), "vintage_dependent_on": sorted(vint),
                    "coverage_min": cov["min_coverage_new"], "coverage_drift_vs_recorded": cov["max_abs_coverage_drift"], "constant_columns": cov["constant_columns"], "first": cov["first_new"], "last": cov["last_new"], "provenance": prov}
    if not det or pert_bad or not cov["present"]:
        return "REPLAY_FAILED", ev
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
    if row["computed_prior"]["pit_class"] == "final_postgame":
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


def load_blocked() -> dict:
    out = {}
    d = VD / "blocked_recheck"
    for f in sorted(d.glob("answers_*.json")) if d.exists() else []:
        out.update(rd(f)["answers"])
    return out


def build(write: bool = True) -> dict:
    rows = rd(DF / "input_audit.json")["rows"]
    replays = load_replays(); dih = load_dih(); blk = load_blocked()
    prov = {sp: provenance_check(sp, rp) for sp, rp in replays.items()}
    out = []
    for r in rows:
        sp = r["sport"]; ev = {}
        if r["status"] == "EXCLUDED_BENCHMARK_ONLY":
            vs = "EXCLUDED_BENCHMARK_ONLY"
        elif r["computed_prior"] and r["status"].startswith("COMPUTED"):
            vs, ev = assess_computed(r, replays.get(sp), prov.get(sp))
        elif r["status"] == "DATA_IN_HAND":
            a = dih.get(r["key"])
            if a is None:
                vs, ev = "CLAIMED_NOT_REPLAYED", {"why": "no verifier verdict recorded"}
            else:
                v = a["verdict"]
                vs = {"CONFIRMED": "DATA_IN_HAND_CONFIRMED", "CONFIRMED_SCHEMA_ONLY": "DATA_IN_HAND_SCHEMA_ONLY", "DOWNGRADED": "DOWNGRADED_BY_VERIFIER", "UNDETERMINED": "DATA_IN_HAND_SCHEMA_ONLY"}[v]
                ev = {"verifier_verdict": v, "columns_used": a.get("columns_used"), "history": a.get("history"), "pit_ok": a.get("pit_ok"), "downgrade_to": a.get("downgrade_to"), "reason": a.get("reason")}
        elif r["bucket"] == "BLOCKED":
            a = blk.get(r["key"])
            if a is None:
                vs, ev = "BLOCKED_CONTESTED", {"why": "no blind re-verification recorded"}
            else:
                vs = "BLOCKED_CONFIRMED" if a["bucket"] == "BLOCKED" else "BLOCKED_CONTESTED"
                ev = {"blind_verifier_bucket": a["bucket"], "confidence": a.get("confidence"), "reason": a.get("limiting_source_or_reason") or a.get("notes")}
        else:
            vs = "REQUIRES_COLLECTION"
        if r["computed_prior"] and not r["status"].startswith("COMPUTED") and r["status"] != "EXCLUDED_BENCHMARK_ONLY":
            ps, pe = assess_computed(r, replays.get(sp), prov.get(sp))   # the earlier milestone computed it but a reviewer/dependency later demoted it: keep what the replay found
            ev = {**ev, "earlier_computation_replay_status": ps, "earlier_computation_replay": pe}
        out.append({"key": r["key"], "sport": sp, "id": r["id"], "draft_bucket": r["bucket"], "draft_status": r["status"], "verified_status": vs, "verified_bucket": HEADLINE[vs], "pit_verdict": r["pit_verdict"], "evidence": ev})
    summ = summarize(out, prov)
    if write:
        (DF / "verified_coverage.json").write_text(json.dumps({"schema_version": "verified-coverage-1.0", "status": "RESEARCH_ONLY", "independently_verified_by_human": False, "rows": out, "summary": summ}, indent=0, sort_keys=True, ensure_ascii=False, default=str) + "\n")
        write_matrix(out, rows)
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
    earlier = collections.Counter((v["evidence"].get("earlier_computation_replay_status") or v["verified_status"]) for v in vrows if v["evidence"].get("earlier_computation_replay_status") or v["verified_status"] in ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY", "REPLAYED_PIT_CAVEAT", "REPLAY_FAILED", "CLAIMED_NOT_REPLAYED") and v["draft_status"].startswith("COMPUTED"))
    return {"earlier_milestone_computed_replay_outcomes": dict(earlier), "by_verified_status": dict(by), "by_verified_bucket": dict(hb), "by_sport_verified_status": sp, "provenance_checks": prov, "n": len(vrows),
            "verified_computable": sum(by[s] for s in VERIFIED_COMPUTABLE), "claimed_computable_at_draft": sum(1 for v in vrows if v["draft_bucket"] == "COMPUTABLE")}


def main() -> int:
    b = build(True)
    print(json.dumps({k: b["summary"][k] for k in ("n", "by_verified_status", "verified_computable", "claimed_computable_at_draft")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

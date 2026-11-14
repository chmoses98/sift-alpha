"""FULL-promotion audit of every PARTIAL input (RESEARCH_ONLY, deterministic).

    python -m alpha_engine.input_research.data_foundation.full_promotion_audit

For each input that is PARTIAL (or was promoted from PARTIAL by a recorded certification) the audit records, from committed artifacts only, which machine-checkable requirement fails first:
  S1 blind exact match on every column   S2 PIT_SAFE and pregame-knowable   S3 coverage >= 0.5, no constant column, no recorded limit   S4 replayed history spans the catalog history   S5 builder declares no missing component
and, for the inputs that clear S1-S4, the recorded clause-level reading of the catalog text (REVIEW below: why the declared gaps are catalog clauses, or why one input qualifies). Nothing here lowers a gate: promotion itself only happens in verified_coverage.certify_extension_full from a reviewed
certification record. Output: data_foundation/full_promotion_audit.json.
"""
from __future__ import annotations

import json
from collections import Counter

from . import market_completeness as M
from . import verified_coverage as V

OUT = M.DF / "full_promotion_audit.json"

# clause-level reading of the catalog measurement text for inputs that clear S1-S4 but declare gaps (agent review, 2026-11-10)
REVIEW = {
 "NFL:nfl.opening_script": "NOT_FULL: per-half opening drives and pass rate vs expected are catalog clauses; first-half drive only",
 "NFL:nfl.dst_td_hazard": "NOT_FULL: returner-threat term (kick/punt return TD per return, k=60) and the k=40 regression are catalog clauses",
 "NFL:nfl.non_offensive_scoring_rate": "NOT_FULL: the 25-game half-life-12 window and k=40 shrink are catalog clauses; no expected-points / P(>=1) output",
 "NFL:nfl.opponent_ball_control_denial": "NOT_FULL: seconds per play and the 12-game half-life-6 window are catalog clauses",
 "NFL:nfl.fourth_and_goal_policy": "NOT_FULL: coach-level random effect and win-probability adjustment are catalog clauses (team level only)",
 "NFL:nfl.fourth_down_fg_decision_rate": "NOT_FULL: per-coach P(go | yard line, distance, score/time bins) is the catalog definition; only a team rate exists",
 "NFL:nfl.goal_to_go_pass_rate": "NOT_FULL: coach random effect and down x score buckets are catalog clauses",
 "NFL:nfl.rush_explosive_tail_rate": "NOT_FULL: per-runner rate with position-role shrink and the opponent factor are catalog clauses; team rate only",
 "NFL:nfl.qb_dropback_to_attempt_leakage": "NOT_FULL: per-QB over his last 17 starts is the catalog definition; team level only",
 "NFL:nfl.endzone_exposure_plays": "NOT_FULL: punts from >=90 and per-play safety probabilities are catalog clauses",
 "NFL:nfl.own_one_yard_line_snap_rate": "NOT_FULL: the opponent-adjusted negative-binomial rate (punting, goal-line stands, penalties) is the catalog output; only the snap count exists",
 "NFL:nfl.two_minute_tempo": "NOT_FULL: points per two-minute drive, opponent adjustment and QB prior are catalog clauses",
 "NFL:nfl.safety_risk": "NOT_FULL: pick-six / return-TD rates, sack-rate adjustment and punter hang time are catalog clauses",
 "TENNIS:ten.straight_set_share_curve": "NOT_FULL: shrink toward a logistic fit is a stated catalog clause; a pooled share is used instead",
 "TENNIS:ten.set_count_distribution_by_edge": "NOT_FULL: the monotone logistic fit in logit(p) is the stated shrink target; not implemented",
 "TENNIS:ten.tiebreak_base_rate_by_event": "NOT_FULL: 'provide split by round and best_of' is a catalog clause; best_of enters only the tour prior",
 "TENNIS:ten.round_upset_calibration": "NOT_FULL: the logistic correction with round dummies is a catalog clause",
 "TENNIS:ten.venue_speed_history": "NOT_FULL: shrink toward the previous-year event effect and the continuous speed index are catalog clauses; coverage 0.563",
 "TENNIS:ten.slam_to_slam_carryover": "NOT_FULL: column coverage 0.17 (< 0.5; majors only) and the ratio to marginal title probabilities / model-implied shrink are catalog clauses",
 "TENNIS:ten.player_set_drop_propensity": "NOT_FULL: round and format terms are catalog clauses (the split-sample persistence test is a pre-use validation, not an input quantity, but the terms are not implemented)",
 "TENNIS:ten.retirement_timing_profile": "NOT_FULL: P(count>k) for every strike k and the censoring flag are catalog clauses",
 "TENNIS:ten.home_slam_depth_prior": "NOT_FULL: no declared gap, but column coverage 0.16 (majors only) fails the >= 0.5 gate; the gate is not relaxed",
 "TENNIS:ten.surface_rating": "NOT_FULL: no blind match; the catalog's K schedule (new players, tour experience, best-of-5 weight), Challenger/ITF results and layoff decay are not implemented (flat K=24 Elo)",
 "MLB:mlb.sp_two_strike_putaway": "NOT_FULL: the pitcher- and batter-level r2/c2 with log5 combination over the confirmed order is the catalog definition; only team-level rates exist",
 "MLB:mlb.max_velocity_extreme_distribution": "NOT_FULL: the per-pitcher peaks-over-threshold generalized Pareto fit and P(speed >= T) per threshold is the catalog output; only an empirical max-speed column exists",
 "NHL:nhl.series_ot_count_dependence": "NOT_FULL: column coverage 0.07 (series only) and the reg_tie_model pregame tie probability and length-conditioned pmf are catalog clauses",
 "CBB:cbb.tempo": "NOT_FULL: the tempo-control adjustment and garbage-time filter are catalog clauses",
 "TENNIS:ten.retirement_margin_state": "NOT_FULL (candidate REJECTED by the gate in Phase 9): every measurement clause is implemented, blind exact match on 4 columns, coverage 0.999, 2000-2026, replay clean (a full replay with the claim raised to FULL was run and was identical apart from the claim) - but the catalog itself records pregame_knowable = 'partial' and the gate requires 'yes'; the earlier 'censoring' gap belonged to ten.retirement_timing_profile. Stays PARTIAL; the gate was not relaxed",
}


def first_failure(row: dict, audit_row: dict, rp: dict | None) -> tuple[str, list[str]]:
    ev = row["evidence"]; ind = ev.get("independent") or {}
    bad = []
    if not ind or any(v != "MATCH" for v in ind.values()): bad.append("S1 no complete blind exact match")
    if row["pit_verdict"] != "PIT_SAFE" or audit_row.get("pregame_knowable") != "yes": bad.append(f"S2 not PIT_SAFE/pregame ({row['pit_verdict']})")
    t = (rp or {}).get("tests", {}); cov = t.get("coverage_replay") or {}
    mc = cov.get("min_coverage_new", (ev.get("replay") or {}).get("coverage_min"))
    if mc is None or mc < 0.5 or cov.get("constant_columns") or ev.get("limits"): bad.append(f"S3 coverage/limits (min coverage {mc})")
    h = audit_row.get("history") or {}
    first = (cov.get("first_new") or (ev.get("replay") or {}).get("first") or "")[:4]; last = (cov.get("last_new") or (ev.get("replay") or {}).get("last") or "")[:4]
    try:
        if not (h.get("complete") and int(first) <= int(h["first"]) and int(last) >= int(h["last"]) - 1): bad.append("S4 history shorter than the catalog's")
    except (ValueError, TypeError, KeyError):
        bad.append("S4 history not determinable")
    if (rp or {}).get("missing_claimed"): bad.append("S5 builder declares missing: " + "; ".join(rp["missing_claimed"]))
    return (bad[0].split(" ")[0] if bad else "PASS"), bad


def build() -> dict:
    vc = json.loads((M.DF / "verified_coverage.json").read_text())["rows"]; aud = {r["key"]: r for r in json.loads((M.DF / "input_audit.json").read_text())["rows"]}
    rep = {}
    for sp, d in V.load_replays().items():
        for iid, x in d["inputs"].items(): rep[f"{x['sport']}:{iid}"] = x
    for sp, d in V.load_ext_replays().items():
        for iid, x in d["inputs"].items(): rep[f"{sp}:{iid}"] = x
    rows = []
    for r in vc:
        promoted = (r["evidence"].get("promoted_from") == "VERIFIED_PARTIAL") and r["verified_status"] == "VERIFIED_FULL"
        if r["verified_status"] != "VERIFIED_PARTIAL" and not promoted: continue
        stage, bad = first_failure(r, aud[r["key"]], rep.get(r["key"])) if not promoted else ("PROMOTED", [])
        review = REVIEW.get(r["key"])
        if review is None and stage == "S5":
            review = f"NOT_FULL: {len(bad[0].split(';'))} declared unimplemented component(s) (see failures); screened from the builder's own declared list, not individually clause-certified (individual review is recorded for inputs with at most 2 declared gaps)"
        rows.append({"key": r["key"], "status": "VERIFIED_FULL" if promoted else "VERIFIED_PARTIAL", "first_failed_stage": stage, "failures": bad, "review": review})
    c = Counter(x["first_failed_stage"] for x in rows)
    cleared = [x["key"] for x in rows if x["first_failed_stage"] in ("S5", "PROMOTED") or (x["first_failed_stage"] == "PASS")]
    return {"schema": "full-promotion-audit-1.0", "status": "RESEARCH_ONLY", "note": "deterministic stage screen plus recorded clause review; promotion only via certification records; agent review, not human",
            "partial_rows_audited": len(rows), "first_failed_stage_counts": dict(sorted(c.items())), "full_via_certification_from_partial": sorted(x["key"] for x in rows if x["first_failed_stage"] == "PROMOTED"),
            "cleared_s1_to_s4_reviewed": sorted(k for k in (x["key"] for x in rows) if any(y["key"] == k and y["first_failed_stage"] in ("S5", "PASS", "PROMOTED") for y in rows)), "rows": rows}


def main() -> int:
    r = build(); OUT.write_text(json.dumps(r, indent=1, sort_keys=True) + "\n"); print(json.dumps({k: r[k] for k in ("partial_rows_audited", "first_failed_stage_counts", "full_via_certification_from_partial")}, indent=1)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

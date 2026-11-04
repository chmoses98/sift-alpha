#!/usr/bin/env python3
"""Output gate for the shadow-order ledger job: a green workflow without VALID output is not success.  RESEARCH ONLY.

    validate_shadow_output.py --ledger L.jsonl --state extract/state.json --health OUT_health.json [--runs runs.jsonl --append-run]

Fails (exit 1) when the ledger is missing/empty/unparseable or any row violates the point-in-time rules:
  * PLACED: KXNFLGAME-* contract, side YES, bid < ask inside (0,1), placed strictly before kickoff AND no later than the ledger's close cutoff
            (kickoff - 15 min), recorded_at >= placed_at (nothing recorded before it happened), decision_id equals its recomputed digest, unique;
            ``prospective`` is TRUE exactly when recorded within PROSPECTIVE_GRACE_S of the decision quote (a decision rebuilt later from the archive is
            RETROSPECTIVE_REPLAY and is never counted as prospective).
  * OBSERVED: refers to a known decision, observed_at >= placed_at and < kickoff, evidence is a bound/touch class, never a fill.
  * SETTLED: refers to a known decision; its close quote is at/before the close cutoff.
Writes health.json (counts + freshness) and, with --append-run, appends one line per job run to runs.jsonl so multiple scheduled runs are provable.
Source freshness is reported (``capture_age_minutes`` from the newest ingested capture run id) and flagged, not hidden.
"""
import argparse, collections, datetime as dt, json, os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_research import shadow_orders as SO            # noqa: E402

CLOSE_CUTOFF_S = 15 * 60
PROSPECTIVE_GRACE_S = 1800
EVIDENCE_OK = {"TAPE_FILL_BOUND_LO", "TAPE_FILL_BOUND_UP", "TAPE_TOUCH"}


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def validate(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None, ["LEDGER_MISSING_OR_EMPTY"]
    errs, placed, c = [], {}, collections.Counter()
    rows = []
    for i, l in enumerate(open(path), 1):
        if not l.strip():
            continue
        try:
            rows.append(json.loads(l))
        except ValueError:
            errs.append(f"UNPARSEABLE_LINE_{i}")
    for r in rows:
        if r.get("kind") != "PLACED":
            continue
        c["placed"] += 1
        ko, pa, ra = ts(r["kickoff"]), ts(r["placed_at"]), ts(r["recorded_at"])
        bad = []
        if not str(r.get("ticker", "")).startswith("KXNFLGAME-"): bad.append("CONTRACT")
        if r.get("side") != "YES": bad.append("SIDE")
        if not (0 < r["bid"] < r["ask"] < 1): bad.append("QUOTE")
        if not pa <= ko - CLOSE_CUTOFF_S: bad.append("PLACED_AFTER_CLOSE_CUTOFF")
        if ra < pa: bad.append("RECORDED_BEFORE_PLACED")
        if SO.decision_id(r) != r["decision_id"]: bad.append("DECISION_ID")
        if r["decision_id"] in placed: bad.append("DUPLICATE")
        want = (ra - pa) <= PROSPECTIVE_GRACE_S
        if bool(r.get("prospective")) != want or r.get("generation") != ("PROSPECTIVE" if want else "RETROSPECTIVE_REPLAY"): bad.append("PROSPECTIVE_FLAG")
        if bad:
            errs.append(f"PLACED_{r['decision_id'][:8]}:{'+'.join(bad)}")
            continue
        placed[r["decision_id"]] = r
        c["prospective" if want else "retrospective"] += 1
    for r in rows:
        k = r.get("kind")
        if k == "OBSERVED":
            d = placed.get(r["decision_id"])
            if d is None: errs.append("OBSERVED_UNKNOWN_DECISION"); continue
            if r.get("evidence") not in EVIDENCE_OK: errs.append("OBSERVED_EVIDENCE_CLASS"); continue
            if not ts(d["placed_at"]) <= ts(r["observed_at"]) < ts(d["kickoff"]): errs.append("OBSERVED_OUTSIDE_WINDOW"); continue
            c["observed"] += 1
        elif k == "SETTLED":
            d = placed.get(r["decision_id"])
            if d is None: errs.append("SETTLED_UNKNOWN_DECISION"); continue
            cq = r.get("close_quote_at")
            if cq and ts(cq) > ts(d["kickoff"]) - CLOSE_CUTOFF_S: errs.append("SETTLED_CLOSE_AFTER_CUTOFF"); continue
            c["settled"] += 1
    c["contracts"] = len({d["ticker"] for d in placed.values()})
    c["games"] = len({d["game_id"] for d in placed.values()})
    if c["placed"] == 0:
        errs.append("NO_PLACED_ROWS")
    return dict(c), errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True); ap.add_argument("--state", required=True); ap.add_argument("--health", required=True)
    ap.add_argument("--runs"); ap.add_argument("--append-run", action="store_true")
    a = ap.parse_args(argv)
    counts, errs = validate(a.ledger)
    now = dt.datetime.now(dt.timezone.utc)
    st = json.load(open(a.state)) if os.path.exists(a.state) else {}
    last = st.get("last_run_id") or ""
    age = None
    if last:
        age = round((now - dt.datetime.strptime(last, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds() / 60, 1)
    health = dict(schema="sift-shadow-health/1", generated_at=now.isoformat(timespec="seconds"), valid=not errs, errors=sorted(set(errs))[:20], error_count=len(errs),
                  counts=counts or {}, last_ingested_capture_run=last or None, capture_age_minutes=age, capture_stale=(age is None or age > 120),
                  note="prospective = recorded within 30 min of the decision quote; RETROSPECTIVE_REPLAY rows are archive rebuilds and are never counted as prospective evidence")
    json.dump(health, open(a.health, "w"), indent=1, sort_keys=True)
    if a.runs and a.append_run:
        with open(a.runs, "a") as fh:
            fh.write(json.dumps(dict(at=health["generated_at"], github_run_id=os.environ.get("GITHUB_RUN_ID"), event=os.environ.get("GITHUB_EVENT_NAME"),
                                     valid=health["valid"], placed=counts.get("placed", 0) if counts else 0, prospective=counts.get("prospective", 0) if counts else 0,
                                     last_ingested_capture_run=last or None), sort_keys=True) + "\n")
    print(json.dumps({k: health[k] for k in ("valid", "error_count", "counts", "capture_age_minutes", "capture_stale")}, sort_keys=True))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

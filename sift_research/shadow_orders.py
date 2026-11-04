"""Prospective shadow-order ledger (research only). Logs what a resting/taker order WOULD have been, immutably, before the
outcome and before the fill are known; later `resolve_fill` appends what the tape/real book showed. Nothing is ever sent to
an exchange: there is no client, key or order call in this module, and records carry ``status = RESEARCH_ONLY``.

Record kinds (append-only JSONL, one object per line, never rewritten):
  PLACED   decision-time snapshot: ticker, side, action, limit, bid/ask/mid + sizes at decision, fair p & se, model_version,
           hours_to_kickoff, fee model version, decision_id = sha256 of the canonical content (idempotent re-runs)
  OBSERVED fill evidence appended later: kind in {TAPE_TOUCH, TAPE_FILL_BOUND_LO, TAPE_FILL_BOUND_UP, BOOK_CROSS}; never 'FILLED'
           unless the evidence class is OBSERVED_BOOK (our own order state), which this module cannot create
  SETTLED  outcome + realised hypothetical P&L; settlement is joined by the evaluator, never by the placer
Point-in-time rule: PLACED.placed_at must precede kickoff and every OBSERVED.observed_at must be >= placed_at.
"""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone

STATUS = "RESEARCH_ONLY"
VERSION = "sift-shadow-orders/1"
EVIDENCE = ("TAPE_TOUCH", "TAPE_FILL_BOUND_LO", "TAPE_FILL_BOUND_UP", "BOOK_CROSS")


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def decision_id(rec: dict) -> str:
    keys = ("ticker", "side", "action", "limit", "placed_at", "model_version", "horizon")
    return hashlib.sha256(_canon({k: rec.get(k) for k in keys}).encode()).hexdigest()[:32]


def placed(*, ticker, side, action, limit, placed_at: datetime, kickoff: datetime, bid, ask, bid_size=None, ask_size=None,
           p, p_se, model_version, horizon, qty=1):
    if placed_at.tzinfo is None or kickoff.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    if not placed_at < kickoff:
        raise ValueError("a shadow order must be placed strictly before kickoff")
    if action not in ("BUY_NOW", "LIMIT", "WAIT", "PASS"):
        raise ValueError("unknown action")
    r = dict(kind="PLACED", version=VERSION, status=STATUS, ticker=ticker, side=side, action=action, limit=limit,
             placed_at=placed_at.astimezone(timezone.utc).isoformat(), kickoff=kickoff.astimezone(timezone.utc).isoformat(),
             bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, p=p, p_se=p_se, model_version=model_version,
             horizon=horizon, qty=qty, fee_model="kalshi_general_2026:taker0.07,maker0.0175:MODELLED")
    r["decision_id"] = decision_id(r)
    return r


def observed(decision: dict, *, evidence: str, observed_at: datetime, price=None, size=None, queue_ahead_assumed=None):
    if evidence not in EVIDENCE:
        raise ValueError(f"evidence must be one of {EVIDENCE}; a shadow order is never recorded as 'FILLED'")
    placed_at = datetime.fromisoformat(decision["placed_at"])
    if observed_at < placed_at:
        raise ValueError("evidence precedes placement (look-ahead)")
    return dict(kind="OBSERVED", version=VERSION, status=STATUS, decision_id=decision["decision_id"], evidence=evidence,
                observed_at=observed_at.astimezone(timezone.utc).isoformat(), price=price, size=size,
                queue_ahead_assumed=queue_ahead_assumed)


def settled(decision: dict, *, win: int, settled_at: datetime):
    return dict(kind="SETTLED", version=VERSION, status=STATUS, decision_id=decision["decision_id"], win=int(win),
                settled_at=settled_at.astimezone(timezone.utc).isoformat())


def append(path: str, rec: dict) -> bool:
    """Append once (idempotent on decision_id+kind+evidence+observed_at). Returns True when a line was written."""
    key = (rec["kind"], rec["decision_id"], rec.get("evidence"), rec.get("observed_at"))
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            if (r["kind"], r["decision_id"], r.get("evidence"), r.get("observed_at")) == key:
                return False
    with open(path, "a") as f:
        f.write(_canon(rec) + "\n")
    return True


def evaluate(path: str):
    """Join PLACED+OBSERVED+SETTLED and report per-action counts, touch/fill-bound rates and hypothetical P&L (cents/contract)."""
    placed_, obs, sett = {}, {}, {}
    for l in open(path):
        r = json.loads(l)
        if r["kind"] == "PLACED": placed_[r["decision_id"]] = r
        elif r["kind"] == "OBSERVED": obs.setdefault(r["decision_id"], []).append(r)
        elif r["kind"] == "SETTLED": sett[r["decision_id"]] = r
    out = {}
    for did, p in placed_.items():
        a = out.setdefault(p["action"], dict(n=0, touched=0, fill_lo=0, fill_up=0, settled=0, pnl_up_cents=0.0, pnl_lo_cents=0.0))
        a["n"] += 1
        ev = {e["evidence"] for e in obs.get(did, [])}
        a["touched"] += "TAPE_TOUCH" in ev
        lo, up = "TAPE_FILL_BOUND_LO" in ev, "TAPE_FILL_BOUND_UP" in ev or "TAPE_FILL_BOUND_LO" in ev
        a["fill_lo"] += lo; a["fill_up"] += up
        if did in sett:
            a["settled"] += 1
            price = p["limit"] if p["limit"] is not None else p["ask"]
            pnl = (sett[did]["win"] - price) * 100
            a["pnl_up_cents"] += pnl * up; a["pnl_lo_cents"] += pnl * lo
    return dict(status=STATUS, by_action=out, note="fills are tape-bound estimates, never observed order state")

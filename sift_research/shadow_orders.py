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
VERSION = "sift-shadow-orders/2"
EVIDENCE = ("TAPE_TOUCH", "TAPE_FILL_BOUND_LO", "TAPE_FILL_BOUND_UP", "BOOK_CROSS")


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def decision_id(rec: dict) -> str:
    keys = ("ticker", "side", "action", "limit", "placed_at", "model_version", "horizon")
    return hashlib.sha256(_canon({k: rec.get(k) for k in keys}).encode()).hexdigest()[:32]


def placed(*, ticker, side, action, limit, placed_at: datetime, kickoff: datetime, bid, ask, bid_size=None, ask_size=None,
           p, p_se, model_version, horizon, qty=1, fallback="NONE"):
    if placed_at.tzinfo is None or kickoff.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    if not placed_at < kickoff:
        raise ValueError("a shadow order must be placed strictly before kickoff")
    if action not in ("BUY_NOW", "LIMIT", "WAIT", "PASS"):
        raise ValueError("unknown action")
    r = dict(kind="PLACED", version=VERSION, status=STATUS, ticker=ticker, side=side, action=action, limit=limit,
             placed_at=placed_at.astimezone(timezone.utc).isoformat(), kickoff=kickoff.astimezone(timezone.utc).isoformat(),
             bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, p=p, p_se=p_se, model_version=model_version,
             horizon=horizon, qty=qty, fallback=fallback,
             fee_model="taker0.07 CONFIRMED(PR26); maker M0/M25/M100 SCENARIOS (sift_exec.fees)")
    r["decision_id"] = decision_id(r)
    return r


def observed(decision: dict, *, evidence: str, observed_at: datetime, price=None, size=None, queue_ahead_assumed=None):
    if evidence not in EVIDENCE:
        raise ValueError(f"evidence must be one of {EVIDENCE}; a shadow order is never recorded as 'FILLED'")
    placed_at = datetime.fromisoformat(decision["placed_at"])
    if observed_at < placed_at:
        raise ValueError("evidence precedes placement (look-ahead)")
    if observed_at >= datetime.fromisoformat(decision["kickoff"]):
        raise ValueError("evidence at/after kickoff cannot fill a pre-game order")
    return dict(kind="OBSERVED", version=VERSION, status=STATUS, decision_id=decision["decision_id"], evidence=evidence,
                observed_at=observed_at.astimezone(timezone.utc).isoformat(), price=price, size=size,
                queue_ahead_assumed=queue_ahead_assumed)


def settled(decision: dict, *, win: int, settled_at: datetime, close_bid=None, close_ask=None):
    """``close_bid``/``close_ask``: the final valid pre-start two-sided quote of the held side (dollars); required to evaluate WAIT and the fallback."""
    return dict(kind="SETTLED", version=VERSION, status=STATUS, decision_id=decision["decision_id"], win=int(win),
                settled_at=settled_at.astimezone(timezone.utc).isoformat(), close_bid=close_bid, close_ask=close_ask)


class Ledger:
    """O(1) idempotent appender for bulk writers (``append`` rescans the file on every call: quadratic for thousands of rows)."""
    def __init__(self, path):
        self.path, self.keys = path, set()
        if os.path.exists(path):
            with open(path) as f:
                for l in f:
                    r = json.loads(l); self.keys.add((r["kind"], r["decision_id"], r.get("evidence"), r.get("observed_at")))
        self.f = open(path, "a")

    def append(self, rec):
        k = (rec["kind"], rec["decision_id"], rec.get("evidence"), rec.get("observed_at"))
        if k in self.keys:
            return False
        self.keys.add(k); self.f.write(_canon(rec) + "\n"); return True

    def close(self):
        self.f.close()


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


def evaluate(path: str, maker_scenarios=None):
    """Join PLACED+OBSERVED+SETTLED and report, per action, counts, exposure and FEE-ADJUSTED hypothetical P&L bounds (cents, totals).

    v2 corrections (sift-shadow-orders/2; the v1 evaluator was fee-free, mis-labelled P&L bounds and ignored quantity, BUY_NOW and WAIT):
      * fees are charged: taker 0.07 on BUY_NOW / WAIT / fallback takes, maker coefficient scenario (M0, M25, M100) on resting fills; whole-order cent rounding
      * fill status is a RANGE [fill_lo, fill_up] in contracts: LO / BOOK_CROSS evidence => fill_lo; UP (or LO) evidence => fill_up; a TOUCH alone is never a fill
      * P&L bounds are min/max of the P&L at fill_lo and at fill_up (a larger fill is NOT a larger P&L when the contract loses); the old pnl_up/pnl_lo
        multiplied one P&L by the fill flag and so reported the worse outcome as the 'lower fill bound' result
      * quantity is respected (observed ``size`` caps a LO fill); BUY_NOW is taken at the quote (capped by displayed ask size), WAIT at the close ask
      * ``fallback == "TAKE_AT_CLOSE"`` buys the unfilled remainder at the close ask (equal-exposure maker->taker); otherwise unfilled = no bet
      * decisions without settlement, or needing a close quote that is missing, are COUNTED as unevaluable, never silently zero
    """
    from sift_exec import fees as FE
    scen = maker_scenarios or FE.SCENARIOS
    placed_, obs, sett = {}, {}, {}
    for l in open(path):
        r = json.loads(l)
        if r["kind"] == "PLACED": placed_[r["decision_id"]] = r
        elif r["kind"] == "OBSERVED": obs.setdefault(r["decision_id"], []).append(r)
        elif r["kind"] == "SETTLED": sett[r["decision_id"]] = r
    out = {}
    for did, p in placed_.items():
        a = out.setdefault(p["action"], dict(n=0, settled=0, unevaluable_no_settlement=0, unevaluable_no_close=0, touched=0, fill_lo=0, fill_up=0,
                                             fill_unresolved=0, exposure_contracts_lo=0.0, exposure_contracts_up=0.0, net_pnl_cents={k: dict(worst=0.0, best=0.0) for k in scen}))
        a["n"] += 1
        ev = obs.get(did, [])
        kinds = {e["evidence"] for e in ev}
        a["touched"] += "TAPE_TOUCH" in kinds
        if did not in sett:
            a["unevaluable_no_settlement"] += 1; continue
        st = sett[did]; win = st["win"]; q = float(p.get("qty") or 1)
        if win is None:                       # result not known yet: counted, never scored as a loss
            a["outcome_pending"] = a.get("outcome_pending", 0) + 1
            continue
        close_ask = st.get("close_ask")
        act, limit, ask = p["action"], p["limit"], p["ask"]
        need_close = act == "WAIT" or (act == "LIMIT" and p.get("fallback") == "TAKE_AT_CLOSE")
        if need_close and close_ask is None:
            a["unevaluable_no_close"] += 1; continue
        a["settled"] += 1
        if act == "PASS":
            continue
        if act == "BUY_NOW":
            flo = min(q, float(p["ask_size"])) if p.get("ask_size") else q; fup = q
        elif act == "LIMIT":
            lo_ev = [e for e in ev if e["evidence"] in ("TAPE_FILL_BOUND_LO", "BOOK_CROSS")]
            up_ev = [e for e in ev if e["evidence"] in ("TAPE_FILL_BOUND_UP", "TAPE_FILL_BOUND_LO", "BOOK_CROSS")]
            flo = min(q, max((float(e["size"]) if e.get("size") else q) for e in lo_ev)) if lo_ev else 0.0
            fup = q if up_ev else flo
        else:   # WAIT
            flo = fup = q
        a["fill_lo"] += flo > 0; a["fill_up"] += fup > 0; a["fill_unresolved"] += fup > flo
        a["exposure_contracts_lo"] += flo; a["exposure_contracts_up"] += fup
        for name, coef in scen.items():
            pnls = []
            for f in (flo, fup):
                if act == "BUY_NOW":
                    c = int(round(ask * 100)); pnl = f * (win * 100 - c) - 100 * FE.order_fee(c, f, FE.TAKER_COEF)
                elif act == "WAIT":
                    c = int(round(close_ask * 100)); pnl = f * (win * 100 - c) - 100 * FE.order_fee(c, f, FE.TAKER_COEF)
                else:
                    c = int(round(limit * 100)); pnl = f * (win * 100 - c) - 100 * FE.order_fee(c, f, coef)
                    if p.get("fallback") == "TAKE_AT_CLOSE" and q - f > 1e-9:
                        k = int(round(close_ask * 100)); pnl += (q - f) * (win * 100 - k) - 100 * FE.order_fee(k, q - f, FE.TAKER_COEF)
                pnls.append(pnl)
            a["net_pnl_cents"][name]["worst"] += min(pnls); a["net_pnl_cents"][name]["best"] += max(pnls)
    return dict(status=STATUS, version=VERSION, by_action=out,
                note="fills are tape-bound estimates, never observed order state; P&L is fee-adjusted (taker 0.07; maker scenarios M0/M25/M100) held to settlement")

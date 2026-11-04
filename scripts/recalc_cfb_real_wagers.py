#!/usr/bin/env python3
"""Re-measure CFB real wagers with the canonical CLV measures.

    recalc_cfb_real_wagers.py --accounting <accounting-data checkout> --join-rows rows.json --out out.json

Inputs
  accounting/wagers/<season>.jsonl, settlements/<season>.jsonl, settlement_amendments/<season>.jsonl
      fee-exclusive VWAP ``execution_price``, ``fees_paid``, ``stake`` (= price*contracts + fees), settlement economics
  rows.json  per-wager output of cfb-edge-finder ``scripts/cfb_evidence_join.py --rows-out`` : last catalog snapshot
      before kickoff that lists the market (a CLOSING PROXY with its lag), side bid/ask, kickoff
The proxy is accepted as a close only when it is two-sided, uncrossed, strictly before kickoff and <= ``--max-age``
seconds old (default 3600 = the join's own NEAR_CLOSE threshold).  Everything else is counted as unverifiable.
Aggregates only are printed/written; per-wager rows are never emitted.
"""
import argparse, json, os, re, sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sift_clv import canonical as C, historical as H  # noqa: E402

EVENT_RE = re.compile(r"^[A-Z0-9]+-(\d{2}[A-Z]{3}\d{2}[A-Z0-9]+)-")


def jl(path):
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def yes_axis(side, side_bid, side_ask):
    b, a = C.D(side_bid), C.D(side_ask)
    if side == "YES":
        return b, a
    return (None if a is None else 1 - a), (None if b is None else 1 - b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounting", required=True)
    ap.add_argument("--join-rows", required=True)
    ap.add_argument("--season", default="2026")
    ap.add_argument("--max-age", type=int, default=3600)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    W = jl(os.path.join(a.accounting, "wagers", f"{a.season}.jsonl"))
    S = {s["source_bet_key"]: s for s in jl(os.path.join(a.accounting, "settlements", f"{a.season}.jsonl"))}
    A = {x["amends_settlement_id"]: x for x in jl(os.path.join(a.accounting, "settlement_amendments", f"{a.season}.jsonl"))}
    text = open(a.join_rows).read()
    try:
        rows = json.loads(text)
        rows = rows["rows"] if isinstance(rows, dict) else rows
    except ValueError:                       # JSON Lines, one evidence row per line
        rows = [json.loads(l) for l in text.splitlines() if l.strip()]
    J = {r["source_bet_key"]: r for r in rows}
    obs, proxy_states = [], {}
    for w in W:
        r = J.get(w["source_bet_key"], {})
        cp = r.get("close_proxy") or {}
        proxy_states[cp.get("state", "NO_JOIN_ROW")] = proxy_states.get(cp.get("state", "NO_JOIN_ROW"), 0) + 1
        t = w["market_ticker"]
        start = ts(cp.get("kickoff"))
        q = None
        if cp.get("side_bid") is not None or cp.get("side_ask") is not None:
            yb, ya = yes_axis(w["side"], cp.get("side_bid"), cp.get("side_ask"))
            q = C.Quote(t, yb, ya, ts(cp.get("captured_at")))
        executed = ts(w["executed_at"])
        # kickoff unknown (game in no archived snapshot) is MISSING EVIDENCE, not 'live entry': keep it eligible so it
        # is counted under its real reason (NO_CLOSE) instead of being silently excluded.
        pregame = True if start is None else bool(executed and executed < start)
        s = S.get(w["source_bet_key"])
        net_filed = gross = None
        if s and s.get("settlement_status") == "SETTLED" and s.get("net_profit_loss") is not None:
            gross, net_filed = C.D(s["gross_return"]), C.D(s["net_profit_loss"])
        m = EVENT_RE.match(t)
        obs.append(H.Obs(
            wager_id=w["wager_id"], ticker=t, side=w["side"], contracts=C.D(w["contracts"]), price=C.D(w["execution_price"]),
            fees=C.D(w["fees_paid"]), stake=C.D(w["stake"]), game=(m.group(1) if m else "?"),
            family=t.split("-")[0], start=start, close=q, entry_eligible=pregame, gross_return=gross, net_recorded=net_filed))
    res = H.summarize(obs, max_close_age_seconds=a.max_age, label="CFB real wagers 2026 (owner-placed, router fills)")
    res["close_proxy_states"] = dict(sorted(proxy_states.items()))
    res["note"] = ("closes are last pre-kickoff catalog snapshots (lag-labelled proxies); selection CLV unverifiable: "
                   "no recommendation->order link. 'net_as_recorded' is the FILED v1/v2 net, amendments are not applied here.")
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps({k: res[k] for k in ("wagers", "entry_eligible", "verified_clv_observations",
                                           "unverifiable_by_reason", "close_proxy_states", "actual_execution_clv",
                                           "fee_per_contract", "fee_adjusted_difference")}, indent=1, default=str))


if __name__ == "__main__":
    main()

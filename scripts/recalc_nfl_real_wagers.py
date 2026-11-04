#!/usr/bin/env python3
"""Re-measure NFL real wagers with the canonical CLV measures from RAW inputs.

    recalc_nfl_real_wagers.py --postmortem season.actual_wagers.json --closes-root <md>/data/shadow/v2/closes --out out.json

Wager rows come from the NFL actual-wager postmortem (ledger fields: fee-exclusive VWAP, entry fees, stake, settlement).
Close quotes are re-read from the canonical closes files (raw yes_bid / yes_ask / observed time), NOT taken from the
postmortem's precomputed close mid, so the recomputation is independent of the published CLV.
"""
import argparse, glob, gzip, json, os, sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sift_clv import canonical as C, historical as H  # noqa: E402


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def load_closes(root, tickers):
    want, out = set(tickers), {}
    for path in sorted(glob.glob(os.path.join(root, "*", "*.closes_v2.jsonl.gz"))):
        with gzip.open(path, "rt") as fh:
            for line in fh:
                if not any(t in line for t in want):
                    continue
                r = json.loads(line)
                if r.get("ticker") in want and r.get("close_status") in ("CLOSE_OK", "CLOSE_ONE_SIDED"):
                    # keep the latest observation per ticker (canonical closes are one per contract; be defensive)
                    prev = out.get(r["ticker"])
                    if prev is None or (r.get("price_observed_at") or "") >= (prev.get("price_observed_at") or ""):
                        out[r["ticker"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--postmortem", required=True)
    ap.add_argument("--closes-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    doc = json.load(open(a.postmortem))
    rows = doc["wagers"]
    closes = load_closes(a.closes_root, [w["market_ticker"] for w in rows])
    obs = []
    for w in rows:
        c = closes.get(w["market_ticker"])
        start = ts(c["kickoff_utc"]) if c else None
        q = C.Quote.of(w["market_ticker"], c.get("yes_bid"), c.get("yes_ask"), ts(c.get("price_observed_at"))) if c else None
        held_to_settle = w.get("settlement_state") == "SETTLED" and w.get("transaction_role") == "OPEN" \
            and w.get("execution_action") == "BUY"
        obs.append(H.Obs(
            wager_id=w["imported_wager_id"], ticker=w["market_ticker"], side=w["side"], contracts=C.D(w["contracts"]),
            price=C.D(w["execution_price"]), fees=C.D(w["fees"]), stake=C.D(w["stake"]), game=w.get("game") or "?",
            family=w.get("family") or "?", start=start, close=q,
            entry_eligible=bool(w.get("clv_eligible")),
            gross_return=C.D(w["gross_return"]) if held_to_settle else None,
            net_recorded=C.D(w["recorded_net_profit_loss"]) if held_to_settle else None))
    res = {"nfl_real_wagers": H.summarize(obs, label="NFL real wagers 2026 (owner-placed, router fills)")}
    # published ("before") figures, passed through untouched
    t = doc["totals"]
    res["published_before"] = {"clv": t["clv"], "established_subset": t["established_subset"], "fees": t["fees"],
                               "recorded_economics_versions": t["recorded"]["economics_versions"]}
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps(res, indent=1, sort_keys=True, default=str)[:6000])


if __name__ == "__main__":
    main()

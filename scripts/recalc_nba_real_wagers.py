#!/usr/bin/env python3
"""Re-measure NBA real wagers with the canonical CLV measures, closes rebuilt from the hash-chained market archive.

    recalc_nba_real_wagers.py --archive <nba data-archive checkout> --nba-repo <nba-edge-finder checkout> \
        --accounting <nba accounting-data checkout> --out out.json

Close = the board reconstructed by ``nba_edge.archive.reconstruct.reconstruct_at`` at (tip - 1s): the last captured
tick strictly before the start, point-in-time safe (only artifacts observed at or before that instant are read) and
fail-closed (a broken delta chain raises).  Start = the EARLIER of the scheduled start and any recorded actual tip, so
a close can only be earlier than the true start, never later.  The close must be a two-sided, uncrossed quote of the
SAME ticker and no older than --max-age seconds.  Aggregates only; no per-wager rows are emitted.
"""
import argparse, gzip, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sift_clv import canonical as C, historical as H  # noqa: E402

EVENT_RE = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})-")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def jl(path):
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def load_schedule(archive):
    games = {}
    for p in sorted(Path(archive, "context", "schedule").glob("dt=*/*.jsonl.gz")):
        with gzip.open(p, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                k = (r["game_date_et"], r["away_tricode"], r["home_tricode"])
                prev = games.get(k)
                if prev is None or r["_observed_at_utc"] >= prev["_observed_at_utc"]:
                    games[k] = r
    return games


def dollars(x):
    return C.D(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    ap.add_argument("--nba-repo", required=True)
    ap.add_argument("--accounting", required=True)
    ap.add_argument("--max-age", type=int, default=3600)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.nba_repo, "src"))
    from nba_edge.archive.reconstruct import reconstruct_at  # noqa: E402

    W = jl(os.path.join(a.accounting, "data", "accounting", "wagers.jsonl"))
    S = {s["source_bet_key"]: s for s in jl(os.path.join(a.accounting, "data", "accounting", "settlements.jsonl"))}
    sched = load_schedule(a.archive)
    boards, board_err = {}, defaultdict(int)
    obs, why = [], defaultdict(int)
    for w in W:
        t = w["market_ticker"]
        m = EVENT_RE.match(t)
        start = close = None
        if m:
            yy, mon, dd, away, home = m.groups()
            g = sched.get((f"20{yy}-{MONTHS[mon]:02d}-{dd}", away, home))
            if g:
                start = ts(g["start_time_utc"])
                if g.get("actual_tip_utc"):
                    start = min(start, ts(g["actual_tip_utc"]))
            else:
                why["GAME_NOT_IN_SCHEDULE_ARCHIVE"] += 1
        else:
            why["TICKER_NOT_PARSEABLE"] += 1
        if start is not None:
            at = start - timedelta(seconds=1)
            key = at.isoformat()
            if key not in boards:
                try:
                    rec = reconstruct_at(Path(a.archive), at)
                    boards[key] = (rec.observed_at_utc, {r["ticker"]: r for r in rec.rows})
                except Exception as e:  # fail closed: a broken/missing chain is evidence we do not have
                    boards[key] = None
                    board_err[type(e).__name__] += 1
            b = boards[key]
            if b is not None:
                row = b[1].get(t)
                if row is not None:
                    close = C.Quote(t, dollars(row.get("yes_bid_dollars")), dollars(row.get("yes_ask_dollars")), ts(b[0]))
                else:
                    why["TICKER_NOT_ON_PREGAME_BOARD"] += 1
        executed = ts(w["executed_at"])
        pregame = True if start is None else bool(executed and executed < start)
        s = S.get(w["source_bet_key"])
        gross = net = None
        if s and s.get("settlement_status") == "SETTLED" and s.get("net_profit_loss") is not None:
            gross, net = C.D(s["gross_return"]), C.D(s["net_profit_loss"])
        obs.append(H.Obs(wager_id=w["wager_id"], ticker=t, side=w["side"], contracts=C.D(w["contracts"]),
                         price=C.D(w["execution_price"]), fees=C.D(w["fees_paid"]), stake=C.D(w["stake"]),
                         game=(m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5)) if m else "?",
                         family=t.split("-")[0], start=start, close=close, entry_eligible=pregame,
                         gross_return=gross, net_recorded=net))
    res = H.summarize(obs, max_close_age_seconds=a.max_age, label="NBA real wagers 2026 (owner-placed, router fills)")
    res["close_source"] = "nba_edge.archive.reconstruct.reconstruct_at(start-1s): checkpoint+hash-verified deltas"
    res["evidence_gaps"] = dict(sorted(why.items()))
    res["reconstruction_errors"] = dict(sorted(board_err.items()))
    res["distinct_boards_reconstructed"] = sum(1 for v in boards.values() if v is not None)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps({k: res[k] for k in ("wagers", "entry_eligible", "verified_clv_observations",
                                           "unverifiable_by_reason", "evidence_gaps", "reconstruction_errors",
                                           "distinct_boards_reconstructed", "actual_execution_clv",
                                           "fee_per_contract", "fee_adjusted_difference")}, indent=1, default=str))


if __name__ == "__main__":
    main()

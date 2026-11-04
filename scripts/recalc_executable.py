#!/usr/bin/env python3
"""Executable-purchase CLV of REAL wagers for NFL / CFB / NBA / NHL (sift-clv-executable/1).  Aggregates only.

    recalc_executable.py --sport nfl --postmortem season.actual_wagers.json --closes-root R1 R2 --books-dir DIR --out out.json
    recalc_executable.py --sport cfb --accounting DIR --join-rows rows.json --out out.json
    recalc_executable.py --sport nba|nhl --archive DIR --repo SPORT_REPO --accounting DIR --out out.json

Fills are the router's fee-exclusive VWAP with the exchange-reported entry fee. The close is the same quote the midpoint
recalculations use (two-sided, uncrossed, same ticker, strictly pre-start, <= 3600 s); its ASK and BID of the held side
are the new benchmarks. Closing depth comes ONLY from an archived order book of the same ticker observed strictly before
the start (NFL capture ``books.jsonl`` of the close's own run; NBA/NHL hash-verified order-book chain). CFB has top-of-book
catalog proxies only, so its size-adjusted measure is reported as unavailable, never approximated.
"""
import argparse, glob, gzip, importlib, json, os, re, sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from sift_clv import canonical as C, executable as X, historical as H, historical_exec as HE  # noqa: E402


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def jl(path):
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


def levels_from_row(row):
    """Resting bids as (price_dollars, size) pairs for YES and NO from either archive shape."""
    fp = (row.get("orderbook_fp") or (row.get("raw") or {}).get("orderbook_fp"))
    if fp:
        return fp.get("yes_dollars") or [], fp.get("no_dollars") or []
    f = lambda ls: [(C.D(p) / 100, s) for p, s in (ls or [])]                       # noqa: E731
    return f(row.get("yes")), f(row.get("no"))


# ------------------------------------------------------------------------------------------------------------- NFL
def nfl(a):
    import recalc_nfl_real_wagers as R
    rows = json.load(open(a.postmortem))["wagers"]
    closes = R.load_closes(a.closes_root, [w["market_ticker"] for w in rows])
    books = {}
    for path in glob.glob(os.path.join(a.books_dir, "*.jsonl")):
        run = os.path.basename(path)[:-6]
        for line in open(path):
            if line.strip():
                r = json.loads(line)
                books[(run, r["ticker"])] = r
    obs = []
    for w in rows:
        t = w["market_ticker"]
        c = closes.get(t)
        start = ts(c["kickoff_utc"]) if c else None
        q = C.Quote.of(t, c.get("yes_bid"), c.get("yes_ask"), ts(c.get("price_observed_at"))) if c else None
        b = None
        if c:
            br = books.get((c.get("price_source_run"), t))
            if br:
                y, n = levels_from_row(br)
                b = X.Book.of(t, y, n, ts(br.get("observed_at")))
        held = w.get("settlement_state") == "SETTLED" and w.get("transaction_role") == "OPEN" and w.get("execution_action") == "BUY"
        obs.append(H.Obs(wager_id=w["imported_wager_id"], ticker=t, side=w["side"], contracts=C.D(w["contracts"]),
                         price=C.D(w["execution_price"]), fees=C.D(w["fees"]), stake=C.D(w["stake"]),
                         game=w.get("game") or "?", family=w.get("family") or "?", start=start, close=q,
                         entry_eligible=bool(w.get("clv_eligible")), executed_at=ts(w.get("executed_at")), book=b))
    return obs, "NFL real wagers 2026"


# ------------------------------------------------------------------------------------------------------------- CFB
EVENT_CFB = re.compile(r"^[A-Z0-9]+-(\d{2}[A-Z]{3}\d{2}[A-Z0-9]+)-")


def cfb(a):
    W = jl(os.path.join(a.accounting, "wagers", "2026.jsonl"))
    text = open(a.join_rows).read()
    try:
        j = json.loads(text); j = j["rows"] if isinstance(j, dict) else j
    except ValueError:
        j = [json.loads(l) for l in text.splitlines() if l.strip()]
    J = {r["source_bet_key"]: r for r in j}
    obs = []
    for w in W:
        cp = (J.get(w["source_bet_key"], {}) or {}).get("close_proxy") or {}
        t, start, q = w["market_ticker"], ts(cp.get("kickoff")), None
        if cp.get("side_bid") is not None or cp.get("side_ask") is not None:
            sb, sa = C.D(cp.get("side_bid")), C.D(cp.get("side_ask"))
            yb, ya = (sb, sa) if w["side"] == "YES" else ((None if sa is None else 1 - sa), (None if sb is None else 1 - sb))
            q = C.Quote(t, yb, ya, ts(cp.get("captured_at")))
        ex = ts(w["executed_at"])
        m = EVENT_CFB.match(t)
        obs.append(H.Obs(wager_id=w["wager_id"], ticker=t, side=w["side"], contracts=C.D(w["contracts"]),
                         price=C.D(w["execution_price"]), fees=C.D(w["fees_paid"]), stake=C.D(w["stake"]),
                         game=(m.group(1) if m else "?"), family=t.split("-")[0], start=start, close=q,
                         entry_eligible=True if start is None else bool(ex and ex < start), executed_at=ex))
    return obs, "CFB real wagers 2026"


# --------------------------------------------------------------------------------------------------------- NBA / NHL
EVENT = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)-")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
SPORTS = {"nba": {"pkg": "nba_edge", "away": "away_tricode", "home": "home_tricode", "label": "NBA", "alias": {}},
          "nhl": {"pkg": "nhl_edge", "away": "away_abbrev", "home": "home_abbrev", "label": "NHL",
                  "alias": {"LAK": "LA", "NJD": "NJ", "TBL": "TB", "SJS": "SJ"}}}


def archive_sport(a):
    cfg = SPORTS[a.sport]
    sys.path.insert(0, os.path.join(a.repo, "src"))
    rec = importlib.import_module(cfg["pkg"] + ".archive.reconstruct")
    games = {}
    for p in sorted(Path(a.archive, "context", "schedule").glob("dt=*/*.jsonl.gz")):
        with gzip.open(p, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                al = cfg["alias"]
                k = (r["game_date_et"], al.get(r[cfg["away"]], r[cfg["away"]]) + al.get(r[cfg["home"]], r[cfg["home"]]))
                if k not in games or r["_observed_at_utc"] >= games[k]["_observed_at_utc"]:
                    games[k] = r
    W = jl(os.path.join(a.accounting, "data", "accounting", "wagers.jsonl"))
    boards, obboards = {}, {}
    obs = []
    for w in W:
        t = w["market_ticker"]
        m = EVENT.match(t)
        start = q = book = None
        if m:
            yy, mon, dd, teams = m.groups()
            g = games.get((f"20{yy}-{MONTHS[mon]:02d}-{dd}", teams))
            if g:
                start = ts(g["start_time_utc"])
                if g.get("actual_tip_utc"):
                    start = min(start, ts(g["actual_tip_utc"]))
        if start is not None:
            at = start - timedelta(seconds=1)
            key = at.isoformat()
            if key not in boards:
                try:
                    r = rec.reconstruct_at(Path(a.archive), at)
                    boards[key] = (r.observed_at_utc, {x["ticker"]: x for x in r.rows})
                except Exception:                                   # fail closed
                    boards[key] = None
                try:
                    r = rec.reconstruct_at(Path(a.archive), at, checkpoint_kind="kalshi/orderbooks", delta_kind="kalshi/orderbooks_delta")
                    obboards[key] = (r.observed_at_utc, {x["ticker"]: x for x in r.rows})
                except Exception:
                    obboards[key] = None
            if boards[key] and t in boards[key][1]:
                row = boards[key][1][t]
                q = C.Quote(t, C.D(row.get("yes_bid_dollars")), C.D(row.get("yes_ask_dollars")), ts(boards[key][0]))
            if obboards[key] and t in obboards[key][1]:
                y, n = levels_from_row(obboards[key][1][t])
                book = X.Book.of(t, y, n, ts(obboards[key][0]))
        ex = ts(w["executed_at"])
        obs.append(H.Obs(wager_id=w["wager_id"], ticker=t, side=w["side"], contracts=C.D(w["contracts"]),
                         price=C.D(w["execution_price"]), fees=C.D(w["fees_paid"]), stake=C.D(w["stake"]),
                         game=(m.group(1) + m.group(2) + m.group(3) + m.group(4)) if m else "?", family=t.split("-")[0],
                         start=start, close=q, entry_eligible=True if start is None else bool(ex and ex < start),
                         executed_at=ex, book=book))
    return obs, f"{cfg['label']} real wagers 2026"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=["nfl", "cfb", "nba", "nhl"])
    ap.add_argument("--postmortem"); ap.add_argument("--closes-root", nargs="+"); ap.add_argument("--books-dir")
    ap.add_argument("--accounting"); ap.add_argument("--join-rows")
    ap.add_argument("--archive"); ap.add_argument("--repo")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    obs, label = {"nfl": nfl, "cfb": cfb}.get(a.sport, archive_sport)(a)
    res = HE.summarize(obs, label=label)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    o = res["overall"]
    print(a.sport, "verified", res["verified"], "of", res["entry_eligible"], "reasons", res["unverifiable_by_reason"])
    for m in ("executable_purchase_clv", "midpoint_execution_clv", "liquidation_clv"):
        print(" ", m, o[m].get("mean"), o[m].get("game_cluster_ci95_cents"))
    print("  decomposition", o.get("cost_decomposition_cents_vs_close_mid"))
    print("  depth", json.dumps(res["depth"]["depth_status_counts"]))


if __name__ == "__main__":
    main()

"""Recover Kalshi's OWN settlement result per contract and cross-check it against a repo's computed settlements.

Why: the MLB, NBA and NHL archives store settlements computed by each repo's own engine from the box score; their
market snapshots hold active markets only, so the exchange's `result` is never preserved.  The public market-data
API still serves it for recently settled markets, but older settled markets leave that listing, so the window is
finite.

MANUAL, RESEARCH_ONLY.  No schedule, no credentials (public read-only endpoint), writes only to --out (a local
directory outside any repository unless the owner chooses otherwise).  Nothing here places or prices an order.

    python -m alpha_engine.game_completeness.kalshi_official fetch --series KXNHLGAME KXNHLTOTAL --out OUT
    python -m alpha_engine.game_completeness.kalshi_official compare --official OUT --computed 'ARCHIVE/settlements/*/*.jsonl.gz'
"""
import argparse
import glob
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.elections.kalshi.com/trade-api/v2/markets"
KEEP = ("ticker", "event_ticker", "status", "result", "expiration_value", "settlement_value_dollars", "close_time",
        "settlement_ts", "rules_primary", "rules_secondary")


def fetch_series(series, out, max_pages=200, pause=1.0, opener=urllib.request.urlopen):
    """Page through settled markets of one series; one JSONL row per contract with the retrieval timestamp."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cursor, n, pages = "", 0, 0
    with open(out / f"{series}.jsonl", "w", encoding="utf-8") as fh:
        while pages < max_pages:
            q = {"series_ticker": series, "status": "settled", "limit": 1000}
            if cursor:
                q["cursor"] = cursor
            req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "research-readonly"})
            for attempt in range(6):                              # back off on rate limiting; never hammer
                try:
                    with opener(req, timeout=60) as r:
                        d = json.loads(r.read())
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 5:
                        raise
                    time.sleep(pause and 5 * (attempt + 1))
            got = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for m in d.get("markets", []):
                fh.write(json.dumps({**{k: m.get(k) for k in KEEP}, "_retrieved_at_utc": got, "_source": API}) + "\n")
                n += 1
            pages += 1
            cursor = d.get("cursor") or ""
            if not cursor or not d.get("markets"):
                break
            time.sleep(pause)
    return {"series": series, "contracts": n, "pages": pages, "truncated": bool(cursor)}


def load_official(folder):
    off = {}
    for f in sorted(Path(folder).glob("*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            off[r["ticker"]] = r
    return off


def compare(official, computed):
    """official: {ticker: row with 'result'}; computed: {ticker: 'YES'|'NO'|other}.
    Only YES/NO vs yes/no pairs are judged; anything else is reported, never forced into agree/disagree."""
    c = Counter()
    disagree = []
    for t, out in computed.items():
        o = official.get(t)
        if o is None:
            c["computed_without_official"] += 1
            continue
        res = (o.get("result") or "").lower()
        if out not in ("YES", "NO"):
            c["official_available_for_unsettleable"] += res in ("yes", "no")
            c["computed_not_binary"] += 1
        elif res not in ("yes", "no"):
            c["official_not_binary"] += 1
        elif res == out.lower():
            c["agree"] += 1
        else:
            c["disagree"] += 1
            disagree.append(t)
    c["official_without_computed"] = sum(1 for t in official if t not in computed)
    return {"counts": dict(c), "disagreements": sorted(disagree)[:200]}


def _computed(pattern, ticker="ticker", outcome=("outcome", "result")):
    out = {}
    for f in sorted(glob.glob(pattern, recursive=True)):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t = r.get(ticker) or r.get("marketTicker")
                v = next((r[k] for k in outcome if r.get(k) is not None), None)
                if t:
                    out[t] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--series", nargs="+", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--max-pages", type=int, default=200)
    c = sub.add_parser("compare")
    c.add_argument("--official", required=True)
    c.add_argument("--computed", required=True, help="glob of computed settlement .jsonl[.gz]")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        for s in a.series:
            print(json.dumps(fetch_series(s, a.out, a.max_pages)))
    else:
        print(json.dumps(compare(load_official(a.official), _computed(a.computed)), indent=1))


if __name__ == "__main__":
    main()

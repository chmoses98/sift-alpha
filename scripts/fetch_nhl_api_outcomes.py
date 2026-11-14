#!/usr/bin/env python3
"""Fetch the OFFICIAL NHL public web API (api-web.nhle.com, free, no key) boxscore + play-by-play for a list of game ids into a
local cache directory, for the independent outcome verification in ``alpha_eval.nhl_archive``. RESEARCH_ONLY; run by hand only
(no schedule). Raw responses stay local (never committed); the report records a sha256 roll-up of the cache.

usage: python3 -I scripts/fetch_nhl_api_outcomes.py --game-ids ids.txt --out <cache dir> [--sleep 0.3]
Generic User-Agent; polite sequential requests; existing files are not re-fetched (pass --refresh to re-fetch)."""
import argparse, json, os, sys, time, urllib.request

BASE = "https://api-web.nhle.com/v1/gamecenter/{gid}/{kind}"
UA = "sift-alpha-research/1.0 (outcome verification)"


def fetch(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retried, then reported
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-ids", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--sleep", type=float, default=0.3); ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    ids = sorted({l.strip() for l in open(a.game_ids) if l.strip()})
    os.makedirs(a.out, exist_ok=True)
    n_new = n_fail = 0
    for gid in ids:
        for kind in ("boxscore", "play-by-play"):
            p = os.path.join(a.out, f"{gid}_{kind}.json")
            if os.path.exists(p) and not a.refresh:
                continue
            try:
                body = fetch(BASE.format(gid=gid, kind=kind))
                json.loads(body)
                with open(p, "wb") as fh:
                    fh.write(body)
                n_new += 1
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                print(f"FAIL {gid} {kind}: {type(e).__name__}", file=sys.stderr)
            time.sleep(a.sleep)
    print(json.dumps(dict(games=len(ids), fetched=n_new, failed=n_fail)))


if __name__ == "__main__":
    main()

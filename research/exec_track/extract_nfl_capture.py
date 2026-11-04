#!/usr/bin/env python3 -I
"""Stream the NFL 2026 live-capture (market-data branch data/kalshi/capture/<day>/*.{quotes,books,trades}.jsonl) into compact,
de-duplicated extracts for the game-winner and spread series.  Reads one day at a time via a sparse checkout of a PARTIAL clone and
deletes it afterwards (a day is ~1.4 GB raw).  usage: extract_nfl_capture.py CLONE_DIR OUT_DIR [day ...]
Trades are de-duplicated on trade_id (each capture run re-fetches overlapping windows).  The extract keeps `run_id` so that capture
cadence/coverage can be audited.  No private data: public market observations only."""
import json, os, subprocess, sys, glob, shutil
SERIES = ("KXNFLGAME-", "KXNFLSPREAD-")

def main(clone, out, days):
    os.makedirs(out, exist_ok=True)
    seen_path = os.path.join(out, "seen_trade_ids.txt")
    seen = set(open(seen_path).read().split()) if os.path.exists(seen_path) else set()
    if not days:
        names = subprocess.check_output(["git", "-C", clone, "ls-tree", "-d", "--name-only", "FETCH_HEAD:data/kalshi/capture"], text=True).split()
        days = sorted(names)
    done = set(open(os.path.join(out, "days_done.txt")).read().split()) if os.path.exists(os.path.join(out, "days_done.txt")) else set()
    for day in days:
        if day in done:
            continue
        subprocess.check_call(["git", "-C", clone, "sparse-checkout", "set", f"/data/kalshi/capture/{day}/"])
        subprocess.check_call(["git", "-C", clone, "checkout", "-q", "FETCH_HEAD"])
        d = os.path.join(clone, "data/kalshi/capture", day)
        counts = {}
        for kind in ("quotes", "books", "trades"):
            n = 0
            with open(os.path.join(out, f"{kind}.jsonl"), "a") as fo:
                for f in sorted(glob.glob(os.path.join(d, f"*.{kind}.jsonl"))):
                    for line in open(f):
                        i = line.find('"ticker":"')
                        if i < 0 or not line[i + 10:i + 10 + 11].startswith(SERIES[0][:9]):
                            continue
                        if not (line[i + 10:].startswith(SERIES[0]) or line[i + 10:].startswith(SERIES[1])):
                            continue
                        if kind == "trades":
                            r = json.loads(line)
                            if r["trade_id"] in seen:
                                continue
                            seen.add(r["trade_id"])
                            line = json.dumps(r, separators=(",", ":")) + "\n"
                        fo.write(line if line.endswith("\n") else line + "\n"); n += 1
            counts[kind] = n
        open(seen_path, "w").write("\n".join(seen))
        open(os.path.join(out, "days_done.txt"), "a").write(day + "\n")
        print(day, counts, flush=True)
        shutil.rmtree(d, ignore_errors=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])

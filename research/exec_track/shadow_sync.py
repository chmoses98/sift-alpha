#!/usr/bin/env python3
"""Incremental sync of the live capture into a compact KXNFLGAME extract for the shadow-order ledger (research only, read-only git).
usage: shadow_sync.py --clone PARTIAL_CLONE_OF_market-data --extract-dir DIR [--since-days 9]
Lists capture run files by NAME (blobless clone: no content downloaded), selects only quotes/trades runs newer than ``state.json:last_run_id`` (a day of capture is ~1.4 GB; a run is ~15 MB),
sparse-checks-out just those files, appends KXNFLGAME quotes and PRE-KICKOFF trades (de-duplicated on trade_id) to ``quotes.jsonl`` / ``trades.jsonl`` and advances the state.
Files whose run id is not strictly greater than the state are never re-read, so the job is O(new runs)."""
import argparse, datetime as dt, json, os, re, subprocess, sys

RUN = re.compile(r"data/kalshi/capture/(\d{4}-\d{2}-\d{2})/(\d{8}T\d{6}Z)\.(quotes|trades)\.jsonl$")


def sh(cmd, cwd):
    return subprocess.check_output(cmd, cwd=cwd, text=True)


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--clone", required=True); ap.add_argument("--extract-dir", required=True); ap.add_argument("--since-days", type=int, default=9)
    ap.add_argument("--max-runs", type=int, default=60)
    a = ap.parse_args(argv)
    os.makedirs(a.extract_dir, exist_ok=True)
    sp = os.path.join(a.extract_dir, "state.json")
    st = json.load(open(sp)) if os.path.exists(sp) else {"last_run_id": "", "ko": {}, "seen_trades": 0}
    names = sh(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"], a.clone).splitlines()
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.since_days)).strftime("%Y-%m-%d")
    runs = {}
    for n in names:
        m = RUN.search(n)
        if m and m.group(1) >= cutoff and m.group(2) > st["last_run_id"]:
            runs.setdefault(m.group(2), {})[m.group(3)] = n
    todo = sorted(runs)[: a.max_runs]
    if not todo:
        print(json.dumps({"new_runs": 0, "last_run_id": st["last_run_id"]})); return 0
    paths = [p for r in todo for p in runs[r].values()]
    sh(["git", "sparse-checkout", "init", "--no-cone"], a.clone)
    sh(["git", "sparse-checkout", "set", "--no-cone"] + ["/" + p for p in paths], a.clone)
    sh(["git", "checkout", "-q", "FETCH_HEAD"], a.clone)
    seen = set(json.load(open(os.path.join(a.extract_dir, "seen_ids.json")))) if os.path.exists(os.path.join(a.extract_dir, "seen_ids.json")) else set()
    nq = nt = 0
    with open(os.path.join(a.extract_dir, "quotes.jsonl"), "a") as fq, open(os.path.join(a.extract_dir, "trades.jsonl"), "a") as ft:
        for r in todo:
            if "quotes" in runs[r]:
                for l in open(os.path.join(a.clone, runs[r]["quotes"])):
                    if '"series_ticker":"KXNFLGAME"' in l:
                        d = json.loads(l); st["ko"][d["ticker"]] = ts(d["kickoff_utc"]); fq.write(l if l.endswith("\n") else l + "\n"); nq += 1
            if "trades" in runs[r]:
                for l in open(os.path.join(a.clone, runs[r]["trades"])):
                    if '"KXNFLGAME-' not in l:
                        continue
                    d = json.loads(l)
                    k = st["ko"].get(d["ticker"])
                    if d["trade_id"] in seen or (k is not None and ts(d["created_time"]) >= k):
                        continue               # pre-kickoff prints only (a pre-start shadow order never needs in-game prints); duplicates dropped
                    seen.add(d["trade_id"]); ft.write(json.dumps(d, separators=(",", ":")) + "\n"); nt += 1
            st["last_run_id"] = r
    json.dump(sorted(seen), open(os.path.join(a.extract_dir, "seen_ids.json"), "w"))
    json.dump(st, open(sp, "w"), separators=(",", ":"))
    print(json.dumps({"new_runs": len(todo), "quotes": nq, "trades": nt, "last_run_id": st["last_run_id"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

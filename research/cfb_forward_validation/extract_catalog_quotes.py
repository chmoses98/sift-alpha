"""Extract pre-kickoff Kalshi CFB executable quotes from cfb-edge-finder's committed catalog history (RESEARCH_ONLY).

cfb-edge-finder commits the public Kalshi CFB catalog (`data/live/games/<GAMEKEY>.json`, every market with yes/no ask
and bid and displayed size) roughly every 30 minutes. Each commit is therefore a timestamped quote snapshot.

Rules (fixed before scoring anything):
  * snapshot time = the COMMIT time (the capture happened before it, so this is conservative);
  * for each game the LAST commit that changed its file with 15 min <= kickoff - commit_time <= 24 h is used;
    a game whose file did not change in that window is dropped, never filled from an older snapshot;
  * only markets with status "active" and both asks strictly inside (0, 1) are kept;
  * nothing is interpolated or invented; NO-side depth is the YES bid size (buying NO at no_ask = selling YES at yes_bid).

  python research/cfb_forward_validation/extract_catalog_quotes.py --repo ../cfb-edge-finder --ref origin/main \
      --since 2026-10-04 --until 2026-11-20 --out research/cfb_forward_validation/quotes_2026_wk6plus.jsonl.gz
(the cfb-edge-finder clone needs history back to --since; a blob-less partial fetch is enough.)
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

PREFIX = "data/live/games/"
MIN_LEAD, MAX_LEAD = timedelta(minutes=15), timedelta(hours=24)
KEEP = ("market_ticker", "event_ticker", "series_ticker", "family", "period", "strike_type", "floor_strike", "cap_strike",
        "yes_sub_title", "no_sub_title", "yes_ask", "no_ask", "yes_bid", "no_bid", "yes_ask_size", "yes_bid_size", "updated_time")


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def show(repo: str, sha: str, path: str) -> str | None:
    """File content at a commit, or None if the path does not exist there. Lazy partial-clone fetches are retried."""
    for attempt in range(3):
        r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        if "does not exist" in r.stderr or "exists on disk, but not in" in r.stderr:
            return None
    raise RuntimeError(f"git show {sha}:{path} failed: {r.stderr.strip()[:300]}")


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def history(repo: str, ref: str, since: str, until: str) -> dict[str, list[tuple[str, datetime]]]:
    out: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    sha = when = None
    for line in git(repo, "log", ref, f"--since={since}", f"--until={until}", "--format=@@%H %cI", "--name-only", "--", PREFIX).splitlines():
        if line.startswith("@@"):
            sha, iso = line[2:].split(" ", 1); when = ts(iso)
        elif line.startswith(PREFIX) and line.endswith(".json"):
            out[line].append((sha, when))
    return out


def snapshot(repo: str, path: str, commits: list[tuple[str, datetime]]) -> list[dict] | None:
    commits = sorted(commits, key=lambda c: c[1])
    game = None
    for sha, _ in reversed(commits):  # latest existing version tells us the final kickoff (the last change may be a deletion)
        txt = show(repo, sha, path)
        if txt is not None:
            game = json.loads(txt); break
    if game is None or not game.get("kickoff"):
        return None
    kick = ts(game["kickoff"])
    ok = [(s, w) for s, w in commits if MIN_LEAD <= kick - w <= MAX_LEAD]
    if not ok:
        return None
    raw = None
    for sha, when in reversed(ok):  # a change can be the file's deletion: fall back to the previous change in the window
        raw = show(repo, sha, path)
        if raw is not None:
            break
    if raw is None:
        return None
    g = json.loads(raw)
    if ts(g["kickoff"]) != kick:  # kickoff moved after this snapshot: the quote was for a different start time
        return None
    blob = git(repo, "rev-parse", f"{sha}:{path}").strip()
    base = {"game_key": g["game_key"], "title": g.get("title"), "kickoff": g["kickoff"], "season_week": (g.get("identity") or {}).get("season_week"),
            "division": (g.get("identity") or {}).get("division"), "commit": sha, "snapshot_time": when.isoformat().replace("+00:00", "Z"),
            "lead_min": round((kick - when).total_seconds() / 60, 1), "blob": blob, "blob_sha256": hashlib.sha256(raw.encode()).hexdigest()}
    rows = []
    for m in g.get("markets") or []:
        if m.get("status") != "active":
            continue
        ya, na = m.get("yes_ask"), m.get("no_ask")
        if ya is None or na is None or not (0 < ya < 1 and 0 < na < 1):
            continue
        rows.append({**base, **{k: m.get(k) for k in KEEP}, "football_team": (m.get("custom_strike") or {}).get("football_team")})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True); ap.add_argument("--ref", default="origin/main"); ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True); ap.add_argument("--out", required=True); ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    hist = history(a.repo, a.ref, a.since, a.until)
    with ThreadPoolExecutor(a.workers) as pool:
        results = list(pool.map(lambda kv: snapshot(a.repo, *kv), sorted(hist.items())))
    n_games = 0
    with gzip.open(a.out, "wt") as fh:
        for rows in results:
            if rows:
                n_games += 1
                for r in rows:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
    print(json.dumps({"game_files_seen": len(hist), "games_with_pre_kickoff_snapshot": n_games}))


if __name__ == "__main__":
    main()

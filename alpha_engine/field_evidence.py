"""Field-level evidence: does the newest archived file of a directory actually contain the fields an input needs, populated?

Replaces keyword matching. For each SPEC (sport, input, archive dir, required keys) it reads up to N records of the newest
file under the directory in the sport's archive branch and reports, per required key, the share of records where it is
present and non-null, plus the record timestamp field found and the directory's file count / date range.
Usage: python -m alpha_engine.field_evidence SRC_ROOT OUT_JSON  (needs the sport repos cloned and network to the git proxy)."""
import gzip, json, re, subprocess, sys
from pathlib import Path

REPO = {"NFL": "/home/user/nfl-edge-finder", "NBA": "nba-edge-finder", "NHL": "NHL-edge-finder", "SOCCER": "soccer-edge-finder", "CFB": "cfb-edge-finder", "MLB": "edge-finder-api", "TENNIS": "Tennis-Edge-Finder"}
SPECS = [
 # sport, input, branch, dir, required keys
 ("NHL", "nhl.pace", "data-archive", "context/team_games", ["corsiPercentage", "fenwickPercentage"]),
 ("NHL", "nhl.xg_against", "data-archive", "context/team_games", ["xGoalsPercentage"]),
 ("NHL", "nhl.opp_supp", "data-archive", "context/team_summary", ["goalsAgainstPerGame"]),
 ("NHL", "nhl.venue", "data-archive", "context/schedule", ["venue", "neutral_site"]),
 ("NHL", "nhl.goalie_start", "data-archive", "context/goalie_observations", ["status", "source_reported_at_utc", "observed_at_utc"]),
 ("NBA", "nba.venue", "data-archive", "context/schedule", ["arena", "neutral_site"]),
 ("NBA", "nba.matchup_def", "data-archive", "matchup/context", ["home_scheme", "away_scheme"]),
 ("NBA", "nba.starters_pit", "data-archive", "matchup/context", ["expected_home_starters", "lineup_confidence", "observed_at_utc"]),
 ("NFL", "nfl.depth_chart_pit", "market-data", "data/pit_availability", ["nflverse_depth_charts", "retrieved_at"]),
 ("NFL", "nfl.skill_avail", "market-data", "data/pit_availability", ["espn_event_rosters", "espn_injuries", "retrieved_at"]),
 ("SOCCER", "soc.xg", "data-archive", "results", ["home_xg", "away_xg"]),
 ("SOCCER", "soc.score_state", "data-archive", "results", ["home_red", "away_red"]),
 ("SOCCER", "soc.pace_press", "data-archive", "results", ["home_shots", "away_shots", "home_shots_on_target"]),
 ("SOCCER", "soc.set_pieces", "data-archive", "results", ["home_corners", "away_corners"]),
 ("SOCCER", "soc.referee", "data-archive", "results", ["referee"]),
]
TS = ("captured_at", "observed_at_utc", "_observed_at_utc", "retrieved_at", "as_of", "generated_at", "created_at")


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True)


def records(raw, path, n):
    if path.endswith(".gz"):
        raw = gzip.decompress(raw); path = path[:-3]
    t = raw.decode("utf-8", "replace")
    if path.endswith(".jsonl"):
        return [json.loads(l) for l in t.splitlines()[:n] if l.strip()]
    o = json.loads(t)
    return o if isinstance(o, list) else [o]


def find(o, k, depth=0):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        if depth < 2:
            for v in o.values():
                r = find(v, k, depth + 1)
                if r not in (None, "", [], {}):
                    return r
    return None


def present(r, k):
    return find(r, k) not in (None, "", [], {})


def check(sport, root, branch, dd, keys, n=300):
    d = Path(REPO[sport]) if REPO[sport].startswith("/") else Path(root) / REPO[sport]
    if git(d, "fetch", "-q", "--depth=1", "--filter=blob:none", "origin", branch).returncode:
        return {"error": "fetch failed"}
    fs = sorted(f for f in git(d, "ls-tree", "-r", "--name-only", "FETCH_HEAD").stdout.decode().split("\n") if f.startswith(dd + "/"))
    dates = sorted({m.group(0) for f in fs for m in [re.search(r"20\d\d-\d\d-\d\d", f)] if m})
    if not fs:
        return {"files": 0}
    pick = sorted({fs[-1], *[fs[int(i * (len(fs) - 1) / 4)] for i in range(5)]})     # newest + 5 evenly spaced files
    recs = []
    for f in pick:
        try:
            recs += records(git(d, "show", f"FETCH_HEAD:{f}").stdout[:3_000_000], f, 60)
        except Exception:
            pass
    share = {k: round(sum(present(r, k) for r in recs) / len(recs), 3) if recs else None for k in keys}
    ts = next((k for k in TS if recs and present(recs[0], k)), None)
    return {"files": len(fs), "first": dates[0] if dates else None, "last": dates[-1] if dates else None, "files_sampled": len(pick), "sample": fs[-1], "records_read": len(recs), "key_populated_share": share,
            "timestamp_field": ts, "all_keys_populated_ge_90pct": bool(recs) and all(v is not None and v >= 0.9 for v in share.values()), "commit": git(d, "rev-parse", "FETCH_HEAD").stdout.decode().strip()}


if __name__ == "__main__":
    out = []
    for sp, iid, br, dd, keys in SPECS:
        r = check(sp, sys.argv[1], br, dd, keys); out.append({"sport": sp, "input": iid, "branch": br, "dir": dd, "required_keys": keys, **r})
        print(sp, iid, r.get("files"), r.get("key_populated_share"), r.get("timestamp_field"), file=sys.stderr)
    json.dump({"schema_version": "audit-1.0", "checks": out}, open(sys.argv[2], "w"), indent=1)

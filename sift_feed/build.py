"""Build feed/v1/index.json and feed/v1/<sport>.json from each sport's operating artifact.

    python -m sift_feed.build --mode local  --root /home/user   # existing clones, refs/remotes/origin/<branch>
    python -m sift_feed.build --mode remote [--cache DIR]       # blobless depth-1 caches of the public repos
    python -m sift_feed.build --mode https                      # raw.githubusercontent.com + GitHub API
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import adapters
from .schema import DETAIL_KEYS, SCHEMA_VERSION, classify, iso, parse_ts, validate_game, weakest
from .sources import GitSource, HttpSource, remote_git

INDEX_BUDGET = 150_000
TRIM_HOURS = 36
RETRIEVAL = "https://raw.githubusercontent.com/chmoses98/sift-alpha/projection-feed/feed/v1/index.json"
USAGE = [
    "source_class=production: say 'SIFT projects ...'. source_class=operating_unapproved: say 'SIFT's operating "
    "(not production-approved) <SPORT> model projects ...' and never call it a production forecast.",
    "research[] rows (source_class=research) are not SIFT forecasts; quote them only if explicitly asked, labelled research.",
    "Always give projected_at (UTC) and model_version. Recompute age against the current time (see max_age_note).",
    "Null means the model did not publish that number; do not fill it in or compute it.",
    "Forecasts only: no betting recommendation or authority is implied.",
]
MAX_AGE_NOTE = ("age_hours_at_build and stale are as of generated_at only. Recompute age = now - projected_at against "
                "the current time and treat a game as stale when that exceeds stale_after_hours[sport]; if now - "
                "generated_at exceeds it too, say the feed itself is old. Never quote a game whose start_time has passed "
                "as a pre-game forecast.")


def finalize(sport, mod, res, now):
    """Keep upcoming games, stamp age/staleness/source_class, decide the sport status."""
    max_age = mod.MAX_AGE_HOURS * 3600
    art = res.get("artifact") or {}
    games = []
    for g in res.get("games", []):
        st = parse_ts(g["start_time"])
        if st is None or st <= now:
            continue
        age = None if g["projected_at"] is None else int((now - parse_ts(g["projected_at"])).total_seconds())
        g["age_hours_at_build"] = None if age is None else round(age / 3600, 1)
        g["stale"] = age is None or age > max_age
        g["source_updated_at"] = g["source_updated_at"] or art.get("committed_at")
        problems = validate_game(g)
        if problems:
            raise ValueError(f"{sport} {g['game_id']}: {problems}")
        games.append(g)
    games.sort(key=lambda g: (g["start_time"], g["game_id"]))
    proj = res.get("projected_at")
    age = None if proj is None else int((now - parse_ts(proj)).total_seconds())
    status, reason = res.get("status"), res.get("reason")
    if status is None:
        if age is None or age > max_age:
            status = "stale"
            reason = f"latest source artifact is {age // 3600 if age is not None else '?'}h old (limit {mod.MAX_AGE_HOURS}h)"
            if not games:
                reason += "; it covers no upcoming game"
        else:
            status = "ok"
            reason = None if games else "fresh source artifact, but it covers no upcoming game"
    decl = res.get("declaration")
    cls = res.get("source_class") or weakest([classify(decl)] + [g["source_class"] for g in games])
    summary = {"status": status, "reason": reason, "source_class": cls, "source_declaration": decl,
               "model_version": res.get("model_version"), "projected_at": iso(parse_ts(proj)),
               "age_hours_at_build": None if age is None else round(age / 3600, 1),
               "stale_after_hours": mod.MAX_AGE_HOURS, "source_updated_at": art.get("committed_at"),
               "bet_authority": res.get("bet_authority"), "authority_note": res.get("authority_note"),
               "source": res.get("artifact"), "game_count": len(games), "detail_file": f"{sport.lower()}.json",
               "derivations": sorted({d for g in games for d in g["derived"]})}
    return summary, games, res.get("research") or []


def build_sport(sport, make_source, now):
    mod = adapters.load(sport)
    try:
        srcs = {k: make_source(repo, branch) for k, (repo, branch) in mod.SOURCES.items()}
        res = mod.build(srcs, now)
    except Exception as e:  # one sport failing never blocks the others
        res = {"status": "unavailable", "reason": f"adapter error: {type(e).__name__}: {e}"[:300], "games": []}
    return finalize(sport, mod, res, now)


def index_game(g):
    return {k: v for k, v in g.items() if k not in DETAIL_KEYS}


def assemble(results, now):
    """results: {sport: (summary, games, research)} -> (index, {sport: sport_doc})."""
    gen = iso(now)
    head = {"schema_version": SCHEMA_VERSION, "generated_at": gen, "max_age_note": MAX_AGE_NOTE,
            "stale_after_hours": {s: r[0]["stale_after_hours"] for s, r in results.items()}}
    per_sport, games, research = {}, [], []
    for sport, (summary, gs, rs) in results.items():
        if any(r.get("source_class") != "research" for r in rs):
            raise ValueError(f"{sport}: research rows must carry source_class=research")
        per_sport[sport] = {**head, "sport": sport, "summary": summary, "games": gs, "research": rs}
        games += [index_game(g) for g in gs]
        research += rs
    games.sort(key=lambda g: (g["start_time"], g["sport"], g["game_id"]))
    index = {**head, "retrieval": RETRIEVAL, "usage": USAGE,
             "sports": {s: r[0] for s, r in results.items()}, "games": games, "research": research}
    if size(index) > INDEX_BUDGET:  # research rows move to the sport files first
        index["research"] = []
        index["research_note"] = "research rows omitted from the index for size; see the sport files"
    if size(index) > INDEX_BUDGET:  # then only the next TRIM_HOURS of games stay in the index
        cutoff = iso(now + timedelta(hours=TRIM_HOURS))
        index["games"] = [g for g in games if g["start_time"] <= cutoff]
        index["games_note"] = f"index trimmed to games starting by {cutoff} for size; see the sport files"
    if size(index) > INDEX_BUDGET:
        raise ValueError(f"index.json is {size(index)} bytes, over the {INDEX_BUDGET} budget")
    return index, per_sport


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def size(obj):
    return len(dumps(obj).encode())


def write(out_dir, index, per_sport):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for sport, doc in per_sport.items():
        (out / f"{sport.lower()}.json").write_text(dumps(doc) + "\n")
    (out / "index.json").write_text(dumps(index) + "\n")


def source_factory(mode, root=None, cache=None):
    if mode == "local":
        return lambda repo, branch: GitSource(Path(root) / repo, f"refs/remotes/origin/{branch}")
    if mode == "remote":
        return lambda repo, branch: remote_git(cache, repo, branch)
    if mode == "https":
        return lambda repo, branch: HttpSource(repo, branch)
    raise ValueError(mode)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("local", "remote", "https"), default="remote")
    ap.add_argument("--root", default="/home/user")
    ap.add_argument("--cache", default=str(Path(tempfile.gettempdir()) / "sift-feedcache"))
    ap.add_argument("--out", default="feed/v1")
    ap.add_argument("--now", help="override the build instant (ISO, UTC); default now")
    ap.add_argument("--sports", default=",".join(adapters.SPORTS))
    a = ap.parse_args(argv)
    now = parse_ts(a.now) if a.now else datetime.now(timezone.utc).replace(microsecond=0)
    make = source_factory(a.mode, a.root, a.cache)
    results = {s: build_sport(s, make, now) for s in a.sports.split(",")}
    index, per_sport = assemble(results, now)
    write(a.out, index, per_sport)
    for s, (summary, gs, rs) in results.items():
        print(f"{s}: {summary['status']:<11} {summary['source_class'] or '-':<20} games={len(gs):<3} research={len(rs):<3} {summary['reason'] or ''}")
    print(f"index.json {size(index)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

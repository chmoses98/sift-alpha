"""Re-measure the per-game completeness ledger against the private vault (RESEARCH_ONLY, read-only).

The ledger (`research/game_completeness/<SPORT>/games.csv.gz`) was built from the sport repositories' production
archives before Phase 10 stored postgame records in the private vault.  This module reads RESTORED vault archives,
parses every game's records, and writes a second ledger in which a cell is upgraded only when the vault record for
that game was parsed and passed its content check.  It never downgrades a cell, never edits the original ledger and
never counts a game as complete because a file or a training row exists.

    python -m alpha_engine.game_completeness.vault_overlay --as-of <ts> --out research/game_completeness_vault \
        --mlb-feed DIR... --nhl-scores DIR --cfb-summaries DIR... --cbb-schedules DIR --cbb-recovered DIR \
        --official-root RESTORED --computed MLB=glob NBA=glob NHL=glob

Each cell keeps one of two evidence tiers, reported separately in the summary:
  PRODUCTION_ARCHIVE   the status the original verifier read back from the sport repository;
  VAULT_VERIFIED       upgraded here from parsed vault bytes (durable raw archive, content-checked per game).
Neither tier says anything about training readiness: that is the certification catalog's job.
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .settlement_reconcile import COMPARABLE, load_official

SCHEMA = "game-completeness-vault-overlay-1.0"
LEDGER = Path(__file__).resolve().parents[2] / "research" / "game_completeness"
RANK = {"C": 3, "P": 2, "S": 1, "U": 1, "M": 0}       # '-' (not applicable) and 'R' (rights) are never touched


def _json(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------------------------------------ MLB
def mlb_game(j):
    """Content checks on one compact postgame feed record -> {dataset: 'C'|'P'} (absent = nothing verified)."""
    out = {}
    if (j.get("status") or {}).get("abstractGameState") != "Final":
        return out
    ls = j.get("linescore") or {}
    inn, tot = ls.get("innings") or [], ls.get("teams") or {}
    try:
        sums = {s: sum(int((i.get(s) or {}).get("runs") or 0) for i in inn) for s in ("away", "home")}
        final = {s: int(tot[s]["runs"]) for s in ("away", "home")}
    except (KeyError, TypeError, ValueError):
        sums = final = None
    if inn and final is not None:
        out["inning_linescore"] = "C" if sums == final else "P"
    box = j.get("box") or {}
    sides = [box.get(s) or {} for s in ("away", "home")]
    if all((b.get("team_stats") or {}).get("batting") and (b.get("team_stats") or {}).get("pitching") for b in sides):
        out["team_box"] = "C"
    bat = [sum(1 for p in b.get("players") or [] if p.get("bat")) for b in sides]
    order_ok = all(len(b.get("batting_order") or []) >= 9 and
                   {p["id"] for p in b.get("players") or [] if p.get("bat")} >= set(b.get("batting_order") or []) for b in sides)
    if all(bat):
        out["hitter_box"] = "C" if order_ok else "P"
    pit_ok = all(b.get("pitchers") and {p["id"] for p in b.get("players") or [] if p.get("pit")} >= set(b.get("pitchers") or [])
                 for b in sides)
    if any(b.get("pitchers") for b in sides):
        out["pitcher_box"] = "C" if pit_ok else "P"
    plays = j.get("plays") or []
    if plays:
        last = plays[-1]
        n_pitch = sum(len(p.get("pitches") or []) for p in plays)
        scored = final is not None and (last.get("away"), last.get("home")) == (final["away"], final["home"])
        out["pitch_events"] = "C" if n_pitch and scored else "P"
    return out


def read_mlb(folders):
    obs = {}
    for folder in folders:
        for f in sorted(glob.glob(str(Path(folder) / "*.json*"))):
            if Path(f).name.startswith("_"):
                continue
            j = _json(f)
            obs[str(j.get("pk") or Path(f).name.split(".")[0])] = mlb_game(j)
    return obs


# ------------------------------------------------------------------------------------------------ NHL
def read_nhl(folder):
    """period_scores is verified when the goal-level records (each with its period) add up to the final score."""
    obs = {}
    for f in sorted(glob.glob(str(Path(folder) / "*.json*"))):
        for g in _json(f).get("games") or []:
            if g.get("gameState") not in ("OFF", "FINAL"):
                continue
            goals = g.get("goals") or []
            by = Counter((x.get("teamAbbrev") or {}).get("default") if isinstance(x.get("teamAbbrev"), dict) else x.get("teamAbbrev")
                         for x in goals if (x.get("periodDescriptor") or {}).get("periodType") != "SO")
            try:
                a, h = g["away"], g["home"]
                so = (g.get("gameOutcome") or {}).get("lastPeriodType") == "SO"
                # a shootout adds one goal to the winner's final score that is not a goal record in play
                want = {a["abbrev"]: int(a["score"]), h["abbrev"]: int(h["score"])}
                if so:
                    want[max(want, key=want.get)] -= 1
                ok = all(x.get("period") or (x.get("periodDescriptor") or {}).get("number") for x in goals) and \
                    all(by.get(t, 0) == n for t, n in want.items())
            except (KeyError, TypeError, ValueError):
                continue
            obs[str(g["id"])] = {"period_scores": "C" if ok else "P"}
    return obs


# ------------------------------------------------------------------------------------------------ CFB
def cfb_game(j):
    out = {}
    try:
        comp = j["header"]["competitions"][0]
    except (KeyError, IndexError, TypeError):
        return out
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return out
    out["raw_espn_summary"] = "C"
    cs = comp.get("competitors") or []
    try:
        qs_ok = len(cs) == 2 and all(len(c.get("linescores") or []) >= 4 and
                                     sum(int(x["displayValue"]) for x in c["linescores"]) == int(c["score"]) for c in cs)
    except (KeyError, TypeError, ValueError):
        qs_ok = False
    if any(c.get("linescores") for c in cs):
        out["quarter_scores"] = "C" if qs_ok else "P"
    box = j.get("boxscore") or {}
    teams = [t for t in box.get("teams") or [] if t.get("statistics")]
    if teams:
        out["team_box"] = "C" if len(teams) == 2 else "P"
    players = [p for p in box.get("players") or [] if any(s.get("athletes") for s in p.get("statistics") or [])]
    if players:
        out["player_box"] = "C" if len(players) == 2 else "P"
    drives = ((j.get("drives") or {}).get("previous")) or []
    if drives:
        out["drives"] = "C"
        n_plays = sum(len(d.get("plays") or []) for d in drives)
        if n_plays:
            out["play_by_play"] = "C" if all(d.get("plays") for d in drives) else "P"
    return out


def read_cfb(folders):
    obs = {}
    for folder in folders:
        for f in sorted(glob.glob(str(Path(folder) / "*.json*"))):
            if Path(f).name.startswith("_"):
                continue
            try:
                j = _json(f)
            except ValueError:
                continue
            gid = str(j.get("_id") or Path(f).name.split(".")[0])
            got = cfb_game(j)
            if got:
                obs[gid] = got
    return obs


# ------------------------------------------------------------------------------------------------ CBB
_LS = re.compile(r"'value':\s*([0-9.]+)")


def read_cbb_schedules(folder):
    """half_scores from the schedule's own linescore column: both teams, >= 2 periods, summing to the final."""
    import pandas as pd
    obs = {}
    cols = ["game_id", "status_type_completed", "home_score", "away_score", "home_linescores", "away_linescores"]
    for f in sorted(glob.glob(str(Path(folder) / "**" / "*schedule*.parquet"), recursive=True)):
        import pyarrow.parquet as pq
        if not set(cols) <= set(pq.read_schema(f).names):
            continue                                   # early seasons carry no linescore column: nothing to verify
        d = pd.read_parquet(f, columns=cols)
        for r in d[d["status_type_completed"] == True].to_dict("records"):  # noqa: E712
            ok = True
            for s in ("home", "away"):
                ls = r.get(f"{s}_linescores")
                per = [int(float(x)) for x in _LS.findall(ls)] if isinstance(ls, str) else []
                try:
                    ok = ok and len(per) >= 2 and sum(per) == int(r[f"{s}_score"])
                except (TypeError, ValueError):
                    ok = False
            if ok:
                obs[str(r["game_id"])] = {"half_scores": "C"}
    return obs


def read_cbb_recovered(folder):
    """Recovered ESPN summaries for games the ledger lists without a team box.  A box of zeros is not a box."""
    obs = {}
    for f in sorted(glob.glob(str(Path(folder) / "*.json*"))):
        if Path(f).name.startswith("_"):
            continue
        try:
            j = _json(f)
        except ValueError:
            continue
        teams = (j.get("boxscore") or {}).get("teams") or []
        good = 0
        for t in teams:
            st = {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
            fg = str(st.get("fieldGoalsMade-fieldGoalsAttempted") or st.get("fieldGoalsAttempted") or "")
            m = re.search(r"(\d+)$", fg)
            good += bool(m and int(m.group(1)) > 0)
        if good == 2:
            obs.setdefault(str(j.get("_id") or Path(f).name.split(".")[0]), {})["team_box"] = "C"
    return obs


# ------------------------------------------------------------------------------- Kalshi official results
def read_official_by_game(official_root, sport, computed_glob, id_keys=("game_id", "gameId")):
    """kalshi_settlement_official per game: of the contracts our engine archived for the game, how many have an
    official exchange result in the vault.  All -> C, some -> P.  Nonstandard official settlements count as
    preserved (the official layer has them) even though they are not comparable."""
    official = load_official(official_root, sport)
    per = defaultdict(lambda: [0, 0])
    seen = set()
    for f in sorted(glob.glob(computed_glob, recursive=True)):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t = r.get("ticker") or r.get("marketTicker")
                gid = next((r[k] for k in id_keys if r.get(k)), None)
                if not t or not gid or t in seen:
                    continue
                seen.add(t)
                per[str(gid)][0] += 1
                per[str(gid)][1] += t in official
    return {g: {"kalshi_settlement_official": "C" if n == k else "P"} for g, (n, k) in per.items() if k}


# ------------------------------------------------------------------------------------------------ overlay
def apply(sport, obs, ledger_dir=LEDGER):
    """(csv bytes, summary).  A cell moves only upward and only where the dataset applies to the game."""
    with gzip.open(Path(ledger_dir) / sport / "games.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    keys = [k for k in rows[0] if k not in ("season", "date", "game_id", "state", "overall")]
    before, after, up = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    unknown = sorted(set(obs) - {r["game_id"] for r in rows})
    for r in rows:
        got = obs.get(r["game_id"]) or {}
        for k in keys:
            old = r[k]
            before[k][old] += 1
            new = got.get(k)
            if new and old in RANK and RANK[new] > RANK[old]:
                up[k][f"{old}->{new}"] += 1
                r[k] = new
            after[k][r[k]] += 1
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    raw = buf.getvalue().encode()
    ds = {}
    for k in keys:
        if not up[k]:
            continue
        ds[k] = {"before": dict(before[k]), "after": dict(after[k]), "upgraded_vault_verified": dict(up[k]),
                 "still_missing": after[k].get("M", 0), "still_partial": after[k].get("P", 0),
                 "vault_games_checked": sum(1 for g in obs.values() if k in g),
                 "vault_games_failing_content_check": sum(1 for g in obs.values() if g.get(k) == "P")}
    return raw, {"sport": sport, "ledger_rows": len(rows), "datasets_changed": ds,
                 "datasets_unchanged": [k for k in keys if k not in ds],
                 "vault_games_not_in_ledger": {"n": len(unknown), "examples": unknown[:10]},
                 "note": "'overall' is the original verifier's value and is not recomputed here.",
                 "sha256_uncompressed": hashlib.sha256(raw).hexdigest()}


def merge(*parts):
    out = defaultdict(dict)
    for p in parts:
        for g, d in (p or {}).items():
            for k, v in d.items():
                if RANK[v] > RANK.get(out[g].get(k, "M"), 0) or k not in out[g]:
                    out[g][k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mlb-feed", nargs="*", default=[])
    ap.add_argument("--nhl-scores")
    ap.add_argument("--cfb-summaries", nargs="*", default=[])
    ap.add_argument("--cbb-schedules")
    ap.add_argument("--cbb-recovered")
    ap.add_argument("--official-root")
    ap.add_argument("--computed", nargs="*", default=[], metavar="SPORT=GLOB")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    comp = dict(c.split("=", 1) for c in a.computed)
    obs = {s: {} for s in ("MLB", "NHL", "CFB", "CBB", "NBA")}
    obs["MLB"] = merge(read_mlb(a.mlb_feed) if a.mlb_feed else {})
    obs["NHL"] = merge(read_nhl(a.nhl_scores) if a.nhl_scores else {})
    obs["CFB"] = merge(read_cfb(a.cfb_summaries) if a.cfb_summaries else {})
    obs["CBB"] = merge(read_cbb_schedules(a.cbb_schedules) if a.cbb_schedules else {},
                       read_cbb_recovered(a.cbb_recovered) if a.cbb_recovered else {})
    if a.official_root:
        for s, g in comp.items():
            obs[s] = merge(obs.get(s), read_official_by_game(a.official_root, s, g))
    out = Path(a.out)
    doc = {"schema": SCHEMA, "as_of": a.as_of, "research_only": True,
           "notice": "Agent-run, not human verified. Upgrades only, from parsed vault records; the original ledger is "
                     "unchanged. Completeness of a durable raw archive is not training readiness.",
           "tiers": ["PRODUCTION_ARCHIVE", "VAULT_VERIFIED"], "sports": {}}
    for s, o in obs.items():
        if not o:
            continue
        raw, summ = apply(s, o, a.ledger)
        (out / s).mkdir(parents=True, exist_ok=True)
        with open(out / s / "games.csv.gz", "wb") as fh:
            with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
                gz.write(raw)
        doc["sports"][s] = summ
    (out / "overview.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    for s, v in doc["sports"].items():
        for k, d in v["datasets_changed"].items():
            print(f"{s:4} {k:28} C {d['before'].get('C', 0):>7,} -> {d['after'].get('C', 0):>7,}  M left {d['still_missing']:>7,}  "
                  f"failed check {d['vault_games_failing_content_check']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

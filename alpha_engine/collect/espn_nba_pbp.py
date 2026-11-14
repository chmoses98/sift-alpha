"""ESPN NBA game summaries -> on-court stints, verified against ESPN's own box score (RESEARCH_ONLY, $0, anonymous public GETs, manual only).

Why: the lineup/stint family (``nba.lineup_adj_rating``, ``nba.onoff``, ``nba.player_impact``, ``nba.nonadditive_absence_curve``,
``nba.replacement_level_minutes_absorption``) was BLOCKED_NETWORK in Phase 13 because the official hosts (stats.nba.com, official.nba.com,
cdn.nba.com) refuse this environment. ESPN's public ``summary`` endpoint (site.api.espn.com, reachable) carries play-by-play with explicit
substitution events, starters, per-player minutes and plus-minus, and the game's officials. This module reconstructs who was on the court
for every second and then CHECKS the reconstruction against ESPN's box score (+/- exactly, minutes within rounding), so a stint table is
only trusted for games that pass.

    python -m alpha_engine.collect.espn_nba_pbp fetch --dates 2025-03-01 --cache-dir /tmp/x --max-calls 40
    python -m alpha_engine.collect.espn_nba_pbp verify --cache-dir /tmp/x --out digest.json

Rules (fail closed): no key/account; <= ``HARD_MAX_CALLS`` GETs per invocation, >= ``MIN_PAUSE`` s between calls; 429 backs off then
stops; any other non-200 (except 404 = no data) stops; raw JSON is written gzip-compressed ONLY to a cache directory outside the repository.
Odds / pickcenter / againstTheSpread / winprobability blocks in the payload are NEVER read (market-free policy) and are dropped before caching.
Point in time: stints, minutes, plus-minus, starters and officials are POST-GAME records. They are PIT-safe only as strictly-prior history
(e.g. rolling on/off through the previous game); the ``starter`` flag is as-played, never a pre-game lineup.
Rights: ESPN's terms could not be read here (www.espn.com blocked; robots 403) -> UNRESOLVED_INTERNAL_ONLY. Not scheduled anywhere.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HOST = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = {"User-Agent": "research-client/1.0", "Accept": "application/json"}
HARD_MAX_CALLS = 300
MIN_PAUSE = 1.0
MAX_429 = 3
BACKOFF_429 = (20, 60, 120)
DROP_KEYS = ("pickcenter", "odds", "againstTheSpread", "winprobability", "news", "article", "videos", "broadcasts")
REPO_ROOT = Path(__file__).resolve().parents[2]
REG_PERIOD_S, OT_PERIOD_S = 720, 300


class Stop(RuntimeError):
    """Fail-closed stop."""


def _outside_repo(p: Path) -> Path:
    p = Path(p).resolve()
    if p == REPO_ROOT or REPO_ROOT in p.parents:
        raise PermissionError("cache directory must be outside the repository (raw payloads are never committed)")
    return p


# ---------------------------------------------------------------- pure parsing / reconstruction
def period_len(p: int) -> int:
    return REG_PERIOD_S if p <= 4 else OT_PERIOD_S


def period_start(p: int) -> int:
    return REG_PERIOD_S * min(p - 1, 4) + OT_PERIOD_S * max(p - 5, 0)


def clock_s(v) -> float:
    """'6:52' -> 412.0; '45.3' -> 45.3; '0.0' -> 0.0."""
    s = str(v or "0").strip()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)


def elapsed(play: dict) -> float:
    p = int(play["period"]["number"])
    return period_start(p) + period_len(p) - clock_s((play.get("clock") or {}).get("displayValue"))


def box(summary: dict) -> dict:
    """{athlete_id: {team, starter, min, pm, dnp}} from ESPN's box score (pure)."""
    out = {}
    for t in (summary.get("boxscore") or {}).get("players") or []:
        tid = str(t["team"]["id"])
        for s in t.get("statistics") or []:
            keys = s.get("keys") or []
            for a in s.get("athletes") or []:
                st = dict(zip(keys, a.get("stats") or []))
                def num(k):
                    v = str(st.get(k, "")).replace("+", "")
                    try:
                        return int(float(v))
                    except ValueError:
                        return None
                out[str(a["athlete"]["id"])] = {"team": tid, "starter": bool(a.get("starter")), "min": num("minutes"),
                                                "pm": num("plusMinus"), "dnp": bool(a.get("didNotPlay"))}
    return out


def _ordered(plays: list[dict]) -> list[dict]:
    """ESPN's list order is chronological; ``sequenceNumber`` is NOT (late-entered events keep a high number, measured 2025-03-01).
    Stable sort on (period, elapsed); within one clock instant, scoring and other events come BEFORE substitutions, i.e. free throws are
    credited to the five on court when the foul happened. Measured on 1,398 player-games (2009-2026): this convention reproduces ESPN's box
    plus-minus exactly for 92.3% vs 44.3% for raw list order and 23.0% for subs-first."""
    return sorted(plays, key=lambda x: (int(x["period"]["number"]), elapsed(x), 1 if is_sub(x) else 0))


def _participants(play: dict) -> list[str]:
    return [str(x["athlete"]["id"]) for x in play.get("participants") or [] if (x.get("athlete") or {}).get("id")]


def is_sub(play: dict) -> bool:
    return (play.get("type") or {}).get("text") == "Substitution"


def period_starters(plays: list[dict], period: int, team: str, roster: dict, prev_end: set) -> set:
    """Infer who started a period for one team: players active in the period before they are subbed IN, plus players subbed OUT
    without having entered; topped up from the previous period's closing five when a player was idle (pure)."""
    start, entered = [], set()
    for pl in plays:
        if int(pl["period"]["number"]) != period:
            continue
        ids = [i for i in _participants(pl) if roster.get(i, {}).get("team") == team]
        if is_sub(pl) and len(_participants(pl)) >= 2:
            pin, pout = _participants(pl)[:2]
            if roster.get(pout, {}).get("team") == team and pout not in entered and pout not in start:
                start.append(pout)
            if roster.get(pin, {}).get("team") == team:
                entered.add(pin)
            continue
        if (pl.get("type") or {}).get("text", "").lower().startswith("technical"):
            continue                          # bench technicals name players who are not on the court
        for i in ids:
            if i not in entered and i not in start:
                start.append(i)
    for i in sorted(prev_end):
        if len(start) >= 5:
            break
        if i not in start and i not in entered:
            start.append(i)
    return set(start)


def reconstruct(summary: dict) -> dict:
    """Seconds on court and plus-minus per player, plus stints (pure). Returns {'players':..., 'stints':[...], 'issues':[...]}."""
    roster = box(summary)
    comp = summary["header"]["competitions"][0]
    side = {str(c["team"]["id"]): c["homeAway"] for c in comp["competitors"]}
    teams = sorted(side)
    plays = _ordered(summary.get("plays") or [])
    issues = []
    if not plays:
        return {"players": {}, "stints": [], "issues": ["no_plays"], "teams": teams}
    secs, pm = defaultdict(float), defaultdict(int)
    stints = []
    periods = sorted({int(p["period"]["number"]) for p in plays})
    end_prev = {t: {i for i, r in roster.items() if r["team"] == t and r["starter"]} for t in teams}
    last_score = {"home": 0, "away": 0}
    for per in periods:
        on = {t: (end_prev[t] if per == 1 else period_starters(plays, per, t, roster, end_prev[t])) for t in teams}
        for t in teams:
            if len(on[t]) != 5:
                issues.append(f"p{per}:{t}:start_size_{len(on[t])}")
        seg_start = float(period_start(per))
        stint_pts = {"home": 0, "away": 0}
        def close(now):
            nonlocal seg_start, stint_pts
            d = max(0.0, now - seg_start)
            for t in teams:
                for i in on[t]:
                    secs[i] += d
            if d > 0 or any(stint_pts.values()):
                stints.append({"period": per, "start_s": seg_start, "end_s": now,
                               "lineups": {side[t]: sorted(on[t]) for t in teams}, "pts": dict(stint_pts)})
            seg_start, stint_pts = now, {"home": 0, "away": 0}
        for pl in plays:
            if int(pl["period"]["number"]) != per:
                continue
            h, a = pl.get("homeScore"), pl.get("awayScore")
            if h is not None and a is not None and pl.get("scoringPlay"):        # non-scoring rows can carry a later score (measured)
                dh, da = int(h) - last_score["home"], int(a) - last_score["away"]
                if dh or da:
                    for t in teams:
                        diff = (dh - da) if side[t] == "home" else (da - dh)
                        for i in on[t]:
                            pm[i] += diff
                    stint_pts["home"] += dh; stint_pts["away"] += da
                    last_score = {"home": int(h), "away": int(a)}
            if is_sub(pl) and len(_participants(pl)) >= 2:
                pin, pout = _participants(pl)[:2]
                t = roster.get(pin, {}).get("team") or roster.get(pout, {}).get("team")
                if t not in on:
                    issues.append(f"p{per}:sub_unknown_team"); continue
                close(elapsed(pl))
                if pout not in on[t]:
                    issues.append(f"p{per}:{t}:out_not_on_court")
                on[t].discard(pout); on[t].add(pin)
                if len(on[t]) != 5:
                    issues.append(f"p{per}:{t}:size_{len(on[t])}")
        close(float(period_start(per) + period_len(per)))
        end_prev = {t: set(on[t]) for t in teams}
    return {"players": {i: {"sec": round(secs[i], 1), "pm": pm[i]} for i in set(secs) | set(pm)}, "stints": stints,
            "issues": issues, "teams": teams, "final": last_score}


def verify_game(summary: dict) -> dict:
    """Reconstruction vs ESPN's box score (pure): +/- must match exactly; minutes within 1 (ESPN rounds)."""
    roster = box(summary)
    rec = reconstruct(summary)
    comp = summary["header"]["competitions"][0]
    final = {c["homeAway"]: int(float(c.get("score") or 0)) for c in comp["competitors"]}
    played = {i: r for i, r in roster.items() if r["min"] not in (None,) and not r["dnp"] and (r["min"] or 0) > 0}
    pm_ok = min_ok = 0
    worst = []
    for i, r in played.items():
        got = rec["players"].get(i, {"sec": 0.0, "pm": 0})
        pm_match = r["pm"] is not None and got["pm"] == r["pm"]
        min_match = abs(got["sec"] / 60.0 - r["min"]) <= 1.0
        pm_ok += pm_match; min_ok += min_match
        if not (pm_match and min_match) and len(worst) < 3:
            worst.append({"athlete": i, "box_min": r["min"], "rec_min": round(got["sec"] / 60, 2), "box_pm": r["pm"], "rec_pm": got["pm"]})
    n = len(played)
    return {"game_id": str(summary["header"]["id"]), "date": comp.get("date"), "n_plays": len(summary.get("plays") or []),
            "n_subs": sum(is_sub(p) for p in summary.get("plays") or []), "n_stints": len(rec["stints"]),
            "players_played": n, "pm_match": pm_ok, "min_match": min_ok, "game_pass": bool(n) and pm_ok == n and min_ok == n and not rec["issues"],
            "final_matches_pbp": rec.get("final") == final if rec.get("final") else False, "issues": rec["issues"][:5], "mismatch_examples": worst,
            "officials": len(((summary.get("gameInfo") or {}).get("officials")) or []),
            "wallclock_fill": round(sum(bool(p.get("wallclock")) for p in summary.get("plays") or []) / max(1, len(summary.get("plays") or [])), 4),
            "starters_flagged": sum(r["starter"] for r in roster.values())}


def strip_market(summary: dict) -> dict:
    return {k: v for k, v in summary.items() if k not in DROP_KEYS}


# ---------------------------------------------------------------- manual fetch
def _get(url: str, opener, sleep) -> bytes | None:
    n429 = 0
    while True:
        try:
            with opener(urllib.request.Request(url, headers=UA), timeout=60) as r:
                if getattr(r, "status", 200) != 200:
                    raise Stop(f"non_200:{r.status}")
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 and n429 < MAX_429:
                sleep(BACKOFF_429[n429]); n429 += 1; continue
            raise Stop(f"http_{e.code}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise Stop(f"transport:{type(e).__name__}") from e


def fetch_dates(dates: list[str], cache_dir: Path, max_calls: int = 40, per_date: int = 99, pause: float = 1.0,
                opener=urllib.request.urlopen, sleep=time.sleep) -> dict:
    """Scoreboard for each date, then the summary of up to ``per_date`` completed games. Cached as summary_<id>.json.gz."""
    if not 1 <= max_calls <= HARD_MAX_CALLS:
        raise ValueError(f"max_calls must be in 1..{HARD_MAX_CALLS}")
    pause = max(float(pause), MIN_PAUSE)
    out = _outside_repo(cache_dir)
    out.mkdir(parents=True, exist_ok=True)
    calls, log = 0, []
    try:
        for d in dates:
            ds = dt.date.fromisoformat(d).strftime("%Y%m%d")
            if calls >= max_calls:
                log.append({"stop": "max_calls_reached"}); break
            body = _get(f"{HOST}/scoreboard?dates={ds}", opener, sleep); calls += 1; sleep(pause)
            evs = (json.loads(body) if body else {}).get("events") or []
            ids = [e["id"] for e in evs if (((e.get("status") or {}).get("type") or {}).get("completed"))][:per_date]
            log.append({"date": d, "completed_games": len(ids)})
            for gid in ids:
                p = out / f"summary_{gid}.json.gz"
                if p.exists():
                    continue
                if calls >= max_calls:
                    log.append({"stop": "max_calls_reached"}); break
                body = _get(f"{HOST}/summary?event={gid}", opener, sleep); calls += 1
                if body:
                    clean = json.dumps(strip_market(json.loads(body)), sort_keys=True).encode()
                    p.write_bytes(gzip.compress(clean, mtime=0))
                    log.append({"game": gid, "sha256_raw": hashlib.sha256(body).hexdigest()})
                sleep(pause)
    except Stop as e:
        log.append({"stop": str(e)})
    meta = {"retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "calls": calls, "log": log}
    with open(out / "calls.jsonl", "a") as f:
        f.write(json.dumps(meta) + "\n")
    return meta


def season_of(date: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    s = y if m >= 8 else y - 1
    return f"{s}-{str(s + 1)[2:]}"


def digest(results: list[dict]) -> dict:
    """Aggregate per-game verification results (pure)."""
    by = defaultdict(list)
    for r in results:
        by[season_of(r["date"] or "1900-01-01")].append(r)
    def agg(rs):
        n = len(rs)
        with_plays = [r for r in rs if r["n_plays"]]
        pp = sum(r["players_played"] for r in with_plays)
        return {"games": n, "games_with_plays": len(with_plays), "games_pass": sum(r["game_pass"] for r in with_plays),
                "player_games": pp, "pm_exact": sum(r["pm_match"] for r in with_plays), "min_within_1": sum(r["min_match"] for r in with_plays),
                "final_score_matches_pbp": sum(r["final_matches_pbp"] for r in with_plays),
                "officials_3plus": sum(r["officials"] >= 3 for r in rs), "wallclock_fill_mean": round(sum(r["wallclock_fill"] for r in with_plays) / max(1, len(with_plays)), 4),
                "starters_10": sum(r["starters_flagged"] == 10 for r in rs)}
    issues = Counter(i.split(":", 2)[-1] for r in results for i in r["issues"])
    return {"overall": agg(results), "by_season": {k: agg(v) for k, v in sorted(by.items())}, "issue_kinds": dict(issues),
            "failing_examples": [{k: r[k] for k in ("game_id", "date", "issues", "mismatch_examples")} for r in results if r["n_plays"] and not r["game_pass"]][:8]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--dates", nargs="+", required=True); f.add_argument("--cache-dir", required=True)
    f.add_argument("--max-calls", type=int, default=40); f.add_argument("--per-date", type=int, default=99); f.add_argument("--pause", type=float, default=1.0)
    v = sub.add_parser("verify"); v.add_argument("--cache-dir", required=True); v.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        m = fetch_dates(a.dates, Path(a.cache_dir), a.max_calls, a.per_date, a.pause)
        print(json.dumps({"calls": m["calls"], "last": m["log"][-1] if m["log"] else None})); return 0
    res, shas = [], {}
    for p in sorted(Path(a.cache_dir).glob("summary_*.json.gz")):
        raw = p.read_bytes()
        shas[p.name] = hashlib.sha256(raw).hexdigest()
        res.append(verify_game(json.loads(gzip.decompress(raw))))
    out = digest(res)
    out["cached_file_sha256"] = shas
    out["per_game"] = [{k: r[k] for k in ("game_id", "date", "n_plays", "n_subs", "n_stints", "players_played", "pm_match", "min_match", "game_pass", "officials")} for r in res]
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True)); return 0


if __name__ == "__main__":
    sys.exit(main())

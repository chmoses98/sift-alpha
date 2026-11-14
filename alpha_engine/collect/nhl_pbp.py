"""NHL API play-by-play + game-info sampler for the NHL game-family inputs (RESEARCH_ONLY, $0, anonymous public GETs, manual only).

Why: ``nhl.score_state``, ``nhl.goalie_pull_risk``, ``nhl.third_period_equalizer_hazard``, ``nhl.ot_sudden_death_hazard_5v5``,
``nhl.pp_termination_unit_split`` and ``nhl.officials`` all need event-level game data. ``api-web.nhle.com`` (reachable; the Phase 13
cross-check host) serves ``/v1/gamecenter/{id}/play-by-play`` (every event with period/time, a 4-digit ``situationCode`` =
away goalie, away skaters, home skaters, home goalie, goal running scores, penalties with type/duration) and ``/right-rail``
(``gameInfo.referees`` / ``linesmen`` / per-team ``scratches``). This module samples games and CHECKS that the event stream reproduces the
official final score (shootout goal excluded from the event count, credited by the score endpoint) before any derived count is trusted.

    python -m alpha_engine.collect.nhl_pbp fetch --dates 2025-01-15 --cache-dir /tmp/x --max-calls 40
    python -m alpha_engine.collect.nhl_pbp verify --cache-dir /tmp/x --out digest.json

Rules (fail closed): no key/account; <= ``HARD_MAX_CALLS`` GETs per invocation, >= ``MIN_PAUSE`` s apart; 429 backs off then stops; any other
non-200 (except 404) stops; raw JSON only in a cache directory outside the repository. api-web.nhle.com robots.txt carries ``ai-train=no``:
never train models on this data. Rights: nhl.com terms unreadable here (blocked) -> UNRESOLVED_INTERNAL_ONLY. Not scheduled anywhere.
Point in time: everything here is post-game record (as-played situation, as-worked officials, as-scratched players); usable as strictly-prior
history only. Officials are announced on game day, so the as-worked crew is NOT proof of what was knowable pre-game.
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

HOST = "https://api-web.nhle.com/v1"
UA = {"User-Agent": "research-client/1.0", "Accept": "application/json"}
HARD_MAX_CALLS = 300
MIN_PAUSE = 1.0
MAX_429 = 3
BACKOFF_429 = (20, 60, 120)
REPO_ROOT = Path(__file__).resolve().parents[2]


class Stop(RuntimeError):
    """Fail-closed stop."""


def _outside_repo(p: Path) -> Path:
    p = Path(p).resolve()
    if p == REPO_ROOT or REPO_ROOT in p.parents:
        raise PermissionError("cache directory must be outside the repository (raw payloads are never committed)")
    return p


# ---------------------------------------------------------------- pure
def mmss(s: str) -> int:
    m, sec = (s or "0:0").split(":")
    return int(m) * 60 + int(sec)


def situation(code) -> dict | None:
    """'1451' -> {'away_goalie':1,'away_sk':4,'home_sk':5,'home_goalie':1}; None if malformed."""
    c = str(code or "")
    if len(c) != 4 or not c.isdigit():
        return None
    return {"away_goalie": int(c[0]), "away_sk": int(c[1]), "home_sk": int(c[2]), "home_goalie": int(c[3])}


def game_facts(pbp: dict, rail: dict | None) -> dict:
    """Per-game verification + derived event counts (pure)."""
    plays = sorted(pbp.get("plays") or [], key=lambda p: int(p.get("sortOrder") or 0))
    away, home = pbp["awayTeam"], pbp["homeTeam"]
    aid, hid = away["id"], home["id"]
    last = (pbp.get("gameOutcome") or {}).get("lastPeriodType")
    goals = [p for p in plays if p.get("typeDescKey") == "goal" and (p.get("periodDescriptor") or {}).get("periodType") != "SO"]
    g_away = sum((p.get("details") or {}).get("eventOwnerTeamId") == aid for p in goals)
    g_home = sum((p.get("details") or {}).get("eventOwnerTeamId") == hid for p in goals)
    fa, fh = away.get("score"), home.get("score")
    if last == "SO" and fa is not None and fh is not None:          # the score endpoint credits the shootout winner one goal
        exp = (fa - (fa > fh), fh - (fh > fa))
    else:
        exp = (fa, fh)
    running_ok = all((p.get("details") or {}).get("awayScore") is not None for p in goals)
    if running_ok and goals:
        d = goals[-1]["details"]
        running_ok = (d["awayScore"], d["homeScore"]) == (g_away, g_home)
    non_boundary = [p for p in plays if p.get("typeDescKey") not in ("period-start", "period-end", "game-end", "shootout-complete", "game-official")]
    sit_fill = sum(situation(p.get("situationCode")) is not None for p in non_boundary) / max(1, len(non_boundary))
    # goalie out (extra attacker) in regulation, first event per (period, side), with the side's margin at that moment. situationCode alone does
    # not separate a delayed-penalty extra attacker from an end-game pull; the digest counts late (>= 15:00 of P3) pulls by a trailing team separately
    score = {"away": 0, "home": 0}
    pulls, en_goals, pulled_seen = [], 0, set()
    third_eq = []
    for p in plays:
        pd = p.get("periodDescriptor") or {}
        s = situation(p.get("situationCode"))
        if s and pd.get("periodType") == "REG":
            for side in ("away", "home"):
                if s[f"{side}_goalie"] == 0 and (pd.get("number"), side) not in pulled_seen:
                    pulled_seen.add((pd.get("number"), side))
                    pulls.append({"period": pd.get("number"), "t": mmss(p.get("timeInPeriod")), "side": side,
                                  "margin": score[side] - score["home" if side == "away" else "away"]})
        if p.get("typeDescKey") == "goal" and pd.get("periodType") != "SO":
            det = p.get("details") or {}
            scorer = "away" if det.get("eventOwnerTeamId") == aid else "home"
            other = "home" if scorer == "away" else "away"
            before = dict(score)
            if s and s[f"{other}_goalie"] == 0:
                en_goals += 1
            if pd.get("number") == 3 and pd.get("periodType") == "REG" and before[scorer] + 1 == before[other]:
                third_eq.append(mmss(p.get("timeInPeriod")))           # goal that ties the game in the third period
            score[scorer] += 1
    pens = [p for p in plays if p.get("typeDescKey") == "penalty"]
    pen_fill = sum(all(k in (p.get("details") or {}) for k in ("typeCode", "duration", "descKey")) for p in pens) / max(1, len(pens))
    ot_goal = next((p for p in goals if (p.get("periodDescriptor") or {}).get("periodType") == "OT"), None)
    ot_goal_t = mmss(ot_goal.get("timeInPeriod")) if ot_goal else None
    ot_goal_sit = ot_goal.get("situationCode") if ot_goal else None
    ot_goal_period = (ot_goal.get("periodDescriptor") or {}).get("number") if ot_goal else None
    gi = (rail or {}).get("gameInfo") or {}
    return {"game_id": pbp.get("id"), "date": pbp.get("gameDate"), "game_type": pbp.get("gameType"), "last_period": last,
            "n_plays": len(plays), "goals_pbp": [g_away, g_home], "final_expected": list(exp), "goals_match_final": [g_away, g_home] == list(exp),
            "running_score_consistent": running_ok, "situation_fill": round(sit_fill, 4), "penalties": len(pens), "penalty_field_fill": round(pen_fill, 4),
            "goalie_pulls_reg": pulls, "empty_net_goals": en_goals, "third_period_equalizers_t": third_eq, "ot_goal_t": ot_goal_t,
            "ot_goal_situation": ot_goal_sit, "ot_goal_period": ot_goal_period,
            "referees": len(gi.get("referees") or []), "linesmen": len(gi.get("linesmen") or []),
            "scratches_listed": sum(bool(((gi.get(k) or {}).get("scratches"))) for k in ("awayTeam", "homeTeam")),
            "rail_present": rail is not None}


def season_of(date: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    s = y if m >= 8 else y - 1
    return f"{s}-{str(s + 1)[2:]}"


def digest(facts: list[dict]) -> dict:
    by = defaultdict(list)
    for f in facts:
        by[season_of(f["date"])].append(f)
    def agg(fs):
        full = [f for f in fs if f["n_plays"] >= 150]
        return {"games": len(fs), "games_full_pbp": len(full), "goals_match_final": sum(f["goals_match_final"] for f in fs),
                "running_score_consistent": sum(f["running_score_consistent"] for f in fs),
                "situation_fill_mean": round(sum(f["situation_fill"] for f in fs) / max(1, len(fs)), 4),
                "penalties": sum(f["penalties"] for f in fs), "penalty_field_fill_mean": round(sum(f["penalty_field_fill"] for f in fs) / max(1, len(fs)), 4),
                "games_with_reg_goalie_pull": sum(bool(f["goalie_pulls_reg"]) for f in fs),
                "late_trailing_pulls_p3": sum(1 for f in fs for p in f["goalie_pulls_reg"] if p["period"] == 3 and p["margin"] < 0 and p["t"] >= 900),
                "other_extra_attacker_spells": sum(1 for f in fs for p in f["goalie_pulls_reg"] if not (p["period"] == 3 and p["margin"] < 0 and p["t"] >= 900)),
                "empty_net_goals": sum(f["empty_net_goals"] for f in fs), "third_period_equalizers": sum(len(f["third_period_equalizers_t"]) for f in fs),
                "ot_games": sum(f["last_period"] == "OT" for f in fs), "so_games": sum(f["last_period"] == "SO" for f in fs),
                "ot_goal_time_present": sum(f["ot_goal_t"] is not None for f in fs if f["last_period"] == "OT"),
                "playoff_games": sum(f["game_type"] == 3 for f in fs), "playoff_ot_games": sum(f["game_type"] == 3 and f["last_period"] == "OT" for f in fs),
                "playoff_ot_goals_at_5v5": sum(f["game_type"] == 3 and f["ot_goal_situation"] == "1551" for f in fs),
                "playoff_multi_ot_games": sum(f["game_type"] == 3 and (f["ot_goal_period"] or 0) >= 5 for f in fs),
                "officials_2_2": sum(f["referees"] == 2 and f["linesmen"] == 2 for f in fs), "scratches_both_teams": sum(f["scratches_listed"] == 2 for f in fs)}
    return {"overall": agg(facts), "by_season": {k: agg(v) for k, v in sorted(by.items())},
            "goal_mismatch_examples": [{k: f[k] for k in ("game_id", "date", "last_period", "goals_pbp", "final_expected")} for f in facts if not f["goals_match_final"]][:8]}


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
                opener=urllib.request.urlopen, sleep=time.sleep, last_period: str | None = None) -> dict:
    """Score endpoint per date, then play-by-play + right-rail per final game; ``last_period`` ('OT'/'SO'/'REG') keeps only such games."""
    if not 1 <= max_calls <= HARD_MAX_CALLS:
        raise ValueError(f"max_calls must be in 1..{HARD_MAX_CALLS}")
    pause = max(float(pause), MIN_PAUSE)
    out = _outside_repo(cache_dir)
    out.mkdir(parents=True, exist_ok=True)
    calls, log = 0, []
    try:
        for d in dates:
            if calls >= max_calls:
                log.append({"stop": "max_calls_reached"}); break
            body = _get(f"{HOST}/score/{dt.date.fromisoformat(d).isoformat()}", opener, sleep); calls += 1; sleep(pause)
            games = [g for g in (json.loads(body) if body else {}).get("games") or [] if g.get("gameState") in ("OFF", "FINAL")
                     and (last_period is None or (g.get("gameOutcome") or {}).get("lastPeriodType") == last_period)][:per_date]
            log.append({"date": d, "final_games": len(games)})
            for g in games:
                for kind in ("play-by-play", "right-rail"):
                    p = out / f"{kind}_{g['id']}.json.gz"
                    if p.exists():
                        continue
                    if calls >= max_calls:
                        raise Stop("max_calls_reached")
                    body = _get(f"{HOST}/gamecenter/{g['id']}/{kind}", opener, sleep); calls += 1
                    if body:
                        p.write_bytes(gzip.compress(body, mtime=0))
                        log.append({"file": p.name, "sha256_raw": hashlib.sha256(body).hexdigest()})
                    sleep(pause)
    except Stop as e:
        log.append({"stop": str(e)})
    meta = {"retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "calls": calls, "log": log}
    with open(out / "calls.jsonl", "a") as f:
        f.write(json.dumps(meta) + "\n")
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--dates", nargs="+", required=True); f.add_argument("--cache-dir", required=True)
    f.add_argument("--max-calls", type=int, default=40); f.add_argument("--per-date", type=int, default=99); f.add_argument("--pause", type=float, default=1.0)
    f.add_argument("--last-period", choices=("REG", "OT", "SO"))
    v = sub.add_parser("verify"); v.add_argument("--cache-dir", required=True); v.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        m = fetch_dates(a.dates, Path(a.cache_dir), a.max_calls, a.per_date, a.pause, last_period=a.last_period)
        print(json.dumps({"calls": m["calls"], "last": m["log"][-1] if m["log"] else None})); return 0
    cache = Path(a.cache_dir)
    facts, shas = [], {}
    for p in sorted(cache.glob("play-by-play_*.json.gz")):
        gid = p.name.split("_", 1)[1].split(".")[0]
        r = cache / f"right-rail_{gid}.json.gz"
        for q in (p, r):
            if q.exists():
                shas[q.name] = hashlib.sha256(q.read_bytes()).hexdigest()
        facts.append(game_facts(json.loads(gzip.decompress(p.read_bytes())), json.loads(gzip.decompress(r.read_bytes())) if r.exists() else None))
    out = digest(facts)
    out["cached_file_sha256"] = shas
    out["per_game"] = [{k: f[k] for k in ("game_id", "date", "game_type", "last_period", "n_plays", "goals_match_final", "situation_fill", "referees", "linesmen")} for f in facts]
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True)); return 0


if __name__ == "__main__":
    sys.exit(main())

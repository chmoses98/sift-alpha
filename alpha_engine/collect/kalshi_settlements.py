"""Kalshi OFFICIAL settlement results for the market families Alpha evaluates (RESEARCH_ONLY, $0, anonymous public GETs, manual only).

Why: ``alpha_eval`` grades NBA game families from the producer's own outcomes; "Kalshi's official result is not retained in the archive"
(alpha_eval/nba_games.py). The public Trade API v2 serves settled markets anonymously, with ``result`` / ``settlement_value_dollars`` /
``settlement_ts``; markets settled before the exchange's ``/historical/cutoff`` are served by ``/historical/markets`` instead.

    python -m alpha_engine.collect.kalshi_settlements fetch --series KXNHLGAME --source live --cache-dir /tmp/x --max-calls 10
    python -m alpha_engine.collect.kalshi_settlements ledger --cache-dir /tmp/x --out digest.json

Rules (fail closed): no key, no account, no orders; at most ``HARD_MAX_CALLS`` GETs per invocation and ``>= MIN_PAUSE`` seconds between calls;
a 429 backs off and, after ``MAX_429`` in a row, STOPS (the exchange is rate limiting - never hammered); any other non-200 stops.
Raw pages are written gzip-compressed ONLY to a cache directory outside the repository (bulk data is never committed); the committed
artefact is the ledger (counts, spans, field fill rates, result mix, consistency checks, sha256 of each page).
Point-in-time: a settlement is post-event truth (known at ``settlement_ts``); it is an OUTCOME label, never a pre-game input.
Rights: Kalshi's API/market-data terms could not be read from this environment (kalshi.com / docs.kalshi.com blocked), so the tier is
UNRESOLVED_INTERNAL_ONLY: internal research grading only, no redistribution. Not scheduled anywhere.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HOST = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "research-client/1.0", "Accept": "application/json"}
SERIES_RE = re.compile(r"KX[A-Z0-9]{2,40}\Z")
SOURCES = {"live": "/markets", "historical": "/historical/markets"}
PAGE_LIMIT = 1000
HARD_MAX_CALLS = 200
MIN_PAUSE = 2.0
MAX_429 = 4
BACKOFF_429 = (15, 30, 60, 120)
REPO_ROOT = Path(__file__).resolve().parents[2]
# Families evaluated by alpha_eval (NBA, on main) and their NHL counterparts (same base kinds).
EVALUATED_SERIES = {
    "KXNBAGAME": "game_winner", "KXNBASPREAD": "game_spread", "KXNBATOTAL": "game_total", "KXNBATEAMTOTAL": "team_total",
    "KXNHLGAME": "game_winner", "KXNHLSPREAD": "game_spread", "KXNHLTOTAL": "game_total", "KXNHLTEAMTOTAL": "team_total",
}
ROW_FIELDS = ("ticker", "event_ticker", "status", "result", "settlement_value_dollars", "settlement_ts", "expiration_value", "close_time",
              "open_time", "occurrence_datetime", "expected_expiration_time", "strike_type", "floor_strike", "cap_strike", "custom_strike",
              "yes_sub_title", "rules_primary", "market_type")


class Stop(RuntimeError):
    """Fail-closed stop (rate limit persisted, non-200, cap reached)."""


def _outside_repo(p: Path) -> Path:
    p = Path(p).resolve()
    if p == REPO_ROOT or REPO_ROOT in p.parents:
        raise PermissionError("cache directory must be outside the repository (raw pages are never committed)")
    return p


def page_url(source: str, series: str, cursor: str | None = None, extra: dict | None = None) -> str:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}")
    if not SERIES_RE.match(series or ""):
        raise ValueError("invalid series ticker")
    q = {"series_ticker": series, "limit": PAGE_LIMIT}
    if source == "live":
        q["status"] = "settled"
    if cursor:
        q["cursor"] = cursor
    q.update(extra or {})
    return HOST + SOURCES[source] + "?" + urllib.parse.urlencode(q)


def fetch_series(series: str, source: str, cache_dir: Path, max_calls: int = 20, pause: float = 5.0, opener=urllib.request.urlopen,
                 sleep=time.sleep, extra: dict | None = None) -> dict:
    """Paginate one series. Returns a call log; raw pages land in cache_dir/<series>/<source>/page_NNN.json.gz."""
    if not 1 <= max_calls <= HARD_MAX_CALLS:
        raise ValueError(f"max_calls must be in 1..{HARD_MAX_CALLS}")
    pause = max(float(pause), MIN_PAUSE)
    out = _outside_repo(cache_dir) / series / source
    out.mkdir(parents=True, exist_ok=True)
    log, cursor, calls, n429, page = [], None, 0, 0, 0
    while True:
        if calls >= max_calls:
            log.append({"stop": "max_calls_reached", "cursor_remaining": bool(cursor)}); break
        url = page_url(source, series, cursor, extra)
        calls += 1
        try:
            with opener(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = r.read()
                status = getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            if e.code == 429 and n429 < MAX_429:
                log.append({"call": calls, "status": 429, "backoff_s": BACKOFF_429[n429]})
                sleep(BACKOFF_429[n429]); n429 += 1; continue
            log.append({"call": calls, "status": e.code, "stop": "http_error"}); break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log.append({"call": calls, "status": None, "stop": f"transport:{type(e).__name__}"}); break
        n429 = 0
        if status != 200:
            log.append({"call": calls, "status": status, "stop": "non_200"}); break
        data = json.loads(body)
        markets = data.get("markets") or []
        p = out / f"page_{page:03d}.json.gz"
        p.write_bytes(gzip.compress(body, mtime=0))
        log.append({"call": calls, "status": 200, "page": page, "markets": len(markets), "sha256": hashlib.sha256(body).hexdigest()})
        page += 1
        cursor = data.get("cursor") or None
        if not cursor or not markets:
            log.append({"stop": "exhausted"}); break
        sleep(pause)
    meta = {"series": series, "source": source, "retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "calls": calls, "log": log, "url_pattern": page_url(source, series)}
    (out / "calls.json").write_text(json.dumps(meta, indent=1))
    return meta


def load_rows(cache_dir: Path, series: str) -> list[dict]:
    """Normalised rows from every cached page of a series (live + historical), de-duplicated by ticker (live wins)."""
    rows = {}
    for source in ("historical", "live"):
        d = Path(cache_dir) / series / source
        for p in sorted(d.glob("page_*.json.gz")):
            for m in json.loads(gzip.decompress(p.read_bytes())).get("markets") or []:
                r = {k: m.get(k) for k in ROW_FIELDS}
                r["series"], r["source"] = series, source
                rows[r["ticker"]] = r
    return list(rows.values())


_SETTLED = ("settled", "finalized", "determined")


def summarize(rows: list[dict]) -> dict:
    """Coverage digest for one series (pure)."""
    if not rows:
        return {"markets": 0}
    settled = [r for r in rows if r.get("status") in _SETTLED]
    ts = sorted(r["settlement_ts"] for r in settled if r.get("settlement_ts"))
    occ = sorted((r.get("occurrence_datetime") or r.get("close_time"))[:10] for r in rows if r.get("occurrence_datetime") or r.get("close_time"))
    fill = {k: round(sum(r.get(k) not in (None, "") for r in rows) / len(rows), 4) for k in ROW_FIELDS}
    by_season = Counter(_season(r) for r in rows)
    return {"markets": len(rows), "events": len({r["event_ticker"] for r in rows}), "settled_markets": len(settled),
            "by_source": dict(Counter(r["source"] for r in rows)), "status": dict(Counter(r.get("status") for r in rows)),
            "result": dict(Counter(r.get("result") for r in rows)), "first_settlement_ts": ts[0] if ts else None,
            "last_settlement_ts": ts[-1] if ts else None, "first_event_date": occ[0] if occ else None,
            "last_event_date": occ[-1] if occ else None, "events_by_season": dict(sorted(by_season.items())), "field_fill": fill}


def _season(r: dict) -> str:
    """Season label from the event date (NBA/NHL seasons start in autumn): 2026-11-12 -> '2026-27'."""
    d = (r.get("occurrence_datetime") or r.get("close_time") or "")[:10]
    if not d:
        return "unknown"
    y, m = int(d[:4]), int(d[5:7])
    s = y if m >= 8 else y - 1
    return f"{s}-{str(s + 1)[2:]}"


def event_consistency(rows: list[dict]) -> dict:
    """Winner families: each finalized two-outcome event must have exactly one YES (pure)."""
    ev = defaultdict(list)
    for r in rows:
        if r.get("status") in _SETTLED and r.get("result") in ("yes", "no"):
            ev[r["event_ticker"]].append(r["result"])
    bad = sorted(e for e, v in ev.items() if v.count("yes") != 1)
    return {"events_checked": len(ev), "events_not_exactly_one_yes": len(bad), "examples": bad[:5]}


def ladder_monotonic(rows: list[dict]) -> dict:
    """Threshold ladders ('greater' strikes on the same event and side): YES at a higher strike implies YES at every lower one (pure)."""
    groups = defaultdict(list)
    for r in rows:
        if r.get("strike_type") == "greater" and r.get("floor_strike") is not None and r.get("result") in ("yes", "no"):
            side = json.dumps(r.get("custom_strike") or {}, sort_keys=True)
            groups[(r["event_ticker"], side)].append((float(r["floor_strike"]), r["result"]))
    bad = []
    for k, v in groups.items():
        v.sort()
        seen_no = False
        for _, res in v:
            if res == "no":
                seen_no = True
            elif seen_no:
                bad.append(k[0]); break
    return {"ladders_checked": len(groups), "non_monotonic": len(bad), "examples": sorted(bad)[:5]}


# ---- independent cross-check against the league's own final scores (NHL API) ----
TEAM_RE = re.compile(r"^KXNHL[A-Z]+-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")
# Kalshi event tickers use 2-letter codes where the NHL API uses 3 letters (measured: every unmatched event involved one of these).
KALSHI_NHL_CODE = {"LAK": "LA", "NJD": "NJ", "SJS": "SJ", "TBL": "TB"}
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def nhl_event_key(event_ticker: str):
    """'KXNHLTOTAL-26NOV12WPGDAL' -> ('2026-11-12', 'WPGDAL') or None."""
    m = TEAM_RE.match(event_ticker or "")
    if not m or m.group(2) not in MONTHS:
        return None
    return f"20{m.group(1)}-{MONTHS[m.group(2)]:02d}-{m.group(3)}", m.group(4)


def nhl_scores_from_payload(payload: dict) -> dict:
    """api-web.nhle.com /v1/score/{date} -> {(date, AWAYHOME): {...}} for FINAL/OFF games (pure)."""
    out = {}
    for g in (payload or {}).get("games") or []:
        if g.get("gameState") not in ("OFF", "FINAL"):
            continue
        a, h = g["awayTeam"], g["homeTeam"]
        last = (g.get("gameOutcome") or {}).get("lastPeriodType") or (g.get("periodDescriptor") or {}).get("periodType")
        for ka in {a["abbrev"], KALSHI_NHL_CODE.get(a["abbrev"], a["abbrev"])}:        # Kalshi used 3-letter codes in 2025, 2-letter later
            for kh in {h["abbrev"], KALSHI_NHL_CODE.get(h["abbrev"], h["abbrev"])}:
                out[(g["gameDate"], ka + kh)] = {"away": ka, "home": kh, "away_goals": a.get("score"), "home_goals": h.get("score"),
                                                 "last_period": last, "game_id": g.get("id")}
    return out


def _team_code(r: dict, game: dict):
    """Which team a GAME/SPREAD/TEAMTOTAL market is about: ticker suffix after the last '-' starts with the team code."""
    suf = r["ticker"].rsplit("-", 1)[-1]
    for t in (game["away"], game["home"]):
        if suf.startswith(t):
            return t
    return None


def nhl_expected(r: dict, game: dict, family: str, shootout_counts: bool):
    """Expected YES/NO for one NHL market from final scores. NHL API final scores credit the shootout winner with one goal;
    with shootout_counts=False that goal is removed from both the winner's tally and the total."""
    ag, hg = game["away_goals"], game["home_goals"]
    if ag is None or hg is None:
        return None
    if game.get("last_period") == "SO" and not shootout_counts:
        if ag > hg:
            ag -= 1
        else:
            hg -= 1
    goals = {game["away"]: ag, game["home"]: hg}
    if family == "game_total":
        return "yes" if ag + hg > float(r["floor_strike"]) else "no"
    team = _team_code(r, game)
    if team is None:
        return None
    other = game["home"] if team == game["away"] else game["away"]
    if family == "game_winner":
        a2, h2 = game["away_goals"], game["home_goals"]          # the winner is the official winner (shootout included)
        return "yes" if (a2 > h2) == (team == game["away"]) else "no"
    if family == "game_spread":
        return "yes" if goals[team] - goals[other] > float(r["floor_strike"]) else "no"
    if family == "team_total":
        return "yes" if goals[team] > float(r["floor_strike"]) else "no"
    return None


def nhl_crosscheck(rows: list[dict], scores: dict, family: str) -> dict:
    """Compare Kalshi results with NHL API scores under both shootout conventions (pure)."""
    res = {"matched_markets": 0, "unmatched_markets": 0}
    for conv in ("shootout_goal_counts", "shootout_goal_excluded"):
        res[conv] = {"agree": 0, "disagree": 0, "disagree_in_so_games": 0, "examples": []}
    so_markets = 0
    for r in rows:
        if r.get("result") not in ("yes", "no"):
            continue
        k = nhl_event_key(r["event_ticker"])
        g = scores.get(k) if k else None
        if g is None:
            res["unmatched_markets"] += 1; continue
        res["matched_markets"] += 1
        so_markets += g.get("last_period") == "SO"
        for conv, flag in (("shootout_goal_counts", True), ("shootout_goal_excluded", False)):
            e = nhl_expected(r, g, family, flag)
            if e is None:
                continue
            c = res[conv]
            if e == r["result"]:
                c["agree"] += 1
            else:
                c["disagree"] += 1
                c["disagree_in_so_games"] += g.get("last_period") == "SO"
                if len(c["examples"]) < 5:
                    c["examples"].append({"ticker": r["ticker"], "kalshi": r["result"], "expected": e, "score": f"{g['away']} {g['away_goals']}-{g['home_goals']} {g['home']}", "last_period": g.get("last_period")})
    res["markets_in_shootout_games"] = so_markets
    return res


SCORE_RE = re.compile(r"^\s*(\d{2,3})\s*-\s*(\d{2,3})\s*$")


def nba_scores_from_game_rows(game_rows: list[dict]) -> dict:
    """KXNBAGAME events whose expiration_value is a score string 'A-B' -> {event_suffix: {team: pts}} with the YES team given max(A, B).
    This is Kalshi's OWN reported value, so a check built on it is cross-family consistency, not independent truth (pure)."""
    by_ev = defaultdict(list)
    for r in game_rows:
        by_ev[r["event_ticker"]].append(r)
    out = {}
    for ev, rs in by_ev.items():
        m = SCORE_RE.match(str(rs[0].get("expiration_value") or ""))
        yes = [r for r in rs if r.get("result") == "yes"]
        no = [r for r in rs if r.get("result") == "no"]
        if not m or len(yes) != 1 or len(no) != 1:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        out[ev.split("-", 1)[1]] = {yes[0]["ticker"].rsplit("-", 1)[1]: max(a, b), no[0]["ticker"].rsplit("-", 1)[1]: min(a, b)}
    return out


ESPN_NBA_CODE = {"NY": "NYK", "SA": "SAS", "GS": "GSW", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}
_MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def nba_scores_from_espn(payload: dict, date: str) -> dict:
    """ESPN NBA scoreboard for one US date (YYYY-MM-DD) -> {'26NOV12TORPHI': {'TOR': 112, 'PHI': 123}} for final games (pure).
    Independent of Kalshi (ESPN is one of the settlement sources Kalshi's series metadata names)."""
    tag = f"{date[2:4]}{_MON[int(date[5:7]) - 1]}{date[8:10]}"
    out = {}
    for e in (payload or {}).get("events") or []:
        c = (e.get("competitions") or [{}])[0]
        if not ((c.get("status") or {}).get("type") or {}).get("completed"):
            continue
        t = {x["homeAway"]: x for x in c.get("competitors") or []}
        if set(t) != {"home", "away"}:
            continue
        code = {k: ESPN_NBA_CODE.get(v["team"]["abbreviation"], v["team"]["abbreviation"]) for k, v in t.items()}
        out[tag + code["away"] + code["home"]] = {code[k]: int(float(t[k]["score"])) for k in ("away", "home")}
    return out


def nba_cross_family(rows: list[dict], scores: dict, family: str) -> dict:
    """Kalshi results vs final scores keyed by event suffix (from KXNBAGAME's own score string, or independently from ESPN) (pure)."""
    res = {"checked": 0, "agree": 0, "disagree": 0, "no_score": 0, "examples": []}
    for r in rows:
        if r.get("result") not in ("yes", "no") or (family != "game_winner" and r.get("floor_strike") is None):
            continue
        sc = scores.get(r["event_ticker"].split("-", 1)[1])
        if not sc:
            res["no_score"] += 1; continue
        k = float(r["floor_strike"]) if r.get("floor_strike") is not None else 0.0
        suf = r["ticker"].rsplit("-", 1)[1]
        team = next((t for t in sc if suf.startswith(t)), None)
        if family == "game_total":
            e = "yes" if sum(sc.values()) > k else "no"
        elif team is None:
            res["no_score"] += 1; continue
        elif family == "game_winner":
            e = "yes" if sc[team] == max(sc.values()) else "no"
        elif family == "game_spread":
            other = next(t for t in sc if t != team)
            e = "yes" if sc[team] - sc[other] > k else "no"
        else:
            e = "yes" if sc[team] > k else "no"
        res["checked"] += 1
        if e == r["result"]:
            res["agree"] += 1
        else:
            res["disagree"] += 1
            if len(res["examples"]) < 5:
                res["examples"].append({"ticker": r["ticker"], "kalshi": r["result"], "expected": e, "score": sc})
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--series", required=True); f.add_argument("--source", choices=sorted(SOURCES), required=True)
    f.add_argument("--cache-dir", required=True); f.add_argument("--max-calls", type=int, default=20); f.add_argument("--pause", type=float, default=5.0)
    f.add_argument("--min-close-ts", type=int); f.add_argument("--max-close-ts", type=int)
    l = sub.add_parser("ledger"); l.add_argument("--cache-dir", required=True); l.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        extra = {k: v for k, v in (("min_close_ts", a.min_close_ts), ("max_close_ts", a.max_close_ts)) if v is not None}
        meta = fetch_series(a.series, a.source, Path(a.cache_dir), a.max_calls, a.pause, extra=extra)
        print(json.dumps({k: meta[k] for k in ("series", "source", "calls")} | {"last": meta["log"][-1]})); return 0
    cache = Path(a.cache_dir)
    out = {}
    for s in sorted(p.name for p in cache.iterdir() if p.is_dir() and SERIES_RE.match(p.name)):
        rows = load_rows(cache, s)
        d = summarize(rows)
        d["family"] = EVALUATED_SERIES.get(s)
        d["winner_one_yes"] = event_consistency(rows) if d.get("family") == "game_winner" else None
        d["ladder_monotonic"] = ladder_monotonic(rows) if d.get("family") in ("game_spread", "game_total", "team_total") else None
        out[s] = d
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True)); return 0


if __name__ == "__main__":
    sys.exit(main())

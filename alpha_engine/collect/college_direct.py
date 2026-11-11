"""CFBD / CBBD direct-API collector (RESEARCH_ONLY). INACTIVE: it makes no request unless an owner-written authorization file exists.

    python -m alpha_engine.collect.college_direct plan  --domain cbb --seasons 2014-2025      # pure planning: no network, no key
    python -m alpha_engine.collect.college_direct probe --domain cbb --dry-run                # lists the <=10 probe calls, no network
    python -m alpha_engine.collect.college_direct probe --domain cbb --out-dir D --ledger L    # real probe; runs from the manual workflow only

Guards (each fails closed):
  1. `research/input_research/data_collection/college_direct_authorization.json` must exist, be owner-written (`authorized: true`, `monthly_call_cap`, `max_share_of_cap` <= 0.5,
     `authorized_by`, `date`, `expires`) and be unexpired. It does NOT exist in the repository.
  2. The API key is read only from an environment variable (`CFBD_API_KEY` / `CBBD_API_KEY`; names to be confirmed by the owner); never logged, written or put in a URL.
  3. A month-keyed call ledger (outside the repo) caps calls at max_share_of_cap * monthly_call_cap, because the quota is shared with other tools; the run stops at the first 401/403/429/non-200.
  4. Raw responses are written only outside the repository tree (no raw redistribution). Derived outputs only may be committed, tagged CLEARED_PROVIDER_TERMS_DIRECT_API
     (owner-reported terms; exact text not agent-verified).
Endpoint names, start seasons and call-count formulas are from the public API surface as the agent knows it (plus owner-relayed facts: CBBD lineups start in 2024; /plays/date and /plays/team exist).
The hosts were unreachable to the agent, so everything marked UNVERIFIED stays so until the first authorised probe records real status codes, row counts and the remaining-quota figure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_FILE = ROOT / "research/input_research/data_collection/college_direct_authorization.json"
HOSTS = {"cfb": "https://api.collegefootballdata.com", "cbb": "https://api.collegebasketballdata.com"}
KEY_ENV = {"cfb": "CFBD_API_KEY", "cbb": "CBBD_API_KEY"}
W_CFB = 16              # regular-season weeks 1-15 (one call each) + one postseason call: upper bound per season for a per-week endpoint
PER_GAME = 6200         # approx D-I games per season (one call per game for /plays/game and /lineups/game)
TEAMS = 365             # approx D-I teams per season (one call per team for /plays/team and /lineups/team) + 1 /teams call to enumerate them
DATES = 161             # game days per CBB season, Nov 1 - Apr 10 (one call per date for /plays/date)
LINEUPS_FROM = 2024     # owner-relayed from the CBBD coverage page: lineup data starts in 2024, not 2013
MAX_PROBE_CALLS = 10

# domain -> endpoint -> {calls per season, first season (UNVERIFIED), served need/dataset, PIT note}
ENDPOINTS = {
    "cfb": {
        "/games":            {"calls": 2,     "from": 2001, "pit": "event-time; safe"},
        "/games/teams":      {"calls": W_CFB, "from": 2001, "pit": "event-time; safe"},
        "/games/players":    {"calls": W_CFB, "from": 2004, "pit": "event-time; safe"},
        "/plays":            {"calls": W_CFB, "from": 2005, "pit": "event-time; safe (ppa / win-probability columns are model outputs and market-adjacent: never loaded)"},
        "/drives":           {"calls": W_CFB, "from": 2001, "pit": "event-time; safe"},
        "/coaches":          {"calls": 1,     "from": 2001, "pit": "season-level only"},
        "/recruiting/teams": {"calls": 1,     "from": 2000, "pit": "retrospective class rankings"},
        "/rankings":         {"calls": 1,     "from": 1936, "pit": "poll week stamped; safe"},
    },
    "cbb": {
        "/games":             {"calls": 2,        "from": 2002, "pit": "event-time; safe"},
        "/games/teams":       {"calls": 2,        "from": 2002, "pit": "event-time; safe"},
        "/games/players":     {"calls": 2,        "from": 2002, "pit": "event-time; safe"},
        "/plays/date":        {"calls": DATES,    "from": 2013, "pit": "event-time; one call per game day (UNVERIFIED param, response limit, incomplete fields); cheapest full-season path"},
        "/plays/team?team={team}": {"calls": TEAMS,    "from": 2013, "pit": "event-time; one call per team-season; every game appears twice (both teams); needs /teams first"},
        "/plays/game/{id}":   {"calls": PER_GAME, "from": 2013, "pit": "event-time; one call per game: fallback only for dates/teams whose response looks truncated"},
        "/lineups/team?team={team}": {"calls": TEAMS,    "from": LINEUPS_FROM, "pit": "event-time; 2024+ only; per team-season"},
        "/lineups/game/{id}": {"calls": PER_GAME, "from": LINEUPS_FROM, "pit": "event-time; 2024+ only; per game: fallback only"},
        "/rankings":          {"calls": 1,        "from": 2002, "pit": "poll week stamped; safe"},
    },
}
# catalog dataset id -> endpoints that could serve it; None = no direct-API source
DATASET_ENDPOINTS = {
    "cfb.pbp_cfbd": ["/plays", "/drives"], "cfb.box_player": ["/games/players"], "cfb.games_espn": ["/games", "/games/teams"],
    "cfb.coach_history": ["/coaches"], "cfb.recruiting_portal": ["/recruiting/teams"], "cfb.rankings_polls": ["/rankings"],
    "cbb.games_espn": ["/games", "/games/teams"], "cbb.box_player": ["/games/players"], "cbb.polls": ["/rankings"],
}
# need types served by an endpoint when the catalog dataset is not one of the above
NEED_ENDPOINTS = {"cfb": {"RESULTS": ["/games"], "TEAM_BOX": ["/games/teams"], "PLAYER_BOX": ["/games/players"], "EVENT": ["/plays", "/drives"]},
                  "cbb": {"RESULTS": ["/games"], "TEAM_BOX": ["/games/teams"], "PLAYER_BOX": ["/games/players"], "EVENT": ["/plays/date", "/plays/team?team={team}"], "LINEUP": ["/lineups/team?team={team}"]}}
# datasets that are by definition not direct-API data (availability vintages, news, weather, rules, tracking, paid or third-party ratings)
NEVER_DIRECT = ("availability", "news", "weather", "rules", "tracking", "pff", "kenpom", "barttorvik", "officials", "coaching_finance", "coordinator", "fcs_grants", "ncaa_", "d3_", "wcbb", "ap_poll", "net_bracket", "tourney")


def serviceability(domain: str, requirements: list[dict]) -> dict:
    """Which of an input's catalog requirement entries a direct-API endpoint could serve (pure function of the catalog entry)."""
    served, unserved, eps = [], [], set()
    for q in requirements:
        ds = q.get("satisfied_by") or (q.get("candidates") or [""])[0]
        if ds in DATASET_ENDPOINTS: cand = DATASET_ENDPOINTS[ds]
        elif any(t in str(ds) for t in NEVER_DIRECT) or q["need"] in ("AVAIL", "NEWS", "RULES", "WEATHER", "TRACKING"): cand = None
        else: cand = NEED_ENDPOINTS[domain].get(q["need"])
        (served if cand else unserved).append({"need": q["need"], "dataset": ds, "endpoints": cand or []})
        eps.update(cand or [])
    cls = "NOT_SERVICEABLE" if not served else ("FULLY_SERVICEABLE" if not unserved else "PARTLY_SERVICEABLE")
    return {"class": cls, "served": served, "unserved": unserved, "endpoints": sorted(eps)}


def parse_seasons(s: str) -> list[int]:
    m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", s.strip())
    if not m: raise ValueError("seasons must look like 2014 or 2014-2025")
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if b < a: raise ValueError("seasons descend")
    return list(range(a, b + 1))


@dataclass(frozen=True)
class Req:
    domain: str
    path: str
    params: tuple

    def url(self) -> str:
        q = "&".join(f"{k}={v}" for k, v in self.params)
        return f"{HOSTS[self.domain]}{self.path}" + (f"?{q}" if q else "")


def plan(domain: str, seasons: list[int], endpoints: list[str] | None = None) -> list[Req]:
    """Deterministic static request list. Dependent endpoints ({id}/{team}) are excluded: their count needs a /games or /teams result first. CBB /plays/date is enumerable from the calendar."""
    yk = "year" if domain == "cfb" else "season"; out = []
    for y in seasons:
        for p, meta in ENDPOINTS[domain].items():
            if (endpoints and p not in endpoints) or "{" in p or y < meta["from"]: continue
            if p == "/plays/date":
                d = date(y - 1, 11, 1)                      # CBBD season = ending year (UNVERIFIED; the probe cross-checks game dates)
                while d <= date(y, 4, 10): out.append(Req(domain, p, (("date", d.isoformat()),))); d += timedelta(days=1)
            elif domain == "cfb" and meta["calls"] == W_CFB:
                out += [Req(domain, p, ((yk, y), ("week", w), ("seasonType", "regular"))) for w in range(1, 16)] + [Req(domain, p, ((yk, y), ("seasonType", "postseason")))]
            elif meta["calls"] == 2:
                out += [Req(domain, p, ((yk, y), ("seasonType", t))) for t in ("regular", "postseason")]
            else:
                out.append(Req(domain, p, ((yk, y),)))
    return out


def estimate(domain: str, seasons: list[int], endpoints: list[str] | None = None) -> dict:
    static = plan(domain, seasons, endpoints); per_ep: dict[str, int] = {}
    for r in static: per_ep[r.path] = per_ep.get(r.path, 0) + 1
    dep = {p: sum(m["calls"] for y in seasons if y >= m["from"])
           for p, m in ENDPOINTS[domain].items() if "{" in p and (not endpoints or p in endpoints)}
    return {"domain": domain, "seasons": [seasons[0], seasons[-1]], "static_calls": len(static), "static_by_endpoint": per_ep, "dependent_calls_estimate": dep}


def cbb_event_strategies(seasons: list[int]) -> dict:
    """Realistic CBB play-by-play cost per strategy (calls; all UNVERIFIED until the probe). Plays from 2013, lineups from 2024; +1 /teams call per season for team strategies."""
    ps = [y for y in seasons if y >= ENDPOINTS["cbb"]["/plays/date"]["from"]]; ls = [y for y in seasons if y >= LINEUPS_FROM]
    return {"plays_by_date": DATES * len(ps), "plays_by_team": (TEAMS + 1) * len(ps), "plays_by_game_fallback": PER_GAME * len(ps),
            "lineups_by_team_2024plus": (TEAMS + 1) * len(ls), "lineups_by_game_2024plus": PER_GAME * len(ls),
            "recommended": "plays_by_date + lineups_by_team; per-game only for responses that hit a limit", "recommended_calls": DATES * len(ps) + (TEAMS + 1) * len(ls),
            "unverified": ["per-response row limit (a date with ~60 games may truncate)", "plays season start (2013 assumed)", "season numbering (ending year assumed)", "which play fields are populated in early seasons"]}


class Refusal(RuntimeError):
    pass


def load_authorization(path: Path = AUTH_FILE, today: date | None = None) -> dict:
    if not Path(path).exists(): raise Refusal("no owner authorization file: collection is not authorised")
    a = json.loads(Path(path).read_text()); today = today or datetime.now(timezone.utc).date()
    for k in ("authorized", "monthly_call_cap", "max_share_of_cap", "authorized_by", "date", "expires"):
        if k not in a: raise Refusal(f"authorization missing field {k}")
    if a["authorized"] is not True: raise Refusal("authorization not granted")
    if not (0 < float(a["max_share_of_cap"]) <= 0.5): raise Refusal("max_share_of_cap must be in (0, 0.5]: the quota is shared")
    if int(a["monthly_call_cap"]) <= 0: raise Refusal("monthly_call_cap must be positive")
    if date.fromisoformat(a["expires"]) < today: raise Refusal("authorization expired")
    return a


class Ledger:
    """Month-keyed call counter stored outside the repository; refuses to spend past the allowed share."""

    def __init__(self, path: Path, allowed: int):
        self.path, self.allowed = Path(path), int(allowed)
        self.d = json.loads(self.path.read_text()) if self.path.exists() else {}

    def used(self, month: str) -> int: return int(self.d.get(month, 0))

    def spend(self, month: str, n: int = 1) -> None:
        if self.used(month) + n > self.allowed: raise Refusal(f"budget: {self.used(month)}+{n} > {self.allowed} calls allowed this month")
        self.d[month] = self.used(month) + n
        self.path.parent.mkdir(parents=True, exist_ok=True); self.path.write_text(json.dumps(self.d))


def run(domain: str, reqs: list[Req], out_dir: Path, ledger_path: Path, transport, env: dict, auth_path: Path = AUTH_FILE, today: date | None = None, sleep=time.sleep) -> dict:
    """transport(url, headers) -> (status, body, headers). Raw bodies go to out_dir (outside the repo). The key exists only inside `headers`."""
    auth = load_authorization(auth_path, today)
    key = env.get(KEY_ENV[domain])
    if not key: raise Refusal(f"{KEY_ENV[domain]} not set")
    out_dir = Path(out_dir).resolve()
    if out_dir == ROOT or ROOT in out_dir.parents: raise Refusal("raw provider data may not be stored inside the repository")
    month = (today or datetime.now(timezone.utc).date()).strftime("%Y-%m")
    led = Ledger(ledger_path, int(auth["monthly_call_cap"] * float(auth["max_share_of_cap"])))
    out_dir.mkdir(parents=True, exist_ok=True); done = 0; stopped = None
    for r in reqs:
        fn = out_dir / (re.sub(r"[^A-Za-z0-9._-]+", "_", r.path.strip("/") + "_" + "_".join(f"{k}{v}" for k, v in r.params)) + ".json")
        if fn.exists(): continue                                   # resumable: never re-spends a call
        led.spend(month)
        status, body, _ = transport(r.url(), {"Authorization": f"Bearer {key}", "Accept": "application/json"})
        if status != 200: stopped = status; break                  # first 401/403/429/other: stop
        fn.write_bytes(body); done += 1; sleep(0.25)
    return {"requests_done": done, "stopped_on_status": stopped, "month": month, "used_this_month": led.used(month), "allowed": led.allowed}


# ---- fail-closed initial probe (<= MAX_PROBE_CALLS calls) ----
QUOTA_URL = HOSTS["cfb"] + "/info"        # CFBD reports remainingCalls here (UNVERIFIED field names); the quota is shared across tools/hosts under one key
PROBE = {
    "cfb": [("cfb", "/info", ()), ("cfb", "/games", (("year", 2024), ("week", 1), ("seasonType", "regular"))), ("cfb", "/games/teams", (("year", 2024), ("week", 1), ("seasonType", "regular"))),
            ("cfb", "/plays", (("year", 2024), ("week", 1), ("seasonType", "regular")))],
    "cbb": [("cfb", "/info", ()), ("cbb", "/data-availability", ()), ("cbb", "/games", (("season", 2025), ("seasonType", "regular"))), ("cbb", "/plays/date", (("date", "2025-02-01"),)),
            ("cbb", "/plays/team", (("team", "Duke"), ("season", 2025))), ("cbb", "/lineups/team", (("team", "Duke"), ("season", 2025)))],
}
PROBE_FIELDS = ("authorized", "probe_authorized", "authorized_by", "date", "expires", "monthly_call_cap", "max_share_of_cap", "shared_quota_remaining", "quota_declared_on", "quota_reserve")


def probe_requests(domain: str) -> list[Req]:
    reqs = [Req(d, p, q) for d, p, q in PROBE[domain]]
    assert len(reqs) <= MAX_PROBE_CALLS
    return reqs


def load_probe_authorization(path: Path = AUTH_FILE, today: date | None = None) -> dict:
    """Owner authorization for a probe: base checks plus an owner-declared remaining shared quota, declared within 2 days, that covers the probe plus a reserve."""
    a = load_authorization(path, today); today = today or datetime.now(timezone.utc).date()
    for k in PROBE_FIELDS:
        if k not in a: raise Refusal(f"authorization missing field {k}")
    if a["probe_authorized"] is not True: raise Refusal("probe not authorized")
    if not (0 <= (today - date.fromisoformat(a["quota_declared_on"])).days <= 2): raise Refusal("owner quota declaration is older than 2 days (or future-dated): quota uncertain")
    if int(a["quota_reserve"]) < 100: raise Refusal("quota_reserve must be >= 100 calls left for other tools")
    if int(a["shared_quota_remaining"]) < MAX_PROBE_CALLS + int(a["quota_reserve"]): raise Refusal("declared remaining shared quota does not cover the probe plus reserve")
    return a


def api_remaining(body: bytes) -> int | None:
    try: d = json.loads(body)
    except ValueError: return None
    d = d[0] if isinstance(d, list) and d else d
    v = d.get("remainingCalls", d.get("remaining_calls")) if isinstance(d, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def probe(domain: str, out_dir: Path, ledger_path: Path, transport, env: dict, auth_path: Path = AUTH_FILE, today: date | None = None, sleep=time.sleep, repo_is_private: bool = False) -> dict:
    """<=10 calls. Order: authorization, key, private storage, then call 1 (/info) must return an integer remaining quota that covers the rest plus the reserve; any non-200 or doubt stops the run.
    Every call is counted in the durable ledger BEFORE it is made and appended to a call log (url without secrets, status, bytes, sha256). Raw bodies stay in out_dir (outside the repo)."""
    auth = load_probe_authorization(auth_path, today)
    key = env.get(KEY_ENV[domain]) or env.get(KEY_ENV["cfb"])
    if not key: raise Refusal("API key not set in the environment")
    if not repo_is_private: raise Refusal("raw storage requires a private repository/runner: repo_is_private not asserted")
    out_dir = Path(out_dir).resolve()
    if out_dir == ROOT or ROOT in out_dir.parents: raise Refusal("raw provider data may not be stored inside the repository")
    reqs = probe_requests(domain); month = (today or datetime.now(timezone.utc).date()).strftime("%Y-%m")
    led = Ledger(ledger_path, min(MAX_PROBE_CALLS, int(auth["monthly_call_cap"] * float(auth["max_share_of_cap"]))))
    if led.used(month + "-probe") + len(reqs) > led.allowed: raise Refusal("probe already run this month or probe budget exhausted")
    out_dir.mkdir(parents=True, exist_ok=True); log = []; stopped = None; remaining = None
    for n, r in enumerate(reqs):
        led.spend(month + "-probe"); led.spend(month)                         # counted before the call: a crash can only over-count
        try: status, body, _ = transport(r.url(), {"Authorization": f"Bearer {key}", "Accept": "application/json"})
        except Exception as e: status, body = 0, type(e).__name__.encode()    # network error text never includes headers
        row = {"n": n, "url": r.url(), "status": status, "bytes": len(body), "sha256": __import__("hashlib").sha256(body).hexdigest()}
        if status == 200:
            (out_dir / f"{n:02d}.json").write_bytes(body)
            try: v = json.loads(body); row["rows"] = len(v) if isinstance(v, list) else None
            except ValueError: row["rows"] = None
        log.append(row)
        if status != 200: stopped = f"access/availability status {status} on call {n}"; break
        if n == 0:
            remaining = api_remaining(body)
            if remaining is None: stopped = "quota uncertain: /info gave no integer remaining-call count"; break
            if remaining < len(reqs) - 1 + int(auth["quota_reserve"]): stopped = f"quota too low: {remaining} remaining"; break
            if remaining > int(auth["shared_quota_remaining"]) * 2 + 100: stopped = "quota mismatch with the owner declaration: refuse to guess"; break
        sleep(0.5)
    summary = {"domain": domain, "month": month, "calls_made": len(log), "max_probe_calls": MAX_PROBE_CALLS, "stopped": stopped, "api_remaining_before": remaining, "used_this_month": led.used(month), "log": log}
    (out_dir / "probe_summary.json").write_text(json.dumps(summary, indent=1)); return summary


def urllib_transport(url: str, headers: dict):
    import urllib.error, urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r: return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, b"", {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "probe"]); ap.add_argument("--domain", choices=["cfb", "cbb"], required=True)
    ap.add_argument("--seasons"); ap.add_argument("--endpoints", nargs="*"); ap.add_argument("--out-dir"); ap.add_argument("--ledger"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo-private", action="store_true"); a = ap.parse_args(argv)
    if a.cmd == "plan":
        if not a.seasons: ap.error("--seasons required")
        seas = parse_seasons(a.seasons); e = estimate(a.domain, seas, a.endpoints)
        if a.domain == "cbb": e["cbb_event_strategies"] = cbb_event_strategies(seas)
        print(json.dumps(e, indent=1)); return 0
    if a.dry_run: print(json.dumps([r.url() for r in probe_requests(a.domain)], indent=1)); return 0
    if not (a.out_dir and a.ledger): ap.error("--out-dir and --ledger required")
    try: s = probe(a.domain, Path(a.out_dir), Path(a.ledger), urllib_transport, dict(__import__("os").environ), repo_is_private=a.repo_private)
    except Refusal as e: print(f"REFUSED: {e}", file=sys.stderr); return 3
    print(json.dumps({k: v for k, v in s.items() if k != "log"})); return 4 if s["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())

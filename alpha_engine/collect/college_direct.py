"""CFBD / CBBD direct-API collector (RESEARCH_ONLY). INACTIVE: it makes no request unless an owner-written authorization file exists.

    python -m alpha_engine.collect.college_direct plan  --domain cbb --seasons 2014-2025      # pure planning: no network, no key
    python -m alpha_engine.collect.college_direct probe --domain cbb --dry-run                # lists the <=10 probe calls, no network
    python -m alpha_engine.collect.college_direct reserve|probe|reconcile ...                # real probe phases; run from the manual workflow only

Guards (each fails closed):
  1. `research/input_research/data_collection/college_direct_authorization.json` must exist, be owner-written (`authorized: true`, `monthly_call_cap`, `max_share_of_cap` <= 0.5,
     `authorized_by`, `date`, `expires`) and be unexpired. It does NOT exist in the repository.
  2. The API key is read only from an environment variable (`CFBD_API_KEY` / `CBBD_API_KEY`; names to be confirmed by the owner); never logged, written or put in a URL.
  3. A month-keyed call ledger (outside the repo) caps calls at max_share_of_cap * monthly_call_cap, because the quota is shared with other tools; the run stops at the first 401/403/429/non-200.
     The probe charges its full size to the ledger (and the workflow pushes it) BEFORE any call; only a valid summary of that run refunds unused calls.
  4. The repository is PUBLIC. The probe never writes response bodies anywhere (sha256 + shape + field names + counts only); the bulk collector is local-only and refuses in
     GitHub Actions. Raw responses are never committed or uploaded. Derived outputs may enter the repository only through write_derived() with full provenance and tier
     CLEARED_PROVIDER_TERMS_DIRECT_API (owner-reported terms; exact text not agent-verified); check_public_derived() is the CI gate.
Endpoint names, start seasons and call-count formulas are from the public API surface as the agent knows it (plus owner-relayed facts: CBBD lineups start in 2024; /plays/date and /plays/team exist).
The hosts were unreachable to the agent, so everything marked UNVERIFIED stays so until the first authorised probe records real status codes, row counts and the remaining-quota figure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

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


LEDGER_VERSION = 2


class Ledger:
    """Month-keyed call counter (counts and hashes only, never response data). Format v2:
    {"version": 2, "months": {"YYYY-MM": {"calls": n, "probe_calls": n}}, "pending": {run_id: reservation}, "history": [...]}.
    Writes are atomic (temp file + fsync + rename). A missing file is an empty ledger; an unreadable or malformed one is a Refusal (never treated as empty)."""

    def __init__(self, path: Path, allowed: int):
        self.path, self.allowed = Path(path), int(allowed)
        self.d = self._load()

    def _load(self) -> dict:
        if not self.path.exists(): return {"version": LEDGER_VERSION, "months": {}, "pending": {}, "history": []}
        try: d = json.loads(self.path.read_text())
        except (ValueError, OSError) as e: raise Refusal(f"ledger unreadable ({type(e).__name__}): refusing to treat it as empty")
        if not isinstance(d, dict): raise Refusal("ledger malformed")
        if "version" not in d:                                             # v1 flat {"YYYY-MM": n, "YYYY-MM-probe": n}: migrate, keep counts
            m: dict = {}
            for k, v in d.items():
                if not (isinstance(v, int) and re.fullmatch(r"\d{4}-\d{2}(-probe)?", k)): raise Refusal("ledger malformed (v1)")
                m.setdefault(k[:7], {"calls": 0, "probe_calls": 0})["probe_calls" if k.endswith("-probe") else "calls"] = v
            d = {"version": LEDGER_VERSION, "months": m, "pending": {}, "history": []}
        if d.get("version") != LEDGER_VERSION or not all(isinstance(d.get(k), t) for k, t in (("months", dict), ("pending", dict), ("history", list))):
            raise Refusal("ledger malformed or unknown version")
        for mo in d["months"].values():
            if not (isinstance(mo, dict) and all(isinstance(mo.get(k, 0), int) and mo.get(k, 0) >= 0 for k in ("calls", "probe_calls"))): raise Refusal("ledger malformed (counts)")
        return d

    def _month(self, month: str) -> dict: return self.d["months"].setdefault(month, {"calls": 0, "probe_calls": 0})
    def used(self, month: str) -> int: return int(self.d["months"].get(month, {}).get("calls", 0))
    def probe_used(self, month: str) -> int: return int(self.d["months"].get(month, {}).get("probe_calls", 0))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f: json.dump(self.d, f, indent=1, sort_keys=True); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def spend(self, month: str, n: int = 1) -> None:
        if self.used(month) + n > self.allowed: raise Refusal(f"budget: {self.used(month)}+{n} > {self.allowed} calls allowed this month")
        self._month(month)["calls"] += n; self.save()


def run(domain: str, reqs: list[Req], out_dir: Path, ledger_path: Path, transport, env: dict, auth_path: Path = AUTH_FILE, today: date | None = None, sleep=time.sleep) -> dict:
    """Bulk collector: LOCAL ONLY, never in GitHub Actions (the repository is public; there is no safe place for raw bodies there).
    transport(url, headers) -> (status, body, headers). Raw bodies go to out_dir (outside the repo, never committed/uploaded). The key exists only inside `headers`."""
    if str(env.get("GITHUB_ACTIONS", "")).lower() == "true": raise Refusal("bulk raw collection is not permitted on GitHub Actions in a public repository")
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


# ---- fail-closed initial probe (<= MAX_PROBE_CALLS calls per calendar month, both domains together) ----
# Three phases, each its own workflow job, so the shared-quota spend is durable before any call is made:
#   reserve   (no key)  : checks the owner authorization and the ledger, charges the FULL probe size to the month, records a pending reservation; the workflow pushes it.
#   probe     (key)     : refuses unless the pushed ledger holds this run's reservation; makes <= reserved calls; keeps raw bodies in memory only; emits a safe summary.
#   reconcile (no key)  : refunds reserved - made using the summary. No/invalid summary (crash, cancel, lost output) => the reservation stays charged in full.
QUOTA_URL = HOSTS["cfb"] + "/info"        # CFBD reports remainingCalls here (UNVERIFIED field names); the quota is shared across tools/hosts under one key
PROBE = {
    "cfb": [("cfb", "/info", ()), ("cfb", "/games", (("year", 2024), ("week", 1), ("seasonType", "regular"))), ("cfb", "/games/teams", (("year", 2024), ("week", 1), ("seasonType", "regular"))),
            ("cfb", "/plays", (("year", 2024), ("week", 1), ("seasonType", "regular")))],
    "cbb": [("cfb", "/info", ()), ("cbb", "/data-availability", ()), ("cbb", "/games", (("season", 2025), ("seasonType", "regular"))), ("cbb", "/plays/date", (("date", "2025-02-01"),)),
            ("cbb", "/plays/team", (("team", "Duke"), ("season", 2025))), ("cbb", "/lineups/team", (("team", "Duke"), ("season", 2025)))],
}
PROBE_FIELDS = ("authorized", "probe_authorized", "authorized_by", "date", "expires", "monthly_call_cap", "max_share_of_cap", "shared_quota_remaining", "quota_declared_on", "quota_reserve")
RUN_ID = re.compile(r"\d{1,20}-\d{1,4}")                 # github.run_id-github.run_attempt: a re-run attempt never inherits an earlier attempt's reservation
SUMMARY_KEYS = {"run_id", "domain", "month", "reserved", "calls_made", "max_probe_calls", "stopped", "outcome", "api_remaining_before", "log"}
LOG_KEYS = {"n", "url", "status", "bytes", "sha256", "json", "type", "rows", "fields", "non_null"}


class Interrupted(BaseException):
    """Raised from SIGTERM so a cancelled run still reports how many calls it made."""


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


def _probe_allowed(auth: dict) -> int: return min(MAX_PROBE_CALLS, int(auth["monthly_call_cap"] * float(auth["max_share_of_cap"])))


def _now() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reserve_probe(domain: str, ledger_path: Path, run_id: str, auth_path: Path = AUTH_FILE, today: date | None = None) -> dict:
    """Phase 1 (no key). Charges the full probe size before any call. A pending reservation left by an earlier run (crash/cancel before reconcile) stays charged in full."""
    if not RUN_ID.fullmatch(run_id): raise Refusal("run id must be <run_id>-<run_attempt>")
    auth = load_probe_authorization(auth_path, today)
    month = (today or datetime.now(timezone.utc).date()).strftime("%Y-%m"); n = len(probe_requests(domain))
    led = Ledger(ledger_path, int(auth["monthly_call_cap"] * float(auth["max_share_of_cap"])))
    if run_id in led.d["pending"] or any(h.get("run_id") == run_id for h in led.d["history"]): raise Refusal("run id already used")
    for rid, p in list(led.d["pending"].items()):                      # stale: never reconciled -> keep the full charge, close it out
        led.d["history"].append({**p, "run_id": rid, "made": None, "charged": p["reserved"], "outcome": "UNRECONCILED_COUNTED_IN_FULL", "closed_at": _now()})
        del led.d["pending"][rid]
    if led.probe_used(month) + n > _probe_allowed(auth): raise Refusal(f"probe budget: {led.probe_used(month)}+{n} > {_probe_allowed(auth)} probe calls this month")
    if led.used(month) + n > led.allowed: raise Refusal(f"budget: {led.used(month)}+{n} > {led.allowed} calls allowed this month")
    mo = led._month(month); mo["calls"] += n; mo["probe_calls"] += n
    r = {"domain": domain, "month": month, "reserved": n, "reserved_at": _now()}
    led.d["pending"][run_id] = r; led.save(); return {"run_id": run_id, **r}


def api_remaining(body: bytes) -> int | None:
    try: d = json.loads(body)
    except ValueError: return None
    d = d[0] if isinstance(d, list) and d else d
    v = d.get("remainingCalls", d.get("remaining_calls")) if isinstance(d, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def validation_summary(body: bytes) -> dict:
    """Safe, publishable description of one response: size, sha256, JSON shape, row count, field names and per-field non-null counts. No values."""
    out = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    try: v = json.loads(body)
    except ValueError: return {**out, "json": False}
    recs = v if isinstance(v, list) else [v]
    fields: dict[str, int] = {}
    for x in recs:
        if isinstance(x, dict):
            for k, val in x.items():
                k = str(k)[:64]; fields[k] = fields.get(k, 0) + (val is not None)
    names = sorted(fields)[:200]
    return {**out, "json": True, "type": type(v).__name__, "rows": len(v) if isinstance(v, list) else None, "fields": names, "non_null": {k: fields[k] for k in names}}


def probe(domain: str, summary_dir: Path, ledger_path: Path, run_id: str, transport, env: dict, auth_path: Path = AUTH_FILE, today: date | None = None, sleep=time.sleep) -> dict:
    """Phase 2 (key). <= reserved calls. Order: authorization, key, this run's reservation in the ledger, then call 1 (/info) must return an integer remaining quota that covers
    the rest plus the reserve; any non-200, transport error or doubt stops the run. No retries. Response bodies are never written anywhere: each is reduced in memory to a
    validation summary (sha256, shape, field names, counts) and dropped. `calls_made` is incremented BEFORE each call, so it is an upper bound even on interruption."""
    summary_dir = Path(summary_dir).resolve()
    if summary_dir == ROOT or ROOT in summary_dir.parents: raise Refusal("probe output may not be written inside the repository")
    month = (today or datetime.now(timezone.utc).date()).strftime("%Y-%m"); reqs = probe_requests(domain)
    res = Ledger(ledger_path, 0).d["pending"].get(run_id)
    if not res or res.get("domain") != domain or res.get("month") != month or int(res.get("reserved", 0)) < len(reqs): raise Refusal("no durable reservation for this run: run the reserve phase first")
    summary_dir.mkdir(parents=True, exist_ok=True)
    log: list = []; stopped = None; remaining = None; made = 0; outcome = "COMPLETED"; key = None
    try:
        try:                                                                     # pre-call refusals: exactly 0 calls made, so the reservation can be refunded
            auth = load_probe_authorization(auth_path, today)
            key = env.get(KEY_ENV[domain]) or env.get(KEY_ENV["cfb"])
            if not key: raise Refusal("API key not set in the environment")
        except Refusal as e:
            stopped, outcome = f"refused before any call: {e}", "REFUSED"; raise
        for n, r in enumerate(reqs):
            made += 1                                                            # counted before the call: interruption can only over-count
            try: status, body, _ = transport(r.url(), {"Authorization": f"Bearer {key}", "Accept": "application/json"})
            except Exception as e: status, body = 0, type(e).__name__.encode()  # exception class name only; never headers
            row = {"n": n, "url": r.url(), "status": status, **(validation_summary(body) if status == 200 else {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})}
            if n == 0 and status == 200: remaining = api_remaining(body)
            del body                                                             # raw response dropped here; never persisted
            log.append(row)
            if status != 200: stopped = f"access/availability status {status} on call {n}"; break
            if n == 0:
                if remaining is None: stopped = "quota uncertain: /info gave no integer remaining-call count"; break
                if remaining < len(reqs) - 1 + int(auth["quota_reserve"]): stopped = f"quota too low: {remaining} remaining"; break
                if remaining > int(auth["shared_quota_remaining"]) * 2 + 100: stopped = "quota mismatch with the owner declaration: refuse to guess"; break
            sleep(0.5)
    except BaseException as e:                                                   # cancel (SIGTERM/SIGINT) or bug: still report the upper-bound count
        if outcome != "REFUSED": stopped, outcome = f"interrupted: {type(e).__name__}", "INTERRUPTED"
        raise
    finally:
        if stopped and outcome == "COMPLETED": outcome = "STOPPED"
        if outcome == "REFUSED": stopped = stopped[:250]
        s = {"run_id": run_id, "domain": domain, "month": month, "reserved": int(res["reserved"]), "calls_made": made, "max_probe_calls": MAX_PROBE_CALLS,
             "stopped": stopped, "outcome": outcome, "api_remaining_before": remaining, "log": log}
        txt = json.dumps(s, indent=1, sort_keys=True)
        if key and key in txt: raise Refusal("summary would contain the key: not written")       # defence in depth; the key is only ever in a header
        (summary_dir / "probe_summary.json").write_text(txt)
    return s


def check_summary(s) -> str | None:
    """Reason a probe summary is unusable for a refund (None = usable). Only known keys and value types are accepted, so nothing else can reach the public ledger."""
    if not isinstance(s, dict) or set(s) - SUMMARY_KEYS or not SUMMARY_KEYS <= set(s): return "unexpected summary keys"
    if not (isinstance(s["calls_made"], int) and isinstance(s["reserved"], int) and 0 <= s["calls_made"] <= s["reserved"] <= MAX_PROBE_CALLS): return "bad counts"
    if not isinstance(s["log"], list) or len(s["log"]) > s["calls_made"]: return "bad log"
    for row in s["log"]:
        if not isinstance(row, dict) or set(row) - LOG_KEYS: return "unexpected log keys"
        if not (isinstance(row.get("url"), str) and row["url"].startswith(tuple(HOSTS.values())) and re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256")))): return "bad log row"
        if any(isinstance(v, str) and len(v) > 300 for v in row.values()): return "oversized value"
    return None


def reconcile(ledger_path: Path, run_id: str, summary_path: Path | None) -> dict:
    """Phase 3 (no key). Refund reserved - calls_made only for a valid summary of THIS run; otherwise the reservation stays charged in full."""
    led = Ledger(ledger_path, 0); p = led.d["pending"].pop(run_id, None)
    if p is None: raise Refusal("no pending reservation for this run")
    s, why = None, "no summary"
    if summary_path and Path(summary_path).is_file():
        try: s = json.loads(Path(summary_path).read_text()); why = check_summary(s)
        except ValueError: why = "summary not JSON"
        if why is None and (s["run_id"], s["domain"], s["month"], s["reserved"]) != (run_id, p["domain"], p["month"], p["reserved"]): why = "summary is for another run"
    if why is None:
        refund = p["reserved"] - s["calls_made"]; mo = led._month(p["month"])
        mo["calls"] -= refund; mo["probe_calls"] -= refund
        h = {**p, "run_id": run_id, "made": s["calls_made"], "charged": s["calls_made"], "outcome": s["outcome"], "stopped": s["stopped"],
             "summary_sha256": hashlib.sha256(Path(summary_path).read_bytes()).hexdigest()}
    else:
        h = {**p, "run_id": run_id, "made": None, "charged": p["reserved"], "outcome": "UNRECONCILED_COUNTED_IN_FULL", "reason": why}
    h["closed_at"] = _now(); led.d["history"].append(h); led.save(); return h


# ---- public derived outputs: provenance + licence gate (the repository is public) ----
PUBLIC_DERIVED_DIR = ROOT / "research/input_research/derived/college_direct"
PUBLIC_TIERS = {"CLEARED_PROVIDER_TERMS_DIRECT_API"}           # owner-reported CFBD/CBBD terms: derived outputs allowed, raw redistribution prohibited
DERIVATIONS = {"aggregate", "model_feature", "validation_summary"}
PROVENANCE_FIELDS = ("source", "hosts", "endpoints", "retrieved_at", "raw_sha256", "terms_url", "terms_effective", "terms_evidence", "tier", "derivation",
                     "contains_raw_records", "attribution", "generated_by")


def provenance_problems(p) -> list[str]:
    if not isinstance(p, dict): return ["provenance is not an object"]
    bad = [f"missing {k}" for k in PROVENANCE_FIELDS if k not in p]
    if bad: return bad
    if p["tier"] not in PUBLIC_TIERS: bad.append(f"tier {p['tier']!r} is not cleared for public derived output")
    if p["derivation"] not in DERIVATIONS: bad.append(f"derivation must be one of {sorted(DERIVATIONS)}")
    if p["contains_raw_records"] is not False: bad.append("contains_raw_records must be false (no raw or row-for-row copies of provider records)")
    if not set(p["hosts"]) <= {urlparse(h).netloc for h in HOSTS.values()}: bad.append("hosts must be CFBD/CBBD API hosts")
    if not (isinstance(p["raw_sha256"], list) and p["raw_sha256"] and all(re.fullmatch(r"[0-9a-f]{64}", str(h)) for h in p["raw_sha256"])): bad.append("raw_sha256 must list the source responses' hashes")
    if not str(p["attribution"]).strip(): bad.append("attribution required")
    return bad


def write_derived(name: str, data, provenance: dict, out_dir: Path = PUBLIC_DERIVED_DIR) -> Path:
    """The only sanctioned way to put CFBD/CBBD-derived data in the repository: refuses without complete provenance and a public-cleared tier."""
    if not re.fullmatch(r"[a-z0-9_]+\.json", name): raise Refusal("derived output name must be [a-z0-9_]+.json")
    bad = provenance_problems(provenance)
    if bad: raise Refusal("; ".join(bad))
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / name; f.write_text(json.dumps(data, indent=1, sort_keys=True))
    (out_dir / (name + ".provenance.json")).write_text(json.dumps({**provenance, "output_sha256": hashlib.sha256(f.read_bytes()).hexdigest()}, indent=1, sort_keys=True))
    return f


def check_public_derived(root: Path = PUBLIC_DERIVED_DIR) -> list[str]:
    """CI gate: every file under the public derived directory has valid provenance with a public-cleared tier and a matching hash."""
    root = Path(root); out = []
    if not root.exists(): return out
    for f in sorted(x for x in root.rglob("*") if x.is_file()):
        if f.name.endswith(".provenance.json"):
            if not f.with_name(f.name[: -len(".provenance.json")]).exists(): out.append(f"{f}: orphan provenance")
            continue
        pf = f.with_name(f.name + ".provenance.json")
        if not pf.exists(): out.append(f"{f}: no provenance"); continue
        try: p = json.loads(pf.read_text())
        except ValueError: out.append(f"{pf}: not JSON"); continue
        out += [f"{f}: {b}" for b in provenance_problems(p)]
        if isinstance(p, dict) and p.get("output_sha256") != hashlib.sha256(f.read_bytes()).hexdigest(): out.append(f"{f}: output_sha256 mismatch")
    return out


def urllib_transport(url: str, headers: dict):
    """Single attempt, no retries (a retry spends shared quota). HTTP errors return their status; network errors raise (the probe stops on them)."""
    import urllib.error, urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r: return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, b"", {}


def _sigterm(signum, frame): raise Interrupted(f"signal {signum}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "reserve", "probe", "reconcile", "check-derived"]); ap.add_argument("--domain", choices=["cfb", "cbb"])
    ap.add_argument("--seasons"); ap.add_argument("--endpoints", nargs="*"); ap.add_argument("--out-dir"); ap.add_argument("--ledger"); ap.add_argument("--run-id")
    ap.add_argument("--summary"); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args(argv)
    if a.cmd == "check-derived":
        bad = check_public_derived(); print("\n".join(bad) or "ok"); return 1 if bad else 0
    if a.cmd == "reconcile":
        if not (a.ledger and a.run_id): ap.error("--ledger and --run-id required")
        try: h = reconcile(Path(a.ledger), a.run_id, Path(a.summary) if a.summary else None)
        except Refusal as e: print(f"REFUSED: {e}", file=sys.stderr); return 3
        print(json.dumps(h)); return 0
    if not a.domain: ap.error("--domain required")
    if a.cmd == "plan":
        if not a.seasons: ap.error("--seasons required")
        seas = parse_seasons(a.seasons); e = estimate(a.domain, seas, a.endpoints)
        if a.domain == "cbb": e["cbb_event_strategies"] = cbb_event_strategies(seas)
        print(json.dumps(e, indent=1)); return 0
    if a.dry_run: print(json.dumps([r.url() for r in probe_requests(a.domain)], indent=1)); return 0
    if not (a.ledger and a.run_id): ap.error("--ledger and --run-id required")
    try:
        if a.cmd == "reserve": print(json.dumps(reserve_probe(a.domain, Path(a.ledger), a.run_id))); return 0
        if not a.out_dir: ap.error("--out-dir required")
        signal.signal(signal.SIGTERM, _sigterm)
        s = probe(a.domain, Path(a.out_dir), Path(a.ledger), a.run_id, urllib_transport, dict(os.environ))
    except Refusal as e: print(f"REFUSED: {e}", file=sys.stderr); return 3
    except (Interrupted, KeyboardInterrupt): print("INTERRUPTED: summary written with an upper-bound call count", file=sys.stderr); return 5
    print(json.dumps({k: v for k, v in s.items() if k != "log"})); return 4 if s["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())

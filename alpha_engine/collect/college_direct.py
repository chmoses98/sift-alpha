"""CFBD / CBBD direct-API ingestion scaffold (RESEARCH_ONLY). INACTIVE: it makes no request unless an owner-written authorization file exists.

    python -m alpha_engine.collect.college_direct plan --domain cfb --seasons 2014-2025     # pure planning: no network, no key

Guards (each fails closed):
  1. `research/input_research/data_collection/college_direct_authorization.json` must exist, be owner-written (`authorized: true`, `monthly_call_cap`, `max_share_of_cap` <= 0.5,
     `authorized_by`, `date`, `expires`) and be unexpired. It does NOT exist in the repository.
  2. The API key is read only from an environment variable (`CFBD_API_KEY` / `CBBD_API_KEY`; names to be confirmed by the owner); never logged, written or put in a URL.
  3. A month-keyed call ledger (outside the repo) caps calls at max_share_of_cap * monthly_call_cap, because the quota is shared with other tools; the run stops at the first 401/403/429/non-200.
  4. Raw responses are written only outside the repository tree (no raw redistribution). Derived outputs only may be committed, tagged CLEARED_PROVIDER_TERMS_DIRECT_API
     (owner-reported terms; exact text not agent-verified).
Endpoint names, start seasons and call-count formulas are from the public API surface as the agent knows it. The hosts were unreachable in Phase 12, so they are UNVERIFIED
against the live OpenAPI document until the first authorised probe. `main` is deliberately not wired to a network transport.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_FILE = ROOT / "research/input_research/data_collection/college_direct_authorization.json"
HOSTS = {"cfb": "https://api.collegefootballdata.com", "cbb": "https://api.collegebasketballdata.com"}
KEY_ENV = {"cfb": "CFBD_API_KEY", "cbb": "CBBD_API_KEY"}
W_CFB = 16              # regular-season weeks 1-15 (one call each) + one postseason call: upper bound per season for a per-week endpoint
PER_GAME = 6200         # approx D-I games per season (one call per game for /plays/game and /lineups/game)

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
        "/plays/game/{id}":   {"calls": PER_GAME, "from": 2013, "pit": "event-time; safe; one call per game: expensive"},
        "/lineups/game/{id}": {"calls": PER_GAME, "from": 2013, "pit": "event-time; one call per game: expensive"},
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
                  "cbb": {"RESULTS": ["/games"], "TEAM_BOX": ["/games/teams"], "PLAYER_BOX": ["/games/players"], "EVENT": ["/plays/game/{id}"], "LINEUP": ["/lineups/game/{id}"]}}
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
    """Deterministic static request list. Per-game ({id}) endpoints are excluded: their count needs the /games result first."""
    yk = "year" if domain == "cfb" else "season"; out = []
    for y in seasons:
        for p, meta in ENDPOINTS[domain].items():
            if (endpoints and p not in endpoints) or "{id}" in p or y < meta["from"]: continue
            if domain == "cfb" and meta["calls"] == W_CFB:
                out += [Req(domain, p, ((yk, y), ("week", w), ("seasonType", "regular"))) for w in range(1, 16)] + [Req(domain, p, ((yk, y), ("seasonType", "postseason")))]
            elif meta["calls"] == 2:
                out += [Req(domain, p, ((yk, y), ("seasonType", t))) for t in ("regular", "postseason")]
            else:
                out.append(Req(domain, p, ((yk, y),)))
    return out


def estimate(domain: str, seasons: list[int], endpoints: list[str] | None = None) -> dict:
    static = plan(domain, seasons, endpoints); per_ep: dict[str, int] = {}
    for r in static: per_ep[r.path] = per_ep.get(r.path, 0) + 1
    per_game = {p: sum(PER_GAME for y in seasons if y >= m["from"]) for p, m in ENDPOINTS[domain].items() if "{id}" in p and (not endpoints or p in endpoints)}
    return {"domain": domain, "seasons": [seasons[0], seasons[-1]], "static_calls": len(static), "static_by_endpoint": per_ep, "per_game_calls_estimate": per_game}


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan"]); ap.add_argument("--domain", choices=["cfb", "cbb"], required=True)
    ap.add_argument("--seasons", required=True); ap.add_argument("--endpoints", nargs="*"); a = ap.parse_args(argv)
    print(json.dumps(estimate(a.domain, parse_seasons(a.seasons), a.endpoints), indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
